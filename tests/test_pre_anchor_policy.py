from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge_profile import BridgeProfile
from object_resolver import ObjectResolutionResult
from paixueji_assistant import PaixuejiAssistant
from pre_anchor_policy import classify_pre_anchor_reply


def _profile() -> BridgeProfile:
    return BridgeProfile(
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_intent="bridge from the food to how the cat notices and eats it.",
        good_question_angles=("how the cat smells it", "how the cat starts eating it"),
        avoid_angles=("unrelated cat body parts",),
        steer_back_rule="acknowledge briefly, then return to noticing or eating.",
        focus_cues=("smell", "eat"),
    )


@pytest.mark.asyncio
async def test_clarification_request_does_not_consume_bridge_attempt(monkeypatch):
    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="whay do you mean?",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
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
        bridge_profile=_profile(),
        previous_bridge_question="Does she use her nose to sniff it?",
    )

    assert result.reply_type == "idk_or_stuck"
    assert result.consume_bridge_attempt is False
    assert result.support_action == "scaffold"


@pytest.mark.asyncio
async def test_followed_reply_activates_anchor(monkeypatch):
    semantic_reply_classifier = AsyncMock(
        return_value={"reply_type": "followed", "reason": "child answered the bridge question"}
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="maybe it smells nice",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
        previous_bridge_question="How does it smell to her?",
        semantic_reply_classifier=semantic_reply_classifier,
    )

    assert result.reply_type == "in_lane_follow"
    assert result.bridge_followed is True
    assert result.consume_bridge_attempt is False


@pytest.mark.asyncio
async def test_anchor_related_but_off_lane_answer_is_not_a_true_miss(monkeypatch):
    semantic_reply_classifier = AsyncMock(
        return_value={
            "reply_type": "anchor_related_but_off_lane",
            "reason": "child stayed on the anchor but answered a different angle",
        }
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="they can see it",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
        previous_bridge_question="How do you think they know the food is there before they take a bite?",
        semantic_reply_classifier=semantic_reply_classifier,
    )

    assert result.reply_type == "anchor_related_but_off_lane"
    assert result.consume_bridge_attempt is False
    assert result.support_action == "steer"


@pytest.mark.asyncio
async def test_unrelated_answer_is_true_miss(monkeypatch):
    semantic_reply_classifier = AsyncMock(
        return_value={"reply_type": "true_miss", "reason": "child did not engage the bridge"}
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="my shoes are blue",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
        previous_bridge_question="Does she use her nose to sniff it?",
        semantic_reply_classifier=semantic_reply_classifier,
    )

    assert result.reply_type == "true_miss"
    assert result.consume_bridge_attempt is True


@pytest.mark.asyncio
async def test_negative_reply_short_circuits_without_semantic_model():
    semantic_reply_classifier = AsyncMock()

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="no",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
        previous_bridge_question="Does she use her nose to sniff it?",
        semantic_reply_classifier=semantic_reply_classifier,
    )

    assert result.reply_type == "negative_or_refusal"
    assert result.consume_bridge_attempt is True
    semantic_reply_classifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_content_bearing_negative_runs_semantic_classifier_and_can_steer():
    semantic_reply_classifier = AsyncMock(
        return_value={
            "reply_type": "anchor_related_but_off_lane",
            "reason": "child corrected the premise and added anchor context",
        }
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="she does not really use her nose, she is used to where the food is",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
        semantic_reply_classifier=semantic_reply_classifier,
    )

    assert result.reply_type == "anchor_related_but_off_lane"
    assert result.consume_bridge_attempt is False
    assert result.support_action == "steer"
    semantic_reply_classifier.assert_awaited_once()


@pytest.mark.asyncio
async def test_bare_not_really_still_short_circuits_without_semantic_model():
    semantic_reply_classifier = AsyncMock()

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="not really",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
        semantic_reply_classifier=semantic_reply_classifier,
    )

    assert result.reply_type == "negative_or_refusal"
    assert result.consume_bridge_attempt is True
    semantic_reply_classifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_content_bearing_negative_can_still_be_true_miss():
    semantic_reply_classifier = AsyncMock(
        return_value={"reply_type": "true_miss", "reason": "child did not engage the bridge"}
    )

    result = await classify_pre_anchor_reply(
        assistant=SimpleNamespace(),
        child_answer="not really, my shoes are blue",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        bridge_profile=_profile(),
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
        semantic_reply_classifier=semantic_reply_classifier,
    )

    assert result.reply_type == "true_miss"
    assert result.consume_bridge_attempt is True
    semantic_reply_classifier.assert_awaited_once()


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
        bridge_profile=_profile(),
    ))

    assert assistant.pre_anchor_support_count == 0
