"""
Response stream generators for Paixueji assistant.

Functions:
    - generate_intent_response_stream: Universal intent response generator (9-node architecture)
    - generate_topic_switch_response_stream: Celebration for named-object topic transitions
    - generate_bridge_activation_response_stream: Completes a successful pre-anchor bridge
"""
import time
from typing import AsyncGenerator

from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from schema import TokenUsage
import paixueji_prompts
from .errors import raise_if_rate_limited
from .utils import clean_messages_for_api, convert_messages_to_gemini_format


async def generate_intent_response_stream(
    intent_type: str,
    messages: list[dict],
    child_answer: str,
    object_name: str,
    age: int,
    age_prompt: str,
    last_model_response: str,
    config: dict = None,
    client: genai.Client = None,
    knowledge_context: str = "",
    resolution_guardrails: str = "",
    surface_only_mode: bool = False,
    surface_object_name: str = "",
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """
    Universal intent response generator for the 9-node architecture.

    Selects the prompt template using `{intent_type}_intent_prompt` from get_prompts(),
    formats it with conversation context, and streams the LLM response.

    Args:
        intent_type: One of curiosity, clarifying, informative, play, emotional,
                     avoidance, boundary, action, social (case-insensitive)
        messages: Conversation history
        child_answer: The child's input text
        object_name: Current object being discussed
        age: Child's age
        age_prompt: Age-specific guidance string
        last_model_response: The previous full response by the model (response + question combined)
        knowledge_context: Formatted physical_dimensions facts from YAML (optional grounding)
        config: Configuration dict with model settings
        client: Gemini client instance

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_response_so_far)
    """
    start_time = time.time()
    intent_lower = intent_type.lower()
    logger.info(f"generate_intent_response_stream started | intent={intent_lower}, object={object_name}, age={age}")
    if not surface_only_mode and "No supported anchor is active" in (resolution_guardrails or ""):
        surface_only_mode = True
        surface_object_name = surface_object_name or object_name

    prompt_key = f"{intent_lower}_intent_prompt"
    prompts = paixueji_prompts.get_prompts()
    prompt_template = prompts.get(prompt_key, "")

    if not prompt_template:
        logger.warning(f"No prompt template found for key '{prompt_key}', using fallback")
        prompt_template = "Respond warmly and helpfully to the child's input: \"{child_answer}\""

    try:
        prompt = prompt_template.format(
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt=age_prompt,
            last_model_response=last_model_response,
            knowledge_context=knowledge_context,
        )
        if surface_only_mode:
            surface_only_prompt = paixueji_prompts.get_prompts()["unresolved_surface_only_prompt"].format(
                surface_object_name=surface_object_name or object_name
            )
            prompt = f"{surface_only_prompt}\n\n{prompt}"
        elif resolution_guardrails:
            prompt = f"{resolution_guardrails}\n\n{prompt}"
    except KeyError as e:
        logger.warning(f"Prompt template formatting error for '{prompt_key}': {e}")
        prompt = prompt_template

    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

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

    duration = time.time() - start_time
    logger.info(f"generate_intent_response_stream completed | intent={intent_lower}, duration={duration:.3f}s, length={len(full_response)}")

    yield ("", token_usage, full_response)


async def generate_classification_fallback_stream(
    messages: list[dict],
    child_answer: str,
    object_name: str,
    age: int,
    age_prompt: str,
    last_model_response: str,
    config: dict,
    client: genai.Client,
    resolution_guardrails: str = "",
    surface_only_mode: bool = False,
    surface_object_name: str = "",
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """Generate a natural recovery response when intent classification failed."""
    start_time = time.time()
    logger.info(f"generate_classification_fallback_stream started | object={object_name}, age={age}")
    if not surface_only_mode and "No supported anchor is active" in (resolution_guardrails or ""):
        surface_only_mode = True
        surface_object_name = surface_object_name or object_name

    prompt_template = paixueji_prompts.get_prompts()["classification_fallback_prompt"]
    prompt = prompt_template.format(
        child_answer=child_answer,
        object_name=object_name,
        age=age,
        age_prompt=age_prompt,
        last_model_response=last_model_response,
    )
    if surface_only_mode:
        surface_only_prompt = paixueji_prompts.get_prompts()["unresolved_surface_only_prompt"].format(
            surface_object_name=surface_object_name or object_name
        )
        prompt = f"{surface_only_prompt}\n\n{prompt}"
    elif resolution_guardrails:
        prompt = f"{resolution_guardrails}\n\n{prompt}"

    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

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
        logger.error(
            f"generate_classification_fallback_stream error | error={str(e)}, duration={duration:.3f}s",
            exc_info=True,
        )
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

    duration = time.time() - start_time
    logger.info(
        f"generate_classification_fallback_stream completed | duration={duration:.3f}s, length={len(full_response)}"
    )

    yield ("", token_usage, full_response)


async def generate_attribute_activation_response_stream(
    *,
    messages: list[dict],
    intent_type: str,
    object_name: str,
    attribute_label: str,
    activity_target: str,
    child_answer: str,
    reply_type: str,
    state_action: str,
    age: int,
    age_prompt: str,
    knowledge_context: str = "",
    last_model_response: str = "",
    config: dict,
    client: genai.Client,
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """Generate attribute-pipeline RESPONSE part using the normal intent prompt.

    This produces ONLY the response (confirmation + wow fact etc.), with no
    attribute constraint. The follow-up question is generated separately by
    ask_followup_question_stream with the ATTRIBUTE_SOFT_GUIDE appended.
    """
    prompts = paixueji_prompts.get_prompts()
    intent_lower = intent_type.lower()
    # Prefer attribute-specific prompt when available (attribute pipeline only)
    attr_prompt_key = f"{intent_lower}_attribute_response_prompt"
    prompt_key = f"{intent_lower}_intent_prompt"
    intent_template = prompts.get(attr_prompt_key) or prompts.get(prompt_key, "")

    if not intent_template:
        intent_template = prompts.get("classification_fallback_prompt", "")

    # Build the intent prompt (pure response — no attribute constraint)
    try:
        intent_prompt = intent_template.format(
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt=age_prompt,
            last_model_response=last_model_response,
            knowledge_context=knowledge_context,
        )
    except KeyError:
        intent_prompt = intent_template

    # Append response coherence hint (soft — prefers attribute-related wow fact)
    response_hint = prompts["attribute_response_hint"].format(
        attribute_label=attribute_label,
    )
    full_prompt = f"{intent_prompt}\n\n{response_hint}"

    messages_to_send = messages + [{"role": "user", "content": full_prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    full_response = ""
    token_usage = None
    stream = None
    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.7),
            max_output_tokens=config.get("max_tokens", 500),
            system_instruction=system_instruction if system_instruction else None,
        )
        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)
    except Exception as e:
        logger.error("generate_attribute_activation_response_stream error | error={}", str(e), exc_info=True)
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

    yield ("", token_usage, full_response)


async def generate_category_activation_response_stream(
    *,
    messages: list[dict],
    object_name: str,
    category_label: str,
    activity_target: str,
    child_answer: str,
    reply_type: str,
    state_action: str,
    age: int,
    age_prompt: str,
    config: dict,
    client: genai.Client,
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    prompt = paixueji_prompts.get_prompts()["category_continue_prompt"].format(
        object_name=object_name,
        category_label=category_label,
        activity_target=activity_target,
        child_answer=child_answer,
        reply_type=reply_type,
        state_action=state_action,
        age=age,
        age_prompt=age_prompt,
    )
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages_to_send)
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    full_response = ""
    token_usage = None
    stream = None
    try:
        gen_config = GenerateContentConfig(
            temperature=config.get("temperature", 0.7),
            max_output_tokens=config.get("max_tokens", 500),
            system_instruction=system_instruction if system_instruction else None,
        )
        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)
    except Exception as e:
        logger.error("generate_category_activation_response_stream error | error={}", str(e), exc_info=True)
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
    Generate celebration for named-object topic transitions.

    Used by node_avoidance and node_action when new_object_name is set.

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

    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['topic_switch_response_prompt'].format(
        previous_object=previous_object,
        new_object=new_object,
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
            max_output_tokens=config.get("max_tokens", 400),
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
        logger.error("generate_topic_switch_response_stream error | error={} duration={:.3f}s", str(e), duration, exc_info=True)
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

    duration = time.time() - start_time
    logger.info(f"generate_topic_switch_response_stream completed | duration={duration:.3f}s, length={len(full_response)}")

    yield ("", token_usage, full_response)


async def generate_bridge_support_response_stream(
    messages: list[dict],
    child_answer: str,
    surface_object_name: str,
    anchor_object_name: str,
    age: int,
    age_prompt: str,
    bridge_context: str,
    previous_bridge_question: str,
    support_action: str,
    config: dict,
    client: genai.Client,
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """Generate a non-consuming bridge support turn for clarification/scaffolding/steering."""
    start_time = time.time()
    logger.info(
        "generate_bridge_support_response_stream started | "
        f"surface={surface_object_name}, anchor={anchor_object_name}, action={support_action}, age={age}"
    )

    prompt = paixueji_prompts.get_prompts()["bridge_support_response_prompt"].format(
        child_answer=child_answer,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        age=age,
        age_prompt=age_prompt,
        bridge_context=bridge_context,
        previous_bridge_question=previous_bridge_question or "",
        support_action=support_action,
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
            max_output_tokens=config.get("max_tokens", 400),
            system_instruction=system_instruction if system_instruction else None,
        )

        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )

        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            "generate_bridge_support_response_stream error | "
            f"error={str(e)}, duration={duration:.3f}s",
            exc_info=True,
        )
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

    duration = time.time() - start_time
    logger.info(
        "generate_bridge_support_response_stream completed | "
        f"duration={duration:.3f}s, length={len(full_response)}"
    )

    yield ("", token_usage, full_response)


async def generate_bridge_activation_response_stream(
    messages: list[dict],
    child_answer: str,
    surface_object_name: str,
    anchor_object_name: str,
    age: int,
    age_prompt: str,
    bridge_context: str,
    activation_grounding_context: str = "",
    config: dict | None = None,
    client: genai.Client | None = None,
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """Generate the first anchor-side follow-up after a successful pre-anchor switch."""
    start_time = time.time()
    logger.info(
        "generate_bridge_activation_response_stream started | "
        f"surface={surface_object_name}, anchor={anchor_object_name}, age={age}, "
        "grounding_mode=full_chat_kb"
    )

    latent_grounding_section = ""
    if activation_grounding_context:
        latent_grounding_section = (
            "LATENT GROUNDING (hidden support only; do not dump this block directly):\n"
            f"{activation_grounding_context}\n"
        )

    prompt = paixueji_prompts.get_prompts()["bridge_activation_response_prompt"].format(
        child_answer=child_answer,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        age=age,
        age_prompt=age_prompt,
        bridge_context=bridge_context,
        latent_grounding_section=latent_grounding_section,
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
            max_output_tokens=config.get("max_tokens", 400),
            system_instruction=system_instruction if system_instruction else None,
        )

        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )

        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            "generate_bridge_activation_response_stream error | "
            f"error={str(e)}, duration={duration:.3f}s",
            exc_info=True,
        )
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

    duration = time.time() - start_time
    logger.info(
        "generate_bridge_activation_response_stream completed | "
        f"duration={duration:.3f}s, length={len(full_response)}"
    )

    yield ("", token_usage, full_response)


async def generate_bridge_retry_response_stream(
    messages: list[dict],
    child_answer: str,
    surface_object_name: str,
    anchor_object_name: str,
    age: int,
    age_prompt: str,
    bridge_context: str,
    config: dict,
    client: genai.Client,
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
    """Generate one final relation-scoped bridge attempt before giving up."""
    start_time = time.time()
    logger.info(
        f"generate_bridge_retry_response_stream started | surface={surface_object_name}, anchor={anchor_object_name}, age={age}"
    )

    prompt = paixueji_prompts.get_prompts()["anchor_bridge_retry_prompt"].format(
        child_answer=child_answer,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        age=age,
        age_prompt=age_prompt,
        bridge_context=bridge_context,
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
            max_output_tokens=config.get("max_tokens", 400),
            system_instruction=system_instruction if system_instruction else None,
        )

        stream = await client.aio.models.generate_content_stream(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )

        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
                yield (chunk.text, None, full_response)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            f"generate_bridge_retry_response_stream error | error={str(e)}, duration={duration:.3f}s",
            exc_info=True,
        )
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

    duration = time.time() - start_time
    logger.info(
        f"generate_bridge_retry_response_stream completed | duration={duration:.3f}s, length={len(full_response)}"
    )

    yield ("", token_usage, full_response)
