"""
DB Loader for mappings_dev20_0318/ dimension data.

Loads age-tiered dimension maps for physical and engagement dimensions
from the YAML entity files. Used at session start to build coverage hints
for the follow-up question generator.

Functions:
    load_physical_dimensions  — {dim: {attr: value}} for PHYSICAL_DIMS
    load_engagement_dimensions — {dim: [topic_str, ...]} for ENGAGEMENT_DIMS
"""
import os
from functools import lru_cache

import yaml

NEW_MAPPINGS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "mappings_dev20_0318"
)

PHYSICAL_DIMS = {"appearance", "senses", "function", "structure", "context", "change"}
ENGAGEMENT_DIMS = {"emotions", "relationship", "reasoning", "imagination", "narrative"}

_SKIP_FILES = {"_domain.yaml", "_index.yaml"}
_SKIP_EXTS = {".json"}


def _age_to_new_tier(age: int) -> str:
    """Map child age to YAML tier key."""
    if age <= 4:
        return "tier_0"
    elif age <= 6:
        return "tier_1"
    else:
        return "tier_2"


@lru_cache(maxsize=1)
def _load_all_entities(base_dir: str) -> tuple:
    """
    Walk base_dir recursively, parse all entity YAML files, and return a
    tuple of entity dicts.  The result is cached so subsequent calls with
    the same base_dir never re-read the filesystem.
    """
    entities = []
    for root, _dirs, files in os.walk(base_dir):
        for fname in files:
            if fname in _SKIP_FILES:
                continue
            if os.path.splitext(fname)[1] in _SKIP_EXTS:
                continue
            if not fname.endswith(".yaml"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, list):
                    entities.extend(data)
            except Exception:
                pass
    return tuple(entities)


def _find_entity(object_name: str) -> dict | None:
    """
    Return the first entity dict whose entity_name, entity_id, or
    entity_name_cn matches object_name (case-insensitive, stripped).
    Returns None if not found.
    """
    name_lower = object_name.strip().lower()
    for entity in _load_all_entities(NEW_MAPPINGS_DIR):
        if not isinstance(entity, dict):
            continue
        for field in ("entity_name", "entity_id", "entity_name_cn"):
            val = entity.get(field)
            if val and str(val).strip().lower() == name_lower:
                return entity
    return None


def load_physical_dimensions(object_name: str, age: int) -> dict[str, dict[str, str]]:
    """
    Load physical dimension attribute-value pairs for the entity at the
    age-appropriate tier.

    Args:
        object_name: Name to look up (matched case-insensitively).
        age: Child's age (3-8).

    Returns:
        {dim_name: {attribute: value, ...}} for each physical dimension that
        has at least one attribute-value pair at the given tier.
        Returns {} if the entity is not found in the DB.
    """
    entity = _find_entity(object_name)
    if not entity:
        return {}

    tier_key = _age_to_new_tier(age)
    tier_data = (entity.get("tier_guidance") or {}).get(tier_key) or {}
    dimensions = tier_data.get("dimensions") or {}

    result = {}
    for dim_name in PHYSICAL_DIMS:
        items = dimensions.get(dim_name)
        if not items or not isinstance(items, list):
            continue
        attrs = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            attr = item.get("attribute")
            value = item.get("value")
            if attr and value:
                attrs[str(attr)] = str(value)
        if attrs:
            result[dim_name] = attrs

    return result


def load_engagement_dimensions(object_name: str, age: int) -> dict[str, list[str]]:
    """
    Load engagement dimension topic examples for the entity at the
    age-appropriate tier.

    Engagement dimensions store topics as plain strings directly in the list
    (unlike physical dims which use attribute/value dicts).

    Args:
        object_name: Name to look up (matched case-insensitively).
        age: Child's age (3-8).

    Returns:
        {dim_name: [topic_str, ...]} (capped at 3 examples per dimension).
        Returns {} if the entity is not found in the DB.
    """
    entity = _find_entity(object_name)
    if not entity:
        return {}

    tier_key = _age_to_new_tier(age)
    tier_data = (entity.get("tier_guidance") or {}).get(tier_key) or {}
    dimensions = tier_data.get("dimensions") or {}

    result = {}
    for dim_name in ENGAGEMENT_DIMS:
        items = dimensions.get(dim_name)
        if not items or not isinstance(items, list):
            continue
        topics = [str(item) for item in items if isinstance(item, str)][:3]
        if topics:
            result[dim_name] = topics

    return result
