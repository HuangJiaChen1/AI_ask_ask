# tests/test_activity_catalog.py
import pytest
from activities import (
    get_activity_for_attribute,
    list_activities_for_attribute,
    _age_to_tier,
    _normalize_tier_support,
    ActivityDefinition,
)


# ── get_activity_for_attribute with real catalog ──

def test_get_activity_for_pattern():
    activity = get_activity_for_attribute("appearance.pattern", 5)
    assert activity is not None
    assert activity.activity_id == "polka_dot_patrol"


def test_get_activity_for_emotion():
    activity = get_activity_for_attribute("emotion.state", 5)
    assert activity is not None
    assert activity.observation_angle == "emotion"


def test_get_activity_for_texture():
    activity = get_activity_for_attribute("appearance.texture", 5)
    assert activity is not None
    assert activity.activity_id == "fluffy_expedition_dandelion"


def test_get_activity_for_origin():
    activity = get_activity_for_attribute("origin.source", 5)
    assert activity is not None
    assert activity.activity_id == "time_machine_dinosaur"


def test_get_activity_no_match():
    activity = get_activity_for_attribute("nonexistent.attribute", 5)
    assert activity is None


def test_tier_filtering_t1_all_match():
    # Age 5 -> T1; all 5 activities support T1
    assert get_activity_for_attribute("appearance.pattern", 5) is not None
    assert get_activity_for_attribute("emotion.state", 5) is not None


def test_tier_filtering_t2_some_excluded():
    # Age 8 -> T2; only polka_dot_patrol supports T2
    assert get_activity_for_attribute("appearance.pattern", 8) is not None
    # dream_whisperer_cat does NOT support T2
    assert get_activity_for_attribute("emotion.state", 8) is None


def test_get_activity_fallback_body_color_to_color():
    # No color activity in catalog, so fallback also returns None
    activity = get_activity_for_attribute("appearance.body_color", 5)
    assert activity is None


# ── ActivityDefinition field mapping ──

def test_polka_dot_patrol_field_mapping():
    from activities import _load_catalog
    catalog = _load_catalog()
    activity = next(a for a in catalog if a.activity_id == "polka_dot_patrol")
    assert activity.name == "Find three polka-dotted things!"
    assert activity.launch_prompt == "You noticed the polka dots on the {entity}. Let's find more polka-dotted things!"
    assert "patrol" in activity.description.lower()
    assert activity.observation_angle == "pattern"
    assert activity.mechanic == "collect"
    assert activity.game_style == "quest_collector"
    assert activity.entity_binding == "parameterized"
    assert activity.entity_role == "exemplar"
    assert activity.tier_range_span == ("T0", "T1", "T2")
    assert activity.tier_support == {"T0": True, "T1": True, "T2": True}
    assert activity.bridge_prerequisites_primary == ("pattern",)
    assert activity.bridge_prerequisites_secondary == ("color", "shape")
    assert activity.topic_axis == "form"
    assert activity.difficulty_level == 2


def test_dream_whisperer_cat_field_mapping():
    from activities import _load_catalog
    catalog = _load_catalog()
    activity = next(a for a in catalog if a.activity_id == "dream_whisperer_cat")
    assert activity.name == "Peek into the cat dreams"
    assert activity.observation_angle == "emotion"
    assert activity.mechanic == "imagine"
    assert activity.entity_binding == "bound"
    assert activity.entity_class == ("cat", "pet", "toy")
    assert activity.entity_class_filter == ("cat",)
    assert activity.tier_range_span == ("T0", "T1")
    assert activity.tier_support == {"T0": True, "T1": True, "T2": False}
    assert activity.topic_axis == "perspective"
    assert activity.difficulty_level == 1


# ── _normalize_tier_support ──

def test_normalize_tier_support_boolean():
    raw = {"T0": True, "T1": False}
    assert _normalize_tier_support(raw) == {"T0": True, "T1": False}


def test_normalize_tier_support_yes_no():
    raw = {"T0": "yes", "T1": "no", "T2": "yes"}
    assert _normalize_tier_support(raw) == {"T0": True, "T1": False, "T2": True}


def test_normalize_tier_support_mixed():
    raw = {"T0": "true", "T1": "false", "T2": "yes"}
    assert _normalize_tier_support(raw) == {"T0": True, "T1": False, "T2": True}


# ── _age_to_tier ──

def test_age_to_tier_returns_strings():
    assert _age_to_tier(3) == "T0"
    assert _age_to_tier(4) == "T0"
    assert _age_to_tier(5) == "T1"
    assert _age_to_tier(6) == "T1"
    assert _age_to_tier(7) == "T2"
    assert _age_to_tier(10) == "T2"


# ── from_dict backward compat ──

def test_from_dict_flat_keys():
    data = {
        "activity_id": "test_activity",
        "name": "Test",
        "target_attribute": "appearance.color",
        "launch_prompt": "Go!",
        "description": "A test",
        "observation_angle": "color",
        "mechanic": "collect",
        "game_style": "quest",
        "tier_range_span": ["T0", "T1"],
        "tier_support": {"T0": True, "T1": True},
    }
    activity = ActivityDefinition.from_dict(data)
    assert activity.activity_id == "test_activity"
    assert activity.name == "Test"
    assert activity.observation_angle == "color"
    assert activity.tier_range_span == ("T0", "T1")


def test_from_dict_nested_keys():
    data = {
        "activity_id": "test_activity",
        "activity_signature": {
            "preview_label": "Nested Test",
            "preview_prompt": "Let's go!",
            "intro": "An intro",
            "observation_angle": "texture",
            "mechanic": "imagine",
            "entity_role": "subject",
            "bridge_prerequisites": {
                "primary": ["texture"],
                "secondary": ["color"],
            },
        },
        "game_style": "time_traveler",
        "tier_range": {
            "span": ["T0", "T1"],
        },
        "matchability": {
            "tier_support": {"T0": "yes", "T1": "yes"},
        },
        "progression": {
            "topic_axis": "perspective",
            "difficulty_level": 1,
        },
    }
    activity = ActivityDefinition.from_dict(data)
    assert activity.name == "Nested Test"
    assert activity.launch_prompt == "Let's go!"
    assert activity.description == "An intro"
    assert activity.observation_angle == "texture"
    assert activity.mechanic == "imagine"
    assert activity.entity_role == "subject"
    assert activity.bridge_prerequisites_primary == ("texture",)
    assert activity.bridge_prerequisites_secondary == ("color",)
    assert activity.tier_support == {"T0": True, "T1": True}
    assert activity.topic_axis == "perspective"
    assert activity.difficulty_level == 1
