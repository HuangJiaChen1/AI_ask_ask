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


def decide_topic_switch(assistant, child_answer: str, object_name: str, age: int, focus_mode: str | None = None):
    """
    AI-driven topic switching based on conversation context.
    No hardcoded strategies - AI analyzes natural conversation flow.

    Args:
        assistant: PaixuejiAssistant instance
        child_answer: The child's answer text
        object_name: Current object being discussed
        age: Child's age
        focus_mode: Current focus mode (for context only, NOT decision rules)

    Returns:
        dict: {
            'decision': 'SWITCH' | 'CONTINUE',
            'new_object': str | None,
            'reasoning': str  # AI's explanation
        }
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

    # Build contextual decision prompt
    decision_prompt = f"""You are an educational AI helping a {age}-year-old child learn through conversation.

CONTEXT:
- Current Topic: {object_name}
- Focus Mode: {focus_mode or 'depth'} (how we ask questions, NOT a switching rule)
- Last Question You Asked: "{last_model_question}"
- Child's Answer: "{child_answer}"

YOUR TASK:
Decide whether to SWITCH to a new object or CONTINUE with the current object.

DECISION GUIDELINES:
1. **Invited Object Naming**: If you asked the child to name a new object (e.g., "name another red thing") and they did → SWITCH
2. **Off-Topic Response**: If the child answered with a different object instead of answering your question → SWITCH
3. **Explicit Request**: If child says "let's talk about X" or "can we switch to X" → SWITCH
4. **Comparison/Description**: If child mentions object in passing while answering (e.g., "red like cherry") → CONTINUE
5. **No New Object**: If child just answered your question normally → CONTINUE
6. **Stuck/Uncertain**: If child says "I don't know" or can't answer → CONTINUE

VALIDATION (always apply):
- Only SWITCH if the new object is a real, concrete object (not abstract concepts)
- Ignore made-up/nonsense words → CONTINUE
- Celestial objects (sun, moon, stars) are valid

FOCUS MODE CONTEXT (informational only, NOT rules):
- 'depth': Currently exploring one object deeply
- 'width_color/shape/category': Currently exploring by similarities
  (This context helps you understand the conversation style, but doesn't dictate switching rules)

RESPOND WITH VALID JSON:
{{
    "decision": "SWITCH" or "CONTINUE",
    "new_object": "ObjectName" or null,
    "reasoning": "1-2 sentence explanation of why you made this decision, referencing the guidelines above"
}}

EXAMPLES:
Last Q: "What color is the apple?"
Answer: "red"
→ {{"decision": "CONTINUE", "new_object": null, "reasoning": "Child directly answered the question about color. No topic change needed."}}

Last Q: "Can you think of another red fruit?"
Answer: "strawberry"
→ {{"decision": "SWITCH", "new_object": "strawberry", "reasoning": "I invited child to name a new object and they did. Switching to strawberry."}}

Last Q: "What shape is it?"
Answer: "Let's talk about dogs!"
→ {{"decision": "SWITCH", "new_object": "dog", "reasoning": "Child explicitly requested to change topics to dogs."}}

Last Q: "What does it taste like?"
Answer: "sweet like candy"
→ {{"decision": "CONTINUE", "new_object": null, "reasoning": "Child mentioned candy as a comparison, not requesting a topic change."}}

Now decide for the current situation:
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
                "max_output_tokens": 150
            }
        )

        # Parse JSON response
        decision_data = json.loads(response.text)

        logger.info(
            f"[DECIDE] {decision_data['decision']} | "
            f"new_object={decision_data.get('new_object')}, "
            f"reasoning={decision_data.get('reasoning')}"
        )

        return decision_data

    except Exception as e:
        logger.error(f"[DECIDE] Error: {e}, defaulting to CONTINUE")
        import traceback
        traceback.print_exc()
        return {
            'decision': 'CONTINUE',
            'new_object': None,
            'reasoning': f'Error in decision: {str(e)}'
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
    focus_mode: str | None = None
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

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far, new_object_name_or_None)
    """
    start_time = time.time()
    logger.info(f"ask_followup_question_stream started | object={object_name}, correct_count={correct_count}, answer_length={len(child_answer)}")

    # STEP 1: DECISION - Should we switch topics?
    new_topic_name = None
    detected_object_name = None
    switch_decision_reasoning = None

    decision = decide_topic_switch(
        assistant=assistant,
        child_answer=child_answer,
        object_name=object_name,
        age=age,
        focus_mode=focus_mode  # Context only, not a rule
    )

    # Capture reasoning from AI decision
    switch_decision_reasoning = decision.get('reasoning', 'No reasoning provided')

    # STEP 2: HANDLE DECISION & BUILD APPROPRIATE PROMPT
    prompts = paixueji_prompts.get_prompts()

    if decision['decision'] == 'SWITCH' and decision['new_object']:
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

    logger.info(
        f"[{session_id}] call_paixueji_stream started | "
        f"session_id={session_id}, age={age}, object={object_name}, "
        f"level1={level1_category}, level2={level2_category}, level3={level3_category}, "
        f"correct_count={correct_answer_count}, status={status}, "
        f"content_length={len(content)}, message_history={len(messages)}"
    )

    # Add user input to messages
    messages.append({"role": "user", "content": content})

    # INFINITE MODE: Conversation never completes automatically
    conversation_complete = False

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
    else:
        # Follow-up question or explanation (we've already started the conversation)
        # Check if answer is reasonable (and mark as correct if so)
        is_correct = is_answer_reasonable(content)
        
        if is_correct:
            stream_generator = ask_followup_question_stream(
                prepared_messages,
                content,  # child's answer
                assistant,  # Pass assistant for topic switching
                object_name,
                correct_answer_count,
                category_prompt,
                age_prompt,
                age or 6,
                config,
                client,
                level3_category,
                focus_prompt=focus_prompt,
                focus_mode=focus_mode
            )
            response_type = "followup"
            logger.info(f"[{session_id}] Routing to followup question | answer_reasonable=True")
        else:
            # Answer doesn't seem reasonable (child stuck) - provide explanation
            stream_generator = ask_explanation_question_stream(
                prepared_messages,
                content,
                assistant,
                object_name,
                correct_answer_count,  # Don't increment - they didn't answer
                category_prompt,
                age_prompt,
                age or 6,
                config,
                client,
                level3_category,
                focus_prompt=focus_prompt,
                focus_mode=focus_mode
            )
            response_type = "explanation"
            logger.info(f"[{session_id}] Routing to explanation (answer_reasonable=False)")

    # Stream chunks from the selected generator
    if stream_generator:
        new_object_name = None
        detected_object_name = None
        switch_decision_reasoning = None
        buffer = ""

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
                    is_correct=is_correct,
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
        focus_mode=focus_mode
    )
    yield final_chunk
