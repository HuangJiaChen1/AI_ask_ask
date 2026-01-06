"""
Streaming functions for Paixueji assistant.

This module provides async streaming responses for the Paixueji assistant,
where the LLM asks questions about objects and children answer.
"""
import copy
import json
import os
import time
from typing import AsyncGenerator

from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig
from loguru import logger

from schema import StreamChunk, TokenUsage
import paixueji_prompts

# Configure loguru for production
logger.add(
    "logs/paixueji_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    backtrace=True,
    diagnose=True,
)

# Performance thresholds for warnings (in seconds)
SLOW_LLM_CALL_THRESHOLD = 5.0


def safe_print(message):
    """Print message with fallback for encoding errors."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('ascii', 'replace').decode('ascii'))


def clean_messages_for_api(messages: list[dict]) -> list[dict]:
    """
    Remove internal tracking fields from messages before sending to API.

    Args:
        messages: List of message dicts that may contain internal fields

    Returns:
        Cleaned list of messages with only standard fields (role, content)
    """
    cleaned = []
    for msg in messages:
        cleaned_msg = {
            k: v
            for k, v in msg.items()
            if k in ["role", "content"]  # Only keep standard fields
        }
        cleaned.append(cleaned_msg)
    return cleaned


def prepare_messages_for_streaming(messages: list[dict], age_prompt: str = "") -> list[dict]:
    """
    Safely prepare messages for streaming API calls without mutating the original list.

    This function:
    1. Creates a shallow copy of the messages list (10-100x faster than deep copy)
    2. Cleans messages to only include role/content
    3. Optionally appends age-specific guidance to system message

    Args:
        messages: Original message list (will not be modified)
        age_prompt: Optional age-specific guidance to append to system message

    Returns:
        New cleaned message list ready for API calls
    """
    # Shallow copy is sufficient - we only modify the list structure, not the dicts
    # This is 10-100x faster than deep copy for long conversation histories
    messages_copy = messages.copy()

    # Clean messages
    messages_copy = clean_messages_for_api(messages_copy)

    # Append age guidance to system message if provided
    if age_prompt and messages_copy and messages_copy[0].get("role") == "system":
        # Need to copy the first dict since we're modifying its content
        messages_copy[0] = messages_copy[0].copy()
        messages_copy[0]["content"] += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"

    return messages_copy


def convert_messages_to_gemini_format(messages: list[dict]) -> tuple[str, list[dict]]:
    """
    Convert OpenAI-style messages to Gemini format.

    OpenAI format: [{"role": "system"/"user"/"assistant", "content": "..."}]
    Gemini format: (system_instruction, contents_array)

    Returns:
        tuple: (system_instruction_str, contents_array)
    """
    system_instruction = ""
    contents = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "system":
            # System messages become system_instruction
            system_instruction += content + "\n"
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            # Convert "assistant" to "model" for Gemini
            contents.append({"role": "model", "parts": [{"text": content}]})

    return system_instruction.strip(), contents


async def ask_introduction_question_stream(
    messages: list[dict],
    object_name: str,
    category_prompt: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    level3_category: str = "",
    focus_prompt: str = ""
) -> AsyncGenerator[tuple[str, TokenUsage | None, str, str | None], None]:
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
        focus_prompt: Focus strategy guidance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far, new_object_name_or_None)
        Note: new_object_name is always None for introduction questions (no topic switching)
    """
    start_time = time.time()
    logger.info(f"ask_introduction_question_stream started | object={object_name}, age={age}")

    prompts = paixueji_prompts.get_prompts()
    introduction_prompt = prompts['introduction_prompt'].format(
        object_name=object_name,
        category_prompt=category_prompt,
        age_prompt=age_prompt,
        age=age,
        focus_prompt=focus_prompt
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
        stream = client.models.generate_content_stream(
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
        for chunk in stream:
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


# ============================================================================
# DUAL-PARALLEL API FUNCTIONS: Response-Only and Question-Only Generators
# ============================================================================

async def generate_feedback_response_stream(
    messages: list[dict],
    child_answer: str,
    object_name: str,
    age: int,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate ONLY celebratory feedback for correct answers. NO follow-up questions.

    This function is part of the dual-parallel architecture where response generation
    is decoupled from question generation.

    Args:
        messages: Conversation history
        child_answer: The child's correct answer
        object_name: Name of object being discussed
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_feedback_response_stream started | object={object_name}, age={age}")

    # Build feedback-only prompt
    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['feedback_response_prompt'].format(
        child_answer=child_answer,
        object_name=object_name,
        age=age
    )

    # Prepare messages
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 500),  # Shorter for feedback only
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks
        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_feedback_response_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_feedback_response_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    # Final yield
    yield ("", token_usage, full_response)


async def generate_explanation_response_stream(
    messages: list[dict],
    child_answer: str,
    object_name: str,
    previous_question: str,
    age: int,
    category_prompt: str,
    age_prompt: str,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate ONLY explanation when child says "I don't know". NO follow-up questions.

    This function is part of the dual-parallel architecture where response generation
    is decoupled from question generation.

    Args:
        messages: Conversation history
        child_answer: The child's unclear/stuck answer
        object_name: Name of object being discussed
        previous_question: The question that was asked
        age: Child's age
        category_prompt: Category-specific guidance
        age_prompt: Age-specific guidance
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_explanation_response_stream started | object={object_name}, age={age}")

    # Build explanation-only prompt
    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['explanation_response_prompt'].format(
        child_answer=child_answer,
        previous_question=previous_question,
        object_name=object_name,
        age=age
    )

    # Prepare messages
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 800),
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks
        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_explanation_response_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_explanation_response_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    # Final yield
    yield ("", token_usage, full_response)


async def generate_correction_response_stream(
    messages: list[dict],
    child_answer: str,
    object_name: str,
    previous_question: str,
    correctness_reasoning: str,
    age: int,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate ONLY gentle correction for wrong answers. NO follow-up questions.

    This function is part of the dual-parallel architecture where response generation
    is decoupled from question generation.

    Args:
        messages: Conversation history
        child_answer: The child's incorrect answer
        object_name: Name of object being discussed
        previous_question: The question that was asked
        correctness_reasoning: AI's reasoning for why answer is wrong
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_correction_response_stream started | object={object_name}, age={age}")

    # Build correction-only prompt
    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['correction_response_prompt'].format(
        child_answer=child_answer,
        object_name=object_name,
        correctness_reasoning=correctness_reasoning,
        age=age
    )

    # Prepare messages
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 600),
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks
        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_correction_response_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_correction_response_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    # Final yield
    yield ("", token_usage, full_response)


async def generate_topic_switch_response_stream(
    messages: list[dict],
    previous_object: str,
    new_object: str,
    age: int,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate ONLY celebration for topic transitions. NO follow-up questions.

    This function is part of the dual-parallel architecture where response generation
    is decoupled from question generation.

    Args:
        messages: Conversation history
        previous_object: The previous object being discussed
        new_object: The new object child wants to discuss
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_topic_switch_response_stream started | {previous_object} -> {new_object}, age={age}")

    # Build topic switch celebration prompt
    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['topic_switch_response_prompt'].format(
        previous_object=previous_object,
        new_object=new_object,
        age=age
    )

    # Prepare messages
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 400),
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks
        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_topic_switch_response_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_topic_switch_response_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    # Final yield
    yield ("", token_usage, full_response)


async def generate_natural_topic_completion_stream(
    messages: list[dict],
    current_object: str,
    age: int,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate response for natural topic completion (after exploring an object deeply).

    This function congratulates the child on exploring the current object and asks
    what they'd like to explore next. Does NOT provide a list of options - lets them
    use natural language to choose.

    Args:
        messages: Conversation history
        current_object: Current object being discussed
        age: Child's age
        config: Configuration dict
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_natural_topic_completion_stream started | object={current_object}, age={age}")

    prompt = f"""The child has done an excellent job exploring {current_object}!

YOUR TASK:
1. Warmly congratulate them on their exploration of {current_object}
2. Express excitement about what they've learned
3. Ask them what they'd like to explore next (let them choose naturally)
4. Provide a list of options
5. Match vocabulary to age {age}
6. Respond naturally (NOT JSON)
7. Keep it brief and enthusiastic

"""

    # Prepare messages
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=300,
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks
        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_natural_topic_completion_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_natural_topic_completion_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    # Final yield
    yield ("", token_usage, full_response)


async def generate_explicit_switch_response_stream(
    messages: list[dict],
    suggested_objects: list[str],
    age: int,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate response for explicit switch requests (e.g., "talk about something else").

    This function is specifically for when the child explicitly asks to switch topics.
    Unlike generate_object_selection_response_stream, it does NOT congratulate them
    on exploring the previous object (since they might not have explored it much).

    Args:
        messages: Conversation history
        suggested_objects: List of objects to present
        age: Child's age
        config: Configuration dict
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_explicit_switch_response_stream started | objects={suggested_objects}, age={age}")

    # Build object selection prompt for explicit switches
    objects_list = ", ".join(suggested_objects[:-1]) + f", or {suggested_objects[-1]}"

    prompt = f"""The child has explicitly requested to switch topics and explore something new.

YOUR TASK:
1. Warmly agree to switch topics (e.g., "Sure! That sounds fun!", "Okay, let's talk about something else!")
2. Introduce the new choices in an exciting way
3. Present the options: {objects_list}
4. DO NOT ask any follow-up questions about the previous topic
5. DO NOT congratulate them on exploring the previous topic
6. Match vocabulary to age {age}
7. Respond naturally (NOT JSON)
8. Keep it brief and enthusiastic

"""

    # Prepare messages
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=300,
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks
        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_explicit_switch_response_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_explicit_switch_response_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    # Final yield
    yield ("", token_usage, full_response)


async def generate_followup_question_stream(
    messages: list[dict],
    object_name: str,
    correct_count: int,
    category_prompt: str,
    age_prompt: str,
    age: int,
    focus_prompt: str,
    config: dict,
    client: genai.Client,
    is_topic_switch: bool = False
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate ONLY follow-up question based on focus strategy. NO responses or explanations.

    This function is part of the dual-parallel architecture where question generation
    is decoupled from response generation.

    Args:
        messages: Conversation history
        object_name: Name of object being discussed (may be new object if switched)
        correct_count: Number of correct answers so far
        category_prompt: Category-specific guidance
        age_prompt: Age-specific guidance
        age: Child's age
        focus_prompt: Focus strategy guidance
        config: Configuration dict with model settings
        client: Gemini client instance
        is_topic_switch: Whether this follows a topic switch

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_followup_question_stream started | object={object_name}, age={age}, is_switch={is_topic_switch}")

    # Build question-only prompt
    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['followup_question_prompt'].format(
        object_name=object_name,
        age=age,
        focus_prompt=focus_prompt,
        category_prompt=category_prompt,
        age_prompt=age_prompt
    )

    # Prepare messages
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None
    stream = None

    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 600),
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks
        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_followup_question_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_followup_question_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    # Final yield
    yield ("", token_usage, full_response)


# ============================================================================
# VALIDATION & DECISION FUNCTIONS
# ============================================================================

def decide_topic_switch_with_validation(assistant, child_answer: str, object_name: str, age: int, focus_mode: str | None = None, is_awaiting_topic_selection: bool = False):
    """
    Unified AI validation: Checks engagement, factual correctness, AND topic switching in single call.

    Args:
        assistant: PaixuejiAssistant instance
        child_answer: The child's answer text
        object_name: Current object being discussed
        age: Child's age
        focus_mode: Current focus mode
        is_awaiting_topic_selection: Whether we are waiting for user to pick a topic from a list

    Returns:
        dict: Decision result
    """
    # Extract the last question the model asked from conversation history
    conversation_history = assistant.conversation_history
    last_model_question = None

    # Find the most recent assistant message
    for msg in reversed(conversation_history):
        if msg.get('role') == 'assistant':
            last_model_question = msg.get('content')
            break

    if not last_model_question:
        last_model_question = "Unknown (first interaction)"

    # Add specific instructions for topic selection state
    topic_selection_instructions = ""
    if is_awaiting_topic_selection:
        topic_selection_instructions = """
SPECIAL CONTEXT: AWAITING TOPIC SELECTION
The previous message offered the child a choice of topics (e.g., "A, B, or C?").

RULES FOR THIS STATE:
1. **Uncertainty / Request to Pick**: If the child expresses uncertainty (e.g., "not sure", "don't know", "no idea") or asks YOU to pick (e.g., "you decide", "surprise me"):
   - **DECISION: SWITCH**
   - **new_object**: Pick one of the valid options from the previous message (e.g., "Apple").
   - **switching_reasoning**: "Child expressed uncertainty or asked me to pick."

2. **Valid Choice**: If child names a valid object:
   - **DECISION: SWITCH**
   - **new_object**: The object they named.

3. **New Topic**: If child talks about something else entirely:
   - **DECISION: SWITCH** (to their new topic).
"""

    # Build contextual THREE-PART validation prompt
    decision_prompt = f"""You are an educational AI helping a {age}-year-old child learn through conversation.

CONTEXT:
- Current Topic: {object_name}
- Focus Mode: {focus_mode or 'depth'} (how we ask questions, NOT a validation rule)
- Last Question You Asked: "{last_model_question}"
- Child's Answer: "{child_answer}"
{topic_selection_instructions}

YOUR THREE-PART TASK:
You must evaluate THREE aspects of the child's answer in one evaluation:
1. ENGAGEMENT: Is the child trying to answer or are they stuck?
2. FACTUAL CORRECTNESS: If engaged, is their answer factually accurate?
3. TOPIC SWITCHING: Should we switch to a new object?

---

PART 1: ENGAGEMENT CHECK
Is the child engaged and trying to answer, or are they stuck?

STUCK INDICATORS:
- Explicit uncertainty: "I don't know", "idk", "dunno", "not sure", "no idea", "help me"
- Very short/unclear: "??", "um", "uh", answers with 3 or fewer characters
- Empty attempts: just punctuation, just numbers

ENGAGED INDICATORS:
- Any substantive attempt to answer with real words
- Descriptive responses, even if wrong
- Comparisons, examples, or explanations

---

PART 2: FACTUAL CORRECTNESS (only evaluate if child is ENGAGED)
If the child is engaged, is their answer factually accurate given the question asked?

EVALUATION CRITERIA:
- Check if answer matches reality for the question asked
- Consider age {age} - accept age-appropriate simplifications
- Accept partial correctness (e.g., "apples grow outside" is TRUE for age 3-4)
- Be strict on obvious contradictions (e.g., "sun is cold" → FALSE)

---

PART 3: TOPIC SWITCHING
Should we switch to a new object or continue with current one?

SWITCHING GUIDELINES:
1. **Invited Object Naming**: I asked child to name new object and they did → SWITCH
2. **Direct Answer**: If the child's noun is the **direct answer** to your question, do **NOT** switch. (e.g., Q: "What do monkeys eat?" A: "Bananas" → CONTINUE).
3. **Categories & Parts**: If the child names the category (e.g., "Banana is a **fruit**") or a part (e.g., "**skin**", "**seeds**") of the current object → **CONTINUE**.
4. **True Off-Topic**: Only SWITCH if the child **ignores** your question to talk about a completely different, unrelated object.
5. **Explicit Request**: Child says "let's talk about X" → SWITCH
6. **Comparison/Description**: Child mentions object in passing ("red like cherry") → CONTINUE
7. **Stuck**: Child says "I don't know" → CONTINUE (UNLESS "SPECIAL CONTEXT" above applies)

CRITICAL CHECK:
Before deciding SWITCH, ask: "Is this new word just the *answer* to my question?" If yes, decision MUST be **CONTINUE**.

VALIDATION (always apply):
- Only SWITCH if new object is real and concrete (not abstract)
- Ignore made-up/nonsense words → CONTINUE
- Celestial objects (sun, moon, stars) are valid

---

RESPOND WITH VALID JSON:
{{
    "decision": "SWITCH" or "CONTINUE",
    "new_object": "ObjectName" or null,
    "switching_reasoning": "1-2 sentence explanation for switch/continue decision",
    "is_engaged": true or false,
    "is_factually_correct": true or false,
    "correctness_reasoning": "1-2 sentence explanation for why answer is right or wrong"
}}

COMPLETE EXAMPLES:

Example 1: Correct answer, no switching
Q: "What color is the apple?"
A: "Red"
→ {{
    "decision": "CONTINUE",
    "new_object": null,
    "switching_reasoning": "Child directly answered the question. No topic change needed.",
    "is_engaged": true,
    "is_factually_correct": true,
    "correctness_reasoning": "Red is a common and correct color for apples."
}}

Example 2: Noun as Answer (NO SWITCH)
Q: "What do we find inside the skin?"
A: "We find fruit"
→ {{
    "decision": "CONTINUE",
    "new_object": null,
    "switching_reasoning": "'Fruit' is the answer to the question 'what is inside', not a request to change topics.",
    "is_engaged": true,
    "is_factually_correct": true,
    "correctness_reasoning": "The inside of the object is indeed fruit."
}}

Example 3: Wrong answer, no switching
Q: "What color is the apple?"
A: "Blue"
→ {{
    "decision": "CONTINUE",
    "new_object": null,
    "switching_reasoning": "Child answered the question (no new object mentioned).",
    "is_engaged": true,
    "is_factually_correct": false,
    "correctness_reasoning": "Apples are not blue. Common colors are red, green, or yellow."
}}

Example 4: Correct answer WITH switching (invited naming)
Q: "Can you name another red fruit?"
A: "Strawberry"
→ {{
    "decision": "SWITCH",
    "new_object": "strawberry",
    "switching_reasoning": "I invited child to name a new object and they did.",
    "is_engaged": true,
    "is_factually_correct": true,
    "correctness_reasoning": "Strawberries are indeed red fruits."
}}

Example 5: Wrong answer WITH attempted switching (but incorrect)
Q: "Can you name another red fruit?"
A: "Banana"
→ {{
    "decision": "CONTINUE",
    "new_object": null,
    "switching_reasoning": "Child attempted to name a fruit, but it doesn't match the color criteria (red).",
    "is_engaged": true,
    "is_factually_correct": false,
    "correctness_reasoning": "Bananas are yellow, not red. Child confused the color."
}}

Example 6: Stuck/Not engaged
Q: "What color is the apple?"
A: "idk"
→ {{
    "decision": "CONTINUE",
    "new_object": null,
    "switching_reasoning": "Child is stuck, no topic change.",
    "is_engaged": false,
    "is_factually_correct": false,
    "correctness_reasoning": "Child didn't attempt an answer."
}}

Example 7: Wrong shape comparison (from user's log)
Q: "Can you think of something else that's shaped like a banana, all long and curved?"
A: "Apples have the same shape"
→ {{
    "decision": "CONTINUE",
    "new_object": null,
    "switching_reasoning": "Child attempted to answer the question but didn't match criteria.",
    "is_engaged": true,
    "is_factually_correct": false,
    "correctness_reasoning": "Apples are round, bananas are long and curved. They have different shapes."
}}

Now evaluate the current situation:
"""

    try:
        # Call Gemini with JSON mode / structured output
        import json
        response = assistant.client.models.generate_content(
            model=assistant.config.get("model", "gemini-2.0-flash-exp"),
            contents=decision_prompt,
            config={
                "response_mime_type": "application/json",  # Force JSON output
                "temperature": 0.1,  # Low temp for consistent decisions
                "max_output_tokens": 200  # Increased from 150 for additional fields
            }
        )

        # Parse JSON response
        decision_data = json.loads(response.text)

        logger.info(
            f"[VALIDATE] {decision_data['decision']} | "
            f"new_object={decision_data.get('new_object')}, "
            f"engaged={decision_data.get('is_engaged')}, "
            f"correct={decision_data.get('is_factually_correct')}, "
            f"switch_reasoning={decision_data.get('switching_reasoning')}, "
            f"correctness_reasoning={decision_data.get('correctness_reasoning')}"
        )

        return decision_data

    except Exception as e:
        logger.error(f"[VALIDATE] Error: {e}, defaulting to safe state")
        import traceback
        traceback.print_exc()
        return {
            'decision': 'CONTINUE',
            'new_object': None,
            'switching_reasoning': f'Error in validation: {str(e)}',
            'is_engaged': True,  # Safe default - continue conversation
            'is_factually_correct': True,  # Safe default - don't incorrectly penalize
            'correctness_reasoning': 'Could not evaluate due to error'
        }


async def ask_followup_question_stream(
    messages: list[dict],
    child_answer: str,
    assistant,  # PaixuejiAssistant instance
    object_name: str,
    correct_count: int,
    category_prompt: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    level3_category: str = "",
    focus_prompt: str = "",
    focus_mode: str | None = None,
    precomputed_decision: dict | None = None
) -> AsyncGenerator[tuple[str, TokenUsage | None, str, str | None], None]:
    """
    Stream follow-up question based on child's answer.

    Args:
        messages: Conversation history
        child_answer: The child's previous answer
        assistant: PaixuejiAssistant instance for topic switching
        object_name: Name of object being discussed
        correct_count: Number of correct answers so far
        category_prompt: Category-specific guidance
        age_prompt: Age-specific guidance
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance
        level3_category: Level 3 category
        focus_prompt: Focus strategy guidance
        focus_mode: The focus mode key (e.g., depth, width_color)
        precomputed_decision: Optional validation result from earlier call

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far, new_object_name_or_None)
    """
    start_time = time.time()
    logger.info(f"ask_followup_question_stream started | object={object_name}, correct_count={correct_count}, answer_length={len(child_answer)}")

    # STEP 1: DECISION - Should we switch topics?
    new_topic_name = None
    detected_object_name = None
    switch_decision_reasoning = None

    # Use precomputed decision if available (avoids double validation calls)
    if precomputed_decision:
        decision = precomputed_decision
        logger.info(f"Using precomputed decision: {decision.get('decision')}")
    else:
        # Call unified validation (we already know answer is engaged+correct since we're in followup path)
        # We only care about topic switching decision here
        decision = decide_topic_switch_with_validation(
            assistant=assistant,
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            focus_mode=focus_mode  # Context only, not a rule
        )

    # Capture reasoning from AI decision (updated field name)
    switch_decision_reasoning = decision.get('switching_reasoning', 'No reasoning provided')

    # STEP 2: HANDLE DECISION & BUILD APPROPRIATE PROMPT
    prompts = paixueji_prompts.get_prompts()

    if decision['decision'] == 'SWITCH':
        if decision['new_object']:
            # TOPIC SWITCH: Child named a new object!
            new_topic_name = decision['new_object']
            previous_object = object_name  # Save for prompt
            logger.info(f"[SWITCH] Decision: Switch from {previous_object} to {new_topic_name}")

            # Update object name immediately
            assistant.object_name = new_topic_name
            object_name = new_topic_name  # Update local variable too

            # Classify synchronously with timeout
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    assistant.classify_object_sync,
                    new_topic_name
                )
                try:
                    future.result(timeout=1.0)  # Wait up to 1 second
                    logger.info(f"[CLASSIFY] Completed for {new_topic_name}")
                except concurrent.futures.TimeoutError:
                    logger.warning(f"[CLASSIFY] Timeout for {new_topic_name}, continuing in background")

            # Rebuild category prompt for new object
            category_prompt = assistant.get_category_prompt(
                assistant.level1_category,
                assistant.level2_category,
                assistant.level3_category
            )

            # Use TOPIC_SWITCH_PROMPT - celebrate and ask about new object
            question_prompt = prompts['topic_switch_prompt'].format(
                child_answer=child_answer,
                previous_object=previous_object,
                new_object=new_topic_name,
                age=age,
                category_prompt=category_prompt,
                age_prompt=age_prompt
            )
        else:
            # GENERIC SWITCH REQUEST (User said "let's switch" but didn't say what)
            logger.info("[SWITCH] Generic switch request detected (no new object named)")
            
            # Construct a prompt to acknowledge the request and ask for a topic
            # We treat this as a special "followup" where we ask for the topic
            question_prompt = f"""The child explicitly asked to switch topics but didn't say what to talk about.
            
            Their input was: "{child_answer}"
            
            Your task:
            1. Warmly agree to switch topics (e.g., "Sure! That sounds fun!", "Okay, let's talk about something else!")
            2. Ask the child what they would like to talk about next.
            3. Keep it short and encouraging.
            
            Age: {age}
            Tone: Use the established tone.
            """

    else:
        # CONTINUE: Regular follow-up question on same object
        # Check if AI detected an object but decided not to switch
        if decision.get('new_object'):
            detected_object_name = decision['new_object']
            logger.info(f"[CONTINUE] Object detected but not switching: {detected_object_name} | Reasoning: {switch_decision_reasoning}")

        # Validation: Answer was not a valid new object
        validation_guidance = f"❌ NOT A VALID NEW OBJECT - The child's answer did not name a valid new object. Gently acknowledge their attempt but guide them to think of a proper object name. Reasoning: {decision.get('reasoning', 'No valid object')}"

        # Use regular QUESTION_PROMPT with validation
        question_prompt = prompts['question_prompt'].format(
            child_answer=child_answer,
            object_name=object_name,
            correct_count=correct_count,
            age=age,
            category_prompt=category_prompt,
            age_prompt=age_prompt,
            focus_prompt=focus_prompt,
            validation_guidance=validation_guidance
        )

    # Prepare messages with question prompt
    messages_to_send = messages + [{"role": "user", "content": question_prompt}]

    # Clean messages for API
    clean_messages = clean_messages_for_api(messages_to_send)

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
        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Log stream type for debugging
        logger.debug(f"Stream object type: {type(stream).__name__}")

        # Prepare decision info to pass along
        decision_info = {
            'new_object_name': new_topic_name,
            'detected_object_name': detected_object_name,
            'switch_decision_reasoning': switch_decision_reasoning
        }

        # Yield chunks as they arrive
        chunk_count = 0
        for chunk in stream:
            if chunk.text:
                chunk_count += 1
                full_response += chunk.text
                logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                yield (chunk.text, None, full_response, decision_info)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"suggest_topics_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        # Still yield what we have so far (even if incomplete)
        if full_response:
            decision_info = {
                'new_object_name': new_topic_name,
                'detected_object_name': detected_object_name,
                'switch_decision_reasoning': switch_decision_reasoning
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
        f"ask_followup_question_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    # Final yield with token usage (None for Gemini streaming)
    decision_info = {
        'new_object_name': new_topic_name,
        'detected_object_name': detected_object_name,
        'switch_decision_reasoning': switch_decision_reasoning
    }
    yield ("", token_usage, full_response, decision_info)


async def ask_explanation_question_stream(
    messages: list[dict],
    child_answer: str,
    assistant,  # PaixuejiAssistant instance
    object_name: str,
    correct_count: int,
    category_prompt: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    level3_category: str = "",
    focus_prompt: str = "",
    focus_mode: str | None = None
) -> AsyncGenerator[tuple[str, TokenUsage | None, str, str | None], None]:
    """
    Stream explanation + follow-up question when child says "I don't know".

    This function:
    1. Extracts the previous question from conversation history
    2. Uses EXPLANATION_PROMPT to explain the answer
    3. Continues with focus strategy for next question

    Args:
        messages: Conversation history
        child_answer: The child's "I don't know" answer
        assistant: PaixuejiAssistant instance
        object_name: Name of object being discussed
        correct_count: Number of correct answers so far
        category_prompt: Category-specific guidance
        age_prompt: Age-specific guidance
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance
        level3_category: Level 3 category
        focus_prompt: Focus strategy guidance
        focus_mode: The focus mode key (e.g., depth, width_color)

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far, new_object_name_or_None)
    """
    start_time = time.time()
    logger.info(f"ask_explanation_question_stream started | object={object_name}, answer={child_answer[:30]}")

    # Extract the previous question from conversation history
    previous_question = extract_previous_question(messages)
    logger.debug(f"Extracted previous question: {previous_question[:100]}")

    # Build explanation prompt
    prompts = paixueji_prompts.get_prompts()
    explanation_prompt = prompts['explanation_prompt'].format(
        child_answer=child_answer,
        object_name=object_name,
        age=age,
        previous_question=previous_question,
        category_prompt=category_prompt,
        age_prompt=age_prompt,
        focus_prompt=focus_prompt
    )

    # Prepare messages with explanation prompt
    messages_to_send = messages + [{"role": "user", "content": explanation_prompt}]

    # Clean messages for API
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None

    # Prepare decision info (no switching when child doesn't know)
    decision_info = {
        'new_object_name': None,
        'detected_object_name': None,
        'switch_decision_reasoning': None
    }

    stream = None
    try:
        logger.debug(f"Sending {len(contents)} messages to Gemini API (explanation mode)")

        # Configure generation
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 2000),
            system_instruction=system_instruction if system_instruction else None
        )

        # Call streaming API
        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks as they arrive
        chunk_count = 0
        for chunk in stream:
            if chunk.text:
                chunk_count += 1
                full_response += chunk.text
                logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                yield (chunk.text, None, full_response, decision_info)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"ask_explanation_question_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        if full_response:
            yield ("", token_usage, full_response, decision_info)
        return
    finally:
        if stream is not None:
            try:
                del stream
                logger.debug('Cleaned up stream via del in finally block')
            except:
                pass

    duration = time.time() - start_time
    logger.info(
        f"ask_explanation_question_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    # Final yield with token usage (None for Gemini streaming)
    yield ("", token_usage, full_response, decision_info)


async def ask_gentle_correction_stream(
    messages: list[dict],
    child_answer: str,
    assistant,  # PaixuejiAssistant instance
    object_name: str,
    correct_count: int,
    category_prompt: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    correctness_reasoning: str,
    level3_category: str = "",
    focus_prompt: str = "",
    focus_mode: str | None = None
) -> AsyncGenerator[tuple[str, TokenUsage | None, str, dict], None]:
    """
    Stream gentle correction + follow-up when answer is factually wrong.

    This function:
    1. Acknowledges child's effort positively
    2. Provides correct information gently
    3. Continues with focus strategy for next question

    Args:
        messages: Conversation history
        child_answer: The child's incorrect answer
        assistant: PaixuejiAssistant instance
        object_name: Name of object being discussed
        correct_count: Number of correct answers so far (NOT incremented)
        category_prompt: Category-specific guidance
        age_prompt: Age-specific guidance
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance
        correctness_reasoning: AI's explanation of why answer is wrong
        level3_category: Level 3 category
        focus_prompt: Focus strategy guidance
        focus_mode: The focus mode key

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far, decision_info)
    """
    start_time = time.time()
    logger.info(f"ask_gentle_correction_stream started | object={object_name}, answer={child_answer[:30]}")

    # Extract the previous question from conversation history
    previous_question = extract_previous_question(messages)
    logger.debug(f"Extracted previous question: {previous_question[:100]}")

    # Build gentle correction prompt
    prompts = paixueji_prompts.get_prompts()
    correction_prompt = prompts['gentle_correction_prompt'].format(
        child_answer=child_answer,
        object_name=object_name,
        age=age,
        previous_question=previous_question,
        correctness_reasoning=correctness_reasoning,
        category_prompt=category_prompt,
        age_prompt=age_prompt,
        focus_prompt=focus_prompt
    )

    # Prepare messages with correction prompt
    messages_to_send = messages + [{"role": "user", "content": correction_prompt}]

    # Clean messages for API
    clean_messages = clean_messages_for_api(messages_to_send)

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None

    # Prepare decision info (no switching when correcting)
    decision_info = {
        'new_object_name': None,
        'detected_object_name': None,
        'switch_decision_reasoning': None
    }

    stream = None
    try:
        logger.debug(f"Sending {len(contents)} messages to Gemini API (gentle correction mode)")

        # Configure generation
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
            max_output_tokens=config.get("max_tokens", 2000),
            system_instruction=system_instruction if system_instruction else None
        )

        # Call streaming API
        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Yield chunks as they arrive
        chunk_count = 0
        for chunk in stream:
            if chunk.text:
                chunk_count += 1
                full_response += chunk.text
                logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                yield (chunk.text, None, full_response, decision_info)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"ask_gentle_correction_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        if full_response:
            yield ("", token_usage, full_response, decision_info)
        return
    finally:
        if stream is not None:
            try:
                del stream
                logger.debug('Cleaned up stream via del in finally block')
            except:
                pass

    duration = time.time() - start_time
    logger.info(
        f"ask_gentle_correction_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    # Final yield with token usage
    yield ("", token_usage, full_response, decision_info)


def is_answer_reasonable(child_answer: str) -> bool:
    """
    Check if child's answer shows reasonable engagement.

    Simple heuristic - be encouraging, not strict!

    Args:
        child_answer: The child's answer

    Returns:
        True if answer seems reasonable, False if child appears stuck
    """
    answer_lower = child_answer.lower().strip()

    # Too short
    if len(answer_lower) <= 3:
        return False

    # Stuck phrases
    stuck_phrases = [
        "don't know", "dont know", "idk", "dunno",
        "not sure", "no idea", "help me"
    ]
    if any(phrase in answer_lower for phrase in stuck_phrases):
        return False

    # Has some letters (shows attempt)
    if sum(c.isalpha() for c in answer_lower) < 2:
        return False

    # Accept everything else - be encouraging!
    return True


def decide_next_focus_mode(assistant) -> dict:
    """
    Determine next focus mode based on system-managed focus state.

    Returns:
        dict: {
            'focus_mode': str,  # 'depth', 'width_color', 'width_shape', 'width_category', or 'object_selection'
            'reason': str,  # Explanation for the decision
            'suggested_objects': list[str] | None,  # Objects to present if mode = 'object_selection'
            'reset_object': bool  # Whether to reset object state
        }
    """
    if not assistant.system_managed_focus:
        # Not in system-managed mode, return current manual focus
        return {
            'focus_mode': assistant.current_focus_mode,
            'reason': 'Manual focus mode',
            'suggested_objects': None,
            'reset_object': False
        }

    # RULE 1: DEPTH phase (4-5 questions)
    if assistant.current_focus_mode == 'depth':
        if assistant.depth_questions_count < assistant.depth_target:
            # Continue with DEPTH
            return {
                'focus_mode': 'depth',
                'reason': f'Depth phase: {assistant.depth_questions_count}/{assistant.depth_target} questions asked',
                'suggested_objects': None,
                'reset_object': False
            }
        else:
            # Switch to WIDTH mode (choose which category)
            available = [c for c in ['color', 'shape', 'category'] if c not in assistant.width_categories_tried]
            if not available:
                # All WIDTH categories tried? Shouldn't happen but fallback
                available = ['color', 'shape', 'category']
                assistant.width_categories_tried = []

            import random
            width_category = random.choice(available)
            assistant.current_focus_mode = f'width_{width_category}'
            assistant.width_categories_tried.append(width_category)

            return {
                'focus_mode': assistant.current_focus_mode,
                'reason': f'Completed depth phase ({assistant.depth_questions_count} questions). Switching to WIDTH: {width_category}',
                'suggested_objects': None,
                'reset_object': False
            }

    # RULE 2: WIDTH phase - handle wrong answers
    elif assistant.current_focus_mode.startswith('width_'):
        # Note: Wrong answer detection happens in validation
        # This function is called AFTER wrong answer is detected

        # Check if 3 consecutive wrong WIDTH answers
        if assistant.width_wrong_count >= 3:
            # Present object selection
            logger.info(f"[SYSTEM_MANAGED] 3 consecutive wrong WIDTH answers. Triggering object selection.")

            # Generate suggested objects (this will be done via AI)
            return {
                'focus_mode': 'object_selection',
                'reason': '3 consecutive wrong WIDTH answers detected',
                'suggested_objects': None,  # Will be generated by AI
                'reset_object': False
            }

        # Not at threshold yet, continue with current WIDTH or try next category
        # (Decision to switch WIDTH category happens elsewhere)
        return {
            'focus_mode': assistant.current_focus_mode,
            'reason': f'WIDTH mode: {assistant.width_wrong_count}/3 wrong answers',
            'suggested_objects': None,
            'reset_object': False
        }

    # RULE 3: OBJECT_SELECTION mode - waiting for user to pick
    elif assistant.current_focus_mode == 'object_selection':
        return {
            'focus_mode': 'object_selection',
            'reason': 'Awaiting object selection from user',
            'suggested_objects': None,
            'reset_object': False
        }

    # Fallback
    return {
        'focus_mode': 'depth',
        'reason': 'Fallback to depth mode',
        'suggested_objects': None,
        'reset_object': False
    }


def handle_width_wrong_answer(assistant) -> dict:
    """
    Handle wrong answer in WIDTH mode - decide whether to switch WIDTH category.

    Returns:
        dict: {
            'switch_category': bool,
            'new_focus_mode': str | None,
            'reason': str
        }
    """
    assistant.width_wrong_count += 1
    logger.info(f"[SYSTEM_MANAGED] Wrong WIDTH answer. Count: {assistant.width_wrong_count}/3")

    # Check if threshold reached
    if assistant.width_wrong_count >= 3:
        return {
            'switch_category': False,
            'new_focus_mode': None,
            'reason': '3 wrong answers reached - will trigger object selection'
        }

    # Try next WIDTH category if available
    available = [c for c in ['color', 'shape', 'category'] if c not in assistant.width_categories_tried]

    if not available:
        # All categories tried, stay on current
        return {
            'switch_category': False,
            'new_focus_mode': None,
            'reason': 'All WIDTH categories already tried this object'
        }

    # Switch to next category
    import random
    next_category = random.choice(available)
    new_mode = f'width_{next_category}'
    assistant.current_focus_mode = new_mode
    assistant.width_categories_tried.append(next_category)

    return {
        'switch_category': True,
        'new_focus_mode': new_mode,
        'reason': f'Switching WIDTH category to {new_mode}'
    }


def generate_object_suggestions(assistant, config, client, age: int) -> list[str]:
    """
    Use AI to generate 3-4 related object suggestions.

    Args:
        assistant: PaixuejiAssistant instance
        config: Config dict
        client: Gemini client
        age: Child's age

    Returns:
        List of 3-4 object names
    """
    prompt = f"""The child (age {age}) has been learning about {assistant.object_name}.

Suggest 3-4 NEW objects that would be interesting for them to explore next.

Guidelines:
- Objects should be age-appropriate ({age} years old)
- Objects should be concrete and familiar
- Vary difficulty and category
- Make them engaging and fun

Respond with ONLY a JSON array of object names:
["object1", "object2", "object3", "object4"]
"""

    try:
        response = client.models.generate_content(
            model=config.get("model_name", "gemini-2.0-flash-exp"),
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.7,  # Higher temp for variety
                "max_output_tokens": 100
            }
        )

        import json
        objects = json.loads(response.text)
        logger.info(f"[OBJECT_SUGGESTIONS] Generated: {objects}")
        return objects[:4]  # Ensure max 4

    except Exception as e:
        logger.error(f"[OBJECT_SUGGESTIONS] Error: {e}")
        # Fallback suggestions
        return ["apple", "dog", "car", "tree"]


def extract_previous_question(messages: list[dict]) -> str:
    """
    Extract the last question asked by the assistant from conversation history.

    This looks for the most recent assistant message and returns it.
    Used to provide context when explaining answers to "I don't know" responses.

    Args:
        messages: Conversation history (list of role/content dicts)

    Returns:
        The last assistant message, or a fallback string if not found
    """
    # Walk backwards through messages to find last assistant message
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            # Return the content (which contains the question)
            return content

    # Fallback if no assistant message found (shouldn't happen in practice)
    return "the previous question"


async def generate_completion_message_stream(
    messages: list[dict],
    object_name: str,
    child_answer: str,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Stream completion/celebration message after 4 correct answers.

    Args:
        messages: Conversation history
        object_name: Name of object discussed
        child_answer: The child's final answer
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"generate_completion_message_stream started | object={object_name}")

    prompts = paixueji_prompts.get_prompts()
    completion_prompt = prompts['completion_prompt'].format(
        object_name=object_name,
        child_answer=child_answer
    )

    # Prepare messages with completion prompt
    messages_to_send = messages + [{"role": "user", "content": completion_prompt}]

    # Clean messages for API
    clean_messages = clean_messages_for_api(messages_to_send)

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
        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        # Log stream type for debugging
        logger.debug(f"Stream object type: {type(stream).__name__}")

        # Yield chunks as they arrive
        chunk_count = 0
        for chunk in stream:
            if chunk.text:
                chunk_count += 1
                full_response += chunk.text
                logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_completion_message_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        # Still yield what we have so far (even if incomplete)
        if full_response:
            yield ("", token_usage, full_response)
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
        f"generate_completion_message_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    # Final yield with token usage (None for Gemini streaming)
    yield ("", token_usage, full_response)


async def call_paixueji_stream(
    age: int | None,
    messages: list[dict],
    content: str,
    status: str,
    session_id: str,
    request_id: str,
    config: dict,
    client: genai.Client,
    assistant,  # PaixuejiAssistant instance for topic switching
    age_prompt: str = "",
    object_name: str = "",
    level1_category: str = "",
    level2_category: str = "",
    level3_category: str = "",
    correct_answer_count: int = 0,
    category_prompt: str = "",
    focus_prompt: str = "",
    focus_mode: str | None = None
) -> AsyncGenerator[StreamChunk, None]:
    """
    Main streaming function for Paixueji assistant.
    
    Args:
        age: Child's age
        messages: Conversation history
        content: User content
        status: Session status
        session_id: Session ID
        request_id: Request ID
        config: Config dict
        client: Gemini client
        age_prompt: Age guidance
        object_name: Object name
        level1_category: L1 Category
        level2_category: L2 Category
        level3_category: L3 Category
        correct_answer_count: Correct answers count
        category_prompt: Category guidance
        focus_prompt: Focus strategy guidance
        focus_mode: The focus mode key (e.g., depth, width_color)
    """
    start_time = time.time()

    # If system-managed mode, use the actual current focus mode instead of "system_managed"
    if assistant.system_managed_focus:
        focus_mode = assistant.current_focus_mode
        focus_prompt = assistant.get_focus_prompt(focus_mode)
        logger.info(f"[{session_id}] System-managed mode: using focus_mode={focus_mode}")

    logger.info(
        f"[{session_id}] call_paixueji_stream started | "
        f"session_id={session_id}, age={age}, object={object_name}, "
        f"level1={level1_category}, level2={level2_category}, level3={level3_category}, "
        f"correct_count={correct_answer_count}, status={status}, "
        f"content_length={len(content)}, message_history={len(messages)}"
    )

    # Add user input to messages for Gemini API
    messages.append({"role": "user", "content": content})

    # IMPORTANT: Also add to actual conversation_history so it's saved
    # For introduction, we don't want to save the trigger message, so only add for real user inputs
    # Check if this is a real user message (not the introduction trigger)
    if content != f"Start conversation about {object_name}":
        assistant.conversation_history.append({"role": "user", "content": content})

    # Create tree node for this turn
    current_node = None
    if assistant.flow_tree:
        parent_id = assistant.flow_tree.get_latest_node().node_id if assistant.flow_tree.nodes else None
        turn_number = len(assistant.flow_tree.nodes)

        current_node = assistant.flow_tree.create_node(
            parent_id=parent_id,
            turn_number=turn_number,
            node_type="pending"  # Will be updated after routing
        )

        # Capture state BEFORE
        current_node.state_before = {
            "object_name": object_name,
            "level1_category": level1_category,
            "level2_category": level2_category,
            "correct_answer_count": correct_answer_count,
            "focus_mode": focus_mode,
            "tone": assistant.tone
        }
        current_node.user_input = content if turn_number > 0 else None

    # INFINITE MODE: Conversation never completes automatically
    conversation_complete = False

    logger.info(f"[{session_id}] Conversation state | correct_count={correct_answer_count}, complete={conversation_complete}")

    # Track sequence number and token usage
    sequence_number = 0
    token_usage = None
    full_response = ""
    full_response_text = None
    full_question_text = None
    buffer = ""
    new_object_name = None
    detected_object_name = None
    switch_decision_reasoning = None

    # Prepare messages with age guidance
    prepared_messages = prepare_messages_for_streaming(messages, age_prompt)

    # Determine which streaming function to use
    stream_generator = None
    response_type = None
    is_engaged = None
    is_factually_correct = None
    correctness_reasoning = None

    # Check if this is truly the first interaction (no assistant messages yet)
    has_asked_questions = any(msg.get("role") == "assistant" for msg in messages)

    if correct_answer_count == 0 and not has_asked_questions:
        # First question (introduction) - only if we haven't asked any questions yet
        stream_generator = ask_introduction_question_stream(
            prepared_messages,
            object_name,
            category_prompt,
            age_prompt,
            age or 6,  # default to 6 if age not specified
            config,
            client,
            level3_category,
            focus_prompt=focus_prompt
        )
        response_type = "introduction"
        logger.info(f"[{session_id}] Routing to introduction question")

        # Update node type for introduction (no validation)
        if current_node:
            current_node.type = response_type

    else:
        # DUAL-PARALLEL ARCHITECTURE: Separate response and question generation
        # Follow-up question or explanation - Use SINGLE AI VALIDATION for all answers
        logger.info(f"[{session_id}] Running unified AI validation for answer")

        # Check conversation state for special handling
        is_awaiting_topic_selection = (assistant.state.value == "awaiting_topic_selection")
        if is_awaiting_topic_selection:
            logger.info(f"[{session_id}] Special validation context: AWAITING_TOPIC_SELECTION")

        validation_result = decide_topic_switch_with_validation(
            assistant=assistant,
            child_answer=content,
            object_name=object_name,
            age=age or 6,
            focus_mode=focus_mode,
            is_awaiting_topic_selection=is_awaiting_topic_selection
        )

        is_engaged = validation_result.get('is_engaged')
        is_factually_correct = validation_result.get('is_factually_correct')
        correctness_reasoning = validation_result.get('correctness_reasoning')
        switch_decision_reasoning = validation_result.get('switching_reasoning')

        # NEW: System-managed focus tracking
        if assistant.system_managed_focus:
            # Track DEPTH questions (only for engaged answers)
            if is_engaged and assistant.current_focus_mode == 'depth':
                assistant.depth_questions_count += 1
                logger.info(f"[SYSTEM_MANAGED] Depth: {assistant.depth_questions_count}/{assistant.depth_target}")

            # Handle wrong WIDTH answers
            # Include 'not is_engaged' to handle "I don't know" as a wrong answer that triggers a switch
            if assistant.current_focus_mode.startswith('width_') and (not is_engaged or not is_factually_correct):
                width_result = handle_width_wrong_answer(assistant)
                logger.info(f"[SYSTEM_MANAGED] WIDTH wrong: {width_result}")

                # Update local variables if mode changed so response uses new strategy
                if width_result.get('switch_category'):
                    focus_mode = width_result['new_focus_mode']
                    focus_prompt = assistant.get_focus_prompt(focus_mode)
                    logger.info(f"[SYSTEM_MANAGED] Switched focus to {focus_mode} for immediate response")

            # Reset wrong count on correct WIDTH answer
            if assistant.current_focus_mode.startswith('width_') and is_factually_correct:
                assistant.width_wrong_count = 0
                logger.info(f"[SYSTEM_MANAGED] Correct WIDTH answer, reset count")

        # Capture validation in tree
        if current_node:
            current_node.validation = {
                "is_engaged": is_engaged,
                "is_factually_correct": is_factually_correct,
                "correctness_reasoning": correctness_reasoning
            }

        # Check for explicit switch decision
        should_switch = validation_result.get('decision') == 'SWITCH'

        # ROUTING: Determine response generator based on validation
        response_generator = None
        previous_question = extract_previous_question(prepared_messages)

        # Handle explicit request to switch without a specific object named
        if should_switch and not validation_result.get('new_object'):
            # Trigger object selection flow immediately
            suggested_objects = generate_object_suggestions(assistant, config, client, age or 6)
            
            # STATE UPDATE: We are now offering choices
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.AWAITING_TOPIC_SELECTION
            
            response_generator = generate_explicit_switch_response_stream(
                messages=prepared_messages,
                suggested_objects=suggested_objects,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "explicit_switch"
            logger.info(f"[{session_id}] Routing to explicit switch response")

        elif not is_engaged:
            # PATH 1: STUCK/UNCLEAR ("I don't know", unclear answers)
            # STATE UPDATE: Still asking questions about same object
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.ASKING_QUESTION
            
            response_generator = generate_explanation_response_stream(
                messages=prepared_messages,
                child_answer=content,
                object_name=object_name,
                previous_question=previous_question,
                age=age or 6,
                category_prompt=category_prompt,
                age_prompt=age_prompt,
                config=config,
                client=client
            )
            response_type = "explanation"
            logger.info(f"[{session_id}] Routing to explanation | is_engaged=False")

        elif is_factually_correct:
            if should_switch and validation_result.get('new_object'):
                # PATH 2A: TOPIC SWITCH
                new_object = validation_result['new_object']
                previous_object = object_name

                # Update object in assistant and reset focus state for new object
                if assistant.system_managed_focus:
                    assistant.reset_object_state(new_object)
                else:
                    assistant.object_name = new_object
                
                object_name = new_object
                new_object_name = new_object
                switch_decision_reasoning = validation_result.get('switching_reasoning')
                
                # STATE UPDATE: New object, back to asking questions
                from paixueji_assistant import ConversationState
                assistant.state = ConversationState.ASKING_QUESTION

                # Classify new object (background with timeout)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(assistant.classify_object_sync, new_object)
                    try:
                        future.result(timeout=1.0)
                        logger.info(f"[{session_id}] Classification completed for {new_object}")
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"[{session_id}] Classification timeout for {new_object}")

                # Rebuild category prompts for new object
                category_prompt = assistant.get_category_prompt(
                    assistant.level1_category,
                    assistant.level2_category,
                    assistant.level3_category
                )
                level1_category = assistant.level1_category
                level2_category = assistant.level2_category
                level3_category = assistant.level3_category

                response_generator = generate_topic_switch_response_stream(
                    messages=prepared_messages,
                    previous_object=previous_object,
                    new_object=new_object,
                    age=age or 6,
                    config=config,
                    client=client
                )
                response_type = "topic_switch"
                logger.info(f"[{session_id}] Routing to topic switch | {previous_object} -> {new_object}")

            else:
                # PATH 2B: CORRECT ANSWER (no switch)
                # STATE UPDATE: Back to asking questions
                from paixueji_assistant import ConversationState
                assistant.state = ConversationState.ASKING_QUESTION
                
                response_generator = generate_feedback_response_stream(
                    messages=prepared_messages,
                    child_answer=content,
                    object_name=object_name,
                    age=age or 6,
                    config=config,
                    client=client
                )
                response_type = "feedback"
                logger.info(f"[{session_id}] Routing to feedback | is_engaged=True, is_factually_correct=True")

        else:
            # PATH 3: WRONG + ENGAGED
            # STATE UPDATE: Back to asking questions
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.ASKING_QUESTION
            
            response_generator = generate_correction_response_stream(
                messages=prepared_messages,
                child_answer=content,
                object_name=object_name,
                previous_question=previous_question,
                correctness_reasoning=correctness_reasoning,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "correction"
            logger.info(f"[{session_id}] Routing to correction | is_engaged=True, is_factually_correct=False")

        is_engaged = validation_result.get('is_engaged')
        is_factually_correct = validation_result.get('is_factually_correct')
        correctness_reasoning = validation_result.get('correctness_reasoning')
        switch_decision_reasoning = validation_result.get('switching_reasoning')

        # NEW: System-managed focus tracking
        if assistant.system_managed_focus:
            # Track DEPTH questions (only for engaged answers)
            if is_engaged and assistant.current_focus_mode == 'depth':
                assistant.depth_questions_count += 1
                logger.info(f"[SYSTEM_MANAGED] Depth: {assistant.depth_questions_count}/{assistant.depth_target}")

            # Handle wrong WIDTH answers
            # Include 'not is_engaged' to handle "I don't know" as a wrong answer that triggers a switch
            if assistant.current_focus_mode.startswith('width_') and (not is_engaged or not is_factually_correct):
                width_result = handle_width_wrong_answer(assistant)
                logger.info(f"[SYSTEM_MANAGED] WIDTH wrong: {width_result}")

                # Update local variables if mode changed so response uses new strategy
                if width_result.get('switch_category'):
                    focus_mode = width_result['new_focus_mode']
                    focus_prompt = assistant.get_focus_prompt(focus_mode)
                    logger.info(f"[SYSTEM_MANAGED] Switched focus to {focus_mode} for immediate response")

            # Reset wrong count on correct WIDTH answer
            if assistant.current_focus_mode.startswith('width_') and is_factually_correct:
                assistant.width_wrong_count = 0
                logger.info(f"[SYSTEM_MANAGED] Correct WIDTH answer, reset count")

        # Capture validation in tree
        if current_node:
            current_node.validation = {
                "is_engaged": is_engaged,
                "is_factually_correct": is_factually_correct,
                "correctness_reasoning": correctness_reasoning
            }

        # Check for explicit switch decision
        should_switch = validation_result.get('decision') == 'SWITCH'

        # ROUTING: Determine response generator based on validation
        response_generator = None
        previous_question = extract_previous_question(prepared_messages)

        # Handle explicit request to switch without a specific object named
        if should_switch and not validation_result.get('new_object'):
            # Trigger object selection flow immediately
            suggested_objects = generate_object_suggestions(assistant, config, client, age or 6)
            response_generator = generate_explicit_switch_response_stream(
                messages=prepared_messages,
                suggested_objects=suggested_objects,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "explicit_switch"
            logger.info(f"[{session_id}] Routing to explicit switch response")

        elif not is_engaged:
            # PATH 1: STUCK/UNCLEAR ("I don't know", unclear answers)
            response_generator = generate_explanation_response_stream(
                messages=prepared_messages,
                child_answer=content,
                object_name=object_name,
                previous_question=previous_question,
                age=age or 6,
                category_prompt=category_prompt,
                age_prompt=age_prompt,
                config=config,
                client=client
            )
            response_type = "explanation"
            logger.info(f"[{session_id}] Routing to explanation | is_engaged=False")

        elif is_factually_correct:
            if should_switch and validation_result.get('new_object'):
                # PATH 2A: TOPIC SWITCH
                new_object = validation_result['new_object']
                previous_object = object_name

                # Update object in assistant and reset focus state for new object
                if assistant.system_managed_focus:
                    assistant.reset_object_state(new_object)
                else:
                    assistant.object_name = new_object
                
                object_name = new_object
                new_object_name = new_object
                switch_decision_reasoning = validation_result.get('switching_reasoning')

                # Classify new object (background with timeout)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(assistant.classify_object_sync, new_object)
                    try:
                        future.result(timeout=1.0)
                        logger.info(f"[{session_id}] Classification completed for {new_object}")
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"[{session_id}] Classification timeout for {new_object}")

                # Rebuild category prompts for new object
                category_prompt = assistant.get_category_prompt(
                    assistant.level1_category,
                    assistant.level2_category,
                    assistant.level3_category
                )
                level1_category = assistant.level1_category
                level2_category = assistant.level2_category
                level3_category = assistant.level3_category

                response_generator = generate_topic_switch_response_stream(
                    messages=prepared_messages,
                    previous_object=previous_object,
                    new_object=new_object,
                    age=age or 6,
                    config=config,
                    client=client
                )
                response_type = "topic_switch"
                logger.info(f"[{session_id}] Routing to topic switch | {previous_object} -> {new_object}")

            else:
                # PATH 2B: CORRECT ANSWER (no switch)
                response_generator = generate_feedback_response_stream(
                    messages=prepared_messages,
                    child_answer=content,
                    object_name=object_name,
                    age=age or 6,
                    config=config,
                    client=client
                )
                response_type = "feedback"
                logger.info(f"[{session_id}] Routing to feedback | is_engaged=True, is_factually_correct=True")

        else:
            # PATH 3: WRONG + ENGAGED
            response_generator = generate_correction_response_stream(
                messages=prepared_messages,
                child_answer=content,
                object_name=object_name,
                previous_question=previous_question,
                correctness_reasoning=correctness_reasoning,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "gentle_correction"
            logger.info(f"[{session_id}] Routing to gentle correction | is_engaged=True, is_factually_correct=False")

        # Update node type and capture decision
        if current_node:
            current_node.type = response_type
            if validation_result.get('decision'):
                current_node.decision = {
                    "decision_type": validation_result.get('decision'),
                    "detected_object": validation_result.get('new_object'),
                    "switch_reasoning": validation_result.get('switching_reasoning'),
                    "routing": response_type
                }

        # NEW: System-managed focus mode decision (Move BEFORE response generation)
        # This ensures the frontend gets the correct focus mode tag on the very first chunk
        skip_question_generation = False
        natural_topic_completion = False
        suggested_objects = None

        if assistant.system_managed_focus:
            focus_decision = decide_next_focus_mode(assistant)

            if focus_decision['focus_mode'] == 'object_selection':
                # Natural topic completion: congratulate and ask what they want next
                # No selection UI - let them use natural language
                natural_topic_completion = True
                response_type = "natural_topic_completion"
                logger.info(f"[{session_id}] System-managed: natural topic completion triggered")
            else:
                # Update focus mode for BOTH response and question generation
                focus_mode = focus_decision['focus_mode']
                focus_prompt = assistant.get_focus_prompt(focus_mode)
                logger.info(f"[{session_id}] System-managed: focus_mode={focus_mode}, reason={focus_decision['reason']}")

        # DUAL-PARALLEL STREAMING: Stream response first, then question
        full_response_text = ""
        full_question_text = ""

        # Stream response generator
        try:
            logger.debug(f"[{session_id}] Streaming response ({response_type})")
            async for chunk_data in response_generator:
                text_chunk, usage, response_so_far = chunk_data
                full_response_text = response_so_far

                if text_chunk:
                    sequence_number += 1
                    yield StreamChunk(
                        response=text_chunk,
                        session_finished=False,
                        duration=0.0,
                        token_usage=None,
                        finish=False,
                        sequence_number=sequence_number,
                        timestamp=time.time(),
                        session_id=session_id,
                        request_id=request_id,
                        is_stuck=False,
                        correct_answer_count=correct_answer_count,
                        conversation_complete=False,
                        focus_mode=focus_mode, # Uses UPDATED focus mode
                        is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
                        is_engaged=is_engaged,
                        is_factually_correct=is_factually_correct,
                        correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,
                        new_object_name=new_object_name,
                        detected_object_name=detected_object_name,
                        switch_decision_reasoning=switch_decision_reasoning,
                        response_type=response_type,
                        suggested_objects=suggested_objects,
                        object_selection_mode=bool(suggested_objects),
                        system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                        depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
                    )

        except Exception as e:
            logger.error(f"[{session_id}] Response generation failed | error={str(e)}", exc_info=True)
            # Fallback response
            fallback_response = "I see!"
            full_response_text = fallback_response
            sequence_number += 1
            yield StreamChunk(
                response=fallback_response,
                session_finished=False,
                duration=0.0,
                token_usage=None,
                finish=False,
                sequence_number=sequence_number,
                timestamp=time.time(),
                session_id=session_id,
                request_id=request_id,
                is_stuck=False,
                correct_answer_count=correct_answer_count,
                conversation_complete=False,
                focus_mode=focus_mode,
                is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
                is_engaged=is_engaged,
                is_factually_correct=is_factually_correct,
                correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,
                new_object_name=new_object_name,
                detected_object_name=detected_object_name,
                switch_decision_reasoning=switch_decision_reasoning,
                response_type=response_type,
                suggested_objects=suggested_objects,
                object_selection_mode=bool(suggested_objects),
                system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
            )

        # CRITICAL FIX: Update messages with the generated response BEFORE asking follow-up
        # This ensures the question generator sees the explanation/feedback we just gave
        question_messages = prepared_messages.copy()
        if full_response_text:
            question_messages.append({"role": "assistant", "content": full_response_text})

        # Check if this is an explicit switch request (no follow-up question needed)
        if response_type == "explicit_switch":
            # For explicit switches, the response already contains the object selection
            # We don't need to generate a follow-up question
            question_generator = None
            logger.info(f"[{session_id}] Skipping question generation for explicit switch")

        # Check if natural topic completion triggered (system-managed)
        elif natural_topic_completion:
            # Natural completion: congratulate and ask what they want to explore next
            question_generator = generate_natural_topic_completion_stream(
                messages=question_messages,
                current_object=object_name,
                age=age or 6,
                config=config,
                client=client
            )
            logger.info(f"[{session_id}] Using natural topic completion (no selection UI)")

        # ALWAYS generate follow-up question (for all non-introduction turns)
        # Now using the updated history including the response
        else:
            question_generator = generate_followup_question_stream(
                messages=question_messages,
                object_name=object_name,  # Updated object if switched
                correct_count=correct_answer_count,
                category_prompt=category_prompt,
                age_prompt=age_prompt,
                age=age or 6,
                focus_prompt=focus_prompt,
                config=config,
                client=client,
                is_topic_switch=should_switch
            )

        # Stream question generator (skip if None for explicit switches)
        if question_generator is not None:
            try:
                logger.debug(f"[{session_id}] Streaming question")
                async for chunk_data in question_generator:
                    text_chunk, usage, question_so_far = chunk_data
                    full_question_text = question_so_far

                    if text_chunk:
                        sequence_number += 1
                        yield StreamChunk(
                            response=text_chunk,
                            session_finished=False,
                            duration=0.0,
                            token_usage=None,
                            finish=False,
                            sequence_number=sequence_number,
                            timestamp=time.time(),
                            session_id=session_id,
                            request_id=request_id,
                            is_stuck=False,
                            correct_answer_count=correct_answer_count,
                            conversation_complete=False,
                            focus_mode=focus_mode,
                            is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
                            is_engaged=is_engaged,
                            is_factually_correct=is_factually_correct,
                            correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,
                            new_object_name=new_object_name,
                            detected_object_name=detected_object_name,
                            switch_decision_reasoning=switch_decision_reasoning,
                            response_type="followup_question",
                            suggested_objects=suggested_objects,
                            object_selection_mode=bool(suggested_objects),
                            system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                            depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
                        )

            except Exception as e:
                logger.error(f"[{session_id}] Question generation failed | error={str(e)}", exc_info=True)
                # Fallback question
                fallback_question = f"What else can you tell me about {object_name}?"
                full_question_text = fallback_question
                sequence_number += 1
                yield StreamChunk(
                    response=fallback_question,
                    session_finished=False,
                    duration=0.0,
                    token_usage=None,
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    request_id=request_id,
                    is_stuck=False,
                    correct_answer_count=correct_answer_count,
                    conversation_complete=False,
                    focus_mode=focus_mode,
                    is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
                    is_engaged=is_engaged,
                    is_factually_correct=is_factually_correct,
                    correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,
                    new_object_name=new_object_name,
                    detected_object_name=detected_object_name,
                    switch_decision_reasoning=switch_decision_reasoning,
                    response_type="followup_question",
                    suggested_objects=suggested_objects,
                    object_selection_mode=bool(suggested_objects),
                    system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                    depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
                )

        # Combine response and question for conversation history
        # For explicit switches, there's no follow-up question, so just use the response
        if full_question_text:
            full_response = full_response_text + " " + full_question_text
        else:
            full_response = full_response_text
        prepared_messages.append({"role": "assistant", "content": full_response})

        # Set stream_generator to None to skip old streaming logic
        stream_generator = None

    # Stream chunks from the selected generator
    if stream_generator:
        async for chunked_text, chunk_token_usage, full_text, decision_info in stream_generator:
            # Capture decision info from streaming functions
            if decision_info:
                if decision_info.get('new_object_name') and not new_object_name:
                    new_object_name = decision_info['new_object_name']
                    logger.info(f"[{session_id}] TOPIC SWITCH DETECTED: {new_object_name}")
                if decision_info.get('detected_object_name') and not detected_object_name:
                    detected_object_name = decision_info['detected_object_name']
                    switch_decision_reasoning = decision_info.get('switch_decision_reasoning')
                    logger.info(f"[{session_id}] Object detected but not switching: {detected_object_name}")

            if chunk_token_usage:
                token_usage = chunk_token_usage

            # Simple buffering - no tag parsing needed (decision made in separate API call)
            buffer += chunked_text
            text_to_process = buffer
            buffer = ""

            # Yield Result
            if text_to_process:
                full_response += text_to_process # Track what we actually sent to user

                sequence_number += 1
                chunk = StreamChunk(
                    response=text_to_process,
                    session_finished=(status == "over"),
                    duration=0.0,  # Will be set in final chunk
                    token_usage=None,  # Only in final chunk
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    request_id=request_id,
                    is_stuck=False,  # Not used in Paixueji
                    correct_answer_count=correct_answer_count,
                    conversation_complete=False,  # Infinite mode: never complete
                    focus_mode=focus_mode,

                    # DEPRECATED: Keep for backward compat
                    is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,

                    # NEW unified AI validation fields:
                    is_engaged=is_engaged,
                    is_factually_correct=is_factually_correct,
                    correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,

                    # Topic switching fields:
                    new_object_name=new_object_name,
                    detected_object_name=detected_object_name,
                    switch_decision_reasoning=switch_decision_reasoning
                )
                yield chunk

                # Only send these values once (they're sent in first chunk after decision)
                if new_object_name:
                    new_object_name = None
                if detected_object_name:
                    detected_object_name = None
                    switch_decision_reasoning = None

    # Flush remaining buffer if needed
    if buffer:
        full_response += buffer

    # Calculate total duration
    end_time = time.time()
    elapsed_time = end_time - start_time

    # Validate response completeness
    if not full_response:
        logger.warning(f"[{session_id}] Empty response - possible streaming error or reasoning only")

    logger.info(
        f"[{session_id}] call_paixueji_stream completed | "
        f"response_type={response_type}, duration={elapsed_time:.3f}s, "
        f"total_chunks={sequence_number}, response_length={len(full_response)}, "
        f"correct_count={correct_answer_count}, complete={conversation_complete}, "
        f"session_finished={status == 'over'}"
    )

    logger.debug(f"Full response: {full_response}...")

    # Yield final chunk with token usage and duration
    sequence_number += 1
    final_chunk = StreamChunk(
        response=full_response,
        session_finished=(status == "over"),
        duration=elapsed_time,
        token_usage=token_usage,
        finish=True,
        sequence_number=sequence_number,
        timestamp=time.time(),
        session_id=session_id,
        request_id=request_id,
        is_stuck=False,  # Not used in Paixueji
        correct_answer_count=correct_answer_count,
        conversation_complete=conversation_complete,
        focus_mode=focus_mode,

        # DEPRECATED: Keep for backward compat
        is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,

        # NEW unified AI validation fields:
        is_engaged=is_engaged,
        is_factually_correct=is_factually_correct,
        correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,

        # Topic switching fields:
        new_object_name=new_object_name,
        detected_object_name=detected_object_name,
        switch_decision_reasoning=switch_decision_reasoning
    )
    yield final_chunk

    # Finalize tree node
    if current_node:
        current_node.ai_response = full_response
        current_node.ai_response_part1 = full_response_text
        current_node.ai_response_part2 = full_question_text
        current_node.response_duration = elapsed_time

        # Capture state changes
        state_after = {}
        if assistant.object_name != current_node.state_before.get("object_name"):
            state_after["object_name"] = assistant.object_name
            state_after["level1_category"] = assistant.level1_category
            state_after["level2_category"] = assistant.level2_category
        if assistant.correct_answer_count != current_node.state_before.get("correct_answer_count"):
            state_after["correct_answer_count"] = assistant.correct_answer_count

        current_node.state_after = state_after
        current_node.metadata = {
            "chunk_count": sequence_number,
            "token_usage": token_usage.model_dump() if token_usage else None
        }

        # [DEBUG LOG] Structured output matching Debug Panel
        state_b = current_node.state_before
        val = current_node.validation or {}
        dec = current_node.decision or {}
        
        log_msg = (
            f"\n\n[DEBUG TREE NODE] Turn {current_node.turn_number} ({current_node.type.upper()})\n"
            f"--------------------------------------------------\n"
            f"👤 USER INPUT: {current_node.user_input or '(None)'}\n"
            f"🧠 CONTEXT: Object='{state_b.get('object_name')}' | Tone='{state_b.get('tone')}' | Focus='{state_b.get('focus_mode')}'\n"
            f"🔍 VALIDATION: Engaged={val.get('is_engaged')} | Correct={val.get('is_factually_correct')}\n"
            f"💭 REASONING: {val.get('correctness_reasoning') or 'N/A'}\n"
            f"⚡ DECISION: {dec.get('decision_type') or 'N/A'} (Reason: {dec.get('switch_reasoning') or 'N/A'})\n"
            f"🗣️ RESPONSE PART 1: {current_node.ai_response_part1 or '(None)'}\n"
            f"❓ RESPONSE PART 2: {current_node.ai_response_part2 or '(None)'}\n"
            f"--------------------------------------------------\n"
        )
        logger.debug(log_msg)
