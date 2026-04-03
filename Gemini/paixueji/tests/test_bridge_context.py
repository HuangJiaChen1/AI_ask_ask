from bridge_context import SUPPORTED_RELATIONS, build_bridge_context, normalize_relation


def test_supported_relations_are_fixed():
    assert SUPPORTED_RELATIONS == (
        "food_for",
        "used_with",
        "part_of",
        "belongs_to",
        "made_from",
        "related_to",
    )


def test_normalize_relation_falls_back_to_related_to():
    assert normalize_relation("food_for") == "food_for"
    assert normalize_relation(" Food_For ") == "food_for"
    assert normalize_relation("unknown_relation") == "related_to"
    assert normalize_relation(None) == "related_to"


def test_food_for_profile_limits_bridge_focus():
    ctx = build_bridge_context("cat food", "cat", "food_for", attempt_number=1)

    assert ctx is not None
    assert ctx.relation == "food_for"
    assert ctx.allowed_focus_terms == ("smell", "eat", "mouth", "nose")
    assert "paws" in ctx.forbidden_anchor_terms
    assert "cat food" in ctx.prompt_context


def test_used_with_profile_is_code_driven():
    ctx = build_bridge_context("dog leash", "dog", "used_with", attempt_number=2)

    assert ctx is not None
    assert ctx.relation == "used_with"
    assert ctx.attempt_number == 2
    assert "second bridge attempt" in ctx.prompt_context.lower()


def test_related_to_is_conservative():
    ctx = build_bridge_context("cat thing", "cat", "related_to", attempt_number=1)

    assert ctx is not None
    assert ctx.relation == "related_to"
    assert ctx.follow_terms == ()


def test_unknown_relation_returns_none():
    assert build_bridge_context("cat food", "cat", "unknown_relation", 1) is None
