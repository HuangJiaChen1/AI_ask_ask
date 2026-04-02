from unittest.mock import MagicMock

from paixueji_assistant import PaixuejiAssistant

from object_resolver import (
    ObjectResolutionResult,
    parse_anchor_confirmation,
    resolve_object_input,
)


def test_exact_supported_object_returns_exact_supported():
    result = resolve_object_input("cat", age=6, client=None, config={})

    assert result.anchor_status == "exact_supported"
    assert result.surface_object_name == "cat"
    assert result.visible_object_name == "cat"
    assert result.anchor_object_name == "cat"
    assert result.learning_anchor_active is True


def test_curated_relation_returns_high_confidence_anchor():
    result = resolve_object_input("cat food", age=6, client=None, config={})

    assert result.anchor_status == "anchored_high"
    assert result.surface_object_name == "cat food"
    assert result.visible_object_name == "cat food"
    assert result.anchor_object_name == "cat"
    assert result.anchor_relation == "food_for"
    assert result.anchor_confidence_band == "high"
    assert result.learning_anchor_active is False


def test_relation_without_bridge_profile_downgrades_to_confirmation(monkeypatch):
    monkeypatch.setattr(
        "object_resolver.build_bridge_context",
        lambda *args, **kwargs: None,
    )

    result = resolve_object_input("cat food", age=6, client=None, config={})

    assert result.anchor_status == "anchored_medium"
    assert result.anchor_confirmation_needed is True
    assert result.learning_anchor_active is False


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
