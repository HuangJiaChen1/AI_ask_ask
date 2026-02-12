"""
Response stream generators for Paixueji assistant.

This module contains the "Part 1" functions of the dual-parallel architecture:
response-only stream generators that produce feedback, explanations, corrections,
and topic switch celebrations WITHOUT follow-up questions.

Functions:
    - generate_feedback_response_stream: Celebratory feedback for correct answers
    - generate_explanation_response_stream: Explanation when child says "I don't know"
    - generate_correction_response_stream: Gentle correction for wrong answers
    - generate_topic_switch_response_stream: Celebration for topic transitions
    - generate_child_question_response_stream: Direct answer to child's follow-up question
    - generate_natural_topic_completion_stream: Natural topic completion
    - generate_explicit_switch_response_stream: Response for explicit switch requests
"""
import time
from typing import AsyncGenerator

from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from schema import TokenUsage
import paixueji_prompts
from .utils import clean_messages_for_api, convert_messages_to_gemini_format


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


async def generate_child_question_response_stream(
    messages: list[dict],
    child_question: str,
    object_name: str,
    age: int,
    config: dict,
    client: genai.Client
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Generate ONLY a direct answer when the child asks a follow-up question.

    This keeps response generation separate from follow-up question generation.
    """
    start_time = time.time()
    logger.info(f"generate_child_question_response_stream started | object={object_name}, age={age}")

    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['child_question_response_prompt'].format(
        child_question=child_question,
        object_name=object_name,
        age=age
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
            max_output_tokens=config.get("max_tokens", 600),
            system_instruction=system_instruction if system_instruction else None
        )

        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config
        )

        for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"generate_child_question_response_stream error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
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
    logger.info(f"generate_child_question_response_stream completed | duration={duration:.3f}s, length={len(full_response)}")
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
