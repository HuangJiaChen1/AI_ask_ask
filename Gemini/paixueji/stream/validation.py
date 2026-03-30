"""
Intent and KB-mapping logic for Paixueji assistant.

Functions:
    - classify_intent: Async LLM classifier → 9 intents + optional new_object extraction
    - classify_dimension: Legacy dimension classifier (still exported for compatibility)
    - map_response_to_kb_item: Debug-only best-effort mapper from response text to one KB item
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


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "for",
    "from", "has", "have", "if", "in", "is", "it", "its", "like", "of", "on",
    "or", "so", "that", "the", "their", "them", "they", "this", "to", "very",
    "when", "with", "you", "your",
}


def _stem_token(token: str) -> str:
    token = token.lower()
    if token.endswith("ly") and len(token) > 4:
        token = token[:-2]
    if token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    if token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    if token.endswith("es") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 3:
        token = token[:-1]
    return token


def _tokenize(text: str) -> set[str]:
    return {
        _stem_token(token)
        for token in re.findall(r"[a-zA-Z]+", (text or "").lower())
        if _stem_token(token) and _stem_token(token) not in _STOPWORDS
    }


def _score_overlap(response_tokens: set[str], candidate_tokens: set[str]) -> int:
    return len(response_tokens & candidate_tokens)


async def map_response_to_kb_item(
    assistant,
    response_text: str,
    object_name: str,
    physical_dimensions: dict[str, dict[str, str]] | None,
    engagement_dimensions: dict[str, list[str]] | None,
) -> dict | None:
    """
    Best-effort debug mapper from finished response text to one KB item.

    This is descriptive metadata only. It does not claim causal grounding.
    """
    del assistant  # Reserved for future LLM-backed mapping if heuristics prove insufficient.
    del object_name

    response_tokens = _tokenize(response_text)
    if not response_tokens:
        return None

    best_score = 0
    best_item = None

    for dimension, attrs in (physical_dimensions or {}).items():
        for attribute, value in attrs.items():
            attribute_text = attribute.replace("_", " ")
            candidate_tokens = (
                _tokenize(dimension)
                | _tokenize(attribute_text)
                | _tokenize(value)
            )
            score = _score_overlap(response_tokens, candidate_tokens)
            if attribute_text in (response_text or "").lower():
                score += 3
            if value.lower() in (response_text or "").lower():
                score += 5
            if score > best_score:
                best_score = score
                best_item = {
                    "kind": "physical_attribute",
                    "dimension": dimension,
                    "attribute": attribute,
                    "value": value,
                }

    for dimension, seeds in (engagement_dimensions or {}).items():
        dimension_tokens = _tokenize(dimension)
        for seed_text in seeds:
            candidate_tokens = dimension_tokens | _tokenize(seed_text)
            score = _score_overlap(response_tokens, candidate_tokens)
            if score > best_score:
                best_score = score
                best_item = {
                    "kind": "engagement_item",
                    "dimension": dimension,
                    "seed_text": seed_text,
                }

    return best_item if best_score > 0 else None
