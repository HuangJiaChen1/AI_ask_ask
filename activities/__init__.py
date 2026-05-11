"""Activity catalog loader and matcher."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

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
            activities.append(ActivityDefinition.from_dict(data))
    return tuple(activities)


def get_activity_for_attribute(attribute_id: str, age: int) -> ActivityDefinition | None:
    from stream.exploration_loader import _age_to_tier

    tier = _age_to_tier(age)
    catalog = _load_catalog()
    for activity in catalog:
        if activity.target_attribute == attribute_id and tier in activity.tier_range:
            return activity
    return None


def list_activities_for_attribute(attribute_id: str) -> list[ActivityDefinition]:
    catalog = _load_catalog()
    return [a for a in catalog if a.target_attribute == attribute_id]
