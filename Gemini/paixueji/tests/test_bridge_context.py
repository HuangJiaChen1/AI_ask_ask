from bridge_context import SUPPORTED_RELATIONS, build_bridge_context, normalize_relation
from bridge_profile import BridgeProfile


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


def test_bridge_context_uses_semantic_profile_fields():
    profile = BridgeProfile(
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_intent="bridge from the food to how the cat notices and eats it.",
        good_question_angles=("how the cat smells it", "how the cat starts eating it"),
        avoid_angles=("unrelated cat body parts",),
        steer_back_rule="acknowledge briefly, then return to noticing or eating.",
        focus_cues=("smell", "eat"),
    )
    ctx = build_bridge_context(profile, attempt_number=1)

    assert ctx is not None
    assert ctx.relation == "food_for"
    assert ctx.surface_object_name == "cat food"
    assert ctx.bridge_intent == profile.bridge_intent
    assert ctx.good_question_angles == profile.good_question_angles
    assert "Bridge intent" in ctx.prompt_context
    assert "Focus cues: smell, eat" in ctx.prompt_context


def test_second_attempt_context_keeps_semantic_profile():
    profile = BridgeProfile(
        surface_object_name="dog leash",
        anchor_object_name="dog",
        relation="used_with",
        bridge_intent="bridge from the leash to how the dog uses or wears it.",
        good_question_angles=("how the dog wears it",),
        avoid_angles=("unrelated fur details",),
        steer_back_rule="keep the child on use and handling.",
        focus_cues=("wear", "hold"),
    )
    ctx = build_bridge_context(profile, attempt_number=2)

    assert ctx is not None
    assert ctx.relation == "used_with"
    assert ctx.attempt_number == 2
    assert "second bridge attempt" in ctx.prompt_context.lower()
    assert "Avoid angles" in ctx.prompt_context


def test_bridge_context_omits_focus_cues_when_empty():
    profile = BridgeProfile(
        surface_object_name="cat thing",
        anchor_object_name="cat",
        relation="related_to",
        bridge_intent="use a gentle bridge from the thing to the cat.",
        good_question_angles=("how the cat notices it",),
        avoid_angles=(),
        steer_back_rule="keep the question conservative.",
        focus_cues=(),
    )
    ctx = build_bridge_context(profile, attempt_number=1)

    assert ctx is not None
    assert ctx.relation == "related_to"
    assert "Focus cues" not in ctx.prompt_context


def test_missing_profile_returns_none():
    assert build_bridge_context(None, attempt_number=1) is None
