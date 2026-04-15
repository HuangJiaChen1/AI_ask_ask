"""
Intent and KB-mapping logic for Paixueji assistant.

Functions:
    - classify_intent: Async LLM classifier → 9 intents + optional new_object extraction
    - classify_dimension: Legacy dimension classifier (still exported for compatibility)
    - map_response_to_kb_item: Debug-only best-effort mapper from response text to one KB item
"""
import inspect
import json
import re
import time
from unittest.mock import AsyncMock
from loguru import logger
import paixueji_prompts
from bridge_activation_policy import (
    detect_activation_answer_heuristic,
    match_activation_question_to_kb_deterministic,
)
from bridge_context import normalize_relation
from model_json import extract_json_object

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


async def classify_pre_anchor_semantic_reply(
    assistant,
    child_answer: str,
    bridge_profile,
    previous_bridge_question: str | None = None,
) -> dict:
    """Judge whether a pre-anchor reply followed the semantic bridge lane."""
    if bridge_profile is None:
        return {"reply_type": "true_miss", "reason": "no bridge profile"}

    client = getattr(assistant, "client", None)
    config = getattr(assistant, "config", None)
    generate_content = getattr(getattr(getattr(client, "aio", None), "models", None), "generate_content", None)
    if (
        client is None
        or config is None
        or not isinstance(config, dict)
        or not config.get("model_name")
        or generate_content is None
        or not (inspect.iscoroutinefunction(generate_content) or isinstance(generate_content, AsyncMock))
    ):
        return {"reply_type": "true_miss", "reason": "no semantic reply classifier available"}

    prompt = paixueji_prompts.get_prompts()["bridge_follow_classifier_prompt"].format(
        surface_object_name=bridge_profile.surface_object_name,
        anchor_object_name=bridge_profile.anchor_object_name,
        relation=normalize_relation(bridge_profile.relation),
        bridge_intent=bridge_profile.bridge_intent,
        good_question_angles=", ".join(bridge_profile.good_question_angles),
        avoid_angles=", ".join(bridge_profile.avoid_angles),
        steer_back_rule=bridge_profile.steer_back_rule,
        focus_cues=", ".join(bridge_profile.focus_cues),
        previous_bridge_question=previous_bridge_question or "",
        child_answer=child_answer,
    )

    try:
        response = await generate_content(
            model=config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
        )
        payload, _, _ = extract_json_object(response.text or "")
    except Exception:
        payload = None

    if not isinstance(payload, dict):
        return {"reply_type": "true_miss", "reason": "semantic reply classifier failed"}

    reply_type = str(payload.get("reply_type") or "").strip()
    if reply_type not in {"followed", "anchor_related_but_off_lane", "true_miss"}:
        return {"reply_type": "true_miss", "reason": "semantic reply classifier failed"}

    return {
        "reply_type": reply_type,
        "reason": payload.get("reason") or "semantic reply classifier returned no reason",
    }


async def classify_bridge_follow(
    assistant,
    child_answer: str,
    surface_object_name: str,
    anchor_object_name: str,
    relation: str | None,
    previous_bridge_question: str | None = None,
    bridge_profile=None,
) -> dict:
    """Backward-compatible bridge follow wrapper."""
    semantic_result = await classify_pre_anchor_semantic_reply(
        assistant=assistant,
        child_answer=child_answer,
        bridge_profile=bridge_profile,
        previous_bridge_question=previous_bridge_question,
    )
    return {
        "bridge_followed": semantic_result.get("reply_type") == "followed",
        "reason": semantic_result.get("reason"),
    }


def _format_activation_kb_block(dimensions: dict | None) -> str:
    if not dimensions:
        return "none"
    return json.dumps(dimensions, ensure_ascii=False, indent=2, sort_keys=True)


async def validate_bridge_activation_kb_question(
    assistant,
    final_question: str | None,
    anchor_object_name: str,
    physical_dimensions: dict[str, dict[str, str]] | None,
    engagement_dimensions: dict[str, list[str]] | None,
) -> dict:
    deterministic = match_activation_question_to_kb_deterministic(
        final_question,
        physical_dimensions,
        engagement_dimensions,
    )
    if deterministic.confidence != "inconclusive":
        return {
            "kb_backed_question": deterministic.matched,
            "handoff_ready_question": deterministic.handoff_ready,
            "reason": "deterministic match",
            "source": "deterministic",
            "confidence": deterministic.confidence,
            "kb_item": deterministic.kb_item,
        }

    if not hasattr(assistant, "client") or not hasattr(assistant.client, "aio"):
        return {
            "kb_backed_question": bool(deterministic.matched),
            "handoff_ready_question": bool(deterministic.handoff_ready),
            "reason": "no validator available",
            "source": "deterministic_fallback",
            "confidence": "inconclusive",
            "kb_item": deterministic.kb_item,
        }

    prompt = paixueji_prompts.get_prompts()["bridge_activation_kb_question_validator_prompt"].format(
        anchor_object_name=anchor_object_name,
        final_question=final_question or "",
        physical_kb=_format_activation_kb_block(physical_dimensions),
        engagement_kb=_format_activation_kb_block(engagement_dimensions),
    )

    try:
        response = await assistant.client.aio.models.generate_content(
            model=assistant.config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
        )
        payload = json.loads(response.text or "{}")
    except Exception:
        payload = {}

    return {
        "kb_backed_question": bool(payload.get("kb_backed_question")),
        "handoff_ready_question": bool(payload.get("handoff_ready_question") or payload.get("kb_backed_question")),
        "reason": payload.get("reason") or "validator fallback",
        "source": "validator",
        "confidence": "inconclusive",
        "kb_item": deterministic.kb_item if (payload.get("handoff_ready_question") or payload.get("kb_backed_question")) else None,
    }


async def validate_bridge_activation_answer(
    assistant,
    child_answer: str,
    previous_question: str | None,
    anchor_object_name: str,
    physical_dimensions: dict[str, dict[str, str]] | None,
    engagement_dimensions: dict[str, list[str]] | None,
) -> dict:
    heuristic = detect_activation_answer_heuristic(child_answer, previous_question)
    if heuristic["answered_previous_question"] is not None:
        return {
            "answered_previous_question": bool(heuristic["answered_previous_question"]),
            "answered_previous_kb_question": bool(heuristic["answered_previous_question"]),
            "answer_polarity": heuristic["answer_polarity"],
            "reason": heuristic["reason"],
            "source": "deterministic",
        }

    if not hasattr(assistant, "client") or not hasattr(assistant.client, "aio"):
        return {
            "answered_previous_question": False,
            "answered_previous_kb_question": False,
            "answer_polarity": None,
            "reason": "no validator available",
            "source": "deterministic_fallback",
        }

    prompt = paixueji_prompts.get_prompts()["bridge_activation_answer_validator_prompt"].format(
        anchor_object_name=anchor_object_name,
        previous_question=previous_question or "",
        child_answer=child_answer,
        physical_kb=_format_activation_kb_block(physical_dimensions),
        engagement_kb=_format_activation_kb_block(engagement_dimensions),
    )

    try:
        response = await assistant.client.aio.models.generate_content(
            model=assistant.config["model_name"],
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 80},
        )
        payload = json.loads(response.text or "{}")
    except Exception:
        payload = {}

    return {
        "answered_previous_question": bool(
            payload.get("answered_previous_question", payload.get("answered_previous_kb_question"))
        ),
        "answered_previous_kb_question": bool(
            payload.get("answered_previous_question", payload.get("answered_previous_kb_question"))
        ),
        "answer_polarity": payload.get("answer_polarity"),
        "reason": payload.get("reason") or "validator fallback",
        "source": "validator",
    }


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
