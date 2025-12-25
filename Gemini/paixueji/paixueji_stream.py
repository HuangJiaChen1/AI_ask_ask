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
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
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
        f"ask_introduction_question_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    if duration > SLOW_LLM_CALL_THRESHOLD:
        logger.warning(f"Slow LLM call | duration={duration:.3f}s exceeded threshold {SLOW_LLM_CALL_THRESHOLD}s")

    # Final yield with token usage (None for Gemini streaming)
    yield ("", token_usage, full_response)


async def ask_followup_question_stream(
    messages: list[dict],
    child_answer: str,
    object_name: str,
    correct_count: int,
    category_prompt: str,
    age_prompt: str,
    age: int,
    config: dict,
    client: genai.Client,
    level3_category: str = "",
    focus_prompt: str = ""
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Stream follow-up question based on child's answer.

    Args:
        messages: Conversation history
        child_answer: The child's previous answer
        object_name: Name of object being discussed
        correct_count: Number of correct answers so far
        category_prompt: Category-specific guidance
        age_prompt: Age-specific guidance
        age: Child's age
        config: Configuration dict with model settings
        client: Gemini client instance
        level3_category: Level 3 category
        focus_prompt: Focus strategy guidance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    logger.info(f"ask_followup_question_stream started | object={object_name}, correct_count={correct_count}, answer_length={len(child_answer)}")

    prompts = paixueji_prompts.get_prompts()
    question_prompt = prompts['question_prompt'].format(
        child_answer=child_answer,
        object_name=object_name,
        correct_count=correct_count,
        age=age,
        category_prompt=category_prompt,
        age_prompt=age_prompt,
        focus_prompt=focus_prompt
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
        f"ask_followup_question_stream completed | "
        f"duration={duration:.3f}s, response_length={len(full_response)}"
    )

    # Final yield with token usage (None for Gemini streaming)
    yield ("", token_usage, full_response)


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

    logger.info(
        f"[{session_id}] call_paixueji_stream started | "
        f"session_id={session_id}, age={age}, object={object_name}, "
        f"level1={level1_category}, level2={level2_category}, level3={level3_category}, "
        f"correct_count={correct_answer_count}, status={status}, "
        f"content_length={len(content)}, message_history={len(messages)}"
    )

    # Add user input to messages
    messages.append({"role": "user", "content": content})

    # Check if conversation is complete (4 correct answers)
    conversation_complete = correct_answer_count >= 4

    logger.info(f"[{session_id}] Conversation state | correct_count={correct_answer_count}, complete={conversation_complete}")

    # Track sequence number and token usage
    sequence_number = 0
    token_usage = None
    full_response = ""

    # Prepare messages with age guidance
    prepared_messages = prepare_messages_for_streaming(messages, age_prompt)

    # Determine which streaming function to use
    stream_generator = None
    response_type = None
    is_correct = False

    if correct_answer_count == 0:
        # First question (introduction)
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
    else:
        # Follow-up question
        # Check if answer is reasonable (and mark as correct if so)
        is_correct = is_answer_reasonable(content)
        
        if is_correct:
            stream_generator = ask_followup_question_stream(
                prepared_messages,
                content,  # child's answer
                object_name,
                correct_answer_count,
                category_prompt,
                age_prompt,
                age or 6,
                config,
                client,
                level3_category,
                focus_prompt=focus_prompt
            )
            response_type = "followup"
            logger.info(f"[{session_id}] Routing to followup question | answer_reasonable=True")
        else:
            # Answer doesn't seem reasonable (child stuck) - ask encouraging question
            stream_generator = ask_followup_question_stream(
                prepared_messages,
                content,
                object_name,
                correct_answer_count,
                category_prompt,
                age_prompt,
                age or 6,
                config,
                client,
                level3_category,
                focus_prompt=focus_prompt
            )
            response_type = "followup_encouraging"
            logger.info(f"[{session_id}] Routing to followup question | answer_reasonable=False")

    # Stream chunks from the selected generator
    if stream_generator:
        new_object_detected = False
        new_object_name = None
        buffer = ""

        async for chunked_text, chunk_token_usage, full_text in stream_generator:
            if chunk_token_usage:
                token_usage = chunk_token_usage

            if not new_object_detected:
                buffer += chunked_text
                text_to_process = ""
                
                if "<new_topic>" in buffer:
                    if "</new_topic>" in buffer:
                        # Extract topic
                        start_idx = buffer.find("<new_topic>") + len("<new_topic>")
                        end_idx = buffer.find("</new_topic>")
                        new_object_name = buffer[start_idx:end_idx].strip()
                        new_object_detected = True
                        logger.info(f"[{session_id}] NEW TOPIC DETECTED: {new_object_name}")
                        
                        # Remove tag from output
                        text_to_process = buffer.replace(f"<new_topic>{new_object_name}</new_topic>", "")
                        buffer = "" # Clear buffer
                    else:
                        # Wait for closing tag
                        pass
                else:
                    # If buffer gets too long without tag, assume no tag (optimization)
                    if len(buffer) > 100: 
                         text_to_process = buffer
                         buffer = ""
            else:
                text_to_process = chunked_text

            full_response += text_to_process

            # Only yield non-empty text chunks
            if text_to_process:
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
                    conversation_complete=False, # Infinite stream
                    focus_mode=focus_mode,
                    is_correct=is_correct,
                    new_object_name=new_object_name
                )
                yield chunk
                
                # Only send new_object_name once
                if new_object_name:
                    new_object_name = None

    # Flush remaining buffer if needed
    if buffer and not new_object_detected:
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
        is_stuck=False,  # Not used in Paixueji
        correct_answer_count=correct_answer_count,
        conversation_complete=conversation_complete,
        focus_mode=focus_mode
    )
    yield final_chunk
