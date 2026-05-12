"""Activity catalog loader and matcher."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CATALOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog")


@dataclass(frozen=True)
class ActivityDefinition:
    activity_id: str
    name: str
    target_attribute: str
    tier_range: tuple[int, ...]
    launch_prompt: str
    description: str = ""
    estimated_duration_minutes: int = 5
    materials_needed: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActivityDefinition":
        return cls(
            activity_id=data["activity_id"],
            name=data["name"],
            target_attribute=data["target_attribute"],
            tier_range=tuple(data["tier_range"]),
            launch_prompt=data["launch_prompt"],
            description=data.get("description", ""),
            estimated_duration_minutes=data.get("estimated_duration_minutes", 5),
            materials_needed=tuple(data.get("materials_needed", [])),
        )


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[ActivityDefinition, ...]:
    activities = []
    if not os.path.isdir(_CATALOG_DIR):
        return ()
    for filename in os.listdir(_CATALOG_DIR):
        if not filename.endswith(".yaml"):
            continue
        filepath = os.path.join(_CATALOG_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            try:
                activities.append(ActivityDefinition.from_dict(data))
            except (KeyError, TypeError) as e:
                logger.warning("Skipping malformed activity YAML %s: %s", filename, e)
                continue
    return tuple(activities)


# Maps domain-specific sub-attributes to their generic equivalents so that
# activities defined for generic IDs (e.g. appearance.color) can be matched
# when the topic selector returns a domain-specific ID (e.g. appearance.body_color).
_SUB_ATTRIBUTE_TO_GENERIC: dict[str, str] = {
    # → color
    "body_color": "color",
    "flower_color": "color",
    "clothing_color": "color",
    "skin_color": "color",
    # → shape
    "leaf_shape": "shape",
    "terrain_shape": "shape",
    # → size
    "body_size": "size",
}


def _resolve_generic_attribute_id(attribute_id: str) -> str | None:
    """Resolve a domain-specific attribute_id to its generic equivalent."""
    if "." not in attribute_id:
        return None
    dimension, sub = attribute_id.split(".", 1)
    generic_sub = _SUB_ATTRIBUTE_TO_GENERIC.get(sub)
    if generic_sub:
        return f"{dimension}.{generic_sub}"
    return None


def _match_activity(catalog: tuple[ActivityDefinition, ...], attribute_id: str, tier: int) -> ActivityDefinition | None:
    """Return the first activity matching *attribute_id* and *tier*."""
    for activity in catalog:
        if activity.target_attribute == attribute_id and tier in activity.tier_range:
            return activity
    return None


def _age_to_tier(age: int) -> int:
    """Map child age to tier index (0, 1, 2)."""
    if age <= 4:
        return 0
    elif age <= 6:
        return 1
    else:
        return 2


def get_activity_for_attribute(attribute_id: str, age: int) -> ActivityDefinition | None:
    """Return the first activity matching *attribute_id* and the child's age tier.

    Falls back to a generic attribute ID if the domain-specific ID has no
    direct match but a generic equivalent exists.
    """
    tier = _age_to_tier(age)
    catalog = _load_catalog()
    activity = _match_activity(catalog, attribute_id, tier)
    if activity:
        return activity
    generic_id = _resolve_generic_attribute_id(attribute_id)
    if generic_id:
        activity = _match_activity(catalog, generic_id, tier)
        if activity:
            logger.info(
                "[ACTIVITY_MATCH] fallback mapping %s → %s → activity=%s",
                attribute_id, generic_id, activity.activity_id,
            )
            return activity
    return None


def list_activities_for_attribute(attribute_id: str) -> list[ActivityDefinition]:
    """Return all activities whose *target_attribute* equals *attribute_id*.

    Falls back to a generic attribute ID when no direct matches exist.
    """
    catalog = _load_catalog()
    results = [a for a in catalog if a.target_attribute == attribute_id]
    if results:
        return results
    generic_id = _resolve_generic_attribute_id(attribute_id)
    if generic_id:
        return [a for a in catalog if a.target_attribute == generic_id]
    return []
