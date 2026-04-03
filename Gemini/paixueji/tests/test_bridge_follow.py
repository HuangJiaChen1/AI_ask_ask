from unittest.mock import AsyncMock, MagicMock

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
