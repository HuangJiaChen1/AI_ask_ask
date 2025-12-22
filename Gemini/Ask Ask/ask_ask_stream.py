"""
Streaming functions for Ask Ask assistant.

This module provides async streaming responses for the Ask Ask assistant,
matching the architecture of the reference agent_func_stream.py but adapted
for Q&A interactions instead of picture book discussions.
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
import ask_ask_prompts

# Configure loguru for production
logger.add(
    "logs/ask_ask_{time:YYYY-MM-DD}.log",
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


async def answer_question_stream(
    messages: list[dict],
    child_question: str,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Stream answer to child's question with follow-up.

    Args:
        messages: Conversation history
        child_question: The child's question
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"answer_question_stream started | question_length={len(child_question)}, message_count={len(messages)}")

    prompts = ask_ask_prompts.get_prompts()
    answer_prompt = prompts['answer_question_prompt'].format(child_question=child_question)

    # Prepare messages with answer prompt
    messages_to_send = messages + [{"role": "user", "content": answer_prompt}]

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

        # Yield chunks as they arrive
        chunk_count = 0
        for chunk in stream:
            if chunk.text:
                chunk_count += 1
                full_response += chunk.text
                logger.debug(f"Chunk {chunk_count} | length={len(chunk.text)}, total_length={len(full_response)}")
                yield (chunk.text, None, full_response)

        # Note: Gemini API doesn't provide token usage in streaming mode
        # We'll leave token_usage as None
        logger.debug("Gemini streaming API does not provide token usage in stream mode")

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"answer_question_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
        f"answer_question_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    if duration > SLOW_LLM_CALL_THRESHOLD:
        logger.warning(f"Slow LLM call | duration={duration:.3f}s exceeded threshold {SLOW_LLM_CALL_THRESHOLD}s")

    # Final yield with token usage (None for Gemini streaming)
    yield ("", token_usage, full_response)


async def suggest_topics_stream(
    messages: list[dict],
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Stream topic suggestions when child is stuck.

    Args:
        messages: Conversation history
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"suggest_topics_stream started | message_count={len(messages)}")

    prompts = ask_ask_prompts.get_prompts()
    suggest_prompt = prompts['suggest_topics_prompt']

    # Prepare messages with suggest prompt
    messages_to_send = messages + [{"role": "user", "content": suggest_prompt}]

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
        logger.error(f"suggest_topics_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
        f"suggest_topics_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    # Final yield with token usage (None for Gemini streaming)
    yield ("", token_usage, full_response)


def is_child_stuck(child_input: str) -> bool:
    """
    Check if child is stuck and doesn't know what to ask.
    Uses simple keyword detection.

    Args:
        child_input: The child's input

    Returns:
        True if child appears stuck, False otherwise
    """
    input_lower = child_input.lower().strip()

    # Check if it's a question (ends with ? or starts with why/what/how/when/where)
    question_starters = ["why", "what", "how", "when", "where", "who", "can", "could", "do", "does"]
    is_likely_question = (
        child_input.strip().endswith("?") or
        any(input_lower.startswith(word + " ") for word in question_starters)
    )

    # If it looks like a question, they're not stuck
    if is_likely_question and len(input_lower) > 5:
        return False

    stuck_phrases = [
        "don't know", "dont know", "idk", "dunno", "not sure",
        "no idea", "help me", "i need help"
    ]

    # Check for stuck phrases
    if any(phrase in input_lower for phrase in stuck_phrases):
        return True

    # Also check if input is very short and not a question (likely stuck)
    if len(input_lower) <= 3 and not is_likely_question:
        return True

    # Single word responses like "huh", "what", "nope" without context
    single_word_stuck = ["huh", "what", "nope", "idk", "dunno", "help"]
    if input_lower in single_word_stuck:
        return True

    return False


async def call_ask_ask_stream(
    age: int | None,
    messages: list[dict],
    content: str,
    status: str,
    session_id: str,
    request_id: str,
    config: dict,
    client: genai.Client,
    age_prompt: str = ""
) -> AsyncGenerator[StreamChunk, None]:
    """
    Main streaming function for Ask Ask assistant.

    This is the primary entry point matching call_Leonard_stream() from the reference.
    It orchestrates the conversation flow and yields StreamChunk objects.

    Args:
        age: Child's age (3-8) for age-appropriate responses
        messages: Conversation message history
        content: Child's current question or input
        status: Current conversation status ("normal" or "over")
        session_id: Unique session identifier
        request_id: Unique identifier for this specific request
        config: Configuration dict with model settings
        client: Gemini client instance
        age_prompt: Age-specific guidance to append to system message

    Yields:
        StreamChunk objects containing response chunks and metadata
    """
    start_time = time.time()

    logger.info(
        f"[{session_id}] call_ask_ask_stream started | "
        f"session_id={session_id}, age={age}, "
        f"status={status}, content_length={len(content)}, "
        f"message_history={len(messages)}"
    )

    # Add user input to messages
    messages.append({"role": "user", "content": content})

    # Check if child is stuck
    stuck = is_child_stuck(content)

    logger.info(f"[{session_id}] Stuck detection | is_stuck={stuck}")

    # Track sequence number and token usage
    sequence_number = 0
    token_usage = None
    full_response = ""

    # Prepare messages with age guidance
    prepared_messages = prepare_messages_for_streaming(messages, age_prompt)

    # Determine which streaming function to use
    stream_generator = None
    response_type = None

    if stuck:
        stream_generator = suggest_topics_stream(prepared_messages, config, client)
        response_type = "suggest_topics"
        logger.info(f"[{session_id}] Routing to suggest_topics")
    else:
        stream_generator = answer_question_stream(prepared_messages, content, config, client)
        response_type = "answer_question"
        logger.info(f"[{session_id}] Routing to answer_question")

    # Stream chunks from the selected generator
    if stream_generator:
        async for chunked_text, chunk_token_usage, full_text in stream_generator:
            if chunk_token_usage:
                token_usage = chunk_token_usage

            full_response = full_text

            # Only yield non-empty text chunks (skip the final empty yield from stream functions)
            if chunked_text:
                sequence_number += 1
                chunk = StreamChunk(
                    response=chunked_text,
                    session_finished=(status == "over"),
                    duration=0.0,  # Will be set in final chunk
                    token_usage=None,  # Only in final chunk
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    request_id=request_id,
                    is_stuck=stuck,
                )
                yield chunk

    # Calculate total duration
    end_time = time.time()
    elapsed_time = end_time - start_time

    # Validate response completeness
    if not full_response:
        logger.warning(f"[{session_id}] Empty response - possible streaming error")

    logger.info(
        f"[{session_id}] call_ask_ask_stream completed | "
        f"response_type={response_type}, duration={elapsed_time:.3f}s, "
        f"total_chunks={sequence_number}, response_length={len(full_response)}, "
        f"session_finished={status == 'over'}"
    )

    logger.debug(f"Full response (first 200 chars): {full_response[:200]}...")

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
        is_stuck=stuck,
    )
    yield final_chunk
