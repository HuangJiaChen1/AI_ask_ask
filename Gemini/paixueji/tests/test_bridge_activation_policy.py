from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from object_resolver import ObjectResolutionResult
from paixueji_assistant import PaixuejiAssistant

from bridge_activation_policy import (
    BRIDGE_PHASE_ACTIVATION,
    BRIDGE_PHASE_ANCHOR_GENERAL,
    BRIDGE_PHASE_NONE,
    BRIDGE_PHASE_PRE_ANCHOR,
    classify_activation_reopen_signal,
    detect_activation_answer_heuristic,
    extract_final_question,
    match_activation_question_to_kb_deterministic,
)
from stream.validation import (
    validate_bridge_activation_answer,
    validate_bridge_activation_kb_question,
)


def test_phase_constants_are_stable():
    assert BRIDGE_PHASE_NONE == "none"
    assert BRIDGE_PHASE_PRE_ANCHOR == "pre_anchor"
    assert BRIDGE_PHASE_ACTIVATION == "activation"
    assert BRIDGE_PHASE_ANCHOR_GENERAL == "anchor_general"


def test_extract_final_question_returns_last_question_sentence():
    text = "That makes sense. After she eats, does she lick her paw pads?"
    assert extract_final_question(text) == "After she eats, does she lick her paw pads?"


def test_match_activation_question_to_kb_deterministic_rejects_sound_only_question():
    result = match_activation_question_to_kb_deterministic(
        question="Does she make a loud crunching sound when she bites into the food?",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={"behavior": ["Cats may sniff food before eating."]},
    )
    assert result.matched is False
    assert result.confidence == "high"


def test_match_activation_question_to_kb_deterministic_accepts_clear_kb_match():
    result = match_activation_question_to_kb_deterministic(
        question="After she eats, does she lick her paw pads?",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={"behavior": ["Cats may sniff food before eating."]},
    )
    assert result.matched is True
    assert result.confidence == "high"
    assert result.kb_item == {
        "kind": "physical_attribute",
        "dimension": "appearance",
        "attribute": "paw_pads",
        "value": "Soft pads underneath the paws",
    }


def test_detect_activation_answer_heuristic_accepts_direct_yes_no():
    assert (
        detect_activation_answer_heuristic(
            child_answer="yes",
            previous_question="After she eats, does she lick her paw pads?",
        )
        == "yes"
    )
    assert (
        detect_activation_answer_heuristic(
            child_answer="not really",
            previous_question="After she eats, does she lick her paw pads?",
        )
        == "yes"
    )


def test_detect_activation_answer_heuristic_returns_inconclusive_when_no_previous_question():
    assert detect_activation_answer_heuristic(
        child_answer="yes",
        previous_question=None,
    ) == "inconclusive"


def test_classify_activation_reopen_signal_accepts_clean_anchor_side_attribute():
    assert classify_activation_reopen_signal(
        child_answer="she licks her paw pads",
        anchor_object_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={},
    ) is True


def test_classify_activation_reopen_signal_rejects_stale_surface_only_detail():
    assert classify_activation_reopen_signal(
        child_answer="it makes a loud crunching sound",
        anchor_object_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={},
    ) is False


def test_apply_resolution_sets_pre_anchor_phase_for_high_confidence_bridge():
    assistant = PaixuejiAssistant(client=object())
    assistant.apply_resolution(
        ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        )
    )

    assert assistant.bridge_phase == BRIDGE_PHASE_PRE_ANCHOR


def test_begin_bridge_activation_keeps_surface_object_visible_and_stashes_anchor_state():
    assistant = PaixuejiAssistant(client=object())
    assistant.object_name = "cat food"
    assistant.surface_object_name = "cat food"
    assistant.anchor_object_name = "cat"

    assistant.begin_bridge_activation(
        anchor_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={"behavior": ["Cats may sniff food before eating."]},
        grounding_context="Current-object KB for cat:\n[physical.appearance]\n  - paw pads: Soft pads underneath the paws",
    )

    assert assistant.object_name == "cat food"
    assert assistant.bridge_phase == BRIDGE_PHASE_ACTIVATION
    assert assistant.activation_anchor_object_name == "cat"
    assert assistant.activation_grounding_context.startswith("Current-object KB for cat:")


def test_commit_bridge_activation_promotes_anchor_to_general_chat():
    assistant = PaixuejiAssistant(client=object())
    assistant.object_name = "cat food"
    assistant.surface_object_name = "cat food"

    assistant.begin_bridge_activation(
        anchor_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={},
        grounding_context="Current-object KB for cat:\n[physical.appearance]\n  - paw pads: Soft pads underneath the paws",
    )
    assistant.commit_bridge_activation()

    assert assistant.object_name == "cat"
    assert assistant.learning_anchor_active is True
    assert assistant.bridge_phase == BRIDGE_PHASE_ANCHOR_GENERAL


@pytest.mark.asyncio
async def test_validate_bridge_activation_kb_question_short_circuits_on_clear_match():
    assistant = PaixuejiAssistant(client=SimpleNamespace())

    result = await validate_bridge_activation_kb_question(
        assistant=assistant,
        final_question="After she eats, does she lick her paw pads?",
        anchor_object_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={},
    )

    assert result["kb_backed_question"] is True
    assert result["source"] == "deterministic"
    assert result["confidence"] == "high"


@pytest.mark.asyncio
async def test_validate_bridge_activation_kb_question_reports_inconclusive_confidence_for_validator_path():
    response = SimpleNamespace(
        text='{"kb_backed_question": true, "reason": "validator matched"}'
    )
    assistant = SimpleNamespace(
        client=SimpleNamespace(
            aio=SimpleNamespace(
                models=SimpleNamespace(generate_content=AsyncMock(return_value=response))
            )
        ),
        config={"model_name": "fake-model"},
    )

    result = await validate_bridge_activation_kb_question(
        assistant=assistant,
        final_question="After she eats, does she use her paws?",
        anchor_object_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={},
    )

    assert result["source"] == "validator"
    assert result["confidence"] == "inconclusive"


@pytest.mark.asyncio
async def test_validate_bridge_activation_answer_uses_validator_for_ambiguous_reply():
    response = SimpleNamespace(
        text='{"answered_previous_kb_question": true, "reason": "child answered softly"}'
    )
    assistant = SimpleNamespace(
        client=SimpleNamespace(
            aio=SimpleNamespace(
                models=SimpleNamespace(generate_content=AsyncMock(return_value=response))
            )
        ),
        config={"model_name": "fake-model"},
    )

    result = await validate_bridge_activation_answer(
        assistant=assistant,
        child_answer="maybe a little",
        previous_question="After she eats, does she lick her paw pads?",
        anchor_object_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={},
    )

    assert result["answered_previous_kb_question"] is True
    assert result["source"] == "validator"
