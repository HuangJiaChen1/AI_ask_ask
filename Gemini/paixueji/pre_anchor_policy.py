from __future__ import annotations

import re
from dataclasses import dataclass

from bridge_context import build_bridge_context, normalize_relation
from stream.validation import classify_bridge_follow


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

_OUT_OF_LANE_ANCHOR_RELATED_TERMS = (
    "see",
    "look",
    "watch",
    "hear",
    "sound",
    "bowl",
    "find",
    "notice",
    "there",
)


def _normalize(text: str | None) -> str:
    return " ".join(re.sub(r"[^a-zA-Z']+", " ", text or "").strip().lower().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return phrase in f" {text} "


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(_contains_phrase(text, pattern) for pattern in patterns)


def _previous_question_mentions_bridge_context(
    previous_bridge_question: str | None,
    relation: str | None,
    surface_object_name: str,
    anchor_object_name: str,
) -> bool:
    bridge_context = build_bridge_context(
        surface_object_name,
        anchor_object_name,
        normalize_relation(relation),
        attempt_number=1,
    )
    normalized_question = _normalize(previous_bridge_question)
    if not normalized_question or not bridge_context:
        return False

    lane_terms = set(bridge_context.allowed_focus_terms) | set(bridge_context.follow_terms) | {"food", "cat"}
    return any(_contains_phrase(normalized_question, term) for term in lane_terms if term)


def _looks_anchor_related_out_of_lane(
    child_answer: str,
    previous_bridge_question: str | None,
    relation: str | None,
    surface_object_name: str,
    anchor_object_name: str,
) -> bool:
    normalized_answer = _normalize(child_answer)
    if not _previous_question_mentions_bridge_context(
        previous_bridge_question,
        relation,
        surface_object_name,
        anchor_object_name,
    ):
        return False
    return _matches_any(normalized_answer, _OUT_OF_LANE_ANCHOR_RELATED_TERMS)


async def classify_pre_anchor_reply(
    *,
    assistant,
    child_answer: str,
    surface_object_name: str,
    anchor_object_name: str,
    relation: str | None,
    previous_bridge_question: str | None = None,
    bridge_follow_classifier=classify_bridge_follow,
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

    bridge_follow = await bridge_follow_classifier(
        assistant=assistant,
        child_answer=child_answer,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        relation=relation,
        previous_bridge_question=previous_bridge_question,
    )

    if bridge_follow.get("bridge_followed"):
        return PreAnchorReplyDecision(
            reply_type="in_lane_follow",
            bridge_followed=True,
            reason="child followed bridge",
            consume_bridge_attempt=False,
            bridge_follow_reason=bridge_follow.get("reason"),
        )

    if _matches_any(normalized_answer, _NEGATIVE_OR_REFUSAL_PATTERNS):
        return PreAnchorReplyDecision(
            reply_type="negative_or_refusal",
            bridge_followed=False,
            reason="child declined bridge",
            consume_bridge_attempt=True,
            bridge_follow_reason=bridge_follow.get("reason"),
        )

    if _looks_anchor_related_out_of_lane(
        child_answer,
        previous_bridge_question,
        relation,
        surface_object_name,
        anchor_object_name,
    ):
        return PreAnchorReplyDecision(
            reply_type="valid_out_of_lane_anchor_related",
            bridge_followed=False,
            reason="child answered reasonably outside bridge lane",
            consume_bridge_attempt=False,
            support_action="steer",
            bridge_follow_reason=bridge_follow.get("reason"),
        )

    return PreAnchorReplyDecision(
        reply_type="true_miss",
        bridge_followed=False,
        reason=bridge_follow.get("reason") or "child did not engage bridge",
        consume_bridge_attempt=True,
        bridge_follow_reason=bridge_follow.get("reason"),
    )
