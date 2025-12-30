"""
Streaming functions for Ask Ask assistant.

This module provides async streaming responses for the Ask Ask assistant,
matching the architecture of the reference agent_func_stream.py but adapted
for Q&A interactions instead of picture book discussions.
"""
import copy
import json
import os
import re
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


def sanitize_text(text: str, strip: bool = True) -> str:
    """
    Remove emojis, newlines, and markdown formatting from text.
    Returns pure text with only letters, numbers, spaces, and basic punctuation.

    Args:
        text: Input text to sanitize
        strip: Whether to strip leading/trailing whitespace (default: True)

    Returns:
        Sanitized text without emojis, newlines, and markdown formatting
    """
    if not text:
        return text

    # Remove emojis using comprehensive Unicode ranges
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"  # dingbats
        "\U000024C2-\U0001F251"  # enclosed characters
        "\U0001F900-\U0001F9FF"  # supplemental symbols and pictographs
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "\U0001FA70-\U0001FAFF"  # symbols and pictographs extended-A
        "\U00002600-\U000026FF"  # miscellaneous symbols
        "\U00002700-\U000027BF"  # dingbats
        "]+",
        flags=re.UNICODE
    )

    # Replace emojis with a space (to avoid concatenating adjacent words)
    text = emoji_pattern.sub(' ', text)

    # Replace newlines and tabs with spaces
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')

    # Handle markdown bold/italic patterns - remove ** and __ but preserve the text
    # Match **text** or __text__ and replace with just the text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'__([^_]+)__', r'\1', text)      # __bold__
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *italic*
    text = re.sub(r'_([^_]+)_', r'\1', text)        # _italic_

    # Remove any remaining markdown formatting characters (*, _, `, #, etc.)
    # Add space around them before removal to prevent concatenation
    text = re.sub(r'([*_`#~\[\]])', r' \1 ', text)
    text = re.sub(r'[*_`#~\[\]]+', ' ', text)

    # Clean up multiple spaces (reduces any sequence of whitespace to a single space)
    text = re.sub(r'\s+', ' ', text)

    # Strip leading/trailing whitespace
    if strip:
        text = text.strip()

    return text


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
    logger.debug(f"[ANSWER] Starting answer_question_stream | question_length={len(child_question)}, message_count={len(messages)}")

    prompts = ask_ask_prompts.get_prompts()
    answer_prompt = prompts['answer_question_prompt'].format(child_question=child_question)

    # Prepare messages with answer prompt
    messages_to_send = messages + [{"role": "user", "content": answer_prompt}]

    # Clean messages for API
    clean_messages = clean_messages_for_api(messages_to_send)
    logger.debug(f"[ANSWER] Prepared {len(clean_messages)} messages for Gemini API")

    # Convert to Gemini format
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    # Stream from LLM
    full_response = ""
    token_usage = None

    stream = None
    try:
        logger.debug(f"[ANSWER] Calling Gemini API with {len(contents)} messages")

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

        logger.debug(f"[ANSWER] Receiving stream from Gemini (model: {config['model_name']})")

        # Yield chunks as they arrive
        chunk_count = 0
        for chunk in stream:
            if chunk.text:
                chunk_count += 1
                # Sanitize text to remove emojis and newlines
                sanitized_text = sanitize_text(chunk.text, strip=False)
                full_response += sanitized_text
                # Only log first few chunks to reduce noise
                if chunk_count <= 3:
                    logger.debug(f"[ANSWER] Chunk {chunk_count}: {repr(sanitized_text[:50])}... ({len(sanitized_text)} chars)")
                yield (sanitized_text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"[ANSWER] ❌ ERROR: {str(e)} (duration={duration:.3f}s)", exc_info=True)
        # Still yield what we have so far (even if incomplete)
        if full_response:
            yield ("", token_usage, full_response)
        return
    finally:
        # Always attempt cleanup via deletion
        if stream is not None:
            try:
                del stream
            except:
                pass

    duration = time.time() - start_time
    logger.info(f"[ANSWER] ✓ Completed | {len(full_response)} chars in {duration:.3f}s")

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
                # Sanitize text to remove emojis and newlines
                sanitized_text = sanitize_text(chunk.text, strip=False)
                full_response += sanitized_text
                logger.debug(f"Chunk {chunk_count} | text={repr(sanitized_text)} | length={len(sanitized_text)}, total_length={len(full_response)}")
                yield (sanitized_text, None, full_response)

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

    logger.info(f"\n{'='*80}")
    logger.info(f"[STREAM] New streaming request")
    logger.info(f"  Session ID: {session_id}")
    logger.info(f"  Request ID: {request_id}")
    logger.info(f"  Child Age: {age}")
    logger.info(f"  User Input: {repr(content[:100])}...")
    logger.info(f"  Conversation History: {len(messages)} messages")
    logger.info(f"  Status: {status}")

    # Log conversation context for debugging
    logger.info(f"\n[STREAM] Conversation context being used:")
    for i, msg in enumerate(messages):
        role = msg.get('role', 'unknown')
        content_preview = msg.get('content', '')[:60]
        logger.info(f"    [{i}] {role}: {content_preview}...")
    logger.info(f"{'='*80}\n")

    # Add user input to messages
    messages.append({"role": "user", "content": content})

    # Check if child is stuck
    stuck = is_child_stuck(content)

    logger.info(f"[STREAM] Stuck detection result: {'STUCK - will suggest topics' if stuck else 'NOT STUCK - will answer question'}")

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
        logger.info(f"[STREAM] → Routing to SUGGEST_TOPICS function")
    else:
        stream_generator = answer_question_stream(prepared_messages, content, config, client)
        response_type = "answer_question"
        logger.info(f"[STREAM] → Routing to ANSWER_QUESTION function")

    # Stream chunks from the selected generator
    if stream_generator:
        async for chunked_text, chunk_token_usage, full_text in stream_generator:
            if chunk_token_usage:
                token_usage = chunk_token_usage

            full_response = full_text

            # Only yield non-empty text chunks (skip the final empty yield from stream functions)
            if chunked_text:
                sequence_number += 1
                # Only log first and every 5th chunk to reduce noise
                if sequence_number == 1 or sequence_number % 5 == 0:
                    logger.debug(f"[STREAM] Chunk #{sequence_number} | {len(chunked_text)} chars | total={len(full_text)} chars")
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
        logger.warning(f"[STREAM] ⚠️  WARNING: Empty response - possible streaming error")

    logger.info(f"\n{'='*80}")
    logger.info(f"[STREAM] Streaming completed successfully")
    logger.info(f"  Response Type: {response_type}")
    logger.info(f"  Duration: {elapsed_time:.3f}s")
    logger.info(f"  Total Chunks: {sequence_number}")
    logger.info(f"  Response Length: {len(full_response)} chars")
    logger.info(f"  Session Finished: {status == 'over'}")
    logger.info(f"  Full Response Preview: {full_response[:150]}...")
    logger.info(f"{'='*80}\n")

    # Sanitize final response to ensure it's clean
    full_response = sanitize_text(full_response)

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
