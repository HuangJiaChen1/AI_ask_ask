from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class BridgeContext:
    relation: str
    attempt_number: int
    surface_object_name: str
    anchor_object_name: str
    allowed_focus_terms: tuple[str, ...]
    forbidden_anchor_terms: tuple[str, ...]
    follow_terms: tuple[str, ...]
    prompt_context: str


@lru_cache(maxsize=1)
def _load_bridge_profiles() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_relation_profiles.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_bridge_context(
    surface_object_name: str,
    anchor_object_name: str,
    relation: str | None,
    attempt_number: int,
) -> BridgeContext | None:
    profile = (_load_bridge_profiles().get(relation or "") or None)
    if not profile:
        return None

    allowed_focus_terms = tuple(profile.get("allowed_focus_terms") or ())
    forbidden_anchor_terms = tuple(profile.get("forbidden_anchor_terms") or ())
    follow_terms = tuple(profile.get("follow_terms") or ())
    attempt_key = "attempt_2_guidance" if attempt_number >= 2 else "attempt_1_guidance"
    guidance = profile.get(attempt_key, "")
    attempt_label = "Second bridge attempt." if attempt_number >= 2 else "First bridge attempt."
    prompt_context = "\n".join(
        [
            attempt_label,
            f"Surface object: {surface_object_name}",
            f"Supported anchor: {anchor_object_name}",
            f"Allowed focus terms: {', '.join(allowed_focus_terms)}",
            f"Forbidden anchor terms: {', '.join(forbidden_anchor_terms)}",
            guidance,
        ]
    )

    return BridgeContext(
        relation=relation or "",
        attempt_number=attempt_number,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        allowed_focus_terms=allowed_focus_terms,
        forbidden_anchor_terms=forbidden_anchor_terms,
        follow_terms=follow_terms,
        prompt_context=prompt_context,
    )
