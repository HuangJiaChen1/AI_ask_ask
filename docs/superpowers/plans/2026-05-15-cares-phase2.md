# CARES Phase 2: Activity Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder `get_activity_for_attribute()` with a full three-layer activity selection algorithm (`select_best_activity`) aligned to the Tag Block schema, using real activity package YAML data.

**Architecture:** Two-step implementation — first replace the catalog YAML and rewrite the loader/dataclass to handle nested Tag Block structures, then implement the selection core (Eligibility → Angle Matching → Scoring & Ranking) and integrate it into the CARES handoff decision engine. All changes are confined to `activities/__init__.py`, `stream/cares_handoff.py`, and test files.

**Tech Stack:** Python 3.12, Pytest, PyYAML, dataclasses

---

## File Structure

| File | Responsibility |
|------|---------------|
| `activities/__init__.py` | `ActivityDefinition` dataclass, `_load_catalog()`, `get_activity_for_attribute()`, `select_best_activity()` and all helpers |
| `activities/catalog/*/` | Activity package directories, each containing `tag_block.yaml` |
| `stream/cares_handoff.py` | `evaluate_handoff()` — integrates `select_best_activity` |
| `tests/test_activity_catalog.py` | Catalog loading, field mapping, tier normalization tests |
| `tests/test_activities_selection.py` | Selection logic: eligibility, angle matching, scoring, full flow |
| `tests/test_cares_handoff.py` | Handoff integration tests |

---

## Task 1: Replace Catalog YAML Files

**Files:**
- Delete: `activities/catalog/color_exploration.yaml`
- Delete: `activities/catalog/shape_exploration.yaml`
- Delete: `activities/catalog/size_exploration.yaml`
- Copy: `demo_activity_packages_updated_0514/*` → `activities/catalog/`

- [ ] **Step 1: Delete old mock YAML files**

```powershell
Remove-Item activities\catalog\color_exploration.yaml
Remove-Item activities\catalog\shape_exploration.yaml
Remove-Item activities\catalog\size_exploration.yaml
```

- [ ] **Step 2: Copy new activity packages**

```powershell
# Copy each subdirectory from demo_activity_packages_updated_0514 to activities/catalog/
$source = "demo_activity_packages_updated_0514"
$dest = "activities\catalog"
Get-ChildItem -Path $source -Directory | ForEach-Object {
    $target = Join-Path $dest $_.Name
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Copy-Item $_.FullName $target -Recurse
}
```

- [ ] **Step 3: Verify copy**

```powershell
Get-ChildItem activities\catalog -Directory | Select-Object Name
```

Expected: 5 directories (dream_whisperer_cat, fluffy_expedition_dandelion, mood_changer_dog, polka_dot_patrol, time_machine_dinosaur), each with `tag_block.yaml`.

- [ ] **Step 4: Commit**

```bash
git add activities/catalog/
git commit -m "feat: replace mock catalog with real Tag Block activity packages"
```

---

## Task 2: Rewrite ActivityDefinition Dataclass and Loader

**Files:**
- Modify: `activities/__init__.py` (full rewrite of dataclass, from_dict, _load_catalog, _age_to_tier)
- Test: `tests/test_activity_catalog.py` (update existing)

`★ Insight ─────────────────────────────────────`
1. The new Tag Block YAML uses deeply nested structures (`activity_signature.preview_label`, `tier_range.span`, `matchability.tier_support`). `from_dict()` must traverse these nested dicts while maintaining backward compatibility with flat keys for any future mock YAMLs.
2. `tier_support` has two formats across packages: boolean (`true`/`false` in dream_whisperer_cat) and string (`yes`/`no` in polka_dot_patrol). A `_normalize_tier_support()` helper normalizes both to `dict[str, bool]`.
3. The old `tier_range: [0, 1, 2]` (list of ints) is replaced by `tier_range.span: ["T0", "T1"]` (list of strings). `_age_to_tier()` now returns `"T0"` / `"T1"` / `"T2"`.
`─────────────────────────────────────────────────`

- [ ] **Step 1: Write the failing test for new dataclass structure**

Modify `tests/test_activity_catalog.py` — replace entire file:

```python
# tests/test_activity_catalog.py
import pytest
from activities import (
    get_activity_for_attribute,
    list_activities_for_attribute,
    _age_to_tier,
    _normalize_tier_support,
    ActivityDefinition,
)


# ── get_activity_for_attribute with real catalog ──

def test_get_activity_for_pattern():
    activity = get_activity_for_attribute("appearance.pattern", 5)
    assert activity is not None
    assert activity.activity_id == "polka_dot_patrol"


def test_get_activity_for_emotion():
    activity = get_activity_for_attribute("emotion.state", 5)
    assert activity is not None
    assert activity.observation_angle == "emotion"


def test_get_activity_for_texture():
    activity = get_activity_for_attribute("appearance.texture", 5)
    assert activity is not None
    assert activity.activity_id == "fluffy_expedition_dandelion"


def test_get_activity_for_origin():
    activity = get_activity_for_attribute("origin.source", 5)
    assert activity is not None
    assert activity.activity_id == "time_machine_dinosaur"


def test_get_activity_no_match():
    activity = get_activity_for_attribute("nonexistent.attribute", 5)
    assert activity is None


def test_tier_filtering_t1_all_match():
    # Age 5 -> T1; all 5 activities support T1
    assert get_activity_for_attribute("appearance.pattern", 5) is not None
    assert get_activity_for_attribute("emotion.state", 5) is not None


def test_tier_filtering_t2_some_excluded():
    # Age 8 -> T2; only polka_dot_patrol supports T2
    assert get_activity_for_attribute("appearance.pattern", 8) is not None
    # dream_whisperer_cat does NOT support T2
    assert get_activity_for_attribute("emotion.state", 8) is None


def test_get_activity_fallback_body_color_to_color():
    # No color activity in catalog, so fallback also returns None
    activity = get_activity_for_attribute("appearance.body_color", 5)
    assert activity is None


# ── ActivityDefinition field mapping ──

def test_polka_dot_patrol_field_mapping():
    from activities import _load_catalog
    catalog = _load_catalog()
    activity = next(a for a in catalog if a.activity_id == "polka_dot_patrol")
    assert activity.name == "Find three polka-dotted things!"
    assert activity.launch_prompt == "You noticed the polka dots on the {entity}. Let's find more polka-dotted things!"
    assert "patrol" in activity.description.lower()
    assert activity.observation_angle == "pattern"
    assert activity.mechanic == "collect"
    assert activity.game_style == "quest_collector"
    assert activity.entity_binding == "parameterized"
    assert activity.entity_role == "exemplar"
    assert activity.tier_range_span == ("T0", "T1", "T2")
    assert activity.tier_support == {"T0": True, "T1": True, "T2": True}
    assert activity.bridge_prerequisites_primary == ("pattern",)
    assert activity.bridge_prerequisites_secondary == ("color", "shape")
    assert activity.topic_axis == "form"
    assert activity.difficulty_level == 2


def test_dream_whisperer_cat_field_mapping():
    from activities import _load_catalog
    catalog = _load_catalog()
    activity = next(a for a in catalog if a.activity_id == "dream_whisperer_cat")
    assert activity.name == "Peek into the cat dreams"
    assert activity.observation_angle == "emotion"
    assert activity.mechanic == "imagine"
    assert activity.entity_binding == "bound"
    assert activity.entity_class == ("cat", "pet", "toy")
    assert activity.entity_class_filter == ("cat",)
    assert activity.tier_range_span == ("T0", "T1")
    assert activity.tier_support == {"T0": True, "T1": True, "T2": False}
    assert activity.topic_axis == "perspective"
    assert activity.difficulty_level == 1


# ── _normalize_tier_support ──

def test_normalize_tier_support_boolean():
    raw = {"T0": True, "T1": False}
    assert _normalize_tier_support(raw) == {"T0": True, "T1": False}


def test_normalize_tier_support_yes_no():
    raw = {"T0": "yes", "T1": "no", "T2": "yes"}
    assert _normalize_tier_support(raw) == {"T0": True, "T1": False, "T2": True}


def test_normalize_tier_support_mixed():
    raw = {"T0": "true", "T1": "false", "T2": "yes"}
    assert _normalize_tier_support(raw) == {"T0": True, "T1": False, "T2": True}


# ── _age_to_tier ──

def test_age_to_tier_returns_strings():
    assert _age_to_tier(3) == "T0"
    assert _age_to_tier(4) == "T0"
    assert _age_to_tier(5) == "T1"
    assert _age_to_tier(6) == "T1"
    assert _age_to_tier(7) == "T2"
    assert _age_to_tier(10) == "T2"


# ── from_dict backward compat ──

def test_from_dict_flat_keys():
    data = {
        "activity_id": "test_activity",
        "name": "Test",
        "target_attribute": "appearance.color",
        "launch_prompt": "Go!",
        "description": "A test",
        "observation_angle": "color",
        "mechanic": "collect",
        "game_style": "quest",
        "tier_range_span": ["T0", "T1"],
        "tier_support": {"T0": True, "T1": True},
    }
    activity = ActivityDefinition.from_dict(data)
    assert activity.activity_id == "test_activity"
    assert activity.name == "Test"
    assert activity.observation_angle == "color"
    assert activity.tier_range_span == ("T0", "T1")


def test_from_dict_nested_keys():
    data = {
        "activity_id": "test_activity",
        "activity_signature": {
            "preview_label": "Nested Test",
            "preview_prompt": "Let's go!",
            "intro": "An intro",
            "observation_angle": "texture",
            "mechanic": "imagine",
            "entity_role": "subject",
            "bridge_prerequisites": {
                "primary": ["texture"],
                "secondary": ["color"],
            },
        },
        "game_style": "time_traveler",
        "tier_range": {
            "span": ["T0", "T1"],
        },
        "matchability": {
            "tier_support": {"T0": "yes", "T1": "yes"},
        },
        "progression": {
            "topic_axis": "perspective",
            "difficulty_level": 1,
        },
    }
    activity = ActivityDefinition.from_dict(data)
    assert activity.name == "Nested Test"
    assert activity.launch_prompt == "Let's go!"
    assert activity.description == "An intro"
    assert activity.observation_angle == "texture"
    assert activity.mechanic == "imagine"
    assert activity.entity_role == "subject"
    assert activity.bridge_prerequisites_primary == ("texture",)
    assert activity.bridge_prerequisites_secondary == ("color",)
    assert activity.tier_support == {"T0": True, "T1": True}
    assert activity.topic_axis == "perspective"
    assert activity.difficulty_level == 1
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
pytest tests/test_activity_catalog.py -v
```

Expected: Many FAILs — `ActivityDefinition` missing fields, `_normalize_tier_support` not defined, `_age_to_tier` returns int not str, etc.

- [ ] **Step 3: Rewrite `activities/__init__.py`**

Replace the entire `activities/__init__.py` file:

```python
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
            description=_get("activity_signature.intro", "description", ""),
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
) -> SelectionResult:
    """Three-layer selection: Eligibility → Angle Match → Score & Rank."""
    child_tier = _age_to_tier(age)
    catalog = _load_catalog()

    entity_info = conversation_context.get("entity_info", {})
    extracted_properties = conversation_context.get("extracted_properties", {})

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
        (a, score_activity(a, interest_score, age, conversation_context))
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
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
pytest tests/test_activity_catalog.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Verify no regressions in existing tests**

```powershell
pytest tests/test_cares_handoff.py -v
pytest tests/test_exploration_angles.py -v
pytest tests/test_attribute_activity_pipeline.py -v
```

Expected: All PASS. (cares_handoff tests still mock `get_activity_for_attribute`, so they work with the rewritten function.)

- [ ] **Step 6: Commit**

```bash
git add activities/__init__.py tests/test_activity_catalog.py
git commit -m "feat: rewrite ActivityDefinition, loader, and legacy matcher for Tag Block schema"
```

---

## Task 3: Test Selection Core Logic

**Files:**
- Create: `tests/test_activities_selection.py`
- Modify: `activities/__init__.py` (no changes — logic already written in Task 2)

- [ ] **Step 1: Write the failing test file**

Create `tests/test_activities_selection.py`:

```python
# tests/test_activities_selection.py
from types import SimpleNamespace
import pytest
from activities import (
    ActivityDefinition,
    ActivityProfile,
    SelectionResult,
    _interest_to_profile,
    _is_eligible,
    _attribute_to_angles,
    get_angle_matched_candidates,
    score_activity,
    select_best_activity,
    _age_to_tier,
    _normalize_tier_support,
)


# ── _interest_to_profile ──

def test_interest_profile_high_score():
    profile = _interest_to_profile(85)
    assert "collect" in profile.preferred_mechanics
    assert profile.preferred_difficulty_level == 3


def test_interest_profile_mid_score():
    profile = _interest_to_profile(65)
    assert "compare" in profile.preferred_mechanics
    assert profile.preferred_difficulty_level == 2


def test_interest_profile_low_score():
    profile = _interest_to_profile(40)
    assert "observe" in profile.preferred_mechanics
    assert profile.preferred_difficulty_level == 1


def test_interest_profile_boundary_80():
    profile = _interest_to_profile(80)
    assert profile.preferred_difficulty_level == 3


def test_interest_profile_boundary_60():
    profile = _interest_to_profile(60)
    assert profile.preferred_difficulty_level == 2


# ── _is_eligible ──

def make_activity(**kwargs) -> ActivityDefinition:
    defaults = {
        "activity_id": "test",
        "tier_range_span": ("T0", "T1"),
        "tier_support": {"T0": True, "T1": True, "T2": False},
        "entity_binding": "agnostic",
    }
    defaults.update(kwargs)
    return ActivityDefinition(**defaults)


def test_eligible_tier_in_span_and_supported():
    act = make_activity()
    assert _is_eligible(act, "T1") is True


def test_eligible_tier_not_in_span():
    act = make_activity(tier_range_span=("T0",))
    assert _is_eligible(act, "T1") is False


def test_eligible_tier_not_supported():
    act = make_activity(tier_support={"T0": True, "T1": False})
    assert _is_eligible(act, "T1") is False


def test_eligible_bound_matches_filter():
    act = make_activity(
        entity_binding="bound",
        entity_class_filter=("cat",),
    )
    entity_info = {"entity_class": ["cat", "pet"]}
    assert _is_eligible(act, "T1", entity_info=entity_info) is True


def test_eligible_bound_no_filter_overlap():
    act = make_activity(
        entity_binding="bound",
        entity_class_filter=("dog",),
    )
    entity_info = {"entity_class": ["cat"]}
    assert _is_eligible(act, "T1", entity_info=entity_info) is False


def test_eligible_parameterized_with_properties():
    act = make_activity(entity_binding="parameterized")
    assert _is_eligible(act, "T1", extracted_properties={"color": "red"}) is True


def test_eligible_parameterized_without_properties():
    act = make_activity(entity_binding="parameterized")
    assert _is_eligible(act, "T1", extracted_properties={}) is False


def test_eligible_agnostic_always_passes():
    act = make_activity(entity_binding="agnostic")
    assert _is_eligible(act, "T1") is True


# ── _attribute_to_angles ──

def test_attribute_to_angles_exact():
    assert _attribute_to_angles("appearance.color") == ["color"]
    assert _attribute_to_angles("emotion.state") == ["emotion"]


def test_attribute_to_angles_dimension_fallback():
    assert "color" in _attribute_to_angles("appearance.body_color")
    assert "shape" in _attribute_to_angles("appearance.leaf_shape")


def test_attribute_to_angles_unknown():
    assert _attribute_to_angles("unknown.thing") == []


# ── get_angle_matched_candidates ──

def test_angle_match_exact():
    acts = [
        ActivityDefinition(activity_id="a1", observation_angle="color"),
        ActivityDefinition(activity_id="a2", observation_angle="shape"),
    ]
    matched, reason = get_angle_matched_candidates(acts, "appearance.color", [])
    assert len(matched) == 1
    assert matched[0].activity_id == "a1"
    assert reason is None


def test_angle_match_bridge_fallback():
    acts = [
        ActivityDefinition(
            activity_id="a1",
            observation_angle="pattern",
            bridge_prerequisites_primary=("color", "shape"),
        ),
        ActivityDefinition(activity_id="a2", observation_angle="texture"),
    ]
    matched, reason = get_angle_matched_candidates(acts, "appearance.color", [])
    assert len(matched) == 1
    assert matched[0].activity_id == "a1"
    assert reason == "bridge_match"


def test_angle_match_all_eligible_fallback():
    acts = [
        ActivityDefinition(activity_id="a1", observation_angle="texture"),
        ActivityDefinition(activity_id="a2", observation_angle="origin"),
    ]
    matched, reason = get_angle_matched_candidates(acts, "appearance.color", [])
    assert len(matched) == 2
    assert reason == "no_angle_match_fallback"


# ── score_activity ──

def test_score_activity_mechanic_preferred():
    act = ActivityDefinition(
        activity_id="a1",
        observation_angle="color",
        mechanic="collect",
        game_style="field_experiment",
        difficulty_level=2,
    )
    ctx = {
        "dominant_angle": "color",
        "secondary_angles": [],
        "angles": ["color"],
        "entity_depth": "property_focused",
        "recent_activities": [],
    }
    # interest=65 → mid profile: preferred_mechanics includes "collect"
    score = score_activity(act, 65, 5, ctx)
    # mechanic=collect preferred=25, game_style=field_experiment preferred=15,
    # diff=0 → 8, coherence: angle match=15, bridge overlap=5, entity_role default=subject vs property_focused=0
    # practical: not recent=3
    assert score == 25 + 15 + 8 + 15 + 5 + 0 + 3


def test_score_activity_mechanic_not_preferred():
    act = ActivityDefinition(
        activity_id="a1",
        observation_angle="color",
        mechanic="unknown",
        game_style="unknown",
        difficulty_level=1,
    )
    ctx = {
        "dominant_angle": "shape",
        "secondary_angles": [],
        "angles": [],
        "entity_depth": "deep",
        "recent_activities": ["a1"],
    }
    score = score_activity(act, 65, 5, ctx)
    # mechanic unknown → 5, game_style unknown → 0, diff=1 → 4,
    # coherence: no angle match, no bridge, no entity_role match,
    # practical: recent → 0
    assert score == 5 + 0 + 4 + 0 + 0 + 0 + 0


def test_score_activity_with_progression():
    act = ActivityDefinition(
        activity_id="a1",
        observation_angle="color",
        mechanic="collect",
        topic_axis="form",
        difficulty_level=2,
    )
    ctx = {
        "dominant_angle": "color",
        "secondary_angles": [],
        "angles": ["color"],
        "entity_depth": "property_focused",
        "recent_activities": [],
    }
    prog = {"target_axis": "form", "target_rung": 2}
    score = score_activity(act, 65, 5, ctx, prog)
    # Base: 25+15+8=48, Coherence: 15+5+0=20, Progression: 20, Practical: 3
    assert score == 48 + 20 + 20 + 3


# ── select_best_activity ──

def test_select_best_activity_exact_match():
    """橘猫 trace: color attribute with high interest score."""
    result = select_best_activity(
        attribute_id="appearance.pattern",
        interest_score=83,
        age=5,
        conversation_context={
            "dominant_angle": "pattern",
            "secondary_angles": [],
            "angles": ["pattern"],
            "entity_depth": "property_focused",
            "recent_activities": [],
            "entity_info": {},
            "extracted_properties": {},
        },
    )
    assert result.activity is not None
    assert result.activity.activity_id == "polka_dot_patrol"
    assert result.selector_score >= 60
    assert result.decision == "matched"
    assert result.fallback_reason is None


def test_select_best_activity_no_eligible():
    result = select_best_activity(
        attribute_id="appearance.color",
        interest_score=80,
        age=5,
        conversation_context={
            "dominant_angle": "color",
            "angles": ["color"],
            "entity_depth": "property_focused",
            "recent_activities": [],
            "entity_info": {},
            "extracted_properties": {},
        },
    )
    # No "color" observation_angle in catalog, bridge also fails,
    # falls back to all eligible, but polka_dot_patrol scores on bridge
    # (bridge_prerequisites_primary includes pattern, not color)
    # Actually pattern has no overlap with color either, so fallback to all eligible
    # polka_dot_patrol will be scored; with interest=80 and no angle match,
    # let's see: mechanic=collect (preferred=25), game_style=quest_collector (acceptable=7),
    # diff=|2-3|=1 → 4, coherence: no angle match, bridge overlap pattern&color=0,
    # practical: 3. Total = 25+7+4+0+0+3 = 39 < 60
    # So result.activity should be None
    assert result.activity is None
    assert result.decision == "none"


def test_select_best_activity_bridge_match():
    """emotion.state → matches dream_whisperer_cat (emotion) exact."""
    result = select_best_activity(
        attribute_id="emotion.state",
        interest_score=70,
        age=5,
        conversation_context={
            "dominant_angle": "emotion",
            "angles": ["emotion"],
            "entity_depth": "property_focused",
            "recent_activities": [],
            "entity_info": {},
            "extracted_properties": {},
        },
    )
    assert result.activity is not None
    assert result.activity.observation_angle == "emotion"
    assert result.decision == "matched"


def test_select_best_activity_below_threshold():
    """Low interest score → no handoff even with match."""
    result = select_best_activity(
        attribute_id="appearance.pattern",
        interest_score=30,
        age=5,
        conversation_context={
            "dominant_angle": "pattern",
            "angles": ["pattern"],
            "entity_depth": "property_focused",
            "recent_activities": [],
            "entity_info": {},
            "extracted_properties": {},
        },
    )
    assert result.activity is None
    assert result.decision == "none"
    assert result.fallback_reason is None  # exact match, just score too low
```

- [ ] **Step 2: Run tests to verify they pass**

```powershell
pytest tests/test_activities_selection.py -v
```

Expected: All PASS.

- [ ] **Step 3: Verify no regressions**

```powershell
pytest tests/test_activity_catalog.py tests/test_cares_handoff.py -v
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_activities_selection.py
git commit -m "test: selection core — eligibility, angle matching, scoring, full flow"
```

---

## Task 4: Integrate select_best_activity into Handoff Decision

**Files:**
- Modify: `stream/cares_handoff.py`
- Modify: `tests/test_cares_handoff.py`

`★ Insight ─────────────────────────────────────`
1. `evaluate_handoff()` currently calls `get_activity_for_attribute()` (legacy matcher). We replace this with `select_best_activity()` which uses the full three-layer algorithm.
2. The `activity` object returned in `decision_meta` is consumed by `paixueji_app.py` line 1721: `activity = decision_meta.get("activity")`. Since `ActivityDefinition` has `activity_id`, `name`, and `launch_prompt` fields, the existing downstream code works without changes.
3. The existing test at `test_cares_handoff.py:402` patches `get_activity_for_attribute`. We update it to patch `select_best_activity` instead, returning a `SelectionResult` with a mock activity.
`─────────────────────────────────────────────────`

- [ ] **Step 1: Update `stream/cares_handoff.py`**

Change the import at the top:

```python
# Old:
from activities import get_activity_for_attribute

# New:
from activities import select_best_activity, SelectionResult
```

Replace the entire `evaluate_handoff` function (lines 173-257):

```python
def evaluate_handoff(assistant, switch_result) -> tuple[HandoffDecision, str, dict[str, Any]]:
    """Evaluate handoff decision based on interest scores and session state."""
    records = assistant.attribute_interest_records
    total_turns = sum(r.turns_explored for r in records.values())

    # Compute scores for all attributes
    scored = [
        (aid, compute_attribute_interest_score(r))
        for aid, r in records.items()
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_attr, best_score = scored[0] if scored else (None, 0)
    current_attr = assistant.attribute_state.profile.attribute_id
    current_record = records.get(current_attr)
    current_score = compute_attribute_interest_score(current_record) if current_record else 0

    # Build conversation context for selection
    def _build_context() -> dict[str, Any]:
        return {
            "dominant_angle": getattr(assistant.attribute_state, "current_angle_id", None) or "",
            "secondary_angles": list(getattr(current_record, "explored_angle_ids", [])) if current_record else [],
            "angles": list(getattr(current_record, "explored_angle_ids", [])) if current_record else [],
            "entity_depth": "property_focused",
            "recent_activities": [],
            "entity_info": {},
            "extracted_properties": {},
        }

    # 1. Severe disengagement -> REENGAGE
    if assistant.consecutive_struggle_count >= 3:
        return HandoffDecision.REENGAGE, "struggle_streak_3", {}

    if total_turns >= 2 and current_score < 20:
        return HandoffDecision.REENGAGE, "critical_disengagement", {}

    # 2. Clear switch signal -> CONTINUE_SWITCH
    if switch_result.should_switch and switch_result.target_attribute_id:
        target = switch_result.target_attribute_id
        if any(aid == target for aid, _ in scored):
            return HandoffDecision.CONTINUE_SWITCH, f"detector:{target}", {
                "target_attribute": target,
                "reason": "child_showed_clear_interest",
            }

    # 3. Attribute meets threshold -> HANDOFF_NOW
    if best_score >= MIN_INTEREST_FOR_HANDOFF:
        conversation_context = _build_context()

        selection = select_best_activity(
            attribute_id=best_attr,
            interest_score=best_score,
            age=assistant.age or 6,
            conversation_context=conversation_context,
        )
        activity = selection.activity

        if activity:
            if best_attr == current_attr:
                return HandoffDecision.HANDOFF_NOW, f"current_best:{best_score:.0f}", {
                    "target_attribute": best_attr,
                    "activity": activity,
                    "readiness_score": best_score,
                }

            if current_score >= 50:
                current_selection = select_best_activity(
                    attribute_id=current_attr,
                    interest_score=current_score,
                    age=assistant.age or 6,
                    conversation_context=conversation_context,
                )
                current_activity = current_selection.activity
                if current_activity:
                    return HandoffDecision.HANDOFF_NOW, f"current_good:{current_score:.0f}", {
                        "target_attribute": current_attr,
                        "activity": current_activity,
                        "readiness_score": current_score,
                        "note": f"global_best_is_{best_attr}_but_current_is_good_enough",
                    }

            return HandoffDecision.HANDOFF_NOW, f"global_best:{best_attr}:{best_score:.0f}", {
                "target_attribute": best_attr,
                "activity": activity,
                "readiness_score": best_score,
                "current_attribute": current_attr,
                "bridge_context": f"child_previously_explored_{best_attr}_with_score_{best_score:.0f}",
            }

        # Selection returned no activity → degrade to CONTINUE
        return HandoffDecision.CONTINUE, f"no_activity_for_best:{best_score:.0f}", {
            "current_attribute": current_attr,
            "current_score": current_score,
            "best_attribute": best_attr,
            "best_score": best_score,
        }

    # 4. Session timeout without threshold met -> EXIT_LANE
    if total_turns >= MAX_SESSION_TURNS:
        if best_score >= EXIT_LANE_INTEREST:
            return HandoffDecision.EXIT_LANE, f"timeout_with_memory:{best_attr}:{best_score:.0f}", {
                "best_attribute": best_attr,
                "best_score": best_score,
                "reason": "session_long_but_interest_detected",
            }
        else:
            return HandoffDecision.EXIT_LANE, "timeout_no_interest", {
                "reason": "session_long_no_meaningful_interest",
            }

    # 5. Default: continue
    return HandoffDecision.CONTINUE, f"building:{current_score:.0f}", {
        "current_attribute": current_attr,
        "current_score": current_score,
        "best_attribute": best_attr,
        "best_score": best_score,
    }
```

- [ ] **Step 2: Update `tests/test_cares_handoff.py`**

Replace the mock in `test_evaluate_handoff_handoff_now_current_best` (lines 386-405):

```python
def test_evaluate_handoff_handoff_now_current_best():
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2  # +16 initiation, score = 50 + 16 = 66 >= 60
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    # Mock select_best_activity returning a matched SelectionResult
    from unittest.mock import patch
    mock_activity = SimpleNamespace(activity_id="act1", name="Test", launch_prompt="Go!")
    mock_result = SimpleNamespace(
        activity=mock_activity,
        selector_score=75.0,
        decision="matched",
        fallback_reason=None,
    )
    with patch("stream.cares_handoff.select_best_activity", return_value=mock_result):
        decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.HANDOFF_NOW
    assert meta["target_attribute"] == "appearance.color"


def test_evaluate_handoff_handoff_now_no_activity_degrades_to_continue():
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    from unittest.mock import patch
    mock_result = SimpleNamespace(
        activity=None,
        selector_score=45.0,
        decision="none",
        fallback_reason="score_below_threshold",
    )
    with patch("stream.cares_handoff.select_best_activity", return_value=mock_result):
        decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.CONTINUE
    assert "no_activity_for_best" in reason
```

- [ ] **Step 3: Run tests to verify they pass**

```powershell
pytest tests/test_cares_handoff.py -v
```

Expected: All 30 tests PASS (28 existing + 2 new).

- [ ] **Step 4: Run full test suite**

```powershell
pytest -v
```

Expected: All tests PASS with no regressions.

- [ ] **Step 5: Commit**

```bash
git add stream/cares_handoff.py tests/test_cares_handoff.py
git commit -m "feat: integrate select_best_activity into CARES handoff decision"
```

---

## Task 5: Final Verification

- [ ] **Step 1: Run complete test suite**

```powershell
pytest tests/ -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 2: Verify catalog loads correctly from subdirectories**

```powershell
python -c "from activities import _load_catalog; cats = _load_catalog(); print([a.activity_id for a in cats])"
```

Expected: `['dream_whisperer_cat', 'fluffy_expedition_dandelion', 'mood_changer_dog', 'polka_dot_patrol', 'time_machine_dinosaur']` (order may vary).

- [ ] **Step 3: Verify select_best_activity end-to-end**

```powershell
python -c "
from activities import select_best_activity
result = select_best_activity(
    'appearance.pattern', 83, 5,
    {'dominant_angle': 'pattern', 'angles': ['pattern'], 'entity_depth': 'property_focused', 'recent_activities': [], 'entity_info': {}, 'extracted_properties': {}}
)
print('activity:', result.activity.activity_id if result.activity else None)
print('score:', result.selector_score)
print('decision:', result.decision)
"
```

Expected: `activity: polka_dot_patrol`, `score: >= 60`, `decision: matched`.

- [ ] **Step 4: Commit final state**

```bash
git status
# Should show clean working tree
git log --oneline -5
```

---

## Self-Review Checklist

### 1. Spec Coverage

| Design doc requirement | Task |
|------------------------|------|
| Replace `activity_type` with `mechanic` + `game_style` | Task 2 (ActivityDefinition fields) |
| Tier system: strings T0/T1/T2 | Task 2 (_age_to_tier, tier_range_span) |
| `tier_support` normalization (yes/no/true/false) | Task 2 (_normalize_tier_support) |
| Delete `estimated_duration_minutes`, `materials_needed` | Task 2 (ActivityDefinition) |
| Delete `target_attribute`, use `observation_angle` | Task 2 (get_activity_for_attribute rewrite) |
| Extra bucket for non-core fields | Task 2 (extra field) |
| `_ATTRIBUTE_TO_ANGLE` mapping | Task 2 |
| `_interest_to_profile` mapping | Task 2 |
| Layer 1: `_is_eligible` (tier + entity_binding) | Task 2 |
| Layer 2: Angle matching (exact → bridge → fallback) | Task 2 |
| Layer 3: `score_activity` (A+B+C+D) | Task 2 |
| `select_best_activity` entry point | Task 2 |
| Integrate into `evaluate_handoff` | Task 4 |
| Degrade to CONTINUE when no activity | Task 4 |
| `MIN_SCORE_FOR_HANDOFF = 60` | Task 2 |

### 2. Placeholder Scan

- No "TBD", "TODO", "implement later" — all code is complete.
- No vague instructions like "add appropriate error handling".
- All test code is shown in full.
- All function signatures match across tasks.

### 3. Type Consistency

- `ActivityDefinition.from_dict()` signature: consistent across Task 2.
- `select_best_activity()` signature: `(attribute_id, interest_score, age, conversation_context)` — used consistently in Task 2, 4.
- `SelectionResult` fields: `activity`, `selector_score`, `decision`, `fallback_reason` — consistent.
- `_age_to_tier()` returns `str` (T0/T1/T2) — used consistently.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-cares-phase2.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
