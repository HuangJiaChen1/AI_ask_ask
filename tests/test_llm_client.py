import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from stream.llm_client import llm_generate, llm_generate_stream
from stream.errors import RateLimitError


class Fake429(Exception):
    """Simulates a Gemini 429 / RESOURCE_EXHAUSTED error."""
    def __init__(self):
        super().__init__("429 RESOURCE_EXHAUSTED")
        self.code = 429


@pytest.mark.asyncio
async def test_llm_generate_retries_on_429_and_returns_response():
    """Simulate 429 on first 2 calls, success on 3rd."""
    client = MagicMock()
    response = MagicMock()
    response.text = "success"

    call_count = 0
    async def fake_generate(*, model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Fake429()
        return response

    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = fake_generate

    result = await llm_generate(
        client=client,
        model="gemini-test",
        contents="test prompt",
        config={"temperature": 0.1},
        call_name="test_classify",
    )

    assert call_count == 3
    assert result.text == "success"


@pytest.mark.asyncio
async def test_llm_generate_propagates_rate_limit_after_all_retries():
    """After all retries exhausted, raise RateLimitError."""
    client = MagicMock()

    async def fake_generate(*, model, contents, config):
        raise Fake429()

    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = fake_generate

    with pytest.raises(RateLimitError):
        await llm_generate(
            client=client,
            model="gemini-test",
            contents="test prompt",
            config={"temperature": 0.1},
            call_name="test_classify",
        )


@pytest.mark.asyncio
async def test_llm_generate_preserves_config_across_retries():
    """Same config object passed to every attempt."""
    client = MagicMock()
    call_count = 0
    captured_configs = []

    async def fake_generate(*, model, contents, config):
        nonlocal call_count
        call_count += 1
        captured_configs.append(config)
        if call_count <= 2:
            raise Fake429()
        return MagicMock(text="success")

    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = fake_generate

    original_config = {"temperature": 0.1, "max_output_tokens": 60}

    await llm_generate(
        client=client,
        model="gemini-test",
        contents="test prompt",
        config=original_config,
        call_name="test_classify",
    )

    assert len(captured_configs) == 3
    assert captured_configs[0] is original_config
    assert captured_configs[1] is original_config
    assert captured_configs[2] is original_config


@pytest.mark.asyncio
async def test_llm_generate_stream_retries_on_429():
    """Stream-init 429 retried; chunks yielded normally on success."""
    client = MagicMock()

    call_count = 0
    async def fake_stream(*, model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Fake429()

        async def gen():
            yield MagicMock(text="chunk1")
            yield MagicMock(text="chunk2")
        return gen()

    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content_stream = fake_stream

    chunks = []
    async for chunk in llm_generate_stream(
        client=client,
        model="gemini-test",
        contents="test prompt",
        config={"temperature": 0.7},
        call_name="test_stream",
    ):
        chunks.append(chunk)

    assert call_count == 3
    assert len(chunks) == 2
    assert chunks[0].text == "chunk1"
    assert chunks[1].text == "chunk2"


@pytest.mark.asyncio
async def test_llm_generate_stream_propagates_429_after_retries():
    """Stream-init 429 after all retries raises RateLimitError."""
    client = MagicMock()

    async def fake_stream(*, model, contents, config):
        raise Fake429()

    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content_stream = fake_stream

    with pytest.raises(RateLimitError):
        async for _ in llm_generate_stream(
            client=client,
            model="gemini-test",
            contents="test prompt",
            config={"temperature": 0.7},
            call_name="test_stream",
        ):
            pass
