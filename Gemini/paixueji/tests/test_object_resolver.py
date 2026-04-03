from unittest.mock import MagicMock

from paixueji_assistant import PaixuejiAssistant

from object_resolver import (
    ObjectResolutionResult,
    parse_anchor_confirmation,
    resolve_object_input,
)
from paixueji_prompts import OBJECT_RESOLUTION_PROMPT


def test_exact_supported_object_returns_exact_supported():
    result = resolve_object_input("cat", age=6, client=None, config={})

    assert result.anchor_status == "exact_supported"
    assert result.surface_object_name == "cat"
    assert result.visible_object_name == "cat"
    assert result.anchor_object_name == "cat"
    assert result.learning_anchor_active is True


def test_unsupported_object_uses_model_inference_when_not_exact(monkeypatch):
    expected = ObjectResolutionResult(
        surface_object_name="cat food",
        visible_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        anchor_confirmation_needed=False,
        learning_anchor_active=False,
    )

    monkeypatch.setattr("object_resolver._model_fallback", lambda *args, **kwargs: expected)

    result = resolve_object_input("cat food", age=6, client=MagicMock(), config={})

    assert result == expected


def test_model_inference_medium_confidence_requires_confirmation():
    client = MagicMock()
    client.models.generate_content.return_value.text = (
        '{"anchor_object_name":"cat","relation":"food_for","confidence_band":"medium"}'
    )

    result = resolve_object_input("cat food", age=6, client=client, config={"model_name": "mock"})

    assert result.anchor_status == "anchored_medium"
    assert result.anchor_relation == "food_for"
    assert result.anchor_confirmation_needed is True
    assert result.learning_anchor_active is False


def test_invalid_model_relation_downgrades_to_related_to_confirmation():
    client = MagicMock()
    client.models.generate_content.return_value.text = (
        '{"anchor_object_name":"cat","relation":"weird_relation","confidence_band":"high"}'
    )

    result = resolve_object_input("cat food", age=6, client=client, config={"model_name": "mock"})

    assert result.anchor_status == "anchored_medium"
    assert result.anchor_relation == "related_to"
    assert result.anchor_confirmation_needed is True
    assert result.learning_anchor_active is False


def test_model_relation_is_normalized_before_validity_check():
    client = MagicMock()
    client.models.generate_content.return_value.text = (
        '{"anchor_object_name":"cat","relation":" Food_For ","confidence_band":"high"}'
    )

    result = resolve_object_input("cat food", age=6, client=client, config={"model_name": "mock"})

    assert result.anchor_status == "anchored_high"
    assert result.anchor_relation == "food_for"
    assert result.anchor_confirmation_needed is False


def test_unknown_object_without_match_returns_unresolved():
    result = resolve_object_input("spaceship fuel", age=6, client=None, config={})

    assert result == ObjectResolutionResult(
        surface_object_name="spaceship fuel",
        visible_object_name="spaceship fuel",
        anchor_object_name=None,
        anchor_status="unresolved",
        anchor_relation=None,
        anchor_confidence_band=None,
        anchor_confirmation_needed=False,
        learning_anchor_active=False,
        anchor_suppressed=False,
    )


def test_confirmation_parser_accepts_anchor_and_rejects_surface():
    assert parse_anchor_confirmation("yes, cat", "cat food", "cat") == "accept"
    assert parse_anchor_confirmation("no, stay with cat food", "cat food", "cat") == "reject"
    assert parse_anchor_confirmation("maybe", "cat food", "cat") == "unclear"


def test_object_resolution_prompt_lists_supported_relation_enum():
    assert "food_for" in OBJECT_RESOLUTION_PROMPT
    assert "used_with" in OBJECT_RESOLUTION_PROMPT
    assert "related_to" in OBJECT_RESOLUTION_PROMPT


def test_activate_anchor_topic_resets_learning_count():
    assistant = PaixuejiAssistant(client=MagicMock())
    assistant.correct_answer_count = 3
    assistant.surface_object_name = "cat food"
    assistant.anchor_object_name = "cat"

    assistant.activate_anchor_topic("cat")

    assert assistant.object_name == "cat"
    assert assistant.visible_object_name == "cat"
    assert assistant.learning_anchor_active is True
    assert assistant.correct_answer_count == 0
