from __future__ import annotations

from typing import Any

from bridge_context import build_bridge_context, normalize_relation


def detect_bridge_visibility(
    response_text: str,
    surface_object_name: str | None,
    anchor_object_name: str | None,
    anchor_relation: str | None,
) -> tuple[bool, str]:
    normalized_response = " ".join((response_text or "").strip().lower().split())
    normalized_surface = " ".join((surface_object_name or "").strip().lower().split())
    normalized_anchor = " ".join((anchor_object_name or "").strip().lower().split())

    response_without_surface = normalized_response
    if normalized_surface:
        response_without_surface = response_without_surface.replace(normalized_surface, " ")
        response_without_surface = " ".join(response_without_surface.split())

    if normalized_anchor and normalized_anchor in response_without_surface:
        return True, "explicit anchor mention outside surface object"

    bridge_context = build_bridge_context(
        surface_object_name=surface_object_name or "",
        anchor_object_name=anchor_object_name or "",
        relation=normalize_relation(anchor_relation),
        attempt_number=1,
    )
    if bridge_context:
        for term in bridge_context.allowed_focus_terms:
            if term and term in normalized_response:
                return True, f"matched relation focus term: {term}"

    return False, "response did not expose the bridge connection"


def build_bridge_debug(
    *,
    surface_object_name: str | None,
    anchor_object_name: str | None,
    anchor_status: str | None,
    anchor_relation: str | None,
    anchor_confidence_band: str | None,
    intro_mode: str | None,
    learning_anchor_active_before: bool | None,
    learning_anchor_active_after: bool | None,
    bridge_attempt_count_before: int | None,
    bridge_attempt_count_after: int | None,
    decision: str | None,
    decision_reason: str | None,
    response_text: str = "",
    response_type: str | None = None,
    bridge_followed: bool | None = None,
    bridge_follow_reason: str | None = None,
    pre_anchor_handler_entered: bool = False,
    kb_mode: str | None = None,
    bridge_context_summary: str | None = None,
) -> dict[str, Any]:
    bridge_visible_in_response, bridge_visibility_reason = detect_bridge_visibility(
        response_text=response_text,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        anchor_relation=anchor_relation,
    )
    return {
        "surface_object_name": surface_object_name,
        "anchor_object_name": anchor_object_name,
        "anchor_status": anchor_status,
        "anchor_relation": normalize_relation(anchor_relation) if anchor_relation else None,
        "anchor_confidence_band": anchor_confidence_band,
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
        "bridge_visible_in_response": bridge_visible_in_response,
        "bridge_visibility_reason": bridge_visibility_reason,
    }


def bridge_verdict(bridge_debug: dict[str, Any] | None) -> str:
    if not bridge_debug:
        return "No bridge debug was recorded for this turn."
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
        f"decision={debug.get('decision')} "
        f"attempt_after={debug.get('bridge_attempt_count_after')}"
    )
