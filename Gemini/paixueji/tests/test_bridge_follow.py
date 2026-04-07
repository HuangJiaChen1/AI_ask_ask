from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

from stream.validation import classify_bridge_follow


@pytest.mark.asyncio
async def test_food_for_follow_detects_clear_bridge_lane():
    assistant = MagicMock()

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="with its nose",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
    )

    assert result["bridge_followed"] is True


@pytest.mark.asyncio
async def test_used_with_follow_detects_use_lane():
    assistant = MagicMock()

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="you hold it",
        surface_object_name="dog leash",
        anchor_object_name="dog",
        relation="used_with",
    )

    assert result["bridge_followed"] is True


@pytest.mark.asyncio
async def test_related_to_is_conservative_without_explicit_anchor():
    assistant = MagicMock()

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="it is brown",
        surface_object_name="cat thing",
        anchor_object_name="cat",
        relation="related_to",
    )

    assert result["bridge_followed"] is False


@pytest.mark.asyncio
async def test_model_fallback_handles_ambiguous_bridge_reply():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": true, "reason": "model saw a valid bridge"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="it helps at dinner time",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
    )

    assert result == {"bridge_followed": True, "reason": "model saw a valid bridge"}


@pytest.mark.asyncio
async def test_model_fallback_receives_previous_bridge_question():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": true, "reason": "model used previous question"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="that is what she does",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
    )

    assert result == {"bridge_followed": True, "reason": "model used previous question"}
    prompt = assistant.client.aio.models.generate_content.call_args.kwargs["contents"]
    assert "Previous bridge question" in prompt
    assert "Does she use her nose" in prompt


@pytest.mark.asyncio
async def test_affirmative_reply_follows_previous_food_for_bridge_question():
    result = await classify_bridge_follow(
        assistant=SimpleNamespace(),
        child_answer="yep",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="When she gets to the bowl, does she use her nose to sniff it before she starts to eat?",
    )

    assert result["bridge_followed"] is True
    assert "affirmed previous bridge question" in result["reason"]


@pytest.mark.asyncio
async def test_hedged_affirmative_reply_follows_previous_food_for_bridge_question():
    result = await classify_bridge_follow(
        assistant=SimpleNamespace(),
        child_answer="she might",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Do you think your cat likes the smell of it when you open the bag?",
    )

    assert result["bridge_followed"] is True
    assert "affirmed previous bridge question" in result["reason"]


@pytest.mark.asyncio
async def test_affirmative_reply_without_previous_bridge_question_does_not_auto_follow():
    result = await classify_bridge_follow(
        assistant=SimpleNamespace(),
        child_answer="yep",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question=None,
    )

    assert result["bridge_followed"] is False


@pytest.mark.asyncio
async def test_negative_reply_to_previous_bridge_question_does_not_follow():
    result = await classify_bridge_follow(
        assistant=SimpleNamespace(),
        child_answer="not really",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
    )

    assert result["bridge_followed"] is False


@pytest.mark.asyncio
async def test_idk_reply_to_previous_bridge_question_does_not_follow():
    result = await classify_bridge_follow(
        assistant=SimpleNamespace(),
        child_answer="I don't know",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
    )

    assert result["bridge_followed"] is False


@pytest.mark.asyncio
async def test_affirmative_reply_to_unrelated_previous_question_does_not_auto_follow():
    result = await classify_bridge_follow(
        assistant=SimpleNamespace(),
        child_answer="yep",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="What does the cat food look like inside the bag?",
    )

    assert result["bridge_followed"] is False
