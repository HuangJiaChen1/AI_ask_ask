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
