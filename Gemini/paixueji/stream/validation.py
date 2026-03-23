"""
Intent and dimension classification logic for Paixueji assistant.

Classifies child utterances into one of 9 communicative intents, enabling
the fan-out architecture where each intent routes to a dedicated response node.

Functions:
    - classify_intent: Async LLM classifier → 9 intents + optional new_object extraction
    - classify_dimension: Async LLM classifier → which exploration dimension a turn belongs to
"""
import re
import time
from loguru import logger
import paixueji_prompts


async def classify_intent(
    assistant,
    child_answer: str,
    object_name: str,
    age: int,
) -> dict:
    """
    Classify the child's utterance into one of 13 communicative intents.

    Args:
        assistant: PaixuejiAssistant instance (provides client + conversation_history)
        child_answer: The child's input text
        object_name: Current object being discussed
        age: Child's age
    Returns:
        dict with keys:
            - intent_type: one of CURIOSITY, CLARIFYING_IDK, CLARIFYING_WRONG,
                           CLARIFYING_CONSTRAINT, CORRECT_ANSWER, INFORMATIVE, PLAY,
                           EMOTIONAL, AVOIDANCE, BOUNDARY, ACTION, SOCIAL,
                           SOCIAL_ACKNOWLEDGMENT
            - new_object: str | None  (only extracted for ACTION or AVOIDANCE)
            - reasoning: brief explanation string
            - classification_status: "ok" | "failed"
            - classification_failure_reason: None | "invalid_output" | "exception"
    """
    # Fast-path: only for truly empty input (≤2 chars total)
    if len(child_answer.strip()) <= 2:
        logger.info("[CLASSIFY] Fast-path CLARIFYING_IDK (empty/silent input)")
        return {
            "intent_type": "CLARIFYING_IDK",
            "new_object": None,
            "reasoning": "Empty or silent input",
            "classification_status": "ok",
            "classification_failure_reason": None,
        }

    # Extract the model's last full response from conversation history
    conversation_history = assistant.conversation_history
    last_model_response = None
    for msg in reversed(conversation_history):
        if msg.get('role') == 'assistant':
            last_model_response = msg.get('content')
            break

    if not last_model_response:
        last_model_response = "Unknown (first interaction)"
    else:
        # Keep full response for better intent disambiguation; cap context size.
        last_model_response = last_model_response[-500:]

    prompt_template = paixueji_prompts.get_prompts()["user_intent_prompt"]
    prompt = prompt_template.format(
        object_name=object_name,
        last_model_response=last_model_response,
        child_answer=child_answer,
        topic_selection_instructions="",
    )

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

        def _get(pattern, default):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1).strip() if m else default

        valid_intents = {
            "CURIOSITY", "CLARIFYING_IDK", "CLARIFYING_WRONG", "CLARIFYING_CONSTRAINT",
            "CORRECT_ANSWER", "INFORMATIVE", "PLAY", "EMOTIONAL",
            "AVOIDANCE", "BOUNDARY", "ACTION", "SOCIAL", "SOCIAL_ACKNOWLEDGMENT",
            "CONCEPT_CONFUSION"
        }
        raw_intent = _get(r"INTENT:\s*(\w+)", "").upper()
        intent_type = raw_intent if raw_intent in valid_intents else None

        if intent_type is None:
            logger.warning(f"[CLASSIFY] Invalid classifier output, using fallback-freeform path | raw_intent={raw_intent!r}")
            return {
                "intent_type": None,
                "new_object": None,
                "reasoning": "Classifier output missing a valid intent",
                "classification_status": "failed",
                "classification_failure_reason": "invalid_output",
            }

        new_object_raw = _get(r"NEW_OBJECT:\s*(.+)", "null")
        new_object = None if new_object_raw.lower() in ("null", "none", "") else new_object_raw

        # new_object is only meaningful for ACTION and AVOIDANCE
        if intent_type not in ("ACTION", "AVOIDANCE"):
            new_object = None

        reasoning = _get(r"REASONING:\s*(.+)", "N/A")

        result = {
            "intent_type": intent_type,
            "new_object": new_object,
            "reasoning": reasoning,
            "classification_status": "ok",
            "classification_failure_reason": None,
        }
        logger.info(f"[CLASSIFY] intent={intent_type} | new_object={new_object} | reasoning={reasoning}")
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


async def classify_dimension(
    assistant,
    child_answer: str,
    last_assistant_message: str,
    object_name: str,
    available_dimensions: list[str],
) -> str | None:
    """
    Classify which exploration dimension the current exchange belongs to.

    Uses a minimal LLM call (temp=0, max 10 tokens) to pick one dimension
    from the provided list, or returns None if none match or on any error.

    Args:
        assistant: PaixuejiAssistant (provides client + config)
        child_answer: The child's input text
        last_assistant_message: The assistant's prior response (truncated)
        object_name: Current object being discussed
        available_dimensions: List of dimension names not yet covered

    Returns:
        Matched dimension name string, or None.
    """
    if not available_dimensions:
        return None

    prompt = (
        f"The assistant and child are talking about: {object_name}\n"
        f"Assistant said: {last_assistant_message[-300:]}\n"
        f"Child replied: {child_answer}\n\n"
        f"Which ONE exploration dimension does this exchange belong to?\n"
        f"Options: {', '.join(available_dimensions)}\n"
        f"If none match, reply: none\n\n"
        f"Reply with exactly one word from the options above."
    )

    try:
        response = await assistant.client.aio.models.generate_content(
            model=assistant.config["model_name"],
            contents=prompt,
            config={
                "temperature": 0,
                "max_output_tokens": 10,
            },
        )
        text = (response.text or "").strip().lower()
        for dim in available_dimensions:
            if text == dim.lower():
                return dim
        return None
    except Exception as e:
        logger.debug(f"[DIM_CLASSIFY] Error (non-fatal): {e}")
        return None
