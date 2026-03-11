import pytest
from graph_lookup import _age_to_tier, _THEME_ID_TO_NAME, _format_concept_anchors


def test_age_to_tier_boundaries():
    assert _age_to_tier(3) == "T0"
    assert _age_to_tier(4) == "T1"
    assert _age_to_tier(5) == "T2"
    assert _age_to_tier(6) == "T2"
    assert _age_to_tier(7) == "T3"
    assert _age_to_tier(8) == "T3"


def test_theme_id_to_name_has_all_six():
    expected_ids = {
        "how_world_works", "sharing_planet", "who_we_are",
        "how_we_express", "how_we_organize", "where_place_time",
    }
    assert expected_ids == set(_THEME_ID_TO_NAME.keys())


def test_format_concept_anchors_basic():
    concept = {
        "concept_id": "change",
        "topic_anchors": {
            "visual": [
                {"attribute": "bud_to_bloom", "value": "Green bud opens into a big face."},
                {"attribute": "head_dries",   "value": "Flower head dries and turns brown."},
            ],
            "kinesthetic": [
                {"attribute": "sprout_to_tall", "value": "Small sprout grows taller each week."},
            ],
        },
    }
    result = _format_concept_anchors(concept, "Sunflower")
    assert result.startswith("CONCEPT FOCUS: change")
    assert "OBSERVATION ANCHORS FOR SUNFLOWER:" in result
    assert "Visual: Green bud opens into a big face.; Flower head dries and turns brown." in result
    assert "Movement: Small sprout grows taller each week." in result


def test_format_concept_anchors_empty_anchors():
    concept = {"concept_id": "form", "topic_anchors": {}}
    result = _format_concept_anchors(concept, "Apple")
    assert "CONCEPT FOCUS: form" in result
    assert "OBSERVATION ANCHORS FOR APPLE:" in result
    # Fallback line present when no anchors
    assert "Explore what" in result


def test_format_concept_anchors_no_anchors_key():
    concept = {"concept_id": "function"}
    result = _format_concept_anchors(concept, "Wheel")
    assert "CONCEPT FOCUS: function" in result


from graph_lookup import classify_object_yaml
import time
from unittest.mock import MagicMock
from paixueji_assistant import PaixuejiAssistant


def test_classify_theme_background_sets_fields():
    """classify_theme_background should set category_prompt and theme fields."""
    assistant = PaixuejiAssistant(client=MagicMock())
    assistant.age = 5
    assistant.classify_theme_background("sunflower")
    # Background thread — give it time to complete
    time.sleep(1.0)
    assert assistant.category_prompt is not None
    assert "CONCEPT FOCUS:" in assistant.category_prompt
    assert assistant.ibpyp_theme_name is not None
    assert assistant.key_concept is not None


def test_classify_object_yaml_known_object():
    """sunflower is in the YAML mappings."""
    result = classify_object_yaml("sunflower", 5)
    assert result["success"] is True
    assert result["theme_id"] in {
        "how_world_works", "sharing_planet", "who_we_are",
        "how_we_express", "how_we_organize", "where_place_time",
    }
    assert result["theme_name"]
    assert result["key_concept"]
    assert result["bridge_question"]
    assert "CONCEPT FOCUS:" in result["category_prompt"]
    assert "OBSERVATION ANCHORS FOR" in result["category_prompt"]
    assert "theme_reasoning" in result
    assert isinstance(result["theme_reasoning"], str)


def test_classify_object_yaml_unknown_object():
    """Completely unknown object returns fallback, does not crash."""
    result = classify_object_yaml("xyzzy_nonexistent_object_99", 5)
    assert result["success"] is False
    assert result["theme_id"] == "how_world_works"
    assert result["theme_name"] == "How the World Works"
    assert result["key_concept"] == "function"
    assert result["bridge_question"]
    assert "CONCEPT FOCUS:" in result["category_prompt"]


def test_classify_object_yaml_all_ages_no_crash():
    """Every valid age 3-8 returns a valid result."""
    for age in [3, 4, 5, 6, 7, 8]:
        result = classify_object_yaml("apple", age)
        assert "theme_id" in result
        assert "category_prompt" in result
