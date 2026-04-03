from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml
from bridge_context import SUPPORTED_RELATIONS, normalize_relation
from paixueji_prompts import OBJECT_RESOLUTION_PROMPT


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


def _model_fallback(name: str, client: Any, config: dict[str, Any]) -> ObjectResolutionResult | None:
    if client is None or not hasattr(client, "models") or not hasattr(client.models, "generate_content"):
        return None

    supported = sorted(set(_load_supported_object_lookup().values()))
    prompt = OBJECT_RESOLUTION_PROMPT.format(
        input_term=name,
        supported_anchors=", ".join(supported),
        supported_relations=", ".join(SUPPORTED_RELATIONS),
    )

    try:
        response = client.models.generate_content(
            model=config.get("model_name", ""),
            contents=prompt,
            config={"temperature": 0},
        )
        payload = json.loads(response.text or "{}")
    except Exception:
        return None

    anchor_name = _exact_supported_match(_normalize_object_name(payload.get("anchor_object_name")))
    confidence_band = (payload.get("confidence_band") or "low").lower()
    raw_relation = payload.get("relation")
    normalized_raw_relation = " ".join((raw_relation or "").strip().lower().split())
    relation = normalize_relation(raw_relation) if raw_relation else None
    relation_is_valid = normalized_raw_relation in SUPPORTED_RELATIONS

    if not anchor_name or confidence_band == "low":
        return None

    if confidence_band == "high" and relation_is_valid and relation:
        return ObjectResolutionResult(
            surface_object_name=name,
            visible_object_name=name,
            anchor_object_name=anchor_name,
            anchor_status="anchored_high",
            anchor_relation=relation,
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        )

    if confidence_band in {"high", "medium"}:
        return ObjectResolutionResult(
            surface_object_name=name,
            visible_object_name=name,
            anchor_object_name=anchor_name,
            anchor_status="anchored_medium",
            anchor_relation=relation or "related_to",
            anchor_confidence_band="medium" if confidence_band == "medium" else "high",
            anchor_confirmation_needed=True,
            learning_anchor_active=False,
        )

    return None


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
