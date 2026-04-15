from __future__ import annotations

import re
from typing import Any

from bridge_context import normalize_relation


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text)


def _contains_token_sequence(tokens: list[str], phrase_tokens: list[str]) -> bool:
    if not tokens or not phrase_tokens or len(phrase_tokens) > len(tokens):
        return False
    window = len(phrase_tokens)
    for index in range(len(tokens) - window + 1):
        if tokens[index:index + window] == phrase_tokens:
            return True
    return False


def build_activation_continuity_anchor(kb_item: dict | None) -> str | None:
    if not kb_item:
        return None
    kind = kb_item.get("kind")
    dimension = (kb_item.get("dimension") or "").strip()
    if kind == "physical_attribute":
        attribute = (kb_item.get("attribute") or "").strip()
        if dimension and attribute:
            return f"physical.{dimension}.{attribute}"
    if kind == "engagement_item":
        seed_text = (kb_item.get("seed_text") or "").strip()
        if dimension and seed_text:
            return f"engagement.{dimension}:{seed_text}"
    return None


def build_activation_transition_debug(
    *,
    before_state: dict[str, Any] | None = None,
    question_validation: dict[str, Any] | None = None,
    answer_validation: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
    turn_interpretation: dict[str, Any] | None = None,
    continuity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transition = {
        "before_state": before_state,
        "question_validation": question_validation,
        "answer_validation": answer_validation,
        "outcome": outcome,
        "turn_interpretation": turn_interpretation,
        "continuity": continuity,
    }
    return {key: value for key, value in transition.items() if value is not None}


def detect_bridge_visibility(
    response_text: str,
    surface_object_name: str | None,
    anchor_object_name: str | None,
    anchor_relation: str | None,
    bridge_profile=None,
) -> tuple[bool, str]:
    normalized_response = " ".join((response_text or "").strip().lower().split())
    normalized_surface = " ".join((surface_object_name or "").strip().lower().split())
    normalized_anchor = " ".join((anchor_object_name or "").strip().lower().split())
    response_tokens = _tokenize(normalized_response)

    response_without_surface = normalized_response
    if normalized_surface:
        response_without_surface = response_without_surface.replace(normalized_surface, " ")
        response_without_surface = " ".join(response_without_surface.split())
    response_without_surface_tokens = _tokenize(response_without_surface)
    anchor_tokens = _tokenize(normalized_anchor)

    if anchor_tokens and _contains_token_sequence(response_without_surface_tokens, anchor_tokens):
        return True, "explicit anchor mention outside surface object"

    if bridge_profile:
        for term in getattr(bridge_profile, "focus_cues", ()) or ():
            term_tokens = _tokenize(term)
            if _contains_token_sequence(response_tokens, term_tokens):
                return True, f"matched bridge focus cue: {term}"

    if normalized_surface and normalized_surface in normalized_response:
        return False, "response stayed on the surface object without an anchor mention"

    return False, "response did not expose the bridge connection"


def build_bridge_debug(
    *,
    surface_object_name: str | None,
    anchor_object_name: str | None,
    anchor_status: str | None,
    anchor_relation: str | None,
    anchor_confidence_band: str | None,
    bridge_profile=None,
    bridge_profile_status: str | None = None,
    bridge_profile_reason: str | None = None,
    intro_mode: str | None,
    learning_anchor_active_before: bool | None,
    learning_anchor_active_after: bool | None,
    bridge_attempt_count_before: int | None,
    bridge_attempt_count_after: int | None,
    decision: str | None,
    decision_reason: str | None,
    response_text: str | None = None,
    response_type: str | None = None,
    bridge_followed: bool | None = None,
    bridge_follow_reason: str | None = None,
    pre_anchor_handler_entered: bool = False,
    kb_mode: str | None = None,
    bridge_context_summary: str | None = None,
    activation_grounding_mode: str | None = None,
    activation_grounding_summary: str | None = None,
    bridge_phase_before: str | None = None,
    bridge_phase_after: str | None = None,
    activation_turn_count_before: int | None = None,
    activation_turn_count_after: int | None = None,
    activation_handoff_ready_after: bool | None = None,
    activation_last_question: str | None = None,
    activation_last_question_kb_item: dict | None = None,
    activation_transition: dict[str, Any] | None = None,
    pre_anchor_reply_type: str | None = None,
    support_action: str | None = None,
    pre_anchor_support_count_before: int | None = None,
    pre_anchor_support_count_after: int | None = None,
) -> dict[str, Any]:
    bridge_visible_in_response = None
    bridge_visibility_reason = "response not evaluated yet"
    if bridge_profile_status is None and bridge_profile is not None:
        bridge_profile_status = "ready"
    if bridge_profile_reason is None and bridge_profile is not None:
        bridge_profile_reason = "bridge_profile_inferred"
    if response_text:
        bridge_visible_in_response, bridge_visibility_reason = detect_bridge_visibility(
            response_text=response_text,
            surface_object_name=surface_object_name,
            anchor_object_name=anchor_object_name,
            anchor_relation=anchor_relation,
            bridge_profile=bridge_profile,
        )
    return {
        "surface_object_name": surface_object_name,
        "anchor_object_name": anchor_object_name,
        "anchor_status": anchor_status,
        "anchor_relation": normalize_relation(anchor_relation) if anchor_relation else None,
        "anchor_confidence_band": anchor_confidence_band,
        "bridge_profile": bridge_profile.__dict__ if bridge_profile else None,
        "bridge_profile_status": bridge_profile_status,
        "bridge_profile_reason": bridge_profile_reason,
        "intro_mode": intro_mode,
        "learning_anchor_active_before": learning_anchor_active_before,
        "learning_anchor_active_after": learning_anchor_active_after,
        "bridge_attempt_count_before": bridge_attempt_count_before,
        "bridge_attempt_count_after": bridge_attempt_count_after,
        "pre_anchor_handler_entered": pre_anchor_handler_entered,
        "bridge_followed": bridge_followed,
        "bridge_follow_reason": bridge_follow_reason,
        "decision": decision,
        "decision_reason": decision_reason,
        "response_type": response_type,
        "kb_mode": kb_mode,
        "bridge_context_summary": bridge_context_summary,
        "activation_grounding_mode": activation_grounding_mode,
        "activation_grounding_summary": activation_grounding_summary,
        "bridge_phase_before": bridge_phase_before,
        "bridge_phase_after": bridge_phase_after,
        "activation_turn_count_before": activation_turn_count_before,
        "activation_turn_count_after": activation_turn_count_after,
        "activation_handoff_ready_after": activation_handoff_ready_after,
        "activation_last_question": activation_last_question,
        "activation_last_question_kb_item": activation_last_question_kb_item,
        "activation_transition": activation_transition,
        "bridge_visible_in_response": bridge_visible_in_response,
        "bridge_visibility_reason": bridge_visibility_reason,
        "pre_anchor_reply_type": pre_anchor_reply_type,
        "support_action": support_action,
        "pre_anchor_support_count_before": pre_anchor_support_count_before,
        "pre_anchor_support_count_after": pre_anchor_support_count_after,
    }


def bridge_verdict(bridge_debug: dict[str, Any] | None) -> str:
    if not bridge_debug:
        return "No bridge debug was recorded for this turn."
    if bridge_debug.get("decision") == "bridge_not_started":
        return "Bridge was never started because anchor resolution ended unresolved."
    if bridge_debug.get("bridge_visible_in_response"):
        return "Bridge was visible in the response."
    return f"Bridge did not expose the connection: {bridge_debug.get('bridge_visibility_reason', 'unknown reason')}."


def build_bridge_trace_entry(
    *,
    node: str,
    state_before: dict[str, Any],
    changes: dict[str, Any],
    time_ms: float,
    phase: str = "response",
) -> dict[str, Any]:
    return {
        "node": node,
        "time_ms": time_ms,
        "changes": changes,
        "state_changes": changes,
        "state_before": state_before,
        "phase": phase,
    }


def format_bridge_log_line(
    *,
    session_id: str,
    request_id: str,
    bridge_debug: dict[str, Any] | None,
) -> str:
    debug = bridge_debug or {}
    return (
        f"session={session_id} "
        f"request={request_id} "
        f"anchor_status={debug.get('anchor_status')} "
        f"response_type={debug.get('response_type')} "
        f"decision={debug.get('decision')} "
        f"reply_type={debug.get('pre_anchor_reply_type')} "
        f"support_action={debug.get('support_action')} "
        f"bridge_followed={debug.get('bridge_followed')} "
        f"follow_reason={debug.get('bridge_follow_reason')!r} "
        f"attempt_before={debug.get('bridge_attempt_count_before')} "
        f"attempt_after={debug.get('bridge_attempt_count_after')} "
        f"support_before={debug.get('pre_anchor_support_count_before')} "
        f"support_after={debug.get('pre_anchor_support_count_after')} "
        f"kb_mode={debug.get('kb_mode')} "
        f"visibility={debug.get('bridge_visible_in_response')}"
    )
