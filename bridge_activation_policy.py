from __future__ import annotations

from dataclasses import dataclass
import re


BRIDGE_PHASE_NONE = "none"
BRIDGE_PHASE_PRE_ANCHOR = "pre_anchor"
BRIDGE_PHASE_ACTIVATION = "activation"
BRIDGE_PHASE_ANCHOR_GENERAL = "anchor_general"

_YES_NO_ANSWER_PATTERNS = {
    "yes",
    "yeah",
    "yep",
    "maybe",
    "no",
    "nope",
    "nah",
    "not really",
}

_POSITIVE_ANSWER_PATTERNS = {
    "yes",
    "yeah",
    "yep",
    "maybe",
}

_NEGATIVE_ANSWER_PATTERNS = {
    "no",
    "nope",
    "nah",
    "not really",
}

_ANSWER_PIVOT_PATTERNS = (
    "yes but",
    "yes, but",
    "no but",
    "no, but",
    "not really but",
    "not really, but",
    "yep but",
    "yep, but",
    "yeah but",
    "yeah, but",
)

_HANDOFF_READY_ATTRIBUTE_ALIASES = {
    "paw_pads": {"paw", "paws"},
}

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "do",
    "does", "for", "from", "has", "have", "her", "if", "in", "into", "is",
    "it", "its", "like", "make", "of", "on", "or", "she", "so", "that", "the",
    "their", "them", "they", "this", "to", "very", "when", "with", "you",
    "your",
}


@dataclass(frozen=True)
class ActivationQuestionMatch:
    matched: bool
    confidence: str
    kb_item: dict | None = None
    handoff_ready: bool = False


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


def _tokenize(text: str | None) -> set[str]:
    return {
        _stem_token(token)
        for token in re.findall(r"[a-zA-Z]+", (text or "").lower())
        if _stem_token(token) and _stem_token(token) not in _STOPWORDS
    }


def extract_final_question(response_text: str) -> str | None:
    question = (response_text or "").strip()
    if not question.endswith("?"):
        return None
    fragments = re.split(r"(?<=[.!])\s+", question)
    return fragments[-1].strip() if fragments else question


def match_activation_question_to_kb_deterministic(
    question: str | None,
    physical_dimensions: dict | None,
    engagement_dimensions: dict | None,
) -> ActivationQuestionMatch:
    question_text = (question or "").strip()
    if not question_text:
        return ActivationQuestionMatch(matched=False, confidence="high", kb_item=None)

    question_lower = question_text.lower()
    question_tokens = _tokenize(question_text)
    best_item = None
    best_score = 0
    handoff_ready_item = None

    for dimension, attrs in (physical_dimensions or {}).items():
        for attribute, value in (attrs or {}).items():
            attribute_text = attribute.replace("_", " ")
            candidate_tokens = _tokenize(dimension) | _tokenize(attribute_text) | _tokenize(value)
            overlap = len(question_tokens & candidate_tokens)
            score = overlap
            if attribute_text in question_lower:
                score += 4
            if value.lower() in question_lower:
                score += 6
            if score > best_score:
                best_score = score
                best_item = {
                    "kind": "physical_attribute",
                    "dimension": dimension,
                    "attribute": attribute,
                    "value": value,
                }
            aliases = _HANDOFF_READY_ATTRIBUTE_ALIASES.get(attribute, set())
            if aliases and question_tokens & aliases:
                handoff_ready_item = {
                    "kind": "physical_attribute",
                    "dimension": dimension,
                    "attribute": attribute,
                    "value": value,
                }

    for dimension, seeds in (engagement_dimensions or {}).items():
        for seed_text in (seeds or []):
            candidate_tokens = _tokenize(dimension) | _tokenize(seed_text)
            overlap = len(question_tokens & candidate_tokens)
            score = overlap if overlap >= 2 else 0
            if seed_text.lower() in question_lower:
                score += 6
            if score > best_score:
                best_score = score
                best_item = {
                    "kind": "engagement_item",
                    "dimension": dimension,
                    "seed_text": seed_text,
                }

    if best_score >= 4:
        return ActivationQuestionMatch(
            matched=True,
            confidence="high",
            kb_item=best_item,
            handoff_ready=True,
        )
    if handoff_ready_item:
        return ActivationQuestionMatch(
            matched=False,
            confidence="high",
            kb_item=handoff_ready_item,
            handoff_ready=True,
        )
    if best_score > 0:
        return ActivationQuestionMatch(
            matched=True,
            confidence="inconclusive",
            kb_item=best_item,
            handoff_ready=False,
        )
    return ActivationQuestionMatch(matched=False, confidence="high", kb_item=None, handoff_ready=False)


def detect_activation_answer_heuristic(child_answer: str, previous_question: str | None) -> dict:
    if not previous_question:
        return {
            "answered_previous_question": None,
            "answer_polarity": None,
            "reason": "missing_previous_question",
        }

    normalized = " ".join((child_answer or "").strip().lower().split())
    if not normalized:
        return {
            "answered_previous_question": None,
            "answer_polarity": None,
            "reason": "empty_answer",
        }
    if normalized.startswith(_ANSWER_PIVOT_PATTERNS):
        return {
            "answered_previous_question": False,
            "answer_polarity": None,
            "reason": "pivot_reply",
        }
    if normalized in _POSITIVE_ANSWER_PATTERNS:
        return {
            "answered_previous_question": True,
            "answer_polarity": "yes",
            "reason": "direct_yes_no",
        }
    if normalized in _NEGATIVE_ANSWER_PATTERNS:
        return {
            "answered_previous_question": True,
            "answer_polarity": "no",
            "reason": "direct_yes_no",
        }
    return {
        "answered_previous_question": None,
        "answer_polarity": None,
        "reason": "inconclusive",
    }


def classify_activation_reopen_signal(
    child_answer: str,
    anchor_object_name: str,
    physical_dimensions: dict | None,
    engagement_dimensions: dict | None,
) -> bool:
    del anchor_object_name  # The signal must resolve through anchor-side content, not anchor memory alone.

    answer_tokens = _tokenize(child_answer)
    if not answer_tokens:
        return False

    for dimension, attrs in (physical_dimensions or {}).items():
        for attribute, value in (attrs or {}).items():
            candidate_tokens = _tokenize(dimension) | _tokenize(attribute.replace("_", " ")) | _tokenize(value)
            if answer_tokens & candidate_tokens:
                return True

    for dimension, seeds in (engagement_dimensions or {}).items():
        for seed_text in (seeds or []):
            candidate_tokens = _tokenize(dimension) | _tokenize(seed_text)
            if answer_tokens & candidate_tokens:
                return True

    return False
