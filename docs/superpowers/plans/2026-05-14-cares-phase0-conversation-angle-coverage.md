# CARES Phase 0: Conversation Angle Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a structured exploration angle pool with runtime coverage tracking so the attribute pipeline gives the LLM a fresh cognitive direction every turn, preventing repetitive questions.

**Architecture:** Add a dimension-level angle pool (`stream/exploration_angles.py`) with 9 angles across physical/engagement dimensions. Track which angles have been used per attribute session in `DiscoverySessionState`. Select the next angle based on coverage and interest-score unlocking. Inject angle guidance into LLM prompts dynamically in `paixueji_app.py`.

**Tech Stack:** Python 3.11, dataclasses, existing Flask/SSE streaming pipeline, pytest.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `stream/exploration_angles.py` | **Create** | Angle pool definitions (`EXPLORATION_ANGLES`), selection logic (`select_next_angle`), `AngleCoverageRecord` dataclass |
| `stream/__init__.py` | **Modify** | Export new public symbols from `exploration_angles` |
| `attribute_activity.py` | **Modify** | Add `explored_angle_ids`, `angle_records`, `current_angle_id` to `DiscoverySessionState`; add `record_angle()` method |
| `paixueji_app.py` | **Modify** | Select next angle before response generation; build angle-aware prompt; record angle after turn completes |
| `tests/test_exploration_angles.py` | **Create** | Unit tests for angle selection, coverage tracking, interest-score unlocking |
| `tests/test_attribute_activity_pipeline.py` | **Modify** | Add tests for `record_angle` and angle field defaults |

---

## Task 1: Exploration Angles Module

**Files:**
- Create: `stream/exploration_angles.py`
- Test: `tests/test_exploration_angles.py`

### Step 1: Write the failing test

Create `tests/test_exploration_angles.py`:

```python
"""Tests for exploration angle pool and selection logic."""

import pytest
from stream.exploration_angles import (
    EXPLORATION_ANGLES,
    PHYSICAL_DIMENSIONS,
    AngleCoverageRecord,
    select_next_angle,
)


def test_select_next_angle_returns_first_for_empty_explored():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=0)
    assert result["angle_id"] == "observation"


def test_select_next_angle_cycles_after_all_used():
    physical_ids = [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]
    result = select_next_angle(explored_angle_ids=physical_ids, dimension="appearance", interest_score=0)
    # All used; should cycle to first (skip-last logic doesn't apply when all are used)
    assert result["angle_id"] == "observation"


def test_select_next_angle_skips_last_when_all_used():
    physical_ids = [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]
    result = select_next_angle(
        explored_angle_ids=physical_ids + ["observation"],  # observation was just used
        dimension="appearance",
        interest_score=0,
    )
    # observation was most recent; skip it if possible
    assert result["angle_id"] != "observation"


def test_select_next_angle_low_interest_restricts_angles():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=20)
    # < 30 should only return observation or comparison
    assert result["angle_id"] in ("observation", "comparison")


def test_select_next_angle_medium_interest_excludes_causal():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=40)
    # 30-55 should exclude causal
    assert result["angle_id"] != "causal"


def test_select_next_angle_high_interest_unlocks_all():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=60)
    # >= 55 should unlock all including causal
    assert result["angle_id"] in [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]


def test_select_next_angle_uses_engagement_pool_for_emotion():
    result = select_next_angle(explored_angle_ids=[], dimension="emotion", interest_score=0)
    assert result["angle_id"] in [a["angle_id"] for a in EXPLORATION_ANGLES["engagement"]]


def test_select_next_angle_no_consecutive_repeat():
    explored = []
    prev = None
    for _ in range(10):
        angle = select_next_angle(explored_angle_ids=explored, dimension="appearance", interest_score=0)
        if prev is not None:
            assert angle["angle_id"] != prev, f"angle {angle['angle_id']} repeated consecutively"
        explored.append(angle["angle_id"])
        prev = angle["angle_id"]


def test_angle_coverage_record_dataclass():
    record = AngleCoverageRecord(
        angle_id="observation",
        turn_index=1,
        question_text="What color do you see?",
        response_text="It is red!",
    )
    assert record.angle_id == "observation"
    assert record.turn_index == 1
```

### Step 2: Run test to verify it fails

```bash
pytest tests/test_exploration_angles.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'stream.exploration_angles'`

### Step 3: Implement `stream/exploration_angles.py`

```python
"""Exploration angle pools and selection logic for CARES attribute pipeline.

Provides structured cognitive directions ("angles") per dimension type,
preventing the LLM from repeating the same question style across turns.
"""

from dataclasses import dataclass


@dataclass
class AngleCoverageRecord:
    angle_id: str
    turn_index: int
    question_text: str
    response_text: str


# Dimensions that map to the "physical" angle pool.
PHYSICAL_DIMENSIONS = frozenset({
    "appearance",
    "senses",
    "structure",
    "function",
    "context",
    "change",
})

EXPLORATION_ANGLES = {
    "physical": [
        {
            "angle_id": "observation",
            "description": "Ask the child to observe and describe the attribute with their own words",
            "response_hint": "Share one concrete sensory fact about the {attribute_label}",
            "question_hint": "Ask what the child notices or sees about the {attribute_label}",
            "example": "What color do you see on the {object_name}?",
        },
        {
            "angle_id": "comparison",
            "description": "Compare this attribute with something familiar to the child",
            "response_hint": "Share a surprising comparison or contrast about the {attribute_label}",
            "question_hint": "Ask the child to compare the {attribute_label} with something they know",
            "example": "Is it more like a banana or a grape in color?",
        },
        {
            "angle_id": "preference",
            "description": "Invite the child to express a personal preference or opinion",
            "response_hint": "Validate that there is no wrong answer",
            "question_hint": "Ask which version of the {attribute_label} they like better",
            "example": "Do you like red apples or green apples better?",
        },
        {
            "angle_id": "association",
            "description": "Connect the attribute to the child's everyday life or other objects",
            "response_hint": "Mention one everyday object that shares this attribute",
            "question_hint": "Ask where else the child has seen this {attribute_label}",
            "example": "What else around you has this same color?",
        },
        {
            "angle_id": "causal",
            "description": "Explore why or how the attribute came to be (age-appropriate)",
            "response_hint": "Give a simple, concrete explanation",
            "question_hint": "Ask why the {object_name} has this {attribute_label}",
            "example": "Why do you think apples turn red when they grow?",
        },
    ],
    "engagement": [
        {
            "angle_id": "emotional",
            "description": "Ask about feelings and emotional reactions",
            "response_hint": "Acknowledge the child's feeling as valid",
            "question_hint": "Ask how the {object_name} makes them feel",
            "example": "Does the red apple make you feel happy or excited?",
        },
        {
            "angle_id": "memory",
            "description": "Connect to personal memories and experiences",
            "response_hint": "Share a brief, relatable memory",
            "question_hint": "Ask if the {object_name} reminds them of something",
            "example": "Does this apple remind you of anything you've eaten before?",
        },
        {
            "angle_id": "imagination",
            "description": "Invite playful imagination and pretend",
            "response_hint": "Play along with the child's imagination",
            "question_hint": "Ask a playful 'what if' about the {attribute_label}",
            "example": "If this apple could change color, what color would you pick?",
        },
        {
            "angle_id": "social",
            "description": "Connect to relationships and social context",
            "response_hint": "Mention how people or animals relate to this",
            "question_hint": "Ask who else might like or use this {attribute_label}",
            "example": "Who do you know that likes red apples?",
        },
    ],
}


def select_next_angle(
    explored_angle_ids: list[str],
    dimension: str,
    interest_score: float = 0,
) -> dict:
    """Select the next exploration angle for the given dimension.

    Args:
        explored_angle_ids: List of angle IDs already used this session.
        dimension: The attribute dimension (e.g. "appearance", "emotion").
        interest_score: Current interest score (0-100). Unlocks deeper angles.

    Returns:
        The selected angle dict with keys: angle_id, description, response_hint,
        question_hint, example.
    """
    pool_key = "physical" if dimension in PHYSICAL_DIMENSIONS else "engagement"
    pool = EXPLORATION_ANGLES.get(pool_key, [])

    if not pool:
        return {
            "angle_id": "observation",
            "description": "Ask the child to observe and describe",
            "response_hint": "Share one concrete fact",
            "question_hint": "Ask what the child notices",
            "example": "What do you notice about it?",
        }

    unused = [a for a in pool if a["angle_id"] not in explored_angle_ids]

    if unused:
        # Filter by interest-score unlocking
        if interest_score < 30:
            simple = [a for a in unused if a["angle_id"] in ("observation", "comparison")]
            return simple[0] if simple else unused[0]
        elif interest_score < 55:
            medium = [a for a in unused if a["angle_id"] != "causal"]
            return medium[0] if medium else unused[0]
        return unused[0]

    # All angles used: cycle, avoiding the most recently used if possible
    for angle in pool:
        if explored_angle_ids and angle["angle_id"] != explored_angle_ids[-1]:
            return angle
    return pool[0]
```

### Step 4: Run tests to verify they pass

```bash
pytest tests/test_exploration_angles.py -v
```

Expected: All 9 tests PASS.

### Step 5: Commit

```bash
git add stream/exploration_angles.py tests/test_exploration_angles.py
git commit -m "feat: add exploration angle pools and selection logic for CARES Phase 0"
```

---

## Task 2: Wire Exports

**Files:**
- Modify: `stream/__init__.py`

### Step 1: Add exports

In `stream/__init__.py`, add to the existing import list:

```python
from .exploration_angles import (
    EXPLORATION_ANGLES,
    AngleCoverageRecord,
    select_next_angle,
)
```

### Step 2: Verify import works

```bash
python -c "from stream import select_next_angle, AngleCoverageRecord, EXPLORATION_ANGLES; print('OK')"
```

Expected: `OK`

### Step 3: Commit

```bash
git add stream/__init__.py
git commit -m "chore: export exploration_angles symbols from stream package"
```

---

## Task 3: Extend DiscoverySessionState

**Files:**
- Modify: `attribute_activity.py`
- Modify: `tests/test_attribute_activity_pipeline.py`

### Step 1: Add fields and record_angle method

In `attribute_activity.py`:

1. Add import at top:
```python
from dataclasses import asdict, dataclass, field
```

2. Add import for `AngleCoverageRecord`:
```python
from stream.exploration_angles import AngleCoverageRecord
```

3. Add fields to `DiscoverySessionState`:
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
    last_activity_ready_rejected_reason: str | None = None
    # NEW: angle coverage tracking (CARES Phase 0)
    explored_angle_ids: list[str] = field(default_factory=list)
    angle_records: list[AngleCoverageRecord] = field(default_factory=list)
    current_angle_id: str | None = None

    def to_debug_dict(self) -> dict:
        d = asdict(self)
        # AngleCoverageRecord is a dataclass; asdict handles it recursively
        return d

    def record_angle(
        self,
        turn_index: int,
        angle_id: str,
        question_text: str,
        response_text: str,
    ) -> None:
        """Record that an angle was used for a given turn."""
        self.explored_angle_ids.append(angle_id)
        self.angle_records.append(
            AngleCoverageRecord(
                angle_id=angle_id,
                turn_index=turn_index,
                question_text=question_text,
                response_text=response_text,
            )
        )
```

### Step 2: Update tests

In `tests/test_attribute_activity_pipeline.py`, add:

```python
from stream.exploration_angles import AngleCoverageRecord


def test_start_attribute_session_initializes_empty_angle_tracking():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )
    assert state.explored_angle_ids == []
    assert state.angle_records == []
    assert state.current_angle_id is None


def test_discovery_session_state_record_angle():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )
    state.record_angle(
        turn_index=1,
        angle_id="observation",
        question_text="What color do you see?",
        response_text="It is red!",
    )
    assert state.explored_angle_ids == ["observation"]
    assert len(state.angle_records) == 1
    assert state.angle_records[0].angle_id == "observation"
    assert state.angle_records[0].turn_index == 1


def test_discovery_session_state_record_multiple_angles():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )
    state.record_angle(1, "observation", "Q1", "R1")
    state.record_angle(2, "comparison", "Q2", "R2")
    assert state.explored_angle_ids == ["observation", "comparison"]
    assert state.angle_records[1].angle_id == "comparison"


def test_build_attribute_debug_includes_angle_fields():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=6)
    state.record_angle(1, "observation", "Q1", "R1")
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="test",
    )
    assert debug["state"]["explored_angle_ids"] == ["observation"]
    assert len(debug["state"]["angle_records"]) == 1
    assert debug["state"]["angle_records"][0]["angle_id"] == "observation"
```

### Step 3: Run tests

```bash
pytest tests/test_attribute_activity_pipeline.py -v
```

Expected: All existing tests + new tests PASS.

### Step 4: Commit

```bash
git add attribute_activity.py tests/test_attribute_activity_pipeline.py
git commit -m "feat: add angle coverage tracking to DiscoverySessionState"
```

---

## Task 4: Prompt Injection in HTTP Layer

**Files:**
- Modify: `paixueji_app.py`

### Step 1: Add import

At the top of `paixueji_app.py`, add to the `from stream import (...)` block:

```python
select_next_angle,
```

### Step 2: Add helper function for angle-aware prompt

Add near the top of `paixueji_app.py` (after `_strip_activity_markers`):

```python
def _build_angle_aware_guide(
    attribute_label: str,
    activity_target: str,
    sensory_safety_rules: str,
    selected_angle: dict,
    explored_angle_ids: list[str],
    turn_count: int,
) -> str:
    """Build the attribute response guide with angle coverage injected.

    This replaces the static ATTRIBUTE_RESPONSE_GUIDE with a dynamic,
    angle-aware version that tells the model which cognitive direction
    to use for this turn and which angles have already been covered.
    """
    angle_id = selected_angle["angle_id"]
    description = selected_angle["description"]
    response_hint = selected_angle["response_hint"].format(
        attribute_label=attribute_label, object_name="{object_name}"
    )
    question_hint = selected_angle["question_hint"].format(
        attribute_label=attribute_label, object_name="{object_name}"
    )
    example = selected_angle["example"].format(
        attribute_label=attribute_label, object_name="{object_name}"
    )

    used_angles = ", ".join(explored_angle_ids) if explored_angle_ids else "(none yet)"

    used_angles_with_examples = []
    for uid in explored_angle_ids:
        # Find the angle definition to show its example
        for pool in EXPLORATION_ANGLES.values():
            for a in pool:
                if a["angle_id"] == uid:
                    ex = a["example"].format(attribute_label=attribute_label, object_name="{object_name}")
                    used_angles_with_examples.append(f"- {uid}: {ex}")
                    break
    used_angles_block = "\n".join(used_angles_with_examples) if used_angles_with_examples else "(none yet)"

    return f"""{sensory_safety_rules}

[CONVERSATION COVERAGE]
Attribute: {attribute_label}
Turns explored: {turn_count}
Angles already used: {used_angles}

[NEXT SUGGESTED ANGLE: {angle_id}]
{description}

For this turn, try using the {angle_id} angle:
- Your RESPONSE should: {response_hint}
- Your FOLLOW-UP QUESTION should: {question_hint}
- Example of a good question: "{example}"

Already-used angles (try something different if possible):
{used_angles_block}

TRANSITION SIGNAL for [ACTIVITY_READY]:
1. one child-facing question
2. then on a new line: [ACTIVITY_READY]
3. then on a new line: REASON: <1-sentence with direct child quote>

ANTI-PATTERNS — NEVER produce these:
- "What {attribute_label} is it?" — quiz
- "Do you know what {attribute_label} it has?" — quiz with wrapper
- "What else can you tell me about it?" — too vague
- "Let us look at its {attribute_label}!" — forced redirect
- "That is nice, but..." then question about {attribute_label} — ignoring child
- "Great! Now we can start an activity!" — mechanical announcement
- Adding [ACTIVITY_READY] after just one shallow exchange — premature handoff
- Switching topics on a single casual mention — too sensitive
- Re-phrasing a question from an already-used angle
"""
```

Also add the import for `EXPLORATION_ANGLES`:

```python
from stream import (
    # ... existing imports ...
    select_next_angle,
    EXPLORATION_ANGLES,
)
```

### Step 3: Modify `stream_attribute_activity` generator

In the `stream_attribute_activity()` async generator inside `paixueji_app.py` (around line 1396), replace the soft_guide construction block (lines 1407-1413):

**OLD:**
```python
# Build response guide BEFORE response generator.
# The topic is already correct (switch applied above if needed).
soft_guide = paixueji_prompts.get_prompts()["attribute_response_guide"].format(
    attribute_label=attribute_label,
    activity_target=activity_target,
    sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
)
```

**NEW:**
```python
# Determine dimension and select next angle (CARES Phase 0)
dimension = assistant.attribute_state.profile.attribute_id.split(".")[0]
selected_angle = select_next_angle(
    explored_angle_ids=assistant.attribute_state.explored_angle_ids,
    dimension=dimension,
    interest_score=0,  # Phase 0: no scoring yet; Phase 1 will pass real score
)
assistant.attribute_state.current_angle_id = selected_angle["angle_id"]

# Build angle-aware response guide
soft_guide = _build_angle_aware_guide(
    attribute_label=attribute_label,
    activity_target=activity_target,
    sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
    selected_angle=selected_angle,
    explored_angle_ids=assistant.attribute_state.explored_angle_ids,
    turn_count=assistant.attribute_state.turn_count,
)
```

### Step 4: Record angle after turn completes

At the end of `stream_attribute_activity()`, after `combined_response` is built (around line 1617), add angle recording before the debug builder:

```python
# Record angle coverage for this turn (CARES Phase 0)
if assistant.attribute_state.current_angle_id:
    assistant.attribute_state.record_angle(
        turn_index=assistant.attribute_state.turn_count,
        angle_id=assistant.attribute_state.current_angle_id,
        question_text=full_followup,
        response_text=full_response,
    )
```

Place this right after:
```python
combined_response = (full_response + " " + full_followup).strip()
```

And before:
```python
attribute_debug = build_attribute_debug(...)
```

### Step 5: Run existing attribute lane tests

```bash
pytest tests/test_attribute_activity_api.py tests/test_attribute_discovery_pipeline.py tests/test_attribute_switching.py -v
```

Expected: All tests PASS (Phase 0 is additive; no behavior removed).

### Step 6: Commit

```bash
git add paixueji_app.py
git commit -m "feat: inject angle-aware prompts and record angle coverage per turn"
```

---

## Task 5: Self-Review

Run this checklist before declaring done:

### Spec Coverage

| Design Doc Requirement | Task | Status |
|------------------------|------|--------|
| 实现 `stream/exploration_angles.py`（维度级角度池定义） | Task 1 | ✅ |
| 在 `DiscoverySessionState` 中新增 `explored_angle_ids` 和 `angle_records` | Task 3 | ✅ |
| 实现 `select_next_angle` 角度选择逻辑 | Task 1 | ✅ |
| 在 `stream_attribute_activity` 中接入角度选择 + 记录 | Task 4 | ✅ |
| 更新 `ATTRIBUTE_RESPONSE_GUIDE` 为角度感知版本 | Task 4 | ✅ |
| 单元测试：模拟 5 轮同属性对话，验证角度不重复 | Task 1 | ✅ |

### Placeholder Scan

- [ ] No "TBD", "TODO", "implement later" in plan → verified
- [ ] No vague "add appropriate error handling" → verified
- [ ] All code blocks contain complete, runnable code → verified
- [ ] Exact file paths in every step → verified

### Type Consistency

- [ ] `select_next_angle` signature: `(list[str], str, float=0) -> dict` — consistent everywhere
- [ ] `AngleCoverageRecord` fields: `angle_id`, `turn_index`, `question_text`, `response_text` — consistent
- [ ] `DiscoverySessionState` new fields: `explored_angle_ids`, `angle_records`, `current_angle_id` — consistent
- [ ] `_build_angle_aware_guide` parameters match usage site — verified

### Regression Check

- [ ] `turn_count >= 3` check still exists (not removed until Phase 3)
- [ ] Quote validation still exists (not removed until Phase 3)
- [ ] `[ACTIVITY_READY]` detection unchanged
- [ ] Topic switch detector untouched
- [ ] Activity matching (`get_activity_for_attribute`) untouched

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-cares-phase0-conversation-angle-coverage.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Use `superpowers:subagent-driven-development` skill.

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans` skill, batch execution with checkpoints for review.

**Which approach?**
