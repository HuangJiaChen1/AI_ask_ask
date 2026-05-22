# tests/test_activities_selection.py
from types import SimpleNamespace
import pytest
from activities import (
    ActivityDefinition,
    _is_eligible,
    _attribute_to_angles,
    attribute_to_angles,
    get_angle_matched_candidates,
    get_explorable_angles,
    _age_to_tier,
    _normalize_tier_support,
)


# ── _is_eligible ──

def make_activity(**kwargs) -> ActivityDefinition:
    defaults = {
        "activity_id": "test",
        "tier_range_span": ("T0", "T1"),
        "tier_support": {"T0": True, "T1": True, "T2": False},
        "entity_binding": "agnostic",
    }
    defaults.update(kwargs)
    return ActivityDefinition(**defaults)


def test_eligible_tier_in_span_and_supported():
    act = make_activity()
    assert _is_eligible(act, "T1") is True


def test_eligible_tier_not_in_span():
    act = make_activity(tier_range_span=("T0",))
    assert _is_eligible(act, "T1") is False


def test_eligible_tier_not_supported():
    act = make_activity(tier_support={"T0": True, "T1": False})
    assert _is_eligible(act, "T1") is False


def test_eligible_bound_matches_filter():
    act = make_activity(
        entity_binding="bound",
        entity_class_filter=("cat",),
    )
    entity_info = {"entity_class": ["cat", "pet"]}
    assert _is_eligible(act, "T1", entity_info=entity_info) is True


def test_eligible_bound_no_filter_overlap():
    act = make_activity(
        entity_binding="bound",
        entity_class_filter=("dog",),
    )
    entity_info = {"entity_class": ["cat"]}
    assert _is_eligible(act, "T1", entity_info=entity_info) is False


def test_eligible_parameterized_always_passes():
    """Parameterized activities pass Layer 1; LLM judges plausibility in Layer 2."""
    act = make_activity(entity_binding="parameterized")
    assert _is_eligible(act, "T1") is True


def test_eligible_agnostic_always_passes():
    act = make_activity(entity_binding="agnostic")
    assert _is_eligible(act, "T1") is True


# ── _attribute_to_angles ──

def test_attribute_to_angles_exact():
    assert _attribute_to_angles("appearance.color") == ["color"]
    assert _attribute_to_angles("emotion.state") == ["emotion"]


def test_attribute_to_angles_dimension_fallback():
    assert "color" in _attribute_to_angles("appearance.body_color")
    assert "shape" in _attribute_to_angles("appearance.leaf_shape")


def test_attribute_to_angles_unknown():
    assert _attribute_to_angles("unknown.thing") == []


# ── get_angle_matched_candidates ──

def test_angle_match_exact():
    acts = [
        ActivityDefinition(activity_id="a1", observation_angle="color"),
        ActivityDefinition(activity_id="a2", observation_angle="shape"),
    ]
    matched, reason = get_angle_matched_candidates(acts, "appearance.color", [])
    assert len(matched) == 1
    assert matched[0].activity_id == "a1"
    assert reason is None


def test_angle_match_bridge_fallback():
    acts = [
        ActivityDefinition(
            activity_id="a1",
            observation_angle="pattern",
            bridge_prerequisites_primary=("color", "shape"),
        ),
        ActivityDefinition(activity_id="a2", observation_angle="texture"),
    ]
    matched, reason = get_angle_matched_candidates(acts, "appearance.color", [])
    assert len(matched) == 1
    assert matched[0].activity_id == "a1"
    assert reason == "bridge_match"


def test_angle_match_all_eligible_fallback():
    acts = [
        ActivityDefinition(activity_id="a1", observation_angle="texture"),
        ActivityDefinition(activity_id="a2", observation_angle="origin"),
    ]
    matched, reason = get_angle_matched_candidates(acts, "appearance.color", [])
    assert len(matched) == 2
    assert reason == "no_angle_match_fallback"


# ── get_explorable_angles ──

def test_get_explorable_angles_basic():
    """Without entity binding constraints, parameterized activities are eligible."""
    angles = get_explorable_angles(
        entity_info=None,
        age=5,  # T1
    )
    # parameterized activities for T1: fluffy_expedition_dandelion (texture), polka_dot_patrol (pattern)
    assert "texture" in angles
    assert "pattern" in angles


def test_get_explorable_angles_with_entity_class():
    """Bound activities become eligible when entity class matches."""
    angles = get_explorable_angles(
        entity_info={"entity_class": ["cat"]},
        age=5,  # T1
    )
    # dream_whisperer_cat (emotion + behavior bridge) should now be included
    assert "emotion" in angles
    assert "behavior" in angles
    # parameterized ones still present
    assert "texture" in angles


def test_get_explorable_angles_empty_for_unsupported_tier():
    """T2 has very limited support in current catalog."""
    angles = get_explorable_angles(
        entity_info=None,
        age=10,  # T2
    )
    # Only polka_dot_patrol supports T2
    assert "pattern" in angles


def test_attribute_to_angles_public_alias():
    """attribute_to_angles is a public alias of _attribute_to_angles."""
    assert attribute_to_angles("appearance.color") == ["color"]
    assert attribute_to_angles is _attribute_to_angles
