from bridge_context import build_bridge_context


def test_food_for_profile_limits_bridge_focus():
    ctx = build_bridge_context("cat food", "cat", "food_for", attempt_number=1)

    assert ctx.relation == "food_for"
    assert ctx.allowed_focus_terms == ("smell", "eat", "mouth", "nose")
    assert "paws" in ctx.forbidden_anchor_terms
    assert "cat food" in ctx.prompt_context


def test_retry_attempt_uses_same_relation_but_retry_guidance():
    ctx = build_bridge_context("cat food", "cat", "food_for", attempt_number=2)

    assert ctx.attempt_number == 2
    assert "second bridge attempt" in ctx.prompt_context.lower()


def test_unknown_relation_returns_none():
    assert build_bridge_context("cat food", "cat", "unknown_relation", 1) is None
