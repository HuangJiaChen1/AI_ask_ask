# tests/test_activities_selection.py
from types import SimpleNamespace
import pytest
from activities import (
    ActivityDefinition,
    ActivityProfile,
    SelectionResult,
    _interest_to_profile,
    _is_eligible,
    _attribute_to_angles,
    get_angle_matched_candidates,
    score_activity,
    select_best_activity,
    _age_to_tier,
    _normalize_tier_support,
)


# ── _interest_to_profile ──

def test_interest_profile_high_score():
    profile = _interest_to_profile(85)
    assert "collect" in profile.preferred_mechanics
    assert profile.preferred_difficulty_level == 3


def test_interest_profile_mid_score():
    profile = _interest_to_profile(65)
    assert "compare" in profile.preferred_mechanics
    assert profile.preferred_difficulty_level == 2


def test_interest_profile_low_score():
    profile = _interest_to_profile(40)
    assert "observe" in profile.preferred_mechanics
    assert profile.preferred_difficulty_level == 1


def test_interest_profile_boundary_80():
    profile = _interest_to_profile(80)
    assert profile.preferred_difficulty_level == 3


def test_interest_profile_boundary_60():
    profile = _interest_to_profile(60)
    assert profile.preferred_difficulty_level == 2


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


def test_eligible_parameterized_with_properties():
    act = make_activity(entity_binding="parameterized")
    assert _is_eligible(act, "T1", extracted_properties={"color": "red"}) is True


def test_eligible_parameterized_without_properties():
    act = make_activity(entity_binding="parameterized")
    assert _is_eligible(act, "T1", extracted_properties={}) is False


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


# ── score_activity ──

def test_score_activity_mechanic_preferred():
    act = ActivityDefinition(
        activity_id="a1",
        observation_angle="color",
        mechanic="collect",
        game_style="field_experiment",
        difficulty_level=2,
    )
    ctx = {
        "dominant_angle": "color",
        "secondary_angles": [],
        "angles": ["color"],
        "entity_depth": "property_focused",
        "recent_activities": [],
    }
    # interest=65 → mid profile: preferred_mechanics includes "collect"
    score = score_activity(act, 65, 5, ctx)
    # mechanic=collect preferred=25, game_style=field_experiment preferred=15,
    # diff=0 → 8, coherence: angle match=15, bridge overlap=0 (no bridge_prerequisites set), entity_role default=subject vs property_focused=0
    # practical: not recent=3
    assert score == 25 + 15 + 8 + 15 + 0 + 0 + 3


def test_score_activity_mechanic_not_preferred():
    act = ActivityDefinition(
        activity_id="a1",
        observation_angle="color",
        mechanic="unknown",
        game_style="unknown",
        difficulty_level=1,
    )
    ctx = {
        "dominant_angle": "shape",
        "secondary_angles": [],
        "angles": [],
        "entity_depth": "deep",
        "recent_activities": ["a1"],
    }
    score = score_activity(act, 65, 5, ctx)
    # mechanic unknown → 5, game_style unknown → 0, diff=1 → 4,
    # coherence: no angle match, no bridge, entity_role=subject + entity_depth=deep → 5,
    # practical: recent → 0
    assert score == 5 + 0 + 4 + 0 + 0 + 5 + 0


def test_score_activity_with_progression():
    act = ActivityDefinition(
        activity_id="a1",
        observation_angle="color",
        mechanic="collect",
        topic_axis="form",
        difficulty_level=2,
    )
    ctx = {
        "dominant_angle": "color",
        "secondary_angles": [],
        "angles": ["color"],
        "entity_depth": "property_focused",
        "recent_activities": [],
    }
    prog = {"target_axis": "form", "target_rung": 2}
    score = score_activity(act, 65, 5, ctx, prog)
    # Base: 25+0+8=33 (game_style empty → 0), Coherence: 15+0+0=15, Progression: 20, Practical: 3
    assert score == 33 + 15 + 20 + 3


# ── select_best_activity ──

def test_select_best_activity_exact_match():
    """Pattern attribute with mid-high interest score — mid profile accepts quest_collector."""
    result = select_best_activity(
        attribute_id="appearance.pattern",
        interest_score=70,
        age=5,
        conversation_context={
            "dominant_angle": "pattern",
            "secondary_angles": [],
            "angles": ["pattern"],
            "entity_depth": "property_focused",
            "recent_activities": [],
        },
    )
    assert result.activity is not None
    assert result.activity.activity_id == "polka_dot_patrol"
    assert result.selector_score >= 60
    assert result.decision == "matched"
    assert result.fallback_reason is None


def test_select_best_activity_no_eligible():
    result = select_best_activity(
        attribute_id="appearance.color",
        interest_score=80,
        age=5,
        conversation_context={
            "dominant_angle": "color",
            "angles": ["color"],
            "entity_depth": "property_focused",
            "recent_activities": [],
            "entity_info": {},
            "extracted_properties": {},
        },
    )
    # No "color" observation_angle in catalog, bridge also fails,
    # falls back to all eligible, but polka_dot_patrol scores on bridge
    # (bridge_prerequisites_primary includes pattern, not color)
    # Actually pattern has no overlap with color either, so fallback to all eligible
    # polka_dot_patrol will be scored; with interest=80 and no angle match,
    # let's see: mechanic=collect (preferred=25), game_style=quest_collector (acceptable=7),
    # diff=|2-3|=1 → 4, coherence: no angle match, bridge overlap pattern&color=0,
    # practical: 3. Total = 25+7+4+0+0+3 = 39 < 60
    # So result.activity should be None
    assert result.activity is None
    assert result.decision == "none"


def test_select_best_activity_texture_match():
    """appearance.texture → matches fluffy_expedition_dandelion (texture) exact."""
    result = select_best_activity(
        attribute_id="appearance.texture",
        interest_score=70,
        age=5,
        conversation_context={
            "dominant_angle": "texture",
            "angles": ["texture"],
            "entity_depth": "property_focused",
            "recent_activities": [],
        },
    )
    assert result.activity is not None
    assert result.activity.activity_id == "fluffy_expedition_dandelion"
    assert result.activity.observation_angle == "texture"
    assert result.decision == "matched"


def test_select_best_activity_below_threshold():
    """Low interest score → no handoff even with match."""
    result = select_best_activity(
        attribute_id="appearance.pattern",
        interest_score=30,
        age=5,
        conversation_context={
            "dominant_angle": "pattern",
            "angles": ["pattern"],
            "entity_depth": "property_focused",
            "recent_activities": [],
        },
    )
    assert result.activity is None
    assert result.decision == "none"
    assert result.fallback_reason == "score_below_threshold"
