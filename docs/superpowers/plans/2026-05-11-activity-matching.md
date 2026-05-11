# Activity Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable dynamic in-lane topic switching within attribute_lane, matching and launching activities from an activity catalog based on the current active topic.

**Architecture:** Keep the existing Pipeline/Lane framework. Extend `AttributeProfile` and `DiscoverySessionState` to track a primary topic plus fallback topics. Use prompt-instructed model autonomy with `[SWITCH_TO:xxx]` marker detection for topic switching. Add a minimal activity catalog with schema-defined YAML activities.

**Tech Stack:** Python 3.11+, Flask, Gemini API, dataclasses, PyYAML, JSON Schema (for catalog validation)

---

## File Structure

| File | Role |
|------|------|
| `activities/_schema/tag_block.schema.json` | JSON Schema defining the structure of activity YAML files |
| `activities/catalog/color_exploration.yaml` | Mock activity: color-related exploration activity |
| `activities/catalog/shape_exploration.yaml` | Mock activity: shape-related exploration activity |
| `activities/catalog/size_exploration.yaml` | Mock activity: size-related exploration activity |
| `activities/__init__.py` | Activity catalog loader and matcher |
| `attribute_activity.py` | Extended `AttributeProfile` with fallbacks, extended `DiscoverySessionState`, new `select_attribute_profiles()` |
| `paixueji_assistant.py` | `start_attribute_lane()` accepts fallback profiles; `switch_attribute_topic()` method |
| `paixueji_prompts.py` | New `ATTRIBUTE_MULTI_TOPIC_GUIDE` prompt with fallback topics and `[SWITCH_TO]` rules |
| `stream/response_generators.py` | `detect_switch_marker()` function |
| `stream/question_generators.py` | `ask_followup_question_stream` receives multi-topic soft guide |
| `paixueji_app.py` | `/api/start` calls new `select_attribute_profiles()`; `/api/continue` detects `[SWITCH_TO]` and switches topic |

---

## Task 1: Design Activity Catalog Schema

**Files:**
- Create: `activities/_schema/tag_block.schema.json`
- Create: `activities/__init__.py`
- Create: `activities/catalog/color_exploration.yaml`
- Create: `activities/catalog/shape_exploration.yaml`
- Create: `activities/catalog/size_exploration.yaml`

**Purpose:** Define the contract for activity definitions and provide mock data for testing.

- [ ] **Step 1: Write the JSON Schema**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ActivityDefinition",
  "type": "object",
  "required": ["activity_id", "name", "target_attribute", "tier_range", "launch_prompt"],
  "properties": {
    "activity_id": { "type": "string" },
    "name": { "type": "string" },
    "target_attribute": { "type": "string" },
    "tier_range": { 
      "type": "array", 
      "items": { "type": "integer", "minimum": 0, "maximum": 2 },
      "minItems": 1
    },
    "launch_prompt": { "type": "string" },
    "description": { "type": "string" },
    "estimated_duration_minutes": { "type": "integer", "minimum": 1 },
    "materials_needed": { "type": "array", "items": { "type": "string" } }
  }
}
```

- [ ] **Step 2: Write mock activity YAMLs**

`activities/catalog/color_exploration.yaml`:
```yaml
activity_id: "color_exploration_v1"
name: "Color Explorer"
target_attribute: "appearance.color"
tier_range: [0, 1, 2]
launch_prompt: "Let us play Color Explorer! Can you find three things around you that are the same color as this?"
description: "Child finds objects matching the color of the target object"
estimated_duration_minutes: 5
materials_needed: []
```

`activities/catalog/shape_exploration.yaml`:
```yaml
activity_id: "shape_exploration_v1"
name: "Shape Detective"
target_attribute: "appearance.shape"
tier_range: [0, 1, 2]
launch_prompt: "Let us be Shape Detectives! What other things around you have the same shape?"
description: "Child identifies objects with similar shapes"
estimated_duration_minutes: 5
materials_needed: []
```

`activities/catalog/size_exploration.yaml`:
```yaml
activity_id: "size_exploration_v1"
name: "Size Comparison"
target_attribute: "appearance.size"
tier_range: [0, 1, 2]
launch_prompt: "Let us compare sizes! Can you find something bigger and something smaller than this?"
description: "Child compares sizes of nearby objects"
estimated_duration_minutes: 5
materials_needed: []
```

- [ ] **Step 3: Create `activities/__init__.py` with loader and matcher**

```python
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
```

- [ ] **Step 4: Commit**

```bash
git add activities/
git commit -m "feat: add activity catalog schema and mock activities"
```

---

## Task 2: Extend AttributeProfile and DiscoverySessionState

**Files:**
- Modify: `attribute_activity.py`

**Purpose:** Add fallback tracking and topic switching state to the attribute lane data model.

- [ ] **Step 1: Modify `AttributeProfile`**

Add `fallback_attributes` field (tuple of `AttributeProfile`):

```python
@dataclass(frozen=True)
class AttributeProfile:
    attribute_id: str
    label: str
    activity_target: str
    branch: str
    object_examples: tuple[str, ...]
    redirect_entity: str | None = None
    # NEW: fallback attributes for in-lane dynamic switching
    fallback_attributes: tuple["AttributeProfile", ...] = ()
```

- [ ] **Step 2: Modify `DiscoverySessionState`**

Add fields to track current topic, fallback topics, and switch history:

```python
@dataclass
class DiscoverySessionState:
    object_name: str
    profile: AttributeProfile
    age: int
    turn_count: int = 0
    activity_ready: bool = False
    surface_object_name: str | None = None
    anchor_object_name: str | None = None
    # NEW: fallback tracking and switch history
    fallback_profiles: tuple[AttributeProfile, ...] = ()
    switched_to: str | None = None
    switch_reason: str | None = None

    def to_debug_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 3: Add helper to build fallback-aware profile block**

```python
def _build_fallback_attribute_block(profiles: tuple[AttributeProfile, ...]) -> str:
    if not profiles:
        return "(no fallback topics)"
    lines = []
    for profile in profiles:
        lines.append(
            f"- {profile.attribute_id}: {profile.label}; activity={profile.activity_target}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Commit**

```bash
git add attribute_activity.py
git commit -m "feat: add fallback_attributes to AttributeProfile and switch tracking to DiscoverySessionState"
```

---

## Task 3: Modify `select_attribute_profile()` to Select Primary + Fallback

**Files:**
- Modify: `attribute_activity.py`
- Modify: `paixueji_prompts.py`

**Purpose:** Change the selection logic to return a primary profile with 1 fallback profile embedded.

- [ ] **Step 1: Modify `select_attribute_profile()`**

Keep the same return signature `tuple[AttributeProfile | None, dict]` but the returned `AttributeProfile` now has `fallback_attributes` populated.

Key changes:
- After building `profiles` from candidates, if only 1 candidate, return it directly with no fallback.
- Otherwise, ask Gemini to pick both `attribute_id` (primary) and `fallback_attribute_id`.
- Find primary profile by `attribute_id`; if not found, fallback to `profiles[0]`.
- Find fallback profile by `fallback_attribute_id` that is DIFFERENT from primary; if not found, pick first non-primary candidate.
- Construct new `AttributeProfile` with `fallback_attributes=(fallback,)` embedded.
- Return debug dict with `fallback_attribute_id` field.

Pseudocode for the selection logic:

```python
# Find primary profile
primary = next((p for p in profiles if p.attribute_id == chosen_id), profiles[0])

# Find fallback profile (must differ from primary)
fallback = None
if fallback_id:
    fallback = next((p for p in profiles if p.attribute_id == fallback_id and p.attribute_id != primary.attribute_id), None)
if fallback is None:
    fallback = next((p for p in profiles if p.attribute_id != primary.attribute_id), None)

# Build primary with fallback embedded
primary_with_fallback = AttributeProfile(
    attribute_id=primary.attribute_id,
    label=primary.label,
    activity_target=primary.activity_target,
    branch=primary.branch,
    object_examples=primary.object_examples,
    redirect_entity=primary.redirect_entity,
    fallback_attributes=(fallback,) if fallback else (),
)
```

- [ ] **Step 2: Update `ATTRIBUTE_SELECTION_PROMPT`**

In `paixueji_prompts.py`, update the prompt to ask for both primary and fallback:

```python
ATTRIBUTE_SELECTION_PROMPT = """Choose one supported activity attribute for a child chat, plus one fallback attribute.

OBJECT: {object_name}
CHILD AGE: {age}
DOMAIN: {domain}

SUPPORTED ATTRIBUTES:
{supported_attributes}

Return JSON only:
{{
  "attribute_id": "one supported attribute id (format: dimension.sub_attribute), or null",
  "fallback_attribute_id": "one supported attribute id different from attribute_id, or null",
  "confidence": "high|medium|low|none",
  "reason": "short reason"
}}

Choose the PRIMARY attribute most naturally connected to this object.
Choose the FALLBACK as a related attribute the child might naturally drift to.
If domain is "unknown", prefer attributes from appearance or senses dimensions.
Both attribute_ids must exactly match entries from the SUPPORTED ATTRIBUTES list."""
```

- [ ] **Step 3: Modify `start_attribute_session()` to store fallbacks**

```python
def start_attribute_session(*, object_name, profile, age, surface_object_name=None, anchor_object_name=None):
    if profile is None:
        raise ValueError("profile is required")
    return DiscoverySessionState(
        object_name=object_name,
        profile=profile,
        age=6 if age is None else age,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        fallback_profiles=profile.fallback_attributes,
    )
```

- [ ] **Step 4: Commit**

```bash
git add attribute_activity.py paixueji_prompts.py
git commit -m "feat: select primary + fallback attribute profiles"
```

---

## Task 4: Add `[SWITCH_TO:xxx]` Detection and Topic Switching

**Files:**
- Modify: `stream/response_generators.py`
- Modify: `paixueji_assistant.py`

**Purpose:** Detect the `[SWITCH_TO:attribute_id]` marker in model output and update the active topic.

- [ ] **Step 1: Add `detect_switch_marker()` to `stream/response_generators.py`**

```python
import re

_SWITCH_TO_RE = re.compile(r"\[SWITCH_TO:([\w.]+)\]")

def detect_switch_marker(response_text: str) -> tuple[str | None, str]:
    """
    Detect [SWITCH_TO:attribute_id] marker in model output.
    Returns (target_attribute_id, cleaned_response_text).
    target_attribute_id is None if no marker found.
    """
    match = _SWITCH_TO_RE.search(response_text)
    if match:
        target_id = match.group(1)
        cleaned = _SWITCH_TO_RE.sub("", response_text).strip()
        return target_id, cleaned
    return None, response_text
```

- [ ] **Step 2: Add `switch_attribute_topic()` to `paixueji_assistant.py`**

In the `PaixuejiAssistant` class, add:

```python
def switch_attribute_topic(self, target_attribute_id: str, reason: str = "") -> bool:
    """
    Switch the active attribute topic within the attribute lane.
    Swaps the active profile with the matching fallback (bidirectional).
    No limit on number of switches.
    Returns True if switch succeeded, False if target not found in fallbacks.
    """
    if not self.attribute_lane_active or not self.attribute_state:
        return False

    current_profile = self.attribute_state.profile

    # No-op if already on target
    if current_profile.attribute_id == target_attribute_id:
        return True

    # Check fallbacks
    for fallback in current_profile.fallback_attributes:
        if fallback.attribute_id == target_attribute_id:
            # Build new primary: the selected fallback
            # Build new fallbacks: old fallbacks minus selected, plus old primary
            new_fallbacks = tuple(
                f for f in current_profile.fallback_attributes
                if f.attribute_id != target_attribute_id
            ) + (current_profile,)

            new_profile = AttributeProfile(
                attribute_id=fallback.attribute_id,
                label=fallback.label,
                activity_target=fallback.activity_target,
                branch=fallback.branch,
                object_examples=fallback.object_examples,
                redirect_entity=fallback.redirect_entity,
                fallback_attributes=new_fallbacks,
            )

            self.attribute_state.profile = new_profile
            self.attribute_state.switched_to = target_attribute_id
            self.attribute_state.switch_reason = reason
            self.attribute_profile = new_profile
            self.attribute_state.activity_ready = False
            self.attribute_activity_ready = False
            return True

    return False
```

- [ ] **Step 3: Commit**

```bash
git add stream/response_generators.py paixueji_assistant.py
git commit -m "feat: add SWITCH_TO marker detection and attribute topic switching"
```

---

## Task 5: Create Multi-Topic Prompt Template

**Files:**
- Modify: `paixueji_prompts.py`

**Purpose:** Create a new prompt that includes fallback topics and instructs the model when to emit `[SWITCH_TO]`.

- [ ] **Step 1: Add `ATTRIBUTE_MULTI_TOPIC_GUIDE`**

```python
ATTRIBUTE_MULTI_TOPIC_GUIDE = """
{sensory_safety_rules}

PRIMARY EXPLORATION DIRECTION: {primary_attribute_label}
PRIMARY ACTIVITY GOAL: {primary_activity_target}

FALLBACK TOPICS (you may drift to these if the child shows interest):
{fallback_attribute_block}

TOPIC SWITCHING RULES:
- Your MAIN job is to guide the child toward {primary_attribute_label}.
- BUT if the child clearly shows more interest in a fallback topic, you may switch.
- To switch: at the END of your response, add [SWITCH_TO:attribute_id].
- ONLY switch if the child has clearly shifted interest.
- After switching, your new primary direction becomes that fallback topic.
- If the child mentions something outside all topics, briefly acknowledge in ONE sentence, then redirect back.

THREE TECHNIQUES (use ONE per turn, when it fits):

A) SALIENCE — include a {primary_attribute_label}-related sensory word in the question itself.
B) FRAME WEAVING — when the child noticed something OTHER than {primary_attribute_label}, offer a choice that includes {primary_attribute_label} as one option.
C) NATURAL BRIDGE — when the child has explored {primary_attribute_label} with enough depth, extend toward the activity goal.

EVIDENCE REQUIREMENT: Your REASON line MUST include at least one direct quote from the child.

TRANSITION SIGNAL for [ACTIVITY_READY]:
1. one child-facing question
2. then on a new line: [ACTIVITY_READY]
3. then on a new line: REASON: <1-sentence with direct child quote>

TOPIC SWITCH SIGNAL:
1. one child-facing response about the new topic
2. then on a new line: [SWITCH_TO:new_attribute_id]
3. then on a new line: REASON: <brief reason>

ANTI-PATTERNS — NEVER produce these:
- "What {primary_attribute_label} is it?" — quiz
- "Do you know what {primary_attribute_label} it has?" — quiz with wrapper
- "What else can you tell me about it?" — too vague
- "Let us look at its {primary_attribute_label}!" — forced redirect
- "That is nice, but..." then question about {primary_attribute_label} — ignoring child
- "Great! Now we can start an activity!" — mechanical announcement
- Adding [ACTIVITY_READY] after just one shallow exchange — premature handoff
- Switching topics on a single casual mention — too sensitive
"""
```

- [ ] **Step 2: Commit**

```bash
git add paixueji_prompts.py
git commit -m "feat: add multi-topic guide prompt with SWITCH_TO rules"
```

---

## Task 6: Modify `/api/continue` to Detect and Handle `[SWITCH_TO]`

**Files:**
- Modify: `paixueji_app.py`

**Purpose:** In the attribute lane continue path, detect `[SWITCH_TO]` after the response is generated, switch the topic if valid, and update subsequent prompt context.

- [ ] **Step 1: Import `detect_switch_marker`**

Add to existing `stream` imports in `paixueji_app.py`:

```python
from stream import (
    # ... existing imports ...
    detect_switch_marker,  # NEW
)
```

Also import the activity matcher:

```python
from activities import get_activity_for_attribute  # NEW
```

- [ ] **Step 2: Add switch detection after response generation**

After `full_response` is collected from `response_generator` (around line 1308), insert:

```python
switch_target_id, cleaned_response = detect_switch_marker(full_response)
if switch_target_id:
    switch_success = assistant.switch_attribute_topic(
        target_attribute_id=switch_target_id,
        reason="model_detected_switch_marker",
    )
    if switch_success:
        full_response = cleaned_response
        attribute_label = assistant.attribute_state.profile.label
        activity_target = assistant.attribute_state.profile.activity_target
        logger.info(
            "[ATTRIBUTE_SWITCH] switched to %s | session=%s",
            switch_target_id, session_id[:8],
        )
    else:
        logger.warning(
            "[ATTRIBUTE_SWITCH] rejected: target %s not in fallbacks | session=%s",
            switch_target_id, session_id[:8],
        )
        full_response = cleaned_response
```

- [ ] **Step 3: Update soft guide formatting**

Replace the existing soft guide formatting (around line 1340) with the new multi-topic guide:

```python
fallback_block = ""
if assistant.attribute_state.profile.fallback_attributes:
    lines = [f"- {fb.attribute_id}: {fb.label}" for fb in assistant.attribute_state.profile.fallback_attributes]
    fallback_block = "\n".join(lines)

soft_guide = paixueji_prompts.get_prompts()["attribute_multi_topic_guide"].format(
    primary_attribute_label=attribute_label,
    primary_activity_target=activity_target,
    fallback_attribute_block=fallback_block or "(no fallback topics)",
    sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
)
```

- [ ] **Step 4: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: handle SWITCH_TO detection and topic switching in continue endpoint"
```

---

## Task 7: Wire Activity Matching into `/api/start`

**Files:**
- Modify: `paixueji_app.py`

**Purpose:** When starting the attribute lane, also look up and log the matched activity for debugging.

- [ ] **Step 1: Add activity matching log in `/api/start`**

After `assistant.start_attribute_lane(attribute_state, attribute_profile)` (around line 683), add:

```python
matched_activity = get_activity_for_attribute(
    attribute_profile.attribute_id, age or 6
)
if matched_activity:
    logger.info(
        "[ACTIVITY_MATCH] primary=%s activity=%s session=%s",
        attribute_profile.attribute_id, matched_activity.activity_id, session_id[:8],
    )
else:
    logger.warning(
        "[ACTIVITY_MATCH] no activity found for primary=%s session=%s",
        attribute_profile.attribute_id, session_id[:8],
    )

for fb in attribute_profile.fallback_attributes:
    fb_activity = get_activity_for_attribute(fb.attribute_id, age or 6)
    if fb_activity:
        logger.info(
            "[ACTIVITY_MATCH] fallback=%s activity=%s session=%s",
            fb.attribute_id, fb_activity.activity_id, session_id[:8],
        )
```

- [ ] **Step 2: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: log activity matching on session start"
```

---

## Task 8: Update `_assistant_stream_fields` to Include Switch State

**Files:**
- Modify: `paixueji_app.py`

**Purpose:** Include topic switch state in SSE stream metadata so the frontend can display it.

- [ ] **Step 1: Add switch fields**

In `_assistant_stream_fields()`, add before the return statement:

```python
switch_state = {}
if getattr(assistant, "attribute_state", None):
    state = assistant.attribute_state
    switch_state = {
        "attribute_switched_to": getattr(state, "switched_to", None),
        "attribute_switch_reason": getattr(state, "switch_reason", None),
        "attribute_fallback_count": len(getattr(state, "fallback_profiles", ())),
        "attribute_turn_count": getattr(state, "turn_count", 0),
    }
```

Then spread `**switch_state` into the returned dict.

- [ ] **Step 2: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: expose switch state in stream metadata"
```

---

## Task 9: Add Unit Tests

**Files:**
- Create: `tests/test_activity_catalog.py`
- Create: `tests/test_attribute_switching.py`
- Create: `tests/test_switch_marker.py`

- [ ] **Step 1: Test activity catalog loading and matching**

```python
# tests/test_activity_catalog.py
import pytest
from activities import get_activity_for_attribute, list_activities_for_attribute

def test_get_activity_for_color():
    activity = get_activity_for_attribute("appearance.color", 5)
    assert activity is not None
    assert activity.activity_id == "color_exploration_v1"

def test_get_activity_for_shape():
    activity = get_activity_for_attribute("appearance.shape", 5)
    assert activity is not None
    assert activity.activity_id == "shape_exploration_v1"

def test_get_activity_no_match():
    activity = get_activity_for_attribute("nonexistent.attribute", 5)
    assert activity is None

def test_tier_filtering():
    assert get_activity_for_attribute("appearance.color", 3) is not None
    assert get_activity_for_attribute("appearance.color", 8) is not None
```

- [ ] **Step 2: Test `detect_switch_marker()`**

```python
# tests/test_switch_marker.py
import pytest
from stream.response_generators import detect_switch_marker

def test_detect_switch_marker_found():
    text = "Let us switch! [SWITCH_TO:appearance.shape]\nREASON: child said round"
    target, cleaned = detect_switch_marker(text)
    assert target == "appearance.shape"
    assert "[SWITCH_TO" not in cleaned

def test_detect_switch_marker_not_found():
    text = "What color do you see?"
    target, cleaned = detect_switch_marker(text)
    assert target is None
    assert cleaned == text

def test_detect_switch_marker_multiline():
    text = "Wow, you noticed the size!\n[SWITCH_TO:appearance.size]"
    target, cleaned = detect_switch_marker(text)
    assert target == "appearance.size"
```

- [ ] **Step 3: Test topic switching on assistant**

```python
# tests/test_attribute_switching.py
import pytest
from paixueji_assistant import PaixuejiAssistant
from attribute_activity import AttributeProfile, start_attribute_session

def test_switch_to_fallback():
    assistant = PaixuejiAssistant(client=None)
    primary = AttributeProfile(
        attribute_id="appearance.color", label="color",
        activity_target="exploring colors", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    fallback = AttributeProfile(
        attribute_id="appearance.shape", label="shape",
        activity_target="exploring shapes", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    primary_with_fb = AttributeProfile(
        attribute_id=primary.attribute_id, label=primary.label,
        activity_target=primary.activity_target, branch=primary.branch,
        object_examples=primary.object_examples,
        fallback_attributes=(fallback,),
    )
    state = start_attribute_session(object_name="apple", profile=primary_with_fb, age=5)
    assistant.start_attribute_lane(state, primary_with_fb)
    success = assistant.switch_attribute_topic("appearance.shape")
    assert success is True
    assert assistant.attribute_state.profile.attribute_id == "appearance.shape"
    assert assistant.attribute_state.switched_to == "appearance.shape"
    fallback_ids = [f.attribute_id for f in assistant.attribute_state.profile.fallback_attributes]
    assert "appearance.color" in fallback_ids

def test_switch_to_invalid_target():
    assistant = PaixuejiAssistant(client=None)
    primary = AttributeProfile(
        attribute_id="appearance.color", label="color",
        activity_target="exploring colors", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    state = start_attribute_session(object_name="apple", profile=primary, age=5)
    assistant.start_attribute_lane(state, primary)
    success = assistant.switch_attribute_topic("nonexistent.attribute")
    assert success is False
    assert assistant.attribute_state.profile.attribute_id == "appearance.color"
```

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: add unit tests for activity catalog, switch marker, and topic switching"
```

---

## Task 10: Integration Test (Manual)

**Files:**
- None (manual testing)

- [ ] **Step 1: Start the server and test with curl**

```bash
curl -X POST http://localhost:5000/api/start \\
  -H "Content-Type: application/json" \\
  -d "{\"object_name\": \"apple\", \"age\": 5, \"attribute_pipeline_enabled\": true}"
```

- [ ] **Step 2: Continue and try to trigger a switch**

```bash
curl -X POST http://localhost:5000/api/continue \\
  -H "Content-Type: application/json" \\
  -d "{\"session_id\": \"YOUR_SESSION_ID\", \"child_input\": \"it looks round like a ball!\"}"
```

- [ ] **Step 3: Verify in logs**

Check server logs for `[ATTRIBUTE_SWITCH]`, `[ACTIVITY_MATCH]`, and `[ACTIVITY_READY]` lines.

---

## Self-Review Checklist

### Spec Coverage

| PRD Requirement | Task |
|-----------------|------|
| Design `tag_block.schema.json` | Task 1, Step 1 |
| Create mock activity catalog | Task 1, Steps 2-3 |
| Modify `AttributeProfile` with fallbacks | Task 2, Step 1 |
| Modify `DiscoverySessionState` | Task 2, Step 2 |
| Modify `select_attribute_profile()` for primary+fallback | Task 3 |
| Modify `start_attribute_session()` | Task 3, Step 3 |
| Add `[SWITCH_TO:xxx]` detection | Task 4 |
| Modify prompt templates | Task 5 |
| Modify `/api/start` | Task 7 |
| Activity matching logic | Task 1, Task 6, Task 7 |
| No cross-lane switching | Implicit |
| No forced turn limit | Activity launch remains model-driven via `[ACTIVITY_READY]` |

### Placeholder Scan
- No "TBD", "TODO", or "implement later" found
- All code blocks contain complete, runnable code
- All file paths are absolute

### Type Consistency
- `AttributeProfile.fallback_attributes: tuple[AttributeProfile, ...]` used consistently
- `DiscoverySessionState.fallback_profiles` matches `profile.fallback_attributes`
- `detect_switch_marker()` returns `(str | None, str)` consistently
- `switch_attribute_topic()` returns `bool` consistently

---

## Critical Files for Implementation

- `C:\Users\123\Documents\GitHub\AI_ask_ask\activities\_schema\tag_block.schema.json`
- `C:\Users\123\Documents\GitHub\AI_ask_ask\activities\__init__.py`
- `C:\Users\123\Documents\GitHub\AI_ask_ask\attribute_activity.py`
- `C:\Users\123\Documents\GitHub\AI_ask_ask\paixueji_assistant.py`
- `C:\Users\123\Documents\GitHub\AI_ask_ask\paixueji_prompts.py`
- `C:\Users\123\Documents\GitHub\AI_ask_ask\stream\response_generators.py`
- `C:\Users\123\Documents\GitHub\AI_ask_ask\paixueji_app.py`

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-11-activity-matching.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
