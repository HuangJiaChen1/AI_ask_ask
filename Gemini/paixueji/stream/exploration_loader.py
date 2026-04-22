"""
Exploration Categories Loader

Loads exploration_categories.yaml and provides tier-aware, domain-aware
sub-attribute candidate generation for the attribute pipeline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import yaml

_YAML_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "exploration_categories.yaml"
)

# The 14 known domains in the YAML (excluding "default").
ALL_DOMAINS = (
    "animals",
    "food",
    "vehicles",
    "plants",
    "people_roles",
    "buildings_places",
    "clothing_accessories",
    "daily_objects",
    "natural_phenomena",
    "arts_music",
    "signs_symbols",
    "nature_landscapes",
    "human_body",
    "imagination",
)

# Tier index mapping: YAML uses [0, 1, 2] lists.
_TIER_INDICES = {0, 1, 2}


@dataclass(frozen=True)
class SubAttributeCandidate:
    dimension: str       # "appearance", "senses", "structure", "function", "context", "change"
    sub_attribute: str   # "body_color", "covering", "taste", ...
    tier: int            # 0, 1, or 2


def _age_to_tier(age: int) -> int:
    """Map child age to tier index (0, 1, 2)."""
    if age <= 4:
        return 0
    elif age <= 6:
        return 1
    else:
        return 2


@lru_cache(maxsize=1)
def _load_yaml() -> dict:
    """Load and cache the exploration_categories.yaml file."""
    with open(_YAML_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_sub_attributes(
    dimension_data: dict,
    domain: str | None,
) -> list[str]:
    """
    Get the sub_attribute list for a dimension given a domain.
    Falls back to "default" if domain is None or not found.
    """
    sub_attrs_map = dimension_data.get("sub_attributes", {})
    if domain and domain in sub_attrs_map:
        return list(sub_attrs_map[domain])
    return list(sub_attrs_map.get("default", []))


def get_candidate_sub_attributes(
    domain: str | None,
    age: int,
) -> list[SubAttributeCandidate]:
    """
    Generate a flat list of sub-attribute candidates filtered by domain and age tier.

    Args:
        domain: One of the 14 known domains, or None to use "default" for all.
        age: Child's age (3-8).

    Returns:
        List of SubAttributeCandidate, one per (dimension, sub_attribute) pair
        that is valid for the given tier.
    """
    data = _load_yaml()
    tier = _age_to_tier(age)

    candidates = []
    for dim_name, dim_data in data.get("physical_dimensions", {}).items():
        # Check tier applicability: dim_data["tiers"] is e.g. [0, 1, 2]
        applicable_tiers = dim_data.get("tiers", [])
        if tier not in applicable_tiers:
            continue

        sub_attrs = _resolve_sub_attributes(dim_data, domain)
        for sa in sub_attrs:
            candidates.append(
                SubAttributeCandidate(
                    dimension=dim_name,
                    sub_attribute=sa,
                    tier=tier,
                )
            )

    return candidates


# Dimension-level activity target templates.
# {object} is replaced with the object name.
DIMENSION_ACTIVITY_TEMPLATES: dict[str, str] = {
    "appearance": "noticing and describing what {object} looks like",
    "senses": "exploring how {object} feels, sounds, or smells",
    "structure": "discovering the parts and materials of {object}",
    "function": "investigating what {object} does and how it is used",
    "context": "finding where and when you encounter {object}",
    "change": "observing how {object} changes over time",
}


def sub_attribute_to_label(sub_attribute: str) -> str:
    """Convert a snake_case sub_attribute name to a human-readable label."""
    return sub_attribute.replace("_", " ")


def dimension_to_activity_target(dimension: str, object_name: str) -> str:
    """
    Generate an activity_target string for a dimension + object.
    Falls back to a generic template if the dimension is unknown.
    """
    template = DIMENSION_ACTIVITY_TEMPLATES.get(
        dimension,
        "exploring {object}",
    )
    return template.format(object=object_name)


def _resolve_domain_from_mappings(object_name: str) -> str | None:
    """
    Try to find the domain for an object in the mappings DB.
    Returns the domain string (e.g. "animals") or None.
    """
    from stream.db_loader import _find_entity

    entity = _find_entity(object_name)
    if entity and isinstance(entity, dict):
        domain = entity.get("domain")
        if domain and domain in ALL_DOMAINS:
            return domain
    return None


async def infer_domain(
    surface_object_name: str,
    client,
    config: dict | None,
) -> str | None:
    """
    Determine the domain of a surface object.

    Strategy:
      1. Look up in mappings DB → use entity's domain if found.
      2. Ask Gemini to classify → validate against ALL_DOMAINS.
      3. Return None if both fail (caller will use default sub_attributes).

    Args:
        surface_object_name: The object the child named.
        client: Gemini client (with aio.models.generate_content).
        config: Config dict with model_name.

    Returns:
        Domain string from ALL_DOMAINS, or None.
    """
    # 1. Try mappings first (no LLM call needed)
    mapped = _resolve_domain_from_mappings(surface_object_name)
    if mapped:
        return mapped

    # 2. Ask Gemini
    try:
        import paixueji_prompts
        from model_json import extract_json_object

        prompt = paixueji_prompts.get_prompts()["domain_classification_prompt"].format(
            object_name=surface_object_name,
            supported_domains=", ".join(ALL_DOMAINS),
        )
        response = await client.aio.models.generate_content(
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 60},
        )
        payload, _kind, _recovered = extract_json_object(response.text or "")
        if isinstance(payload, dict):
            domain = payload.get("domain")
            if domain and domain in ALL_DOMAINS:
                return domain
    except Exception:
        pass

    # 3. No match
    return None
