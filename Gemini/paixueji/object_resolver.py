from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml
from bridge_context import SUPPORTED_RELATIONS, normalize_relation
from resolution_debug import build_resolution_debug
from paixueji_prompts import OBJECT_RESOLUTION_PROMPT, RELATION_REPAIR_PROMPT


@dataclass(frozen=True)
class ObjectResolutionResult:
    surface_object_name: str
    visible_object_name: str
    anchor_object_name: str | None
    anchor_status: str
    anchor_relation: str | None
    anchor_confidence_band: str | None
    anchor_confirmation_needed: bool
    learning_anchor_active: bool
    anchor_suppressed: bool = False
    resolution_debug: dict[str, Any] | None = None


def _normalize_object_name(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


@lru_cache(maxsize=1)
def _load_supported_object_lookup() -> dict[str, str]:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    mappings_dir = os.path.join(base_dir, "mappings_dev20_0318")
    lookup: dict[str, str] = {}

    for root, _dirs, files in os.walk(mappings_dir):
        for fname in files:
            if not fname.endswith(".yaml") or fname in {"_index.yaml", "_domain.yaml"}:
                continue
            path = os.path.join(root, fname)
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or []
            if not isinstance(data, list):
                continue
            for entity in data:
                if not isinstance(entity, dict):
                    continue
                canonical = _normalize_object_name(entity.get("entity_name"))
                if not canonical:
                    continue
                for field in ("entity_name", "entity_id", "entity_name_cn"):
                    candidate = _normalize_object_name(entity.get(field))
                    if candidate:
                        lookup[candidate] = canonical

    return lookup


def _exact_supported_match(name: str) -> str | None:
    return _load_supported_object_lookup().get(name)


def _tokenize(value: str) -> list[str]:
    return [token for token in _normalize_object_name(value).split() if token]


def _contains_token_sequence(tokens: list[str], phrase_tokens: list[str]) -> bool:
    if not tokens or not phrase_tokens or len(phrase_tokens) > len(tokens):
        return False
    window = len(phrase_tokens)
    for index in range(len(tokens) - window + 1):
        if tokens[index:index + window] == phrase_tokens:
            return True
    return False


@lru_cache(maxsize=1)
def _supported_anchor_names() -> tuple[str, ...]:
    return tuple(sorted(set(_load_supported_object_lookup().values())))


def _candidate_anchor_shortlist(name: str) -> list[str]:
    surface_tokens = _tokenize(name)
    if not surface_tokens:
        return []

    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for anchor in _supported_anchor_names():
        if anchor in seen:
            continue
        anchor_tokens = _tokenize(anchor)
        if not anchor_tokens:
            continue
        score = 0
        if _contains_token_sequence(surface_tokens, anchor_tokens):
            score = 3
        elif set(surface_tokens) & set(anchor_tokens):
            score = 2
        if score:
            scored.append((score, anchor))
            seen.add(anchor)

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [anchor for _score, anchor in scored[:5]]


def _extract_json_object(raw_text: str | None) -> tuple[dict[str, Any] | None, str | None, bool]:
    normalized = (raw_text or "").strip()
    if not normalized:
        return None, "empty", False

    try:
        payload = json.loads(normalized)
        return (payload if isinstance(payload, dict) else None), "plain_json", False
    except Exception:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", normalized, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        try:
            payload = json.loads(fenced_match.group(1))
            return (payload if isinstance(payload, dict) else None), "fenced_json", True
        except Exception:
            pass

    wrapped_match = re.search(r"(\{.*\})", normalized, re.DOTALL)
    if wrapped_match:
        try:
            payload = json.loads(wrapped_match.group(1))
            return (payload if isinstance(payload, dict) else None), "wrapped_json", True
        except Exception:
            pass

    return None, "invalid_json", False


def _invoke_model(prompt: str, client: Any, config: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str | None, bool]:
    if client is None or not hasattr(client, "models") or not hasattr(client.models, "generate_content"):
        return None, None, None, False

    try:
        response = client.models.generate_content(
            model=config.get("model_name", ""),
            contents=prompt,
            config={"temperature": 0},
        )
        raw_text = response.text or ""
        payload, payload_kind, recovery_applied = _extract_json_object(raw_text)
        return payload, raw_text, payload_kind, recovery_applied
    except Exception:
        try:
            raw_text = response.text or ""  # type: ignore[has-type]
        except Exception:
            raw_text = None
        _payload, payload_kind, recovery_applied = _extract_json_object(raw_text)
        return None, raw_text, payload_kind, recovery_applied


def _relation_repair(name: str, anchor_name: str, client: Any, config: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str | None, bool]:
    prompt = RELATION_REPAIR_PROMPT.format(
        input_term=name,
        forced_anchor=anchor_name,
        supported_relations=", ".join(SUPPORTED_RELATIONS),
    )
    return _invoke_model(prompt, client, config)


def _model_fallback(name: str, client: Any, config: dict[str, Any]) -> ObjectResolutionResult | None:
    candidate_anchors = _candidate_anchor_shortlist(name)
    prompt = OBJECT_RESOLUTION_PROMPT.format(
        input_term=name,
        supported_anchors=", ".join(_supported_anchor_names()),
        supported_relations=", ".join(SUPPORTED_RELATIONS),
        candidate_anchors=", ".join(candidate_anchors) or "none",
    )

    payload, raw_text, payload_kind, recovery_applied = _invoke_model(prompt, client, config)
    if payload is None:
        if len(candidate_anchors) == 1:
            forced_anchor = candidate_anchors[0]
            repair_payload, repair_raw, repair_kind, repair_recovered = _relation_repair(name, forced_anchor, client, config)
            if isinstance(repair_payload, dict):
                repair_confidence = _normalize_object_name(repair_payload.get("confidence_band")).replace(" ", "")
                repair_relation_raw = repair_payload.get("relation")
                repair_relation = normalize_relation(repair_relation_raw) if repair_relation_raw else None
                repair_relation_is_valid = _normalize_object_name(repair_relation_raw) in SUPPORTED_RELATIONS
                if repair_confidence == "high" and repair_relation_is_valid and repair_relation:
                    return ObjectResolutionResult(
                        surface_object_name=name,
                        visible_object_name=name,
                        anchor_object_name=forced_anchor,
                        anchor_status="anchored_high",
                        anchor_relation=repair_relation,
                        anchor_confidence_band="high",
                        anchor_confirmation_needed=False,
                        learning_anchor_active=False,
                        resolution_debug=build_resolution_debug(
                            surface_object_name=name,
                            decision_source="relation_repair",
                            decision_reason="primary_invalid_json_single_candidate",
                            candidate_anchors=candidate_anchors,
                            model_attempted=True,
                            raw_model_response=repair_raw,
                            raw_model_payload_kind=repair_kind,
                            json_recovery_applied=repair_recovered,
                            parsed_anchor_raw=forced_anchor,
                            parsed_relation_raw=repair_relation_raw,
                            parsed_confidence_raw=repair_payload.get("confidence_band"),
                            anchor_object_name=forced_anchor,
                            anchor_status="anchored_high",
                        ),
                    )

            return ObjectResolutionResult(
                surface_object_name=name,
                visible_object_name=name,
                anchor_object_name=forced_anchor,
                anchor_status="anchored_medium",
                anchor_relation="related_to",
                anchor_confidence_band="medium",
                anchor_confirmation_needed=True,
                learning_anchor_active=False,
                resolution_debug=build_resolution_debug(
                    surface_object_name=name,
                    decision_source="candidate_fallback",
                    decision_reason="invalid_json_single_candidate",
                    candidate_anchors=candidate_anchors,
                    model_attempted=True,
                    raw_model_response=raw_text,
                    raw_model_payload_kind=payload_kind,
                    json_recovery_applied=recovery_applied,
                    anchor_object_name=forced_anchor,
                    anchor_status="anchored_medium",
                ),
            )
        if raw_text is not None:
            return ObjectResolutionResult(
                surface_object_name=name,
                visible_object_name=name,
                anchor_object_name=None,
                anchor_status="unresolved",
                anchor_relation=None,
                anchor_confidence_band=None,
                anchor_confirmation_needed=False,
                learning_anchor_active=False,
                resolution_debug=build_resolution_debug(
                    surface_object_name=name,
                    decision_source="unresolved",
                    decision_reason="invalid_json_multiple_candidates" if len(candidate_anchors) > 1 else "invalid_json_no_candidate",
                    candidate_anchors=candidate_anchors,
                    model_attempted=True,
                    raw_model_response=raw_text,
                    raw_model_payload_kind=payload_kind,
                    json_recovery_applied=recovery_applied,
                    unresolved_surface_only_mode=True,
                ),
            )
        return None

    parsed_anchor_raw = payload.get("anchor_object_name")
    parsed_relation_raw = payload.get("relation")
    parsed_confidence_raw = payload.get("confidence_band")
    confidence_band = _normalize_object_name(parsed_confidence_raw).replace(" ", "") or "low"
    relation = normalize_relation(parsed_relation_raw) if parsed_relation_raw else None
    relation_is_valid = _normalize_object_name(parsed_relation_raw) in SUPPORTED_RELATIONS
    anchor_name = _exact_supported_match(_normalize_object_name(parsed_anchor_raw))

    if anchor_name and confidence_band == "high" and relation_is_valid and relation:
        return ObjectResolutionResult(
            surface_object_name=name,
            visible_object_name=name,
            anchor_object_name=anchor_name,
            anchor_status="anchored_high",
            anchor_relation=relation,
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
            resolution_debug=build_resolution_debug(
                surface_object_name=name,
                decision_source="model_inference",
                decision_reason="high_confidence_valid_anchor",
                candidate_anchors=candidate_anchors,
                model_attempted=True,
                raw_model_response=raw_text,
                raw_model_payload_kind=payload_kind,
                json_recovery_applied=recovery_applied,
                parsed_anchor_raw=parsed_anchor_raw,
                parsed_relation_raw=parsed_relation_raw,
                parsed_confidence_raw=parsed_confidence_raw,
                anchor_object_name=anchor_name,
                anchor_status="anchored_high",
            ),
        )

    if anchor_name and confidence_band == "medium" and relation_is_valid and relation:
        return ObjectResolutionResult(
            surface_object_name=name,
            visible_object_name=name,
            anchor_object_name=anchor_name,
            anchor_status="anchored_medium",
            anchor_relation=relation,
            anchor_confidence_band="medium",
            anchor_confirmation_needed=True,
            learning_anchor_active=False,
            resolution_debug=build_resolution_debug(
                surface_object_name=name,
                decision_source="model_inference",
                decision_reason="medium_confidence_valid_anchor",
                candidate_anchors=candidate_anchors,
                model_attempted=True,
                raw_model_response=raw_text,
                raw_model_payload_kind=payload_kind,
                json_recovery_applied=recovery_applied,
                parsed_anchor_raw=parsed_anchor_raw,
                parsed_relation_raw=parsed_relation_raw,
                parsed_confidence_raw=parsed_confidence_raw,
                anchor_object_name=anchor_name,
                anchor_status="anchored_medium",
            ),
        )

    if len(candidate_anchors) == 1:
        forced_anchor = candidate_anchors[0]
        repair_payload, repair_raw, repair_kind, repair_recovered = _relation_repair(name, forced_anchor, client, config)
        if isinstance(repair_payload, dict):
            repair_confidence = _normalize_object_name(repair_payload.get("confidence_band")).replace(" ", "")
            repair_relation_raw = repair_payload.get("relation")
            repair_relation = normalize_relation(repair_relation_raw) if repair_relation_raw else None
            repair_relation_is_valid = _normalize_object_name(repair_relation_raw) in SUPPORTED_RELATIONS
            if repair_confidence == "high" and repair_relation_is_valid and repair_relation:
                return ObjectResolutionResult(
                    surface_object_name=name,
                    visible_object_name=name,
                    anchor_object_name=forced_anchor,
                    anchor_status="anchored_high",
                    anchor_relation=repair_relation,
                    anchor_confidence_band="high",
                    anchor_confirmation_needed=False,
                    learning_anchor_active=False,
                    resolution_debug=build_resolution_debug(
                        surface_object_name=name,
                        decision_source="relation_repair",
                        decision_reason="primary_low_confidence_single_candidate",
                        candidate_anchors=candidate_anchors,
                        model_attempted=True,
                        raw_model_response=repair_raw,
                        raw_model_payload_kind=repair_kind,
                        json_recovery_applied=repair_recovered,
                        parsed_anchor_raw=forced_anchor,
                        parsed_relation_raw=repair_relation_raw,
                        parsed_confidence_raw=repair_payload.get("confidence_band"),
                        anchor_object_name=forced_anchor,
                        anchor_status="anchored_high",
                    ),
                )

        return ObjectResolutionResult(
            surface_object_name=name,
            visible_object_name=name,
            anchor_object_name=forced_anchor,
            anchor_status="anchored_medium",
            anchor_relation="related_to",
            anchor_confidence_band="medium",
            anchor_confirmation_needed=True,
            learning_anchor_active=False,
            resolution_debug=build_resolution_debug(
                surface_object_name=name,
                decision_source="candidate_fallback",
                decision_reason="relation_repair_failed",
                candidate_anchors=candidate_anchors,
                model_attempted=True,
                raw_model_response=raw_text,
                raw_model_payload_kind=payload_kind,
                json_recovery_applied=recovery_applied,
                parsed_anchor_raw=parsed_anchor_raw,
                parsed_relation_raw=parsed_relation_raw,
                parsed_confidence_raw=parsed_confidence_raw,
                anchor_object_name=forced_anchor,
                anchor_status="anchored_medium",
            ),
        )

    if len(candidate_anchors) > 1:
        return ObjectResolutionResult(
            surface_object_name=name,
            visible_object_name=name,
            anchor_object_name=None,
            anchor_status="unresolved",
            anchor_relation=None,
            anchor_confidence_band=None,
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
            resolution_debug=build_resolution_debug(
                surface_object_name=name,
                decision_source="unresolved",
                decision_reason="multiple_candidate_anchors",
                candidate_anchors=candidate_anchors,
                model_attempted=True,
                raw_model_response=raw_text,
                raw_model_payload_kind=payload_kind,
                json_recovery_applied=recovery_applied,
                parsed_anchor_raw=parsed_anchor_raw,
                parsed_relation_raw=parsed_relation_raw,
                parsed_confidence_raw=parsed_confidence_raw,
                unresolved_surface_only_mode=True,
            ),
        )

    return ObjectResolutionResult(
        surface_object_name=name,
        visible_object_name=name,
        anchor_object_name=None,
        anchor_status="unresolved",
        anchor_relation=None,
        anchor_confidence_band=None,
        anchor_confirmation_needed=False,
        learning_anchor_active=False,
        resolution_debug=build_resolution_debug(
            surface_object_name=name,
            decision_source="unresolved",
            decision_reason="model_low_confidence",
            candidate_anchors=candidate_anchors,
            model_attempted=True,
            raw_model_response=raw_text,
            raw_model_payload_kind=payload_kind,
            json_recovery_applied=recovery_applied,
            parsed_anchor_raw=parsed_anchor_raw,
            parsed_relation_raw=parsed_relation_raw,
            parsed_confidence_raw=parsed_confidence_raw,
            unresolved_surface_only_mode=True,
        ),
    )


def resolve_object_input(
    raw_object_name: str,
    age: int,
    client: Any,
    config: dict[str, Any],
) -> ObjectResolutionResult:
    del age  # Reserved for future age-aware resolution heuristics.

    surface = _normalize_object_name(raw_object_name)
    if not surface:
        surface = "object"

    exact = _exact_supported_match(surface)
    if exact:
        return ObjectResolutionResult(
            surface_object_name=surface,
            visible_object_name=exact,
            anchor_object_name=exact,
            anchor_status="exact_supported",
            anchor_relation="exact_match",
            anchor_confidence_band="exact",
            anchor_confirmation_needed=False,
            learning_anchor_active=True,
            resolution_debug=build_resolution_debug(
                surface_object_name=surface,
                decision_source="exact_supported",
                decision_reason="exact_match",
                candidate_anchors=[exact],
                model_attempted=False,
                anchor_object_name=exact,
                anchor_status="exact_supported",
            ),
        )

    fallback = _model_fallback(surface, client, config or {})
    if fallback:
        return fallback

    return ObjectResolutionResult(
        surface_object_name=surface,
        visible_object_name=surface,
        anchor_object_name=None,
        anchor_status="unresolved",
        anchor_relation=None,
        anchor_confidence_band=None,
        anchor_confirmation_needed=False,
        learning_anchor_active=False,
        resolution_debug=build_resolution_debug(
            surface_object_name=surface,
            decision_source="unresolved",
            decision_reason="no_model_client",
            candidate_anchors=_candidate_anchor_shortlist(surface),
            model_attempted=False,
            unresolved_surface_only_mode=True,
        ),
    )


def parse_anchor_confirmation(reply: str, surface_object_name: str, anchor_object_name: str | None) -> str:
    text = _normalize_object_name(reply)
    surface = _normalize_object_name(surface_object_name)
    anchor = _normalize_object_name(anchor_object_name)

    if not text:
        return "unclear"
    if surface and surface in text:
        return "reject"
    if any(token in text for token in ("no", "stay", "keep", "not")):
        return "reject"
    if anchor and anchor in text:
        return "accept"
    if any(token in text.split() for token in ("yes", "yeah", "yep", "ok", "okay", "sure")):
        return "accept"
    return "unclear"
