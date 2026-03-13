"""
Question stream generators for Paixueji assistant.

This module contains question-only stream generators:
- Introduction question for starting conversations

Functions:
    - ask_introduction_question_stream: First question about an object
"""
import time
from typing import AsyncGenerator

from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from schema import TokenUsage
import paixueji_prompts
from .utils import (
    clean_messages_for_api,
    convert_messages_to_gemini_format,
    SLOW_LLM_CALL_THRESHOLD
)


async def ask_introduction_question_stream(
    messages: list[dict],
    object_name: str,
    category_prompt: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    level3_category: str = "",
    fun_fact: str = "",
    fun_fact_hook: str = "",
    fun_fact_question: str = "",
    real_facts: str = ""
) -> AsyncGenerator[tuple[str, TokenUsage | None, str, dict], None]:
    """
    Stream first question about the object.

    Args:
        messages: Conversation history
        object_name: Name of object to ask about
        category_prompt: Category-specific guidance
        age_prompt: Age-specific guidance
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance
        level3_category: Level 3 category
        fun_fact: Grounded fun fact to share (empty string if unavailable)
        fun_fact_hook: Excited greeting hook (empty string if unavailable)
        fun_fact_question: Follow-up question from fun fact (empty string if unavailable)
        real_facts: Grounded real facts about the object (empty string if unavailable)

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far, decision_info)
        Note: decision_info contains new_object_name which is always None for introduction
    """
    start_time = time.time()
    logger.info(f"ask_introduction_question_stream started | object={object_name}, age={age}, has_fun_fact={bool(fun_fact)}")

    # Build grounded facts section dynamically
    if fun_fact:
        grounded_facts_section = (
            f"\nVERIFIED FACTS ABOUT {object_name}:\n{real_facts}\n\n"
            f"FUN FACT TO SHARE:\n{fun_fact}"
        )
        fun_fact_instruction = "Share the fun fact naturally in your greeting, then ask the FOCUS GUIDANCE question."
    else:
        grounded_facts_section = ""
        fun_fact_instruction = "Ask your FIRST question following the FOCUS GUIDANCE."

    prompts = paixueji_prompts.get_prompts()
    introduction_prompt = prompts['introduction_prompt'].format(
        object_name=object_name,
        category_prompt=category_prompt,
        age_prompt=age_prompt,
        age=age,
        grounded_facts_section=grounded_facts_section,
        fun_fact_instruction=fun_fact_instruction
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
        logger.error(f"answer_question_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
