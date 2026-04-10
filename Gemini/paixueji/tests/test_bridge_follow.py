from unittest.mock import AsyncMock, MagicMock

import pytest

from stream.validation import classify_bridge_follow


@pytest.mark.asyncio
async def test_food_for_follow_detects_clear_bridge_lane_via_model():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": true, "reason": "answered in the food_for lane"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="with its nose",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
    )

    assert result == {"bridge_followed": True, "reason": "answered in the food_for lane"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_used_with_follow_detects_use_lane_via_model():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": true, "reason": "answered how the leash is used"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="you hold it",
        surface_object_name="dog leash",
        anchor_object_name="dog",
        relation="used_with",
    )

    assert result == {"bridge_followed": True, "reason": "answered how the leash is used"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_related_to_is_conservative_without_explicit_anchor():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": false, "reason": "reply stayed vague"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="it is brown",
        surface_object_name="cat thing",
        anchor_object_name="cat",
        relation="related_to",
    )

    assert result == {"bridge_followed": False, "reason": "reply stayed vague"}
    assert assistant.client.aio.models.generate_content.await_count == 1


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
async def test_explicit_anchor_mention_defers_to_model_verdict():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": false, "reason": "mentioning cat alone did not answer the bridge"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="cat",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
    )

    assert result == {
        "bridge_followed": False,
        "reason": "mentioning cat alone did not answer the bridge",
    }
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_teeth_reply_uses_model_only_and_can_follow():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": true, "reason": "answered how the cat eats the food"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="I think just with her teeth",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="When your cat eats, does she crunch it with her teeth or lick it instead?",
    )

    assert result == {"bridge_followed": True, "reason": "answered how the cat eats the food"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_affirmative_reply_defers_to_model_for_previous_food_for_bridge_question():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": true, "reason": "affirmed the prior bridge question"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="yep",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="When she gets to the bowl, does she use her nose to sniff it before she starts to eat?",
    )

    assert result == {"bridge_followed": True, "reason": "affirmed the prior bridge question"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_hedged_affirmative_reply_defers_to_model():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": true, "reason": "hedged yes still answered the bridge"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="she might",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Do you think your cat likes the smell of it when you open the bag?",
    )

    assert result == {"bridge_followed": True, "reason": "hedged yes still answered the bridge"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_affirmative_reply_without_previous_bridge_question_does_not_auto_follow():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": false, "reason": "bare yes without context is not enough"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="yep",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question=None,
    )

    assert result == {"bridge_followed": False, "reason": "bare yes without context is not enough"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_negative_reply_to_previous_bridge_question_defers_to_model():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": false, "reason": "child declined the bridge"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="not really",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
    )

    assert result == {"bridge_followed": False, "reason": "child declined the bridge"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_idk_reply_to_previous_bridge_question_defers_to_model():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": false, "reason": "child did not answer the bridge"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="I don't know",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="Does she use her nose to sniff it before she starts to eat?",
    )

    assert result == {"bridge_followed": False, "reason": "child did not answer the bridge"}
    assert assistant.client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_affirmative_reply_to_unrelated_previous_question_defers_to_model():
    assistant = MagicMock()
    assistant.config = {"model_name": "mock"}
    assistant.client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text='{"bridge_followed": false, "reason": "surface-only question was not a bridge"}')
    )

    result = await classify_bridge_follow(
        assistant=assistant,
        child_answer="yep",
        surface_object_name="cat food",
        anchor_object_name="cat",
        relation="food_for",
        previous_bridge_question="What does the cat food look like inside the bag?",
    )

    assert result == {"bridge_followed": False, "reason": "surface-only question was not a bridge"}
    assert assistant.client.aio.models.generate_content.await_count == 1
