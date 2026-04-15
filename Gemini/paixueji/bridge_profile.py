from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import paixueji_prompts
from model_json import extract_json_object


@dataclass(frozen=True)
class BridgeProfile:
    surface_object_name: str
    anchor_object_name: str
    relation: str
    bridge_intent: str
    good_question_angles: tuple[str, ...]
    avoid_angles: tuple[str, ...]
    steer_back_rule: str
    focus_cues: tuple[str, ...] = ()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_list(values: Any) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = _normalize_text(value)
        if not item or item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    return tuple(normalized)


def infer_bridge_profile(
    surface_object_name: str,
    anchor_object_name: str,
    relation: str,
    client: Any,
    config: dict[str, Any],
) -> tuple[BridgeProfile | None, dict[str, Any]]:
    debug = {
        "surface_object_name": surface_object_name,
        "anchor_object_name": anchor_object_name,
        "relation": relation,
        "decision_source": "bridge_profile_inference",
        "decision_reason": None,
        "raw_model_response": None,
        "raw_model_payload_kind": None,
        "json_recovery_applied": False,
    }
    if client is None or not hasattr(client, "models") or not hasattr(client.models, "generate_content"):
        debug["decision_reason"] = "no_model_client"
        return None, debug

    prompt = paixueji_prompts.get_prompts()["bridge_profile_prompt"].format(
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        relation=relation,
    )
    try:
        response = client.models.generate_content(
            model=config.get("model_name", ""),
            contents=prompt,
            config={"temperature": 0},
        )
        raw_text = response.text or ""
    except Exception:
        raw_text = None
    if not isinstance(raw_text, str):
        raw_text = None

    debug["raw_model_response"] = raw_text
    payload, payload_kind, recovery_applied = extract_json_object(raw_text)
    debug["raw_model_payload_kind"] = payload_kind
    debug["json_recovery_applied"] = recovery_applied
    if not isinstance(payload, dict):
        debug["decision_reason"] = "invalid_bridge_profile_payload"
        return None, debug

    bridge_intent = _normalize_text(payload.get("bridge_intent"))
    good_question_angles = _normalize_list(payload.get("good_question_angles"))
    avoid_angles = _normalize_list(payload.get("avoid_angles"))
    steer_back_rule = _normalize_text(payload.get("steer_back_rule"))
    focus_cues = _normalize_list(payload.get("focus_cues"))

    if not bridge_intent or not good_question_angles or not steer_back_rule:
        debug["decision_reason"] = "invalid_bridge_profile_payload"
        return None, debug

    debug["decision_reason"] = "bridge_profile_inferred"
    return BridgeProfile(
        surface_object_name=_normalize_text(surface_object_name),
        anchor_object_name=_normalize_text(anchor_object_name),
        relation=_normalize_text(relation),
        bridge_intent=bridge_intent,
        good_question_angles=good_question_angles,
        avoid_angles=avoid_angles,
        steer_back_rule=steer_back_rule,
        focus_cues=focus_cues,
    ), debug
