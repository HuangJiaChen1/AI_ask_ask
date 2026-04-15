from __future__ import annotations

import re
from dataclasses import dataclass

from stream.validation import classify_pre_anchor_semantic_reply


@dataclass(frozen=True)
class PreAnchorReplyDecision:
    reply_type: str
    bridge_followed: bool
    reason: str
    consume_bridge_attempt: bool
    support_action: str | None = None
    bridge_follow_reason: str | None = None


_CLARIFICATION_PATTERNS = (
    "what do you mean",
    "whay do you mean",
    "what you mean",
    "i don't understand",
    "i dont understand",
    "huh",
)

_IDK_PATTERNS = (
    "i don't know",
    "i dont know",
    "don't know",
    "dont know",
    "idk",
    "not sure",
)

_NEGATIVE_OR_REFUSAL_PATTERNS = (
    "no",
    "nope",
    "nah",
    "not really",
    "i don't want",
    "i dont want",
)

def _normalize(text: str | None) -> str:
    return " ".join(re.sub(r"[^a-zA-Z']+", " ", text or "").strip().lower().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    text_tokens = text.split()
    phrase_tokens = _normalize(phrase).split()
    if not text_tokens or not phrase_tokens or len(phrase_tokens) > len(text_tokens):
        return False
    window = len(phrase_tokens)
    for index in range(len(text_tokens) - window + 1):
        if text_tokens[index:index + window] == phrase_tokens:
            return True
    return False


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(_contains_phrase(text, pattern) for pattern in patterns)


def _is_standalone_phrase(text: str, patterns: tuple[str, ...]) -> bool:
    return any(text == _normalize(pattern) for pattern in patterns)


async def classify_pre_anchor_reply(
    *,
    assistant,
    child_answer: str,
    surface_object_name: str,
    anchor_object_name: str,
    relation: str | None,
    bridge_profile=None,
    previous_bridge_question: str | None = None,
    semantic_reply_classifier=classify_pre_anchor_semantic_reply,
) -> PreAnchorReplyDecision:
    normalized_answer = _normalize(child_answer)

    if _matches_any(normalized_answer, _CLARIFICATION_PATTERNS):
        return PreAnchorReplyDecision(
            reply_type="clarification_request",
            bridge_followed=False,
            reason="child asked for clarification",
            consume_bridge_attempt=False,
            support_action="clarify",
        )

    if _matches_any(normalized_answer, _IDK_PATTERNS):
        return PreAnchorReplyDecision(
            reply_type="idk_or_stuck",
            bridge_followed=False,
            reason="child is stuck",
            consume_bridge_attempt=False,
            support_action="scaffold",
        )

    if _is_standalone_phrase(normalized_answer, _NEGATIVE_OR_REFUSAL_PATTERNS):
        return PreAnchorReplyDecision(
            reply_type="negative_or_refusal",
            bridge_followed=False,
            reason="child declined bridge",
            consume_bridge_attempt=True,
        )

    semantic_reply = await semantic_reply_classifier(
        assistant=assistant,
        child_answer=child_answer,
        bridge_profile=bridge_profile,
        previous_bridge_question=previous_bridge_question,
    )
    semantic_reply_type = semantic_reply.get("reply_type")
    if semantic_reply_type is None and "bridge_followed" in semantic_reply:
        semantic_reply_type = "followed" if semantic_reply.get("bridge_followed") else "true_miss"

    if semantic_reply_type == "followed":
        return PreAnchorReplyDecision(
            reply_type="in_lane_follow",
            bridge_followed=True,
            reason="child followed bridge",
            consume_bridge_attempt=False,
            bridge_follow_reason=semantic_reply.get("reason"),
        )

    if semantic_reply_type == "anchor_related_but_off_lane":
        return PreAnchorReplyDecision(
            reply_type="anchor_related_but_off_lane",
            bridge_followed=False,
            reason="child answered reasonably outside bridge lane",
            consume_bridge_attempt=False,
            support_action="steer",
            bridge_follow_reason=semantic_reply.get("reason"),
        )

    return PreAnchorReplyDecision(
        reply_type="true_miss",
        bridge_followed=False,
        reason=semantic_reply.get("reason") or "child did not engage bridge",
        consume_bridge_attempt=True,
        bridge_follow_reason=semantic_reply.get("reason"),
    )
