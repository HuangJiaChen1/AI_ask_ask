# Unified LLM 429 Retry Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all 15+ ad-hoc Gemini API calls with unified wrappers that retry on 429, preserve parameters across retries, and propagate rate-limit errors transparently instead of silently falling back.

**Architecture:** A single `stream/llm_client.py` module providing `llm_generate()` (non-streaming) and `llm_generate_stream()` (streaming). Both build parameters once, retry only 429 with exponential backoff (0.5s, 1.5s), and raise `RateLimitError` after exhaustion. No semaphore — retry spacing alone reduces collision rate. Call sites migrate in two phases: non-streaming first (higher impact, fewer files), then streaming (lower risk, mechanical changes).

**Tech Stack:** Python 3.13, `google.genai`, `pytest`, `loguru`, `asyncio`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `stream/llm_client.py` | **Create** | Unified wrappers: `llm_generate()` + `llm_generate_stream()` with 429 retry, parameter tracing, call_id correlation |
| `tests/test_llm_client.py` | **Create** | Unit tests: mock 429 on first N calls, verify retry count, backoff timing, parameter preservation |
| `stream/__init__.py` | Modify | Export `llm_generate`, `llm_generate_stream` |
| `stream/validation.py` | Modify | 4 call sites: `classify_intent`, `classify_pre_anchor_semantic_reply`, `validate_bridge_activation_kb_question`, `validate_bridge_activation_answer` |
| `stream/topic_switch_detector.py` | Modify | 1 call site: `detect_topic_switch` |
| `stream/fun_fact.py` | Modify | 2 call sites: Step 1 grounding + Step 2 structuring |
| `stream/exploration_loader.py` | Modify | 1 call site: `infer_domain` |
| `attribute_activity.py` | Modify | 1 call site: attribute selection LLM call |
| `paixueji_app.py` | Modify | Add `except RateLimitError: raise` at `classify_intent` and `detect_topic_switch` call sites (attribute lane) |
| `stream/response_generators.py` | Modify (Phase 2) | 8 streaming generators |
| `stream/question_generators.py` | Modify (Phase 2) | 4 streaming generators |

---

## Task 1: Create `stream/llm_client.py` with TDD

**Files:**
- Create: `stream/llm_client.py`
- Test: `tests/test_llm_client.py`

**Design constraints from grilling:**
- No semaphore (user explicitly rejected)
- 3 attempts total (1 initial + 2 retries)
- Backoff delays: 0.5s, 1.5s
- Retry only 429 / RESOURCE_EXHAUSTED
- Minimal logging: `call_name`, `call_id`, `attempt`, `model`, `prompt_len`
- Non-streaming: propagate `RateLimitError` after retries
- Streaming: retry at stream-init only, yield raw chunk objects
- Parameters built once, reused across all retry attempts (no re-formatting)

### Step 1: Write the failing test

Create `tests/test_llm_client.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from stream.llm_client import llm_generate, llm_generate_stream
from stream.errors import RateLimitError


class Fake429(Exception):
    def __init__(self):
        super().__init__("429 RESOURCE_EXHAUSTED")


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
```

- [ ] **Step 1 done**

### Step 2: Run the failing tests

```bash
pytest tests/test_llm_client.py -v
```

**Expected output:**
```
tests/test_llm_client.py::test_llm_generate_retries_on_429_and_returns_response FAILED
tests/test_llm_client.py::test_llm_generate_propagates_rate_limit_after_all_retries FAILED
tests/test_llm_client.py::test_llm_generate_preserves_config_across_retries FAILED
tests/test_llm_client.py::test_llm_generate_stream_retries_on_429 FAILED
tests/test_llm_client.py::test_llm_generate_stream_propagates_429_after_retries FAILED
```

All fail with `ImportError: cannot import name 'llm_generate' from 'stream.llm_client'` (module does not exist yet).

- [ ] **Step 2 done**

### Step 3: Implement `stream/llm_client.py`

Create `stream/llm_client.py`:

```python
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
```

- [ ] **Step 3 done**

### Step 4: Run tests to verify they pass

```bash
pytest tests/test_llm_client.py -v
```

**Expected output:**
```
tests/test_llm_client.py::test_llm_generate_retries_on_429_and_returns_response PASSED
tests/test_llm_client.py::test_llm_generate_propagates_rate_limit_after_all_retries PASSED
tests/test_llm_client.py::test_llm_generate_preserves_config_across_retries PASSED
tests/test_llm_client.py::test_llm_generate_stream_retries_on_429 PASSED
tests/test_llm_client.py::test_llm_generate_stream_propagates_429_after_retries PASSED
```

- [ ] **Step 4 done**

### Step 5: Commit

```bash
git add stream/llm_client.py tests/test_llm_client.py
git commit -m "feat: unified LLM client wrappers with 429 retry and parameter tracing

- llm_generate: non-streaming with exponential backoff (0.5s, 1.5s)
- llm_generate_stream: streaming with stream-init retry only
- call_id correlation across retries for log tracing
- parameter objects reused across attempts (no re-formatting)
- all non-429 errors propagate as-is, 429s become RateLimitError after retries"
```

- [ ] **Step 5 done**

---

## Task 2: Export Wrappers from `stream/__init__.py`

**Files:**
- Modify: `stream/__init__.py`

### Step 1: Add imports and `__all__` entries

In `stream/__init__.py`, add after the `# Utilities` block:

```python
# LLM client wrappers (unified retry + tracing)
from .llm_client import (
    llm_generate,
    llm_generate_stream,
)
```

In `__all__`, add after `'SLOW_LLM_CALL_THRESHOLD':

```python
    # LLM client wrappers
    'llm_generate',
    'llm_generate_stream',
```

- [ ] **Step 1 done**

### Step 2: Run existing tests to ensure no import regressions

```bash
pytest tests/ -v --co -q
```

**Expected:** Test collection succeeds with no import errors.

- [ ] **Step 2 done**

### Step 3: Commit

```bash
git add stream/__init__.py
git commit -m "chore: export llm_generate and llm_generate_stream from stream package"
```

- [ ] **Step 3 done**

---

## Task 3: Migrate `validation.py:classify_intent`

**Files:**
- Modify: `stream/validation.py` (lines 81-152)
- Modify: `paixueji_app.py` (lines 1682-1690)

**Why this first:** This is the #1 user pain point — 429s here silently degrade to `classification_fallback`, making it impossible to distinguish node failure from logic bugs.

### Step 1: Replace direct API call with wrapper in `validation.py`

Add imports at the top of `stream/validation.py` (after existing imports):

```python
from .llm_client import llm_generate
from .errors import RateLimitError
```

Replace the `try` block in `classify_intent` (lines 81-152):

**Before:**
```python
    try:
        t0 = time.time()
        response = await assistant.client.aio.models.generate_content(
            model=assistant.config["model_name"],
            contents=prompt,
            config={
                "temperature": 0.1,
                "max_output_tokens": 60
            }
        )
        t1 = time.time()
        logger.info(f"[CLASSIFY] LLM call duration: {t1 - t0:.3f}s")
        text = response.text or ""
        # ... rest of parsing (lines 96-140, unchanged) ...
        return result
    except Exception as e:
        logger.error(f"[CLASSIFY] Error: {e}, using fallback-freeform path")
        import traceback
        traceback.print_exc()
        return {
            "intent_type": None,
            "new_object": None,
            "reasoning": f"Classification error: {str(e)}",
            "classification_status": "failed",
            "classification_failure_reason": "exception",
        }
```

**After:**
```python
    try:
        t0 = time.time()
        response = await llm_generate(
            client=assistant.client,
            model=assistant.config["model_name"],
            contents=prompt,
            config={
                "temperature": 0.1,
                "max_output_tokens": 60
            },
            call_name="classify_intent",
        )
        t1 = time.time()
        logger.info(f"[CLASSIFY] LLM call duration: {t1 - t0:.3f}s")
        text = response.text or ""
        # ... rest of parsing (lines 96-140, unchanged) ...
        return result
    except RateLimitError:
        raise
    except Exception as e:
        logger.error(f"[CLASSIFY] Error: {e}, using fallback-freeform path")
        import traceback
        traceback.print_exc()
        return {
            "intent_type": None,
            "new_object": None,
            "reasoning": f"Classification error: {str(e)}",
            "classification_status": "failed",
            "classification_failure_reason": "exception",
        }
```

The only changes: (1) `llm_generate` replaces direct call, (2) `except RateLimitError: raise` inserted before the broad `except Exception`. The parsing code (lines 96-140) remains untouched.

- [ ] **Step 1 done**

### Step 2: Update `paixueji_app.py` call site to propagate `RateLimitError`

Add import near the top of `paixueji_app.py` (after existing `from stream import ...`):

```python
from stream.errors import RateLimitError
```

Replace the `try/except` at lines 1682-1690:

**Before:**
```python
                    try:
                        intent_result = intent_future.result(timeout=10)
                        intent_type_lower = (intent_result.get("intent_type") or "classification_fallback").lower()
                        attribute_reason = intent_result.get("reasoning") or "intent classified for discovery continuation"
                    except Exception as exc:
                        intent_type_lower = "classification_fallback"
                        attribute_reason = f"intent classification fallback: {exc}"
                        # Cancel switch future if intent failed
                        switch_future.cancel()
```

**After:**
```python
                    try:
                        intent_result = intent_future.result(timeout=10)
                        intent_type_lower = (intent_result.get("intent_type") or "classification_fallback").lower()
                        attribute_reason = intent_result.get("reasoning") or "intent classified for discovery continuation"
                    except RateLimitError:
                        raise
                    except Exception as exc:
                        intent_type_lower = "classification_fallback"
                        attribute_reason = f"intent classification fallback: {exc}"
                        # Cancel switch future if intent failed
                        switch_future.cancel()
```

- [ ] **Step 2 done**

### Step 3: Run existing tests

```bash
pytest tests/ -v -k "not test_llm_client"
```

**Expected:** All existing tests pass. No regressions.

- [ ] **Step 3 done**

### Step 4: Commit

```bash
git add stream/validation.py paixueji_app.py
git commit -m "feat: migrate classify_intent to llm_generate wrapper

- 429 no longer silently falls back to classification_fallback
- RateLimitError propagates to frontend for transparent 'model busy' message
- non-429 errors still fallback gracefully"
```

- [ ] **Step 4 done**

---

## Task 4: Migrate `topic_switch_detector.py`

**Files:**
- Modify: `stream/topic_switch_detector.py` (lines 84-129)
- Modify: `paixueji_app.py` (lines 1692-1696)

**Why this second:** #2 pain point — missing topic switches cause the system to keep asking about the old topic while the child has moved on.

### Step 1: Replace direct API call with wrapper

Add imports at the top of `stream/topic_switch_detector.py` (after existing imports):

```python
from .llm_client import llm_generate
from .errors import RateLimitError
```

Replace the `try` block in `detect_topic_switch` (lines 84-129):

**Before:**
```python
    try:
        gen_config = GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=150,
            system_instruction=system_instruction if system_instruction else None,
        )
        response = await client.aio.models.generate_content(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )
        raw_text = response.text or ""
        # ... parsing (lines 98-122, unchanged) ...
        return False, None, reason or "no_switch_detected"
    except json.JSONDecodeError as exc:
        logger.warning("[TOPIC_SWITCH_DETECTOR] JSON parse error: %s | raw=%r", exc, raw_text[:200])
        return False, None, f"json_error: {exc}"
    except Exception as exc:
        logger.warning("[TOPIC_SWITCH_DETECTOR] error: %s", exc)
        return False, None, f"error: {exc}"
```

**After:**
```python
    try:
        gen_config = GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=150,
            system_instruction=system_instruction if system_instruction else None,
        )
        response = await llm_generate(
            client=client,
            model=config["model_name"],
            contents=contents,
            config=gen_config,
            call_name="detect_topic_switch",
        )
        raw_text = response.text or ""
        # ... parsing (lines 98-122, unchanged) ...
        return False, None, reason or "no_switch_detected"
    except RateLimitError:
        raise
    except json.JSONDecodeError as exc:
        logger.warning("[TOPIC_SWITCH_DETECTOR] JSON parse error: %s | raw=%r", exc, raw_text[:200])
        return False, None, f"json_error: {exc}"
    except Exception as exc:
        logger.warning("[TOPIC_SWITCH_DETECTOR] error: %s", exc)
        return False, None, f"error: {exc}"
```

- [ ] **Step 1 done**

### Step 2: Update `paixueji_app.py` call site

Replace the `try/except` at lines 1692-1696:

**Before:**
```python
                    try:
                        should_switch, switch_target_id, switch_reason = switch_future.result(timeout=10)
                    except Exception as exc:
                        logger.warning("[TOPIC_SWITCH] detector error: %s", exc)
                        should_switch, switch_target_id, switch_reason = False, None, f"detector_error: {exc}"
```

**After:**
```python
                    try:
                        should_switch, switch_target_id, switch_reason = switch_future.result(timeout=10)
                    except RateLimitError:
                        raise
                    except Exception as exc:
                        logger.warning("[TOPIC_SWITCH] detector error: %s", exc)
                        should_switch, switch_target_id, switch_reason = False, None, f"detector_error: {exc}"
```

- [ ] **Step 2 done**

### Step 3: Run existing tests

```bash
pytest tests/ -v -k "not test_llm_client"
```

**Expected:** All pass.

- [ ] **Step 3 done**

### Step 4: Commit

```bash
git add stream/topic_switch_detector.py paixueji_app.py
git commit -m "feat: migrate detect_topic_switch to llm_generate wrapper

- 429 propagates as RateLimitError instead of silently returning no_switch"
```

- [ ] **Step 4 done**

---

## Task 5: Migrate Remaining Validation Classifiers

**Files:**
- Modify: `stream/validation.py` (3 call sites)

### Step 1: Migrate `classify_pre_anchor_semantic_reply`

In `stream/validation.py`, replace lines 218-229:

**Before:**
```python
    try:
        response = await generate_content(
            model=config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
        )
        payload, _, _ = extract_json_object(response.text or "")
    except Exception:
        payload = None
```

**After:**
```python
    try:
        response = await llm_generate(
            client=client,
            model=config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
            call_name="classify_pre_anchor",
        )
        payload, _, _ = extract_json_object(response.text or "")
    except RateLimitError:
        raise
    except Exception:
        payload = None
```

- [ ] **Step 1 done**

### Step 2: Migrate `validate_bridge_activation_kb_question`

Replace lines 309-317:

**Before:**
```python
    try:
        response = await assistant.client.aio.models.generate_content(
            model=assistant.config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
        )
        payload = json.loads(response.text or "{}")
    except Exception:
        payload = {}
```

**After:**
```python
    try:
        response = await llm_generate(
            client=assistant.client,
            model=assistant.config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
            call_name="validate_kb_question",
        )
        payload = json.loads(response.text or "{}")
    except RateLimitError:
        raise
    except Exception:
        payload = {}
```

- [ ] **Step 2 done**

### Step 3: Migrate `validate_bridge_activation_answer`

Replace lines 364-372:

**Before:**
```python
    try:
        response = await assistant.client.aio.models.generate_content(
            model=assistant.config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
        )
        payload = json.loads(response.text or "{}")
    except Exception:
        payload = {}
```

**After:**
```python
    try:
        response = await llm_generate(
            client=assistant.client,
            model=assistant.config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
            call_name="validate_answer",
        )
        payload = json.loads(response.text or "{}")
    except RateLimitError:
        raise
    except Exception:
        payload = {}
```

- [ ] **Step 3 done**

### Step 4: Run existing tests

```bash
pytest tests/ -v -k "not test_llm_client"
```

**Expected:** All pass.

- [ ] **Step 4 done**

### Step 5: Commit

```bash
git add stream/validation.py
git commit -m "feat: migrate remaining validation classifiers to llm_generate wrapper

- classify_pre_anchor_semantic_reply
- validate_bridge_activation_kb_question
- validate_bridge_activation_answer
- all propagate RateLimitError on 429 instead of silent fallback"
```

- [ ] **Step 5 done**

---

## Task 6: Migrate `fun_fact`, `exploration_loader`, `attribute_activity`

**Files:**
- Modify: `stream/fun_fact.py` (2 call sites)
- Modify: `stream/exploration_loader.py` (1 call site)
- Modify: `attribute_activity.py` (1 call site)

### Step 1: Migrate `fun_fact.py` Step 1 and Step 2

Add imports at the top of `stream/fun_fact.py` (after existing imports):

```python
from stream.llm_client import llm_generate
from stream.errors import RateLimitError
```

Replace Step 1 (lines 136-158):

**Before:**
```python
        grounding_response = await client.aio.models.generate_content(
            model=grounding_model,
            contents=grounding_prompt,
            config={
                "tools": [Tool(google_search=GoogleSearch())],
                "temperature": 0.3,
                "max_output_tokens": 1000,
                "safety_settings": safety_settings,
            }
        )
```

**After:**
```python
        grounding_response = await llm_generate(
            client=client,
            model=grounding_model,
            contents=grounding_prompt,
            config={
                "tools": [Tool(google_search=GoogleSearch())],
                "temperature": 0.3,
                "max_output_tokens": 1000,
                "safety_settings": safety_settings,
            },
            call_name="fun_fact_step1",
        )
```

And add `except RateLimitError: raise` before `except Exception as e:` at line 156.

Replace Step 2 (lines 171-180):

**Before:**
```python
        structuring_response = await client.aio.models.generate_content(
            model=grounding_model,
            contents=structuring_prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": 800,
                "safety_settings": safety_settings,
            }
        )
```

**After:**
```python
        structuring_response = await llm_generate(
            client=client,
            model=grounding_model,
            contents=structuring_prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": 800,
                "safety_settings": safety_settings,
            },
            call_name="fun_fact_step2",
        )
```

And add `except RateLimitError: raise` before `except json.JSONDecodeError` and `except Exception` at lines 213-218.

- [ ] **Step 1 done**

### Step 2: Migrate `exploration_loader.py:infer_domain`

Add imports at the top of `stream/exploration_loader.py` (after existing imports):

```python
from stream.llm_client import llm_generate
from stream.errors import RateLimitError
```

Replace lines 206-217:

**Before:**
```python
        response = await client.aio.models.generate_content(
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 60},
        )
```

**After:**
```python
        response = await llm_generate(
            client=client,
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 60},
            call_name="infer_domain",
        )
```

And add `except RateLimitError: raise` before `except Exception:` at line 216.

- [ ] **Step 2 done**

### Step 3: Migrate `attribute_activity.py`

Add imports near the top of `attribute_activity.py`:

```python
from stream import llm_generate
from stream.errors import RateLimitError
```

Replace the generate_content call (around line 180):

**Before:**
```python
        response = await client.aio.models.generate_content(
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 256},
        )
```

**After:**
```python
        response = await llm_generate(
            client=client,
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 256},
            call_name="select_attribute",
        )
```

And add `except RateLimitError: raise` before the broad `except Exception` at the same level.

- [ ] **Step 3 done**

### Step 4: Run existing tests

```bash
pytest tests/ -v -k "not test_llm_client"
```

**Expected:** All pass.

- [ ] **Step 4 done**

### Step 5: Commit

```bash
git add stream/fun_fact.py stream/exploration_loader.py attribute_activity.py
git commit -m "feat: migrate fun_fact, infer_domain, select_attribute to llm_generate wrapper

- all propagate RateLimitError on 429 instead of silent fallback"
```

- [ ] **Step 5 done**

---

## Task 7: Phase 2 — Migrate Streaming Generators

**Files:**
- Modify: `stream/response_generators.py` (8 generators)
- Modify: `stream/question_generators.py` (4 generators)

**Pattern for all 12 generators:**
1. Add `from .llm_client import llm_generate_stream` to imports
2. Delete `stream = None` initialization
3. Replace `stream = await client.aio.models.generate_content_stream(...)` with `async for chunk in llm_generate_stream(...):`
4. Delete `finally` block that does `del stream`
5. Keep `raise_if_rate_limited(e)` in `except` blocks (wrapper handles stream-init 429, this handles mid-stream 429)

### Step 1: Add import to `response_generators.py`

Add after line 18:

```python
from .llm_client import llm_generate_stream
```

- [ ] **Step 1 done**

### Step 2: Migrate `generate_intent_response_stream`

Replace lines 101-135:

**Before:**
```python
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.7),
            max_output_tokens=config.get("max_tokens", 500),
            system_instruction=system_instruction if system_instruction else None
        )

        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error("generate_intent_response_stream error | intent={} error={} duration={:.3f}s", intent_lower, str(e), duration, exc_info=True)
        raise_if_rate_limited(e)
        if full_response:
            yield ("", token_usage, full_response)
        return
    finally:
        if stream is not None:
            try:
                del stream
            except Exception:
                pass
```

**After:**
```python
    full_response = ""
    token_usage = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.7),
            max_output_tokens=config.get("max_tokens", 500),
            system_instruction=system_instruction if system_instruction else None
        )

        async for chunk in llm_generate_stream(
            client=client,
            model=config["model_name"],
            contents=contents,
            config=gen_config,
            call_name="generate_intent_response",
        ):
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error("generate_intent_response_stream error | intent={} error={} duration={:.3f}s", intent_lower, str(e), duration, exc_info=True)
        raise_if_rate_limited(e)
        if full_response:
            yield ("", token_usage, full_response)
        return
```

- [ ] **Step 2 done**

### Step 3: Migrate `generate_classification_fallback_stream`

Apply the exact same pattern as Step 2 to `generate_classification_fallback_stream` (lines 183-220):

- Delete `stream = None`
- Replace `stream = await client.aio.models.generate_content_stream(...)` with `async for chunk in llm_generate_stream(client=client, model=config["model_name"], contents=contents, config=gen_config, call_name="generate_classification_fallback"):`
- Delete `finally` block
- Keep `raise_if_rate_limited(e)` in `except`

- [ ] **Step 3 done**

### Step 4: Migrate remaining 6 response generators

Apply the exact same pattern to:

| Generator | Line | call_name |
|-----------|------|-----------|
| `generate_attribute_activation_response_stream` | ~316 | `generate_attribute_activation_response` |
| `generate_category_activation_response_stream` | ~378 | `generate_category_activation_response` |
| `generate_topic_switch_response_stream` | ~452 | `generate_topic_switch_response` |
| `generate_bridge_support_response_stream` | ~529 | `generate_bridge_support_response` |
| `generate_bridge_activation_response_stream` | ~618 | `generate_bridge_activation_response` |
| `generate_bridge_retry_response_stream` | ~697 | `generate_bridge_retry_response` |

For each: delete `stream = None`, replace `stream = await client.aio.models.generate_content_stream(...)` with `async for chunk in llm_generate_stream(..., call_name="..."):`, delete `finally` block.

- [ ] **Step 4 done**

### Step 5: Add import to `question_generators.py`

Add after line 21:

```python
from .llm_client import llm_generate_stream
```

- [ ] **Step 5 done**

### Step 6: Migrate `ask_introduction_question_stream`

Replace lines 116-177:

**Before:**
```python
        stream = None
        try:
            logger.debug(f"Sending {len(contents)} messages to Gemini API")

            gen_config = GenerateContentConfig(
                temperature=config.get("temperature", 0.3),
                max_output_tokens=config.get("max_tokens", 2000),
                system_instruction=system_instruction if system_instruction else None
            )

            stream = await client.aio.models.generate_content_stream(
                model=config["model_name"],
                contents=contents,
                config=gen_config
            )

            decision_info = {
                'new_object_name': None,
                'detected_object_name': None,
                'switch_decision_reasoning': None
            }

            chunk_count = 0
            async for chunk in stream:
                if chunk.text:
                    chunk_count += 1
                    full_response += chunk.text
                    logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                    yield (chunk.text, None, full_response, decision_info)

        except Exception as e:
            ...
            raise_if_rate_limited(e)
            ...
        finally:
            if stream is not None:
                try:
                    del stream
                except:
                    pass
```

**After:**
```python
        try:
            logger.debug(f"Sending {len(contents)} messages to Gemini API")

            gen_config = GenerateContentConfig(
                temperature=config.get("temperature", 0.3),
                max_output_tokens=config.get("max_tokens", 2000),
                system_instruction=system_instruction if system_instruction else None
            )

            decision_info = {
                'new_object_name': None,
                'detected_object_name': None,
                'switch_decision_reasoning': None
            }

            chunk_count = 0
            async for chunk in llm_generate_stream(
                client=client,
                model=config["model_name"],
                contents=contents,
                config=gen_config,
                call_name="ask_introduction_question",
            ):
                if chunk.text:
                    chunk_count += 1
                    full_response += chunk.text
                    logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                    yield (chunk.text, None, full_response, decision_info)

        except Exception as e:
            ...
            raise_if_rate_limited(e)
            ...
```

Note: `decision_info` moves before the `async for` loop so it's defined even if `llm_generate_stream` fails at stream-init.

- [ ] **Step 6 done**

### Step 7: Migrate remaining 3 question generators

Apply the exact same pattern to:

| Generator | Line | call_name |
|-----------|------|-----------|
| `ask_followup_question_stream` | ~274 | `ask_followup_question` |
| `ask_attribute_intro_stream` | ~346 | `ask_attribute_intro` |
| `ask_category_intro_stream` | ~408 | `ask_category_intro` |

For each: delete `stream = None`, replace `stream = await client.aio.models.generate_content_stream(...)` with `async for chunk in llm_generate_stream(..., call_name="..."):`, delete `finally` block.

- [ ] **Step 7 done**

### Step 8: Run existing tests

```bash
pytest tests/ -v
```

**Expected:** All pass.

- [ ] **Step 8 done**

### Step 9: Commit

```bash
git add stream/response_generators.py stream/question_generators.py
git commit -m "feat: migrate all streaming generators to llm_generate_stream wrapper

- 12 generators migrated (8 response + 4 question)
- stream-init 429 retried with 0.5s, 1.5s backoff
- raw chunk objects yielded unchanged (minimal generator code changes)
- mid-stream 429 still propagates via existing raise_if_rate_limited"
```

- [ ] **Step 9 done**

---

## Task 8: Integration Verification

**Goal:** Confirm the wrapper works end-to-end in a real conversation.

### Step 1: Start the dev server

```bash
python paixueji_app.py
```

Wait for: `[INFO] Paixueji server started on http://127.0.0.1:5000`

- [ ] **Step 1 done**

### Step 2: Run a conversation through the attribute lane

Open `http://127.0.0.1:5000` in browser. Start a conversation with any object. Send 3-4 messages.

Watch the server logs for:
- `[LLM] call=classify_intent call_id=... attempt=1/3 ...` — normal path
- `[LLM] call=detect_topic_switch call_id=... attempt=1/3 ...` — normal path
- `[LLM-STREAM] call=ask_followup_question_stream call_id=... attempt=1/3 ...` — normal path

- [ ] **Step 2 done**

### Step 3: Verify call_id persists across retries (simulated)

Since 429s are hard to trigger on demand, manually verify the code path by temporarily editing `stream/llm_client.py` to raise Fake429 on the first attempt:

```python
# Temporary test hack — add at top of llm_generate:
_test_force_429 = True

# In the try block, before the API call:
if _test_force_429 and attempt == 0:
    raise Fake429("429 RESOURCE_EXHAUSTED")
```

Restart server, send one message. Check logs:
- `attempt=1/3` should show `429, retry in 0.5s`
- `attempt=2/3` should succeed
- Both lines share the same `call_id`

Remove the test hack after verification.

- [ ] **Step 3 done**

### Step 4: Final commit

```bash
git add -A
git commit -m "test: verify wrapper integration in dev server

- confirmed call_id correlation across retries
- confirmed parameter preservation
- all streaming and non-streaming paths exercised"
```

- [ ] **Step 4 done**

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Unified wrapper module (`llm_client.py`) — Task 1
- [x] Non-streaming retry with backoff — Task 1
- [x] Streaming retry at stream-init — Task 1
- [x] Parameter preservation across retries — Task 1 (tested)
- [x] No semaphore — design decision, no code needed
- [x] All non-streaming calls propagate 429 — Tasks 3-6
- [x] Streaming calls yield raw chunks — Task 7
- [x] Minimal logging (call_name, call_id, attempt, model, prompt_len) — Task 1
- [x] Phased migration (non-streaming first, then streaming) — Task ordering

**2. Placeholder scan:**
- [x] No "TBD", "TODO", "implement later"
- [x] No "add appropriate error handling" without code
- [x] No "Similar to Task N" across tasks (within Task 7, pattern repetition is explicit)
- [x] Every step shows actual code or exact commands

**3. Type consistency:**
- [x] `llm_generate` signature consistent across all call sites: `(client, model, contents, config, call_name="")`
- [x] `llm_generate_stream` signature consistent: `(client, model, contents, config, call_name="")`
- [x] `RateLimitError` imported from `stream.errors` everywhere
- [x] `call_name` values are consistent and descriptive

**4. Edge cases covered:**
- [x] Empty/silent input fast-path in `classify_intent` (lines 49-57) is before the wrapper call — untouched
- [x] `classify_pre_anchor_semantic_reply` guard checks (lines 194-203) are before wrapper call — untouched
- [x] `validate_bridge_activation_kb_question` deterministic shortcut (lines 277-290) is before wrapper call — untouched
- [x] `validate_bridge_activation_answer` heuristic shortcut (lines 337-345) is before wrapper call — untouched
- [x] `infer_domain` mappings DB lookup (lines 193-195) is before wrapper call — untouched
- [x] Streaming `except` blocks still call `raise_if_rate_limited(e)` for mid-stream 429s
