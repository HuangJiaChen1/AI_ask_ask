"""
Question stream generators for Paixueji assistant.

This module contains question-only stream generators:
- Introduction question for starting conversations
- Follow-up question after correct-answer confirmation

Functions:
    - ask_introduction_question_stream: First question about an object
    - ask_followup_question_stream: Follow-up question after correct-answer node
"""
import time
from typing import AsyncGenerator

from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from schema import TokenUsage
import paixueji_prompts
from .errors import raise_if_rate_limited
from .utils import (
    clean_messages_for_api,
    convert_messages_to_gemini_format,
    SLOW_LLM_CALL_THRESHOLD
)


async def ask_introduction_question_stream(
    messages: list[dict],
    object_name: str,
    surface_object_name: str | None,
    anchor_object_name: str | None,
    intro_mode: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    hook_type_section: str = "",
    knowledge_context: str = "",
    bridge_context: str = "",
) -> AsyncGenerator[tuple[str, TokenUsage | None, str, dict], None]:
    """
    Stream first question about the object.

    Args:
        messages: Conversation history
        object_name: Name of object to ask about
        age_prompt: Age-specific guidance
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance
        hook_type_section: Pre-formatted hook type block injected into Beat 4 of the prompt
        knowledge_context: Grounded intro facts to keep the opening concrete

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far, decision_info)
        Note: decision_info contains new_object_name which is always None for introduction
    """
    start_time = time.time()
    logger.info(f"ask_introduction_question_stream started | object={object_name}, age={age}")

    prompts = paixueji_prompts.get_prompts()
    if intro_mode == "anchor_bridge":
        base_prompt = prompts["introduction_prompt"].format(
            object_name=surface_object_name or object_name,
            age_prompt=age_prompt,
            age=age,
            hook_type_section=hook_type_section,
            knowledge_context=knowledge_context,
        )
        guardrail = paixueji_prompts.ANCHOR_BRIDGE_INTRO_GUARDRAIL_PROMPT.format(
            bridge_context=bridge_context or "",
        )
        introduction_prompt = (
            f"{base_prompt}\n\n{guardrail}"
        )
    elif intro_mode == "anchor_confirmation":
        introduction_prompt = prompts["anchor_confirmation_intro_prompt"].format(
            surface_object_name=surface_object_name or object_name,
            anchor_object_name=anchor_object_name or object_name,
            age_prompt=age_prompt,
            age=age,
        )
    elif intro_mode == "unknown_object":
        introduction_prompt = prompts["unknown_object_intro_prompt"].format(
            surface_object_name=surface_object_name or object_name,
            age_prompt=age_prompt,
            age=age,
        )
    else:
        introduction_prompt = prompts['introduction_prompt'].format(
            object_name=object_name,
            age_prompt=age_prompt,
            age=age,
            hook_type_section=hook_type_section,
            knowledge_context=knowledge_context,
        )

    # Prepare messages with introduction prompt
    messages_to_send = messages + [{"role": "user", "content": introduction_prompt}]

    # Clean messages for API
    clean_messages = clean_messages_for_api(messages_to_send)
    logger.debug(f"Messages prepared for API | count={len(clean_messages)}")

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None

    stream = None
    try:
        logger.debug(f"Sending {len(contents)} messages to Gemini API")

        # Configure generation
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 2000),
            system_instruction=system_instruction if system_instruction else None
        )

        # Call streaming API
        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Log stream type for debugging
        logger.debug(f"Stream object type: {type(stream).__name__}")

        # Prepare decision info (no switching in introduction)
        decision_info = {
            'new_object_name': None,
            'detected_object_name': None,
            'switch_decision_reasoning': None
        }

        # Yield chunks as they arrive
        chunk_count = 0
        async for chunk in stream:
            if chunk.text:
                chunk_count += 1
                full_response += chunk.text
                logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                yield (chunk.text, None, full_response, decision_info)

        # Note: Gemini API doesn't provide token usage in streaming mode
        # We'll leave token_usage as None
        logger.debug("Gemini streaming API does not provide token usage in stream mode")

    except Exception as e:
        duration = time.time() - start_time
        logger.error("answer_question_stream LLM error | error={} duration={:.3f}s", str(e), duration, exc_info=True)
        raise_if_rate_limited(e)
        # Still yield what we have so far (even if incomplete)
        if full_response:
            decision_info = {
                'new_object_name': None,
                'detected_object_name': None,
                'switch_decision_reasoning': None
            }
            yield ("", token_usage, full_response, decision_info)
        return
    finally:
        # Always attempt cleanup via deletion
        if stream is not None:
            try:
                del stream
                logger.debug('Cleaned up stream via del in finally block')
            except:
                pass

    duration = time.time() - start_time
    logger.info(
        f"ask_introduction_question_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    if duration > SLOW_LLM_CALL_THRESHOLD:
        logger.warning(f"Slow LLM call | duration={duration:.3f}s exceeded threshold {SLOW_LLM_CALL_THRESHOLD}s")

    # Final yield with token usage (None for Gemini streaming)
    decision_info = {
        'new_object_name': None,
        'detected_object_name': None,
        'switch_decision_reasoning': None
    }
    yield ("", token_usage, full_response, decision_info)


async def ask_followup_question_stream(
    messages: list[dict],
    object_name: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    knowledge_context: str = "",
    resolution_guardrails: str = "",
    surface_only_mode: bool = False,
    surface_object_name: str = "",
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Stream a follow-up question after the correct-answer confirmation+wow-fact burst.

    Args:
        knowledge_context: Full current-object KB context for playful inspiration.

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"ask_followup_question_stream started | object={object_name}, age={age}")
    if not surface_only_mode and "No supported anchor is active" in (resolution_guardrails or ""):
        surface_only_mode = True
        surface_object_name = surface_object_name or object_name

    prompts = paixueji_prompts.get_prompts()
    followup_prompt = prompts['followup_question_prompt'].format(
        object_name=object_name,
        age=age,
        age_prompt=age_prompt,
        knowledge_context=knowledge_context,
    )
    if surface_only_mode:
        surface_only_prompt = prompts["unresolved_surface_only_prompt"].format(
            surface_object_name=surface_object_name or object_name
        )
        followup_prompt = f"{surface_only_prompt}\n\n{followup_prompt}"
    elif resolution_guardrails:
        followup_prompt = f"{resolution_guardrails}\n\n{followup_prompt}"

    messages_to_send = messages + [{"role": "user", "content": followup_prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    full_response = ""
    token_usage = None
    stream = None
    try:
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
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)
    except Exception as e:
        duration = time.time() - start_time
        logger.error("ask_followup_question_stream LLM error | error={} duration={:.3f}s", str(e), duration, exc_info=True)
        raise_if_rate_limited(e)
        if full_response:
            yield ("", token_usage, full_response)
        return
    finally:
        if stream is not None:
            try:
                del stream
            except:
                pass

    duration = time.time() - start_time
    logger.info(
        f"ask_followup_question_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )
    if duration > SLOW_LLM_CALL_THRESHOLD:
        logger.warning(f"Slow LLM call | duration={duration:.3f}s exceeded threshold {SLOW_LLM_CALL_THRESHOLD}s")

    yield ("", token_usage, full_response)


async def ask_attribute_intro_stream(
    *,
    messages: list[dict],
    object_name: str,
    attribute_label: str,
    activity_target: str,
    attribute_branch: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
) -> AsyncGenerator[tuple[str, TokenUsage | None, str, dict], None]:
    prompts = paixueji_prompts.get_prompts()
    prompt = prompts["attribute_intro_prompt"].format(
        object_name=object_name,
        attribute_label=attribute_label,
        activity_target=activity_target,
        attribute_branch=attribute_branch,
        age_prompt=age_prompt,
        age=age,
    )
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    full_response = ""
    token_usage = None
    stream = None
    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 2000),
            system_instruction=system_instruction if system_instruction else None,
        )
        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )
        decision_info = {
            "new_object_name": None,
            "detected_object_name": None,
            "switch_decision_reasoning": None,
        }
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response, decision_info)
    except Exception as e:
        logger.error("ask_attribute_intro_stream error | error={}", str(e), exc_info=True)
        raise_if_rate_limited(e)
        if full_response:
            yield ("", token_usage, full_response, {})
        return
    finally:
        if stream is not None:
            try:
                del stream
            except Exception:
                pass

    yield ("", token_usage, full_response, {})
