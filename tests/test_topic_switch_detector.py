# tests/test_topic_switch_detector.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from stream.topic_switch_detector import detect_topic_switch


@pytest.mark.asyncio
async def test_detect_topic_switch_should_switch():
    """Detector returns should_switch=True with valid target."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "should_switch": True,
        "target_attribute_id": "appearance.shape",
        "reason": "child asked about shape",
    })

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    class FakeProfile:
        attribute_id = "appearance.color"
        label = "color"

    class FakeFallback:
        attribute_id = "appearance.shape"
        label = "shape"

    primary = FakeProfile()
    fallbacks = (FakeFallback(),)

    should_switch, target_id, reason = await detect_topic_switch(
        conversation_history=[{"role": "user", "content": "What shape is it?"}],
        primary=primary,
        fallbacks=fallbacks,
        child_input="What shape is it?",
        config={"model_name": "gemini-2.0-flash-lite"},
        client=mock_client,
    )

    assert should_switch is True
    assert target_id == "appearance.shape"
    assert "shape" in reason.lower()


@pytest.mark.asyncio
async def test_detect_topic_switch_should_not_switch():
    """Detector returns should_switch=False."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "should_switch": False,
        "target_attribute_id": None,
        "reason": "still talking about color",
    })

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    class FakeProfile:
        attribute_id = "appearance.color"
        label = "color"

    primary = FakeProfile()
    fallbacks = ()

    should_switch, target_id, reason = await detect_topic_switch(
        conversation_history=[{"role": "user", "content": "It is red"}],
        primary=primary,
        fallbacks=fallbacks,
        child_input="It is red",
        config={"model_name": "gemini-2.0-flash-lite"},
        client=mock_client,
    )

    assert should_switch is False
    assert target_id is None


@pytest.mark.asyncio
async def test_detect_topic_switch_invalid_target_rejected():
    """Detector target not in fallbacks is rejected."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "should_switch": True,
        "target_attribute_id": "nonexistent.attr",
        "reason": "child mentioned it",
    })

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    class FakeProfile:
        attribute_id = "appearance.color"
        label = "color"

    class FakeFallback:
        attribute_id = "appearance.shape"
        label = "shape"

    primary = FakeProfile()
    fallbacks = (FakeFallback(),)

    should_switch, target_id, reason = await detect_topic_switch(
        conversation_history=[],
        primary=primary,
        fallbacks=fallbacks,
        child_input="blah",
        config={"model_name": "gemini-2.0-flash-lite"},
        client=mock_client,
    )

    assert should_switch is False
    assert target_id is None
    assert "invalid" in reason.lower()


@pytest.mark.asyncio
async def test_detect_topic_switch_json_parsing_with_fences():
    """Detector handles markdown-fenced JSON."""
    mock_response = MagicMock()
    mock_response.text = '```json\n{"should_switch": false, "target_attribute_id": null, "reason": "no"}\n```'

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    class FakeProfile:
        attribute_id = "appearance.color"
        label = "color"

    primary = FakeProfile()
    fallbacks = ()

    should_switch, target_id, reason = await detect_topic_switch(
        conversation_history=[],
        primary=primary,
        fallbacks=fallbacks,
        child_input="hi",
        config={"model_name": "gemini-2.0-flash-lite"},
        client=mock_client,
    )

    assert should_switch is False
    assert target_id is None


@pytest.mark.asyncio
async def test_detect_topic_switch_malformed_json_fallback():
    """Detector gracefully handles malformed JSON."""
    mock_response = MagicMock()
    mock_response.text = "not json at all"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    class FakeProfile:
        attribute_id = "appearance.color"
        label = "color"

    primary = FakeProfile()
    fallbacks = ()

    should_switch, target_id, reason = await detect_topic_switch(
        conversation_history=[],
        primary=primary,
        fallbacks=fallbacks,
        child_input="hi",
        config={"model_name": "gemini-2.0-flash-lite"},
        client=mock_client,
    )

    assert should_switch is False
    assert target_id is None
    assert "json_error" in reason.lower()
