from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge_profile import BridgeProfile
from stream.validation import classify_pre_anchor_semantic_reply


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
async def test_semantic_reply_classifier_returns_followed():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"reply_type": "followed", "reason": "child answered how the cat eats it"}')
    )

    result = await classify_pre_anchor_semantic_reply(
        assistant=assistant,
        child_answer="with its mouth",
        previous_bridge_question="How does the cat start eating it?",
        bridge_profile=_profile(),
    )

    assert result == {"reply_type": "followed", "reason": "child answered how the cat eats it"}


@pytest.mark.asyncio
async def test_semantic_reply_classifier_returns_anchor_related_but_off_lane():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"reply_type": "anchor_related_but_off_lane", "reason": "child mentioned the bowl instead of the asked angle"}')
    )

    result = await classify_pre_anchor_semantic_reply(
        assistant=assistant,
        child_answer="she goes to the bowl",
        previous_bridge_question="Does the cat sniff it before eating?",
        bridge_profile=_profile(),
    )

    assert result == {
        "reply_type": "anchor_related_but_off_lane",
        "reason": "child mentioned the bowl instead of the asked angle",
    }


@pytest.mark.asyncio
async def test_semantic_reply_classifier_passes_previous_question_and_profile():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"reply_type": "true_miss", "reason": "reply did not engage the bridge"}')
    )

    await classify_pre_anchor_semantic_reply(
        assistant=assistant,
        child_answer="my shoes are blue",
        previous_bridge_question="Does the cat sniff it before eating?",
        bridge_profile=_profile(),
    )

    prompt = assistant.client.aio.models.generate_content.call_args.kwargs["contents"]
    assert "Previous bridge question" in prompt
    assert "Bridge intent" in prompt
    assert "Good question angles" in prompt
    assert "Steer-back rule" in prompt


@pytest.mark.asyncio
async def test_semantic_reply_classifier_handles_missing_client():
    result = await classify_pre_anchor_semantic_reply(
        assistant=MagicMock(),
        child_answer="with its mouth",
        previous_bridge_question="How does the cat start eating it?",
        bridge_profile=_profile(),
    )

    assert result == {"reply_type": "true_miss", "reason": "no semantic reply classifier available"}
