"""Activity catalog loader, matcher, and selector."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CATALOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ActivityDefinition:
    # === Core presentation ===
    activity_id: str
    name: str = ""
    launch_prompt: str = ""
    description: str = ""

    # === Activity matching fields ===
    attributes: tuple[str, ...] = ()           # e.g. ("polka_dots", "spots")
    preview_prompt: str = ""                   # Short description for LLM selection

    # === Tag Block core tags ===
    observation_angle: str = ""           # color, shape, pattern, emotion, texture, origin...
    mechanic: str = ""                    # collect, compare, imagine, motion_voice...
    game_style: str = ""                  # time_traveler, quest_collector, voice_stage...

    # === Eligibility hard gates ===
    entity_binding: str = "agnostic"      # bound | parameterized | agnostic
    entity_class: tuple[str, ...] = ()
    entity_class_filter: tuple[str, ...] = ()
    tier_range_span: tuple[str, ...] = ()          # ("T0", "T1")
    tier_support: dict[str, bool] = field(default_factory=dict)

    # === Coherence signals ===
    bridge_prerequisites_primary: tuple[str, ...] = ()
    bridge_prerequisites_secondary: tuple[str, ...] = ()
    entity_role: str = "subject"          # subject | exemplar

    # === Progression ===
    topic_axis: str = ""                  # form | perspective | connection | change...
    difficulty_level: int = 1             # 1 | 2

    # === Extra bucket for non-core fields ===
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActivityDefinition":
        """Build from a Tag Block YAML dict (nested) or flat mock dict."""
        sig = data.get("activity_signature", {})
        tier = data.get("tier_range", {})
        match = data.get("matchability", {})
        prog = data.get("progression", {})
        bridge = sig.get("bridge_prerequisites", {}) or {}

        def _get(nested_path: str, flat_key: str, default: Any = "") -> Any:
            """Try nested path first, then flat key."""
            parts = nested_path.split(".")
            d: Any = data
            for p in parts[:-1]:
                d = d.get(p, {}) if isinstance(d, dict) else {}
            val = d.get(parts[-1]) if isinstance(d, dict) else None
            if val is not None:
                return val
            val = data.get(flat_key)
            return val if val is not None else default

        # Normalize tier_support
        raw_ts = match.get("tier_support") if match else data.get("tier_support", {})
        tier_support = _normalize_tier_support(raw_ts)

        # Build extra from fields not in core mapping
        core_keys = {
            "activity_id", "name", "launch_prompt", "description",
            "attributes", "preview_prompt",
            "observation_angle", "mechanic", "game_style",
            "entity_binding", "entity_class", "entity_class_filter",
            "tier_range", "tier_range_span", "tier_support",
            "bridge_prerequisites", "bridge_prerequisites_primary", "bridge_prerequisites_secondary",
            "entity_role", "topic_axis", "difficulty_level",
            "activity_signature", "matchability", "progression",
            "estimated_duration_minutes", "materials_needed", "target_attribute",
        }
        extra = {k: v for k, v in data.items() if k not in core_keys}

        return cls(
            activity_id=data["activity_id"],
            name=_get("activity_signature.preview_label", "name", ""),
            launch_prompt=_get("activity_signature.preview_prompt", "launch_prompt", ""),
            preview_prompt=_get("activity_signature.preview_prompt", "preview_prompt", ""),
            description=_get("activity_signature.intro", "description", ""),
            attributes=tuple(data.get("attributes", [])),
            observation_angle=_get("activity_signature.observation_angle", "observation_angle", ""),
            mechanic=_get("activity_signature.mechanic", "mechanic", ""),
            game_style=data.get("game_style", ""),
            entity_binding=data.get("entity_binding", "agnostic"),
            entity_class=tuple(data.get("entity_class", [])),
            entity_class_filter=tuple(_get("matchability.entity_class_filter", "entity_class_filter", [])),
            tier_range_span=tuple(_get("tier_range.span", "tier_range_span", [])),
            tier_support=tier_support,
            bridge_prerequisites_primary=tuple(_get("activity_signature.bridge_prerequisites.primary", "bridge_prerequisites_primary", [])),
            bridge_prerequisites_secondary=tuple(_get("activity_signature.bridge_prerequisites.secondary", "bridge_prerequisites_secondary", [])),
            entity_role=_get("activity_signature.entity_role", "entity_role", "subject"),
            topic_axis=_get("progression.topic_axis", "topic_axis", ""),
            difficulty_level=_get("progression.difficulty_level", "difficulty_level", 1) or 1,
            extra=extra,
        )


@dataclass
class ActivityProfile:
    """Maps interest score to preferred activity mechanics/styles."""
    preferred_mechanics: list[str]
    acceptable_mechanics: list[str]
    preferred_game_styles: list[str]
    acceptable_game_styles: list[str]
    preferred_difficulty_level: int


@dataclass
class SelectionResult:
    """Output of select_best_activity."""
    activity: ActivityDefinition | None
    selector_score: float
    decision: str                         # "matched" | "fallback" | "none"
    fallback_reason: str | None


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_catalog() -> tuple[ActivityDefinition, ...]:
    """Load all activity packages from subdirectories under catalog/."""
    results: list[ActivityDefinition] = []
    if not os.path.isdir(_CATALOG_DIR):
        return ()
    for entry in os.listdir(_CATALOG_DIR):
        entry_path = os.path.join(_CATALOG_DIR, entry)
        if not os.path.isdir(entry_path):
            continue
        tag_block_path = os.path.join(entry_path, "tag_block.yaml")
        if not os.path.exists(tag_block_path):
            continue
        with open(tag_block_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            continue
        try:
            results.append(ActivityDefinition.from_dict(data))
        except (KeyError, TypeError) as e:
            logger.warning("Skipping malformed activity YAML %s: %s", tag_block_path, e)
            continue
    return tuple(results)


# ---------------------------------------------------------------------------
# Sibling axis routing for progression
# ---------------------------------------------------------------------------

_SIBLING_AXES: dict[str, list[str]] = {
    "form": ["function", "connection"],
    "function": ["form", "causation"],
    "causation": ["function", "change"],
    "change": ["causation", "connection"],
    "connection": ["change", "form", "perspective"],
    "perspective": ["connection", "responsibility"],
    "responsibility": ["perspective"],
}


def _is_sibling_axis(axis_a: str, axis_b: str) -> bool:
    return axis_b in _SIBLING_AXES.get(axis_a, [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_tier_support(raw: dict[str, Any]) -> dict[str, bool]:
    """Normalize tier_support values to bool. Handles yes/no and true/false."""
    result: dict[str, bool] = {}
    for k, v in raw.items():
        if isinstance(v, bool):
            result[k] = v
        elif isinstance(v, str):
            result[k] = v.lower() in ("yes", "true", "1")
    return result


def _age_to_tier(age: int) -> str:
    """Map child age to tier string (T0, T1, T2)."""
    if age <= 4:
        return "T0"
    elif age <= 6:
        return "T1"
    return "T2"


# Maps domain-specific sub-attributes to generic equivalents
_SUB_ATTRIBUTE_TO_GENERIC: dict[str, str] = {
    "body_color": "color",
    "flower_color": "color",
    "clothing_color": "color",
    "skin_color": "color",
    "leaf_shape": "shape",
    "terrain_shape": "shape",
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


# Maps CARES attribute IDs to Tag Block observation angles
_ATTRIBUTE_TO_ANGLE: dict[str, str] = {
    "appearance.color": "color",
    "appearance.shape": "shape",
    "appearance.pattern": "pattern",
    "appearance.size": "size",
    "appearance.texture": "texture",
    "function.behavior": "behavior",
    "function.use": "function",
    "emotion.state": "emotion",
    "quantity.count": "quantity",
    "origin.source": "origin",
}

# Dimension-level fallback: if exact attribute not mapped, try dimension
_DIMENSION_TO_ANGLES: dict[str, list[str]] = {
    "appearance": ["color", "shape", "pattern", "size", "texture"],
    "function": ["behavior", "function", "use"],
    "emotion": ["emotion", "state"],
    "quantity": ["quantity", "count"],
    "origin": ["origin", "source"],
}


MIN_SCORE_FOR_HANDOFF = 60


# ---------------------------------------------------------------------------
# Legacy matcher (kept for paixueji_app.py pre-load calls)
# ---------------------------------------------------------------------------

def get_activity_for_attribute(attribute_id: str, age: int) -> ActivityDefinition | None:
    """Return the first activity matching *attribute_id* and the child's age tier.

    Uses observation_angle matching via _ATTRIBUTE_TO_ANGLE mapping.
    """
    tier = _age_to_tier(age)
    catalog = _load_catalog()
    target_angles = _attribute_to_angles(attribute_id)

    for activity in catalog:
        if activity.observation_angle in target_angles and tier in activity.tier_range_span:
            if activity.tier_support.get(tier, False):
                return activity

    # Fallback: generic attribute ID
    generic_id = _resolve_generic_attribute_id(attribute_id)
    if generic_id:
        target_angles = _attribute_to_angles(generic_id)
        for activity in catalog:
            if activity.observation_angle in target_angles and tier in activity.tier_range_span:
                if activity.tier_support.get(tier, False):
                    logger.info(
                        "[ACTIVITY_MATCH] fallback mapping %s → %s → activity=%s",
                        attribute_id, generic_id, activity.activity_id,
                    )
                    return activity

    return None


def list_activities_for_attribute(attribute_id: str) -> list[ActivityDefinition]:
    """Return all activities whose observation_angle matches *attribute_id*."""
    catalog = _load_catalog()
    target_angles = _attribute_to_angles(attribute_id)
    results = [a for a in catalog if a.observation_angle in target_angles]
    if results:
        return results
    generic_id = _resolve_generic_attribute_id(attribute_id)
    if generic_id:
        target_angles = _attribute_to_angles(generic_id)
        return [a for a in catalog if a.observation_angle in target_angles]
    return []


# ---------------------------------------------------------------------------
# Selection core: Layer 1 — Eligibility
# ---------------------------------------------------------------------------

def _is_eligible(
    activity: ActivityDefinition,
    child_tier: str,
    entity_info: dict | None = None,
    extracted_properties: dict | None = None,
) -> bool:
    """Check hard eligibility gates for an activity."""
    # Catalog active
    if not getattr(activity, "catalog_active", True):
        return False

    # Tier gate
    if child_tier not in activity.tier_range_span:
        return False
    if not activity.tier_support.get(child_tier, False):
        return False

    # Entity binding
    if activity.entity_binding == "bound":
        if activity.entity_class_filter:
            entity_classes = set(entity_info.get("entity_class", [])) if entity_info else set()
            filters = set(activity.entity_class_filter)
            if not (entity_classes & filters):
                return False
    elif activity.entity_binding == "parameterized":
        # V1 simplified: parameterized needs extracted properties to be useful
        if extracted_properties is not None and not extracted_properties:
            return False
    elif activity.entity_binding == "agnostic":
        pass

    # Safety (placeholder)
    return True


# ---------------------------------------------------------------------------
# Selection core: Layer 2 — Angle matching
# ---------------------------------------------------------------------------

def _attribute_to_angles(attribute_id: str) -> list[str]:
    """Map CARES attribute ID to Tag Block observation angle(s)."""
    angle = _ATTRIBUTE_TO_ANGLE.get(attribute_id)
    if angle:
        return [angle]
    # Try generic equivalent before dimension fallback
    generic_id = _resolve_generic_attribute_id(attribute_id)
    if generic_id:
        angle = _ATTRIBUTE_TO_ANGLE.get(generic_id)
        if angle:
            return [angle]
    dimension = attribute_id.split(".")[0] if "." in attribute_id else attribute_id
    return _DIMENSION_TO_ANGLES.get(dimension, [])


def get_angle_matched_candidates(
    eligible: list[ActivityDefinition],
    attribute_id: str,
    conversation_angles: list[str],
) -> tuple[list[ActivityDefinition], str | None]:
    """Return (matched_candidates, fallback_reason).

    Tries exact angle match → bridge prerequisite overlap → all eligible.
    """
    target_angles = _attribute_to_angles(attribute_id)

    # Exact observation_angle match
    exact = [a for a in eligible if a.observation_angle in target_angles]
    if exact:
        return exact, None

    # Bridge prerequisites overlap
    bridge_matched = []
    for a in eligible:
        overlap = set(a.bridge_prerequisites_primary) & set(target_angles)
        if overlap:
            bridge_matched.append(a)
    if bridge_matched:
        return bridge_matched, "bridge_match"

    # Fallback to all eligible
    return eligible, "no_angle_match_fallback"


# ---------------------------------------------------------------------------
# Selection core: Interest score → ActivityProfile
# ---------------------------------------------------------------------------

def _interest_to_profile(interest_score: float) -> ActivityProfile:
    """Map interest score (0-100) to preferred mechanics/styles/difficulty."""
    if interest_score >= 80:
        return ActivityProfile(
            preferred_mechanics=["collect", "compare", "test", "build"],
            acceptable_mechanics=["sort", "voice", "care"],
            preferred_game_styles=["field_experiment", "creation", "mystery_trail"],
            acceptable_game_styles=["voice_stage"],
            preferred_difficulty_level=3,
        )
    elif interest_score >= 60:
        return ActivityProfile(
            preferred_mechanics=["compare", "collect", "sort", "voice"],
            acceptable_mechanics=["observe", "narrate", "imagine"],
            preferred_game_styles=["field_experiment", "voice_stage"],
            acceptable_game_styles=["mystery_trail", "time_traveler", "quest_collector"],
            preferred_difficulty_level=2,
        )
    else:
        return ActivityProfile(
            preferred_mechanics=["observe", "voice"],
            acceptable_mechanics=["narrate", "imagine"],
            preferred_game_styles=["voice_stage", "field_experiment"],
            acceptable_game_styles=[],
            preferred_difficulty_level=1,
        )


# ---------------------------------------------------------------------------
# Selection core: Layer 3 — Scoring
# ---------------------------------------------------------------------------

def score_activity(
    activity: ActivityDefinition,
    interest_score: float,
    age: int,
    conversation_context: dict[str, Any],
    progression_state: dict[str, Any] | None = None,
) -> float:
    """Score a single activity (0-93 in V1)."""
    s = 0.0
    profile = _interest_to_profile(interest_score)

    # ── A. Interest-Profile Match (0-40) ──
    if activity.mechanic in profile.preferred_mechanics:
        s += 25
    elif activity.mechanic in profile.acceptable_mechanics:
        s += 12
    else:
        s += 5

    if activity.game_style in profile.preferred_game_styles:
        s += 15
    elif activity.game_style in profile.acceptable_game_styles:
        s += 7

    # Difficulty match (0-8)
    diff = abs(activity.difficulty_level - profile.preferred_difficulty_level)
    if diff == 0:
        s += 8
    elif diff == 1:
        s += 4

    # ── B. Conversation Coherence (0-30) ──
    dominant = conversation_context.get("dominant_angle", "")
    secondary = conversation_context.get("secondary_angles", [])
    angles = conversation_context.get("angles", [])

    if activity.observation_angle == dominant:
        s += 15
    elif activity.observation_angle in secondary:
        s += 7

    overlap = len(set(activity.bridge_prerequisites_primary) & set(angles))
    s += min(overlap * 5, 10)

    entity_depth = conversation_context.get("entity_depth", "")
    if (activity.entity_role == "subject" and entity_depth == "deep") or \
       (activity.entity_role == "exemplar" and entity_depth == "property_focused"):
        s += 5

    # ── C. Progression Fit (0-20) — V1 stub ──
    if progression_state:
        target_axis = progression_state.get("target_axis")
        target_rung = progression_state.get("target_rung")
        if target_axis and target_rung:
            if activity.topic_axis == target_axis and activity.difficulty_level == target_rung:
                s += 20
            elif activity.topic_axis == target_axis and abs(activity.difficulty_level - target_rung) <= 1:
                s += 15
            elif _is_sibling_axis(activity.topic_axis, target_axis):
                s += 8

    # ── D. Practical Fit (0-3) — V1: recency only ──
    recent = conversation_context.get("recent_activities", [])
    if activity.activity_id not in recent:
        s += 3

    return s


# ---------------------------------------------------------------------------
# Selection core: Entry point
# ---------------------------------------------------------------------------

def select_best_activity(
    attribute_id: str,
    interest_score: float,
    age: int,
    conversation_context: dict[str, Any],
    progression_state: dict[str, Any] | None = None,
) -> SelectionResult:
    """Three-layer selection: Eligibility → Angle Match → Score & Rank."""
    child_tier = _age_to_tier(age)
    catalog = _load_catalog()

    entity_info = conversation_context.get("entity_info")
    extracted_properties = conversation_context.get("extracted_properties")

    # Layer 1: Eligibility
    eligible = [
        a for a in catalog
        if _is_eligible(a, child_tier, entity_info, extracted_properties)
    ]

    if not eligible:
        return SelectionResult(
            activity=None,
            selector_score=0.0,
            decision="none",
            fallback_reason="no_eligible_activities",
        )

    # Layer 2: Angle matching
    conversation_angles = list(conversation_context.get("angles", []))
    matched, fallback_reason = get_angle_matched_candidates(
        eligible, attribute_id, conversation_angles
    )

    # Layer 3: Scoring
    scored = [
        (a, score_activity(a, interest_score, age, conversation_context, progression_state))
        for a in matched
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    best_activity, best_score = scored[0]

    if best_score >= MIN_SCORE_FOR_HANDOFF:
        return SelectionResult(
            activity=best_activity,
            selector_score=best_score,
            decision="matched",
            fallback_reason=fallback_reason,
        )

    return SelectionResult(
        activity=None,
        selector_score=best_score,
        decision="none",
        fallback_reason=fallback_reason or "score_below_threshold",
    )


# ---------------------------------------------------------------------------
# Public API: explorable angles from catalog
# ---------------------------------------------------------------------------

def get_explorable_angles(
    entity_info: dict | None,
    extracted_properties: dict | None,
    age: int,
) -> set[str]:
    """Return all observation angles + bridge prerequisites that are eligible for handoff."""
    child_tier = _age_to_tier(age)
    catalog = _load_catalog()
    eligible = [
        a for a in catalog
        if _is_eligible(a, child_tier, entity_info, extracted_properties)
    ]
    angles: set[str] = set()
    for a in eligible:
        if a.observation_angle:
            angles.add(a.observation_angle)
        angles.update(a.bridge_prerequisites_primary)
    return angles


# Public alias for downstream modules
attribute_to_angles = _attribute_to_angles
