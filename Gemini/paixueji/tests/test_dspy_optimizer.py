"""Tests for DSPy-inspired optimizer components."""
import json
import pytest
from pathlib import Path


# ── paixueji_prompts helpers ───────────────────────────────────────────────

def test_get_prompts_strips_clause_markers():
    """get_prompts() must not expose ## [CLAUSE:...] lines to LLM callers."""
    import paixueji_prompts
    prompts = paixueji_prompts.get_prompts()
    for name, text in prompts.items():
        if not isinstance(text, str):
            continue
        assert "## [CLAUSE:" not in text, (
            f"Clause marker leaked into get_prompts()['{name}']"
        )


def test_get_prompts_strips_few_shot_placeholder():
    """Unresolved {few_shot_examples} must not survive get_prompts()."""
    import paixueji_prompts
    prompts = paixueji_prompts.get_prompts()
    for name, text in prompts.items():
        if not isinstance(text, str):
            continue
        assert "{few_shot_examples}" not in text, (
            f"Unresolved placeholder leaked into get_prompts()['{name}']"
        )


def test_get_prompts_preserves_real_placeholders():
    """{age}, {object_name}, {child_answer} must survive stripping."""
    import paixueji_prompts
    prompts = paixueji_prompts.get_prompts()
    # informative_intent_prompt uses all three
    p = prompts["informative_intent_prompt"]
    assert "{age}" in p
    assert "{object_name}" in p
    assert "{child_answer}" in p


def test_get_annotated_prompt_preserves_markers():
    """get_annotated_prompt() must return a string with ## [CLAUSE:] markers."""
    import paixueji_prompts
    text = paixueji_prompts.get_annotated_prompt("informative_intent_prompt")
    assert "## [CLAUSE:" in text


def test_get_annotated_prompt_invalid_key_raises():
    """Unknown prompt name must raise KeyError."""
    import paixueji_prompts
    with pytest.raises(KeyError):
        paixueji_prompts.get_annotated_prompt("nonexistent_prompt_xyz")


# ── metric ────────────────────────────────────────────────────────────────

class _MockEmbedResult:
    def __init__(self, values): self.values = values

class _MockEmbedding:
    def __init__(self, values): self.embeddings = [_MockEmbedResult(values)]

class _FixedClient:
    """Always returns the same embedding vector."""
    def __init__(self, vec):
        _vec = vec
        class _M:
            def __init__(self): self._vec = _vec
            def embed_content(self, model, contents): return _MockEmbedding(self._vec)
            def generate_content(self, model, contents, config=None):
                class R: text = "synthesized ideal response"
                return R()
        self.models = _M()

class _AlternatingClient:
    """Returns [1,0] first call, [0,1] second call — orthogonal vectors."""
    def __init__(self):
        class _M:
            def __init__(self): self._n = 0
            def embed_content(self, model, contents):
                self._n += 1
                return _MockEmbedding([1.0, 0.0] if self._n == 1 else [0.0, 1.0])
            def generate_content(self, model, contents, config=None):
                class R: text = "x"
                return R()
        self.models = _M()


def test_compute_score_identical_vectors():
    from optimizer.metric import compute_score
    score = compute_score("a", "b", {"embedding_model": "m"}, _FixedClient([1.0, 0.0]))
    assert abs(score - 1.0) < 1e-6


def test_compute_score_orthogonal_vectors():
    from optimizer.metric import compute_score
    score = compute_score("a", "b", {"embedding_model": "m"}, _AlternatingClient())
    assert abs(score) < 1e-6


def test_compute_score_empty_expected_returns_zero():
    from optimizer.metric import compute_score
    score = compute_score("preview", "", {"embedding_model": "m"}, _FixedClient([1.0]))
    assert score == 0.0


def test_compute_batch_score_synthesizes_when_sparse():
    from optimizer.metric import compute_batch_score
    from trace_schema import TraceObject, HumanCritique, ExchangeContext
    trace = TraceObject(
        trace_id="t1", session_id="s1", timestamp="2026-01-01T00:00:00",
        object_name="apple", exchange_index=0,
        critique=HumanCritique(exchange_index=0, model_response_expected="", model_response_problem="too vague"),
        exchange=ExchangeContext(child_response="red", model_response="meh"),
    )
    scores = compute_batch_score(
        ["preview text"], [trace],
        {"embedding_model": "m", "high_reasoning_model": "m"},
        _FixedClient([1.0, 0.0]),
    )
    assert len(scores) == 1
    assert 0.0 <= scores[0] <= 1.0
