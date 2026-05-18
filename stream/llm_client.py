"""Unified LLM client wrappers with 429 retry and parameter tracing."""

import asyncio
import time
import uuid
from typing import Union

from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from .errors import is_rate_limit_error, RateLimitError

_MAX_RETRIES = 2
_BACKOFF_DELAYS = [0.5, 1.5]


async def llm_generate(
    client: genai.Client,
    model: str,
    contents,
    config: Union[dict, GenerateContentConfig],
    call_name: str = "",
):
    """Non-streaming LLM call with 429 retry.

    Builds params once, passes identical objects into every retry attempt.
    Raises RateLimitError after all retries exhausted.
    Raises the original exception for non-429 errors.
    """
    call_id = uuid.uuid4().hex[:12]
    prompt_len = len(str(contents))
    last_exc = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            logger.info(
                "[LLM] call=%s call_id=%s attempt=%d/%d model=%s prompt_len=%d",
                call_name, call_id, attempt + 1, _MAX_RETRIES + 1, model, prompt_len,
            )
            t0 = time.time()
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            duration = time.time() - t0
            logger.info(
                "[LLM] call=%s call_id=%s success duration=%.3fs",
                call_name, call_id, duration,
            )
            return response
        except Exception as exc:
            last_exc = exc
            if is_rate_limit_error(exc) and attempt < _MAX_RETRIES:
                delay = _BACKOFF_DELAYS[attempt]
                logger.warning(
                    "[LLM] call=%s call_id=%s attempt=%d/%d 429, retry in %.1fs",
                    call_name, call_id, attempt + 1, _MAX_RETRIES + 1, delay,
                )
                await asyncio.sleep(delay)
            else:
                break

    if is_rate_limit_error(last_exc):
        logger.error(
            "[LLM] call=%s call_id=%s all retries failed: 429",
            call_name, call_id,
        )
        raise RateLimitError(str(last_exc)) from last_exc

    raise last_exc


async def llm_generate_stream(
    client: genai.Client,
    model: str,
    contents,
    config: Union[dict, GenerateContentConfig],
    call_name: str = "",
):
    """Streaming LLM call with 429 retry at stream-init time.

    Yields raw chunk objects from the Gemini API.
    Mid-stream 429s are not retried and propagate as-is.
    """
    call_id = uuid.uuid4().hex[:12]
    prompt_len = len(str(contents))
    stream = None
    last_exc = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            logger.info(
                "[LLM-STREAM] call=%s call_id=%s attempt=%d/%d model=%s prompt_len=%d",
                call_name, call_id, attempt + 1, _MAX_RETRIES + 1, model, prompt_len,
            )
            stream = await client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            )
            break
        except Exception as exc:
            last_exc = exc
            if is_rate_limit_error(exc) and attempt < _MAX_RETRIES:
                delay = _BACKOFF_DELAYS[attempt]
                logger.warning(
                    "[LLM-STREAM] call=%s call_id=%s attempt=%d/%d 429, retry in %.1fs",
                    call_name, call_id, attempt + 1, _MAX_RETRIES + 1, delay,
                )
                await asyncio.sleep(delay)
            else:
                break

    if stream is None:
        if is_rate_limit_error(last_exc):
            logger.error(
                "[LLM-STREAM] call=%s call_id=%s all retries failed: 429",
                call_name, call_id,
            )
            raise RateLimitError(str(last_exc)) from last_exc
        raise last_exc

    try:
        async for chunk in stream:
            yield chunk
    finally:
        if stream is not None:
            try:
                del stream
            except Exception:
                pass
