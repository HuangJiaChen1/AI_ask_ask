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


# ── backward_pass ─────────────────────────────────────────────────────────

_SAMPLE_PROMPT = (
    "## [CLAUSE: core]\nYou are a learning companion.\n\n"
    "## [CLAUSE: constraints]\nDo not ask questions.\n"
)


def test_parse_clauses_returns_expected_ids():
    from optimizer.backward_pass import parse_clauses
    clauses = parse_clauses(_SAMPLE_PROMPT)
    assert len(clauses) == 2
    assert clauses[0]["clause_id"] == "core"
    assert clauses[1]["clause_id"] == "constraints"
    assert "## [CLAUSE:" not in clauses[0]["content"]


def test_parse_clauses_empty_on_no_markers():
    from optimizer.backward_pass import parse_clauses
    assert parse_clauses("No markers here.") == []


def test_aggregate_gradients_filters_single_low():
    from optimizer.backward_pass import aggregate_gradients
    result = aggregate_gradients([
        {"clause_id": "core", "problem": "p", "suggested_fix": "f", "confidence": "LOW"}
    ])
    assert result == []


def test_aggregate_gradients_sorted_by_priority():
    from optimizer.backward_pass import aggregate_gradients
    grads = [
        {"clause_id": "a", "problem": "p", "suggested_fix": "f1", "confidence": "MODERATE"},
        {"clause_id": "a", "problem": "p", "suggested_fix": "f1", "confidence": "HIGH"},
        {"clause_id": "b", "problem": "p", "suggested_fix": "f2", "confidence": "HIGH"},
    ]
    result = aggregate_gradients(grads)
    # "a": 2 votes, weight 1+2=3; "b": 1 vote, weight 2
    assert result[0]["clause_id"] == "a"


def test_apply_diffs_replaces_content_preserves_marker():
    from optimizer.backward_pass import apply_diffs
    result = apply_diffs(_SAMPLE_PROMPT, [{"clause_id": "core", "suggested_fix": "You are a tutor."}])
    assert "## [CLAUSE: core]" in result
    assert "You are a tutor." in result
    assert "You are a learning companion." not in result
    assert "## [CLAUSE: constraints]" in result


# ── bootstrap ─────────────────────────────────────────────────────────────

def _make_trace(trace_id="t1", age=6, obj="apple", child="red", response="good"):
    from trace_schema import TraceObject, HumanCritique, ExchangeContext
    return TraceObject(
        trace_id=trace_id, session_id="s1", timestamp="2026-01-01T00:00:00",
        object_name=obj, age=age, exchange_index=0,
        critique=HumanCritique(exchange_index=0, model_response_expected="great", model_response_problem=""),
        exchange=ExchangeContext(child_response=child, model_response=response),
        conversation_history=[{"role": "user", "content": child}],
    )


def test_add_golden_example_creates_file(tmp_path, monkeypatch):
    import optimizer.bootstrap as bs
    monkeypatch.setattr(bs, "EXAMPLES_DIR", tmp_path)
    bs.add_golden_example("informative_intent_prompt", _make_trace(), "nice response", 0.95)
    data = json.loads((tmp_path / "informative_intent_prompt.json").read_text())
    assert len(data) == 1 and data[0]["score"] == 0.95


def test_add_golden_example_skips_below_threshold(tmp_path, monkeypatch):
    import optimizer.bootstrap as bs
    monkeypatch.setattr(bs, "EXAMPLES_DIR", tmp_path)
    bs.add_golden_example("informative_intent_prompt", _make_trace(), "meh", 0.80)
    assert not (tmp_path / "informative_intent_prompt.json").exists()


def test_get_best_examples_returns_empty_when_no_file(tmp_path, monkeypatch):
    import optimizer.bootstrap as bs
    monkeypatch.setattr(bs, "EXAMPLES_DIR", tmp_path)
    assert bs.get_best_examples("no_such_prompt") == []


def test_inject_examples_replaces_placeholder():
    from optimizer.bootstrap import inject_examples, GoldenExample, GoldenExampleContext
    ex = GoldenExample(
        id="1", prompt_name="p", score=0.95, trace_id="t", added_at="2026-01-01",
        context=GoldenExampleContext(age=6, object_name="apple", child_response="red",
                                     conversation_history_tail=[]),
        response="Great observation!",
    )
    prompt = "## [CLAUSE: few_shot_examples]\n{few_shot_examples}\n"
    result = inject_examples(prompt, [ex])
    assert "{few_shot_examples}" not in result
    assert 'Child said "red"' in result


# ── trigger ───────────────────────────────────────────────────────────────

def _write_trace(traces_dir, trace):
    (traces_dir / f"{trace.trace_id}.json").write_text(
        trace.model_dump_json(), encoding="utf-8"
    )


def _make_culprit_trace(trace_id, culprit_name, prompt_name):
    from trace_schema import (TraceObject, HumanCritique, ExchangeContext,
                               CulpritIdentification, CulpritType, ConfidenceLevel)
    return TraceObject(
        trace_id=trace_id, session_id="s1", timestamp="2026-01-01T00:00:00",
        object_name="apple", exchange_index=0,
        culprits=[CulpritIdentification(
            culprit_type=CulpritType.NODE, culprit_name=culprit_name,
            confidence_level=ConfidenceLevel.CONFIDENT, reasoning="r",
            prompt_template_name=prompt_name,
        )],
        critique=HumanCritique(exchange_index=0, model_response_expected="good", model_response_problem="bad"),
        exchange=ExchangeContext(child_response="red", model_response="meh"),
    )


def test_group_traces_by_culprit(tmp_path, monkeypatch):
    import optimizer.trigger as trigger
    traces_dir = tmp_path / "traces"; traces_dir.mkdir()
    trace = _make_culprit_trace("t1", "informative", "informative_intent_prompt")
    _write_trace(traces_dir, trace)
    monkeypatch.setattr(trigger, "TRACES_DIR", traces_dir)
    monkeypatch.setattr(trigger, "OPTIMIZATIONS_DIR", tmp_path / "optimizations")
    groups = trigger.group_traces_by_culprit()
    assert "informative" in groups and len(groups["informative"]) == 1


def test_covered_trace_ids_empty_no_optimizations(tmp_path, monkeypatch):
    import optimizer.trigger as trigger
    monkeypatch.setattr(trigger, "OPTIMIZATIONS_DIR", tmp_path / "optimizations")
    assert trigger._get_covered_trace_ids() == set()


def test_get_traces_by_ids(tmp_path, monkeypatch):
    import optimizer.trigger as trigger
    traces_dir = tmp_path / "traces"; traces_dir.mkdir()
    trace = _make_culprit_trace("t99", "informative", "informative_intent_prompt")
    _write_trace(traces_dir, trace)
    monkeypatch.setattr(trigger, "TRACES_DIR", traces_dir)
    result = trigger.get_traces_by_ids(["t99"])
    assert len(result) == 1 and result[0].trace_id == "t99"


# ── convergence_loop ──────────────────────────────────────────────────────

def test_resolve_prompt_name_from_traces():
    from optimizer.convergence_loop import resolve_prompt_name
    trace = _make_culprit_trace("t1", "informative", "informative_intent_prompt")
    assert resolve_prompt_name([trace]) == "informative_intent_prompt"


def test_resolve_prompt_name_raises_on_mismatch():
    from optimizer.convergence_loop import resolve_prompt_name
    t1 = _make_culprit_trace("t1", "informative", "prompt_a")
    t2 = _make_culprit_trace("t2", "informative", "prompt_b")
    with pytest.raises(ValueError):
        resolve_prompt_name([t1, t2])


# ── prompt_optimizer integration ──────────────────────────────────────────

def test_run_dspy_optimization_importable():
    from prompt_optimizer import run_dspy_optimization
    assert callable(run_dspy_optimization)


# ── app endpoints ─────────────────────────────────────────────────────────

def test_candidates_endpoint_exists(client):
    resp = client.get("/api/optimize-prompt/candidates")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), dict)


# ── reporter ──────────────────────────────────────────────────────────────

def test_reporter_disabled_produces_no_output(capsys):
    from optimizer.reporter import Reporter
    r = Reporter(enabled=False)
    r.loop_start("culprit", "my_prompt", 3)
    r.round_start(1, 5)
    r.previews_generated(3)
    r.round_scores(0.65, 0.0, {"t1": 0.65}, [{"trace_id": "t1", "preview": "Apples are red"}])
    r.gradients_computed(2, [
        {"clause_id": "core", "confidence": "HIGH", "problem": "too vague", "suggested_fix": "Be specific."}
    ])
    r.prompt_diff("## [CLAUSE: core]\nold text\n", "## [CLAUSE: core]\nnew text\n")
    r.early_stop("no actionable gradients")
    r.loop_end(0.65, "queued_for_review", 1)
    assert capsys.readouterr().out == ""


def test_reporter_enabled_prints_culprit_and_prompt(capsys):
    from optimizer.reporter import Reporter
    r = Reporter(enabled=True)
    r.loop_start("informative", "informative_intent_prompt", 2)
    out = capsys.readouterr().out
    assert "informative" in out
    assert "informative_intent_prompt" in out


def test_reporter_round_scores_shows_arrow_up(capsys):
    from optimizer.reporter import Reporter
    r = Reporter(enabled=True)
    r.round_scores(0.75, 0.60, {"t1": 0.75}, [{"trace_id": "t1", "preview": "Nice!"}])
    out = capsys.readouterr().out
    assert "0.750" in out
    assert "↑" in out


def test_reporter_prompt_diff_shows_change(capsys):
    from optimizer.reporter import Reporter
    r = Reporter(enabled=True)
    r.prompt_diff("## [CLAUSE: core]\nold line\n", "## [CLAUSE: core]\nnew line\n")
    out = capsys.readouterr().out
    assert "-old line" in out
    assert "+new line" in out


def test_reporter_prompt_diff_silent_when_identical(capsys):
    from optimizer.reporter import Reporter
    r = Reporter(enabled=True)
    r.prompt_diff("same\n", "same\n")
    assert capsys.readouterr().out == ""
