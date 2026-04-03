from __future__ import annotations

from typing import Any


def build_resolution_debug(
    *,
    surface_object_name: str,
    decision_source: str,
    decision_reason: str,
    candidate_anchors: list[str],
    model_attempted: bool,
    raw_model_response: str | None = None,
    raw_model_payload_kind: str | None = None,
    json_recovery_applied: bool = False,
    parsed_anchor_raw: str | None = None,
    parsed_relation_raw: str | None = None,
    parsed_confidence_raw: str | None = None,
    anchor_object_name: str | None = None,
    anchor_status: str | None = None,
    unresolved_surface_only_mode: bool = False,
) -> dict[str, Any]:
    return {
        "surface_object_name": surface_object_name,
        "decision_source": decision_source,
        "decision_reason": decision_reason,
        "candidate_anchors": candidate_anchors,
        "model_attempted": model_attempted,
        "raw_model_response": raw_model_response,
        "raw_model_payload_kind": raw_model_payload_kind,
        "json_recovery_applied": json_recovery_applied,
        "parsed_anchor_raw": parsed_anchor_raw,
        "parsed_relation_raw": parsed_relation_raw,
        "parsed_confidence_raw": parsed_confidence_raw,
        "anchor_object_name": anchor_object_name,
        "anchor_status": anchor_status,
        "unresolved_surface_only_mode": unresolved_surface_only_mode,
    }


def format_resolution_log_line(
    *,
    session_id: str,
    request_id: str,
    resolution_debug: dict[str, Any] | None,
) -> str:
    debug = resolution_debug or {}
    candidate_count = len(debug.get("candidate_anchors") or [])
    return (
        f"session={session_id} "
        f"request={request_id} "
        f"decision_source={debug.get('decision_source')} "
        f"decision_reason={debug.get('decision_reason')} "
        f"payload_kind={debug.get('raw_model_payload_kind')} "
        f"json_recovery={debug.get('json_recovery_applied')} "
        f"anchor_status={debug.get('anchor_status')} "
        f"anchor_object={debug.get('anchor_object_name')} "
        f"candidate_count={candidate_count}"
    )
