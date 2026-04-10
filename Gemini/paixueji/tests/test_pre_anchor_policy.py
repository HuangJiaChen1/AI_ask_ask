from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from object_resolver import ObjectResolutionResult
from paixueji_assistant import PaixuejiAssistant
from pre_anchor_policy import classify_pre_anchor_reply


@pytest.mark.asyncio
async def test_clarification_request_does_not_consume_bridge_attempt(monkeypatch):
    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="whay do you mean?",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="What is the most important part of cat food for a cat to eat?",
    )

    assert result.reply_type == "clarification_request"
    assert result.bridge_followed is False
    assert result.consume_bridge_attempt is False
    assert result.support_action == "clarify"


@pytest.mark.asyncio
async def test_idk_reply_scaffolds_without_consuming_bridge_attempt():
    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="I don't know",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it?",
    )

    assert result.reply_type == "idk_or_stuck"
    assert result.consume_bridge_attempt is False
    assert result.support_action == "scaffold"


@pytest.mark.asyncio
async def test_in_lane_follow_still_activates_anchor(monkeypatch):
    bridge_follow_classifier = AsyncMock(
        return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="maybe it smells nice",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="How does it smell to her?",
        bridge_follow_classifier=bridge_follow_classifier,
    )

    assert result.reply_type == "in_lane_follow"
    assert result.bridge_followed is True
    assert result.consume_bridge_attempt is False


@pytest.mark.asyncio
async def test_valid_out_of_lane_answer_is_not_a_true_miss(monkeypatch):
    bridge_follow_classifier = AsyncMock(
        return_value={"bridge_followed": False, "reason": "no lane term"}
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="they can see it",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="How do you think they know the food is there before they take a bite?",
        bridge_follow_classifier=bridge_follow_classifier,
    )

    assert result.reply_type == "valid_out_of_lane_anchor_related"
    assert result.consume_bridge_attempt is False
    assert result.support_action == "steer"


@pytest.mark.asyncio
async def test_unrelated_answer_is_true_miss(monkeypatch):
    bridge_follow_classifier = AsyncMock(
        return_value={"bridge_followed": False, "reason": "no lane term"}
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="my shoes are blue",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it?",
        bridge_follow_classifier=bridge_follow_classifier,
    )

    assert result.reply_type == "true_miss"
    assert result.consume_bridge_attempt is True


def test_assistant_resets_pre_anchor_support_count_with_bridge_state():
    assistant = PaixuejiAssistant(client=MagicMock())
    assistant.pre_anchor_support_count = 2

    assistant.reset_bridge_state()

    assert assistant.pre_anchor_support_count == 0


def test_apply_resolution_initializes_pre_anchor_support_count():
    assistant = PaixuejiAssistant(client=MagicMock())
    assistant.pre_anchor_support_count = 2

    assistant.apply_resolution(ObjectResolutionResult(
        surface_object_name="cat food",
        visible_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        anchor_confirmation_needed=False,
        learning_anchor_active=False,
    ))

    assert assistant.pre_anchor_support_count == 0
