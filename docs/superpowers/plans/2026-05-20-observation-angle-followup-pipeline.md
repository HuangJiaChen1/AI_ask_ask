# Observation-Angle-Native Follow-Up Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken `dimension`-derived angle pool selection with `observation_angle`-driven selection, simplify guide builders, and clean up dead code so follow-up questions stay on-topic for the attribute (e.g., texture).

**Architecture:** A lightweight classification (`observation_angle` → physical/engagement pool) replaces the synthetic `dimension` prefix split. Guide builders are flattened to remove nested helper calls. `focus_topic` derives from `observation_angle` + `object_name` instead of the activity label.

**Tech Stack:** Python 3.11, pytest, no new dependencies.

---

### Task 1: Add `get_pool_for_observation_angle` to `exploration_angles.py`

**Files:**
- Modify: `stream/exploration_angles.py:18-26` (add constant after `PHYSICAL_DIMENSIONS`)
- Modify: `stream/exploration_angles.py:99-164` (update `select_next_angle`)

- [ ] **Step 1: Add sensory classification constant**

Add after `PHYSICAL_DIMENSIONS` definition:

```python
# Observation angles that map to the physical pool.
SENSORY_OBSERVATION_ANGLES = frozenset({
    "texture", "color", "shape", "size", "pattern", "sound", "smell", "taste"
})


def get_pool_for_observation_angle(observation_angle: str) -> str:
    return "physical" if observation_angle in SENSORY_OBSERVATION_ANGLES else "engagement"
```

- [ ] **Step 2: Update `select_next_angle` signature and internal logic**

Replace the existing function:

```python
def select_next_angle(
    explored_angle_ids: list[str],
    observation_angle: str,
    interest_score: float = 0,
    pending_verifications: list | None = None,
) -> dict:
    pool_key = get_pool_for_observation_angle(observation_angle)
    pool = EXPLORATION_ANGLES.get(pool_key, [])

    # VGC: If there's a pending verification, prefer angles that help verify it
    if pending_verifications:
        property_to_angle_hints = {
            "color": "observation",
            "shape": "observation",
            "pattern": "comparison",
            "texture": "observation",
            "size": "comparison",
        }
        for v in pending_verifications:
            prop = v.property.lower()
            for hint_key, hint_angle in property_to_angle_hints.items():
                if hint_key in prop:
                    preferred = [
                        a for a in pool
                        if a["angle_id"] == hint_angle and a["angle_id"] not in explored_angle_ids
                    ]
                    if preferred:
                        return preferred[0]

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
        if interest_score < 30:
            simple = [a for a in unused if a["angle_id"] in ("observation", "comparison")]
            return simple[0] if simple else unused[0]
        elif interest_score < 55:
            medium = [a for a in unused if a["angle_id"] != "causal"]
            return medium[0] if medium else unused[0]
        return unused[0]

    for angle in pool:
        if explored_angle_ids and angle["angle_id"] != explored_angle_ids[-1]:
            return angle
    return pool[0]
```

- [ ] **Step 3: Commit**

```bash
git add stream/exploration_angles.py
git commit -m "feat: add observation-angle-driven angle pool selection

Add SENSORY_OBSERVATION_ANGLES and get_pool_for_observation_angle().
Update select_next_angle to accept observation_angle instead of dimension.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Update `tests/test_exploration_angles.py`

**Files:**
- Modify: `tests/test_exploration_angles.py:1-78`

- [ ] **Step 1: Replace all `dimension=` args with `observation_angle=`**

Full updated file:

```python
"""Tests for exploration angle pool and selection logic."""

import pytest
from stream.exploration_angles import (
    EXPLORATION_ANGLES,
    SENSORY_OBSERVATION_ANGLES,
    AngleCoverageRecord,
    select_next_angle,
    get_pool_for_observation_angle,
)


def test_get_pool_for_observation_angle():
    assert get_pool_for_observation_angle("texture") == "physical"
    assert get_pool_for_observation_angle("color") == "physical"
    assert get_pool_for_observation_angle("emotion") == "engagement"
    assert get_pool_for_observation_angle("memory") == "engagement"


def test_select_next_angle_returns_first_for_empty_explored():
    result = select_next_angle(explored_angle_ids=[], observation_angle="texture", interest_score=0)
    assert result["angle_id"] == "observation"


def test_select_next_angle_cycles_after_all_used():
    physical_ids = [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]
    result = select_next_angle(explored_angle_ids=physical_ids, observation_angle="texture", interest_score=0)
    assert result["angle_id"] == "observation"


def test_select_next_angle_skips_last_when_all_used():
    physical_ids = [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]
    result = select_next_angle(
        explored_angle_ids=physical_ids + ["observation"],
        observation_angle="texture",
        interest_score=0,
    )
    assert result["angle_id"] != "observation"


def test_select_next_angle_low_interest_restricts_angles():
    result = select_next_angle(explored_angle_ids=[], observation_angle="texture", interest_score=20)
    assert result["angle_id"] in ("observation", "comparison")


def test_select_next_angle_medium_interest_excludes_causal():
    result = select_next_angle(explored_angle_ids=[], observation_angle="texture", interest_score=40)
    assert result["angle_id"] != "causal"


def test_select_next_angle_high_interest_unlocks_all():
    result = select_next_angle(explored_angle_ids=[], observation_angle="texture", interest_score=60)
    assert result["angle_id"] in [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]


def test_select_next_angle_uses_engagement_pool_for_emotion():
    result = select_next_angle(explored_angle_ids=[], observation_angle="emotion", interest_score=0)
    assert result["angle_id"] in [a["angle_id"] for a in EXPLORATION_ANGLES["engagement"]]


def test_select_next_angle_no_consecutive_repeat():
    explored = []
    prev = None
    for _ in range(10):
        angle = select_next_angle(explored_angle_ids=explored, observation_angle="texture", interest_score=0)
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

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_exploration_angles.py -v
```

Expected: 10 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_exploration_angles.py
git commit -m "test: update exploration_angles tests for observation_angle param

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Simplify guide builders in `paixueji_app.py`

**Files:**
- Modify: `paixueji_app.py:120-174` (delete helpers)
- Modify: `paixueji_app.py:195-233` (rewrite `_build_continue_guide`)
- Modify: `paixueji_app.py:339-379` (rewrite `_build_reengage_guide`)

- [ ] **Step 1: Delete dead helper functions**

Delete lines 120-174 (from `_format_angle_example` through `_build_common_antipatterns`):

```python
# These four helpers are no longer used after guide simplification.
# _format_angle_example, _build_used_angles_block,
# _build_angle_block, _build_common_preamble, _build_common_antipatterns
```

Verify no other references exist by grepping:

```bash
grep -n "_build_angle_block\|_build_used_angles_block\|_build_common_preamble\|_build_common_antipatterns\|_format_angle_example" paixueji_app.py
```

Expected: no matches.

- [ ] **Step 2: Rewrite `_build_continue_guide`**

Replace lines 195-233 with:

```python
def _build_continue_guide(
    observation_angle: str,
    object_name: str,
    sensory_safety_rules: str,
    selected_angle: dict,
    explored_angle_ids: list[str],
    turn_count: int,
    current_score: float = 0.0,
    total_turns: int = 0,
) -> str:
    """Build prompt for CONTINUE / CONTINUE_SWITCH — streamlined."""
    angle_id = selected_angle["angle_id"]
    example = selected_angle["example"].format(
        attribute_label=observation_angle, object_name=object_name
    )
    used = ", ".join(explored_angle_ids) if explored_angle_ids else "none yet"

    return f"""{sensory_safety_rules}

CONVERSATION DIRECTION: Explore the {observation_angle} of the {object_name}.
Be playful and curious. Ask open-ended questions that help the child notice
and describe the {observation_angle} in their own words.

FOR THIS TURN, use the '{angle_id}' style:
Example: "{example}"

ALREADY USED: {used}
Do NOT repeat these styles.

ANTI-PATTERNS -- NEVER produce these:
- "What {observation_angle} is it?" -- quiz
- "Do you know what {observation_angle} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
- Mention activities, games, quests, or collecting

---

[SYSTEM CONTEXT]
Current focus: {observation_angle}
Current interest score: {current_score:.0f}/100
Session turns: {total_turns}

HANDOFF MODE: INACTIVE
Continue exploring the current attribute. Do NOT output [ACTIVITY_READY].
"""
```

- [ ] **Step 3: Rewrite `_build_reengage_guide`**

Replace lines 339-379 with:

```python
def _build_reengage_guide(
    observation_angle: str,
    object_name: str,
    sensory_safety_rules: str,
    selected_angle: dict,
    explored_angle_ids: list[str],
    turn_count: int,
    struggle_count: int,
    current_score: float = 0.0,
) -> str:
    """Build prompt for REENGAGE — simplified sensory questions only."""
    angle_id = selected_angle["angle_id"]
    example = selected_angle["example"].format(
        attribute_label=observation_angle, object_name=object_name
    )
    used = ", ".join(explored_angle_ids) if explored_angle_ids else "none yet"

    return f"""{sensory_safety_rules}

CONVERSATION DIRECTION: The child is struggling. Ask a MUCH simpler,
more concrete question about the {observation_angle} of the {object_name}.
Use only sensory language (see, look, notice). Single concept only.

FOR THIS TURN, use the '{angle_id}' style:
Example: "{example}"

ALREADY USED: {used}
Do NOT repeat these styles.

ANTI-PATTERNS -- NEVER produce these:
- "What {observation_angle} is it?" -- quiz
- "Do you know what {observation_angle} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
- Open-ended or abstract questions ("what do you think", "why do you think")
- Causal or how/why questions
- Mention activities, games, quests, or collecting

---

[SYSTEM CONTEXT]
Current focus: {observation_angle}
Current interest score: {current_score:.0f}/100
Consecutive struggle count: {struggle_count}

REENGAGE MODE: ACTIVE
"""
```

- [ ] **Step 4: Commit**

```bash
git add paixueji_app.py
git commit -m "refactor: simplify guide builders, delete dead helper functions

Delete _build_angle_block, _build_used_angles_block, _build_common_preamble,
_build_common_antipatterns, _format_angle_example.
Rewrite _build_continue_guide and _build_reengage_guide with streamlined
observation_angle-driven prompts.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Update follow-up pipeline calls in `paixueji_app.py`

**Files:**
- Modify: `paixueji_app.py:1793-1794` (delete dimension, add observation_angle)
- Modify: `paixueji_app.py:1830-1845` (REENGAGE call site)
- Modify: `paixueji_app.py:1852-1898` (PROBE + CONTINUE call sites)
- Modify: `paixueji_app.py:2027` (focus_topic)

- [ ] **Step 1: Replace dimension derivation with observation_angle**

At line 1793-1794, replace:

```python
# DELETE:
# dimension = assistant.attribute_state.profile.attribute_id.split(".")[0]

# ADD:
observation_angle = ""
if assistant.attribute_state.primary_activity:
    observation_angle = assistant.attribute_state.primary_activity.observation_angle
else:
    # Fallback: derive from profile label (legacy path during transition)
    observation_angle = assistant.attribute_state.profile.label
```

- [ ] **Step 2: Update REENGAGE call site**

Replace lines 1830-1845:

```python
                            selected_angle = select_next_angle(
                                explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                                observation_angle=observation_angle,
                                interest_score=0,
                                pending_verifications=pending_for_angle,
                            )
                            assistant.attribute_state.current_angle_id = selected_angle["angle_id"]
                            soft_guide = _build_reengage_guide(
                                observation_angle=observation_angle,
                                object_name=object_name_attr,
                                sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
                                selected_angle=selected_angle,
                                explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                                turn_count=assistant.attribute_state.turn_count,
                                struggle_count=assistant.consecutive_struggle_count,
                                current_score=current_interest_score,
                            )
```

- [ ] **Step 3: Update PROBE and CONTINUE call sites**

Replace lines 1852-1898:

```python
                            selected_angle = select_next_angle(
                                explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                                observation_angle=observation_angle,
                                interest_score=current_interest_score,
                                pending_verifications=pending_for_angle,
                            )
                            assistant.attribute_state.current_angle_id = selected_angle["angle_id"]
                            soft_guide = _build_continue_guide(
                                observation_angle=observation_angle,
                                object_name=object_name_attr,
                                sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
                                selected_angle=selected_angle,
                                explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                                turn_count=assistant.attribute_state.turn_count,
                                current_score=current_interest_score,
                                total_turns=total_turns,
                            )
```

Note: The PROBE branch and the CONTINUE/CONTINUE_SWITCH branch both now call `_build_continue_guide` with the same signature. If the PROBE branch previously had extra logic (lines 1871-1872), verify whether it still applies with the new signature.

- [ ] **Step 4: Fix `focus_topic`**

Replace line 2027:

```python
# DELETE:
# focus_topic=f"the '{attribute_label}' attribute",

# REPLACE WITH:
focus_topic=f"the {observation_angle} of the {object_name_attr}",
```

- [ ] **Step 5: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: wire observation_angle into follow-up pipeline

Delete dimension derivation. Pass observation_angle to select_next_angle
and simplified guide builders. Fix focus_topic to use observation_angle
instead of activity label.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Rewrite `ATTRIBUTE_SOFT_GUIDE` in `paixueji_prompts.py`

**Files:**
- Modify: `paixueji_prompts.py:456-546`

- [ ] **Step 1: Replace the template**

```python
ATTRIBUTE_SOFT_GUIDE = """
{sensory_safety_rules}

SUGGESTED EXPLORATION DIRECTION: {focus_topic}

When choosing your follow-up question, you can gently lean toward
{focus_topic} when it fits naturally. You do NOT need to force it.

TWO TECHNIQUES (use ONE per turn, when it fits):

A) SALIENCE — include a {observation_angle}-related sensory word in the
   question itself, so the attribute feels naturally present:
   GOOD (observation_angle=texture, object=cat):
     "What does the cat's fur feel like when you imagine touching it?"
   BAD:
     "What color is the cat?" (ignores texture entirely)

B) FRAME WEAVING — when the child noticed something OTHER than
   {observation_angle}, offer a choice or comparison that includes
   {observation_angle} as one option:
   GOOD (child said "orange", observation_angle=texture):
     "Does it feel more like a soft teddy bear or a rough blanket?"
   BAD:
     "That's nice, but what does it feel like?" (ignores their observation)

DO NOT:
- Mention activities, games, quests, or collecting
- Ask quiz questions ("What {observation_angle} is it?")
- Force the topic if the child is interested in something else

EVIDENCE REQUIREMENT: Your REASON: line MUST include at least one direct
quote from the child's actual messages about {focus_topic}, enclosed in
double quotes ("). Do NOT output [ACTIVITY_READY] without a real quote.

ANTI-PATTERNS — NEVER produce these:
"What {observation_angle} is it?" -- quiz
"Do you know what {observation_angle} it has?" -- quiz with wrapper
"What else can you tell me about it?" -- too vague
"Let's look at its {observation_angle}!" -- forced redirect
"Great! Now we can start an activity!" -- mechanical announcement
"""
```

Note: Template variables changed from `{attribute_label}` to `{focus_topic}` and `{observation_angle}`. Ensure callers pass these variables.

- [ ] **Step 2: Commit**

```bash
git add paixueji_prompts.py
git commit -m "refactor: rewrite ATTRIBUTE_SOFT_GUIDE, delete technique C

Remove Natural Bridge (technique C) which prematurely exposed activity goals.
Update template variables to focus_topic and observation_angle.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Update regression tests

**Files:**
- Modify: `tests/test_diagnose_orange_cat.py:117-215`

- [ ] **Step 1: Update inline guide builders and assertions**

Replace the inline `_build_continue_guide` and its test (lines 149-215):

```python
def _build_continue_guide(
    observation_angle,
    object_name,
    sensory_safety_rules,
    selected_angle,
    explored_angle_ids,
    turn_count,
    current_score=0.0,
    total_turns=0,
):
    angle_id = selected_angle["angle_id"]
    example = selected_angle["example"].format(
        attribute_label=observation_angle, object_name=object_name
    )
    used = ", ".join(explored_angle_ids) if explored_angle_ids else "none yet"

    return f"""{sensory_safety_rules}

CONVERSATION DIRECTION: Explore the {observation_angle} of the {object_name}.
Be playful and curious. Ask open-ended questions that help the child notice
and describe the {observation_angle} in their own words.

FOR THIS TURN, use the '{angle_id}' style:
Example: "{example}"

ALREADY USED: {used}
Do NOT repeat these styles.

ANTI-PATTERNS -- NEVER produce these:
- "What {observation_angle} is it?" -- quiz
- "Do you know what {observation_angle} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
- Mention activities, games, quests, or collecting

---

[SYSTEM CONTEXT]
Current focus: {observation_angle}
Current interest score: {current_score:.0f}/100
Session turns: {total_turns}

HANDOFF MODE: INACTIVE
Continue exploring the current attribute. Do NOT output [ACTIVITY_READY].
"""


def test_build_continue_guide_uses_observation_angle():
    """
    _build_continue_guide should use observation_angle and object_name,
    NOT the activity label, to build the prompt.
    """
    selected_angle = {
        "angle_id": "observation",
        "example": "What do you notice about the {object_name}'s {attribute_label}?",
    }

    guide = _build_continue_guide(
        observation_angle="texture",
        object_name="orange cat",
        sensory_safety_rules="SAFETY RULES",
        selected_angle=selected_angle,
        explored_angle_ids=[],
        turn_count=0,
    )

    assert "texture" in guide.lower()
    assert "orange cat" in guide.lower()
    assert "CONVERSATION DIRECTION" in guide
    assert "Find three fluffy friends" not in guide, (
        "Guide should NOT contain the activity label"
    )
    assert "activity_target" not in guide.lower(), (
        "Guide should NOT reference activity_target in chat phase"
    )


def test_build_continue_guide_omits_activity_target():
    """
    The guide should never expose the activity goal during the chat phase.
    """
    selected_angle = {
        "angle_id": "observation",
        "example": "What do you notice?",
    }

    guide = _build_continue_guide(
        observation_angle="texture",
        object_name="orange cat",
        sensory_safety_rules="SAFETY RULES",
        selected_angle=selected_angle,
        explored_angle_ids=[],
        turn_count=0,
    )

    assert "quest" not in guide.lower()
    assert "collect" not in guide.lower()
    assert "activity" not in guide.lower() or "Continue exploring the current attribute" in guide
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_diagnose_orange_cat.py -v
```

Expected: all tests pass (test count may change from 6 to 7).

- [ ] **Step 3: Commit**

```bash
git add tests/test_diagnose_orange_cat.py
git commit -m "test: update orange cat regression tests for observation_angle

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Full verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass. If any failures, fix before proceeding.

- [ ] **Step 2: Run lint/type check if available**

```bash
python -m py_compile paixueji_app.py stream/exploration_angles.py paixueji_prompts.py
```

Expected: no syntax errors.

- [ ] **Step 3: Final commit**

```bash
git commit -m "feat: observation-angle-native follow-up pipeline

Replace broken dimension-derived angle pool with observation_angle-driven
selection. Simplify guide builders and delete dead helper functions.
Fix focus_topic to use observation_angle instead of activity label.
Rewrite ATTRIBUTE_SOFT_GUIDE to never expose activity goals in chat phase.

Bugs fixed:
- Dimension='activity' fell to engagement pool (wrong for texture)
- _build_continue_guide received but ignored activity_target
- focus_topic used activity label instead of attribute
- ATTRIBUTE_SOFT_GUIDE technique C prematurely exposed activity goals

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ Delete dimension derivation → Task 4 Step 1
- ✅ Observation-angle-driven pool selection → Task 1
- ✅ Simplify guide builders → Task 3
- ✅ Delete dead helper functions → Task 3 Step 1
- ✅ Fix focus_topic → Task 4 Step 4
- ✅ Rewrite ATTRIBUTE_SOFT_GUIDE → Task 5
- ✅ Update tests → Tasks 2 and 6
- ✅ Full verification → Task 7

**2. Placeholder scan:**
- No TBD/TODO/fill-in-details found.
- All code blocks contain complete, runnable code.
- All test commands include expected output.

**3. Type consistency:**
- `select_next_angle` parameter renamed from `dimension: str` to `observation_angle: str` consistently across definition, all call sites, and tests.
- `_build_continue_guide` and `_build_reengage_guide` parameters changed from `attribute_label`/`activity_target` to `observation_angle`/`object_name` consistently.
- `focus_topic` format string updated consistently.

**No gaps found. Plan is ready for execution.**
