# Unify Curiosity Prompt and Follow-up Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the attribute-specific curiosity prompt (2 beats), make all pipelines use the single 3-beat curiosity prompt, and unify the follow-up rules between ordinary and attribute pipelines.

**Architecture:** The attribute pipeline currently maintains a separate 2-beat `CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT` and a narrower `INTENTS_WITHOUT_FOLLOWUP` set. We collapse both: one curiosity prompt everywhere, one shared follow-up rule set imported by both pipelines.

**Tech Stack:** Python 3.12, pytest, Gemini/Vertex AI SDK

---

## File Structure

| File | Responsibility |
|------|---------------|
| `paixueji_prompts.py` | Prompt definitions. Delete `CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT` and its dict entry. |
| `stream/response_generators.py` | `generate_attribute_activation_response_stream`. Remove dead attribute-prompt lookup. |
| `paixueji_app.py` | Flask SSE endpoint. Expand `INTENTS_WITHOUT_FOLLOWUP`, import shared constant from graph, clean `response_text` passthrough. |
| `graph.py` | LangGraph nodes. Extract `INTENTS_WITHOUT_FOLLOWUP` as a module-level constant for sharing. |
| `tests/test_attribute_discovery_pipeline.py` | Tests for attribute pipeline. Update assertions that assume old split-prompt behavior and old follow-up rules. |
| `tests/test_overseas_algo_simple_edits.py` | Regression tests. Remove test that asserts `curiosity_attribute_response_prompt` exists. |

---

## Task 1: Extract Shared Follow-up Constant in `graph.py`

**Files:**
- Modify: `graph.py`

- [ ] **Step 1: Add `INTENTS_WITHOUT_FOLLOWUP` constant near the top of `graph.py`**

Find the imports section (after the existing imports, before function definitions). Add:

```python
# Intents that do NOT receive a follow-up question in the response stream.
# Both ordinary and attribute pipelines use this set.
INTENTS_WITHOUT_FOLLOWUP = {
    "curiosity",
    "concept_confusion",
    "clarifying_idk",
    "clarifying_wrong",
    "clarifying_constraint",
    "play",
    "emotional",
    "avoidance",
    "boundary",
    "action",
}
```

This documents the rule that is currently implicit across 10 separate node functions.

---

## Task 2: Delete `CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT` from Prompts Module

**Files:**
- Modify: `paixueji_prompts.py`

- [ ] **Step 1: Delete the prompt definition**

Remove lines ~1119-1172, the entire `CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT` variable.

- [ ] **Step 2: Delete the dict entry**

In the `get_prompts()` return dict (around line 2112), delete this line:

```python
        'curiosity_attribute_response_prompt': CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT,
```

- [ ] **Step 3: Run existing prompt tests**

```bash
pytest tests/test_attribute_discovery_pipeline.py -v
```

Expected: Some tests fail because they still reference the deleted prompt. We fix those in Task 5.

---

## Task 3: Unify Follow-up Rules in Attribute Pipeline

**Files:**
- Modify: `paixueji_app.py`

- [ ] **Step 1: Import shared constant and replace local definition**

At the top of `paixueji_app.py` where `INTENTS_WITHOUT_FOLLOWUP` is currently defined (line ~55), replace:

**Before:**
```python
# Intents that do not receive a follow-up question in the attribute activity stream.
# Defined at module level so tests can import it directly.
INTENTS_WITHOUT_FOLLOWUP = {"play", "emotional"}
```

**After:**
```python
# Intents that do not receive a follow-up question.
# Shared with ordinary pipeline (graph.py) — keep in sync.
from graph import INTENTS_WITHOUT_FOLLOWUP
```

- [ ] **Step 2: Clean up curiosity-specific `response_text` passthrough**

In `paixueji_app.py`, inside `stream_attribute_activity()` (around line 1363), find:

```python
                                response_text=full_response if intent_type_lower == "curiosity" else "",
```

Replace with:

```python
                                response_text="",
```

Since `curiosity` is now in `INTENTS_WITHOUT_FOLLOWUP`, the attribute pipeline will never reach this `ask_followup_question_stream` call for a `curiosity` intent. The parameter still exists for other callers, but this conditional branch is dead.

---

## Task 4: Remove Dead Attribute-Prompt Lookup in Response Generator

**Files:**
- Modify: `stream/response_generators.py`

- [ ] **Step 1: Delete the attribute-prompt key lookup**

In `generate_attribute_activation_response_stream` (around line 252-257), replace:

**Before:**
```python
    prompts = paixueji_prompts.get_prompts()
    intent_lower = intent_type.lower()
    # Prefer attribute-specific prompt when available (attribute pipeline only)
    attr_prompt_key = f"{intent_lower}_attribute_response_prompt"
    prompt_key = f"{intent_lower}_intent_prompt"
    intent_template = prompts.get(attr_prompt_key) or prompts.get(prompt_key, "")
```

**After:**
```python
    prompts = paixueji_prompts.get_prompts()
    intent_lower = intent_type.lower()
    prompt_key = f"{intent_lower}_intent_prompt"
    intent_template = prompts.get(prompt_key, "")
```

Since `curiosity_attribute_response_prompt` was the only attribute-specific prompt, this lookup always misses after Task 2. Clean it up.

---

## Task 5: Update Tests

**Files:**
- Modify: `tests/test_attribute_discovery_pipeline.py`
- Modify: `tests/test_overseas_algo_simple_edits.py`

- [ ] **Step 1: Delete test for deleted prompt in `test_attribute_discovery_pipeline.py`**

Remove the entire function `test_curiosity_attribute_response_prompt_exists()` (lines 163-170).

- [ ] **Step 2: Update `test_curiosity_uses_attribute_prompt_in_pipeline`**

In `tests/test_attribute_discovery_pipeline.py`, update the test starting at line 173.

**Before:**
```python
@pytest.mark.asyncio
async def test_curiosity_uses_attribute_prompt_in_pipeline(monkeypatch):
    prompts = {
        "curiosity_intent_prompt": "INTENT_PROMPT",
        "curiosity_attribute_response_prompt": "ATTR_PROMPT",
        "attribute_response_hint": "HINT: {attribute_label}",
    }
```

**After:**
```python
@pytest.mark.asyncio
async def test_curiosity_uses_intent_prompt_in_pipeline(monkeypatch):
    prompts = {
        "curiosity_intent_prompt": "INTENT_PROMPT",
        "attribute_response_hint": "HINT: {attribute_label}",
    }
```

And update the assertion at line 222:

**Before:**
```python
    assert "ATTR_PROMPT" in contents_text
    assert "INTENT_PROMPT" not in contents_text
```

**After:**
```python
    assert "INTENT_PROMPT" in contents_text
```

- [ ] **Step 3: Update `test_intent_followup_branching_logic`**

In `tests/test_attribute_discovery_pipeline.py` (line 309-315), update the assertion about `curiosity`:

**Before:**
```python
def test_intent_followup_branching_logic():
    """Verify which intents get follow-up and which don't."""
    assert "play" in INTENTS_WITHOUT_FOLLOWUP
    assert "emotional" in INTENTS_WITHOUT_FOLLOWUP
    assert "curiosity" not in INTENTS_WITHOUT_FOLLOWUP
    assert "correct_answer" not in INTENTS_WITHOUT_FOLLOWUP
    assert "informative" not in INTENTS_WITHOUT_FOLLOWUP
```

**After:**
```python
def test_intent_followup_branching_logic():
    """Verify which intents get follow-up and which don't."""
    assert "play" in INTENTS_WITHOUT_FOLLOWUP
    assert "emotional" in INTENTS_WITHOUT_FOLLOWUP
    assert "curiosity" in INTENTS_WITHOUT_FOLLOWUP
    assert "concept_confusion" in INTENTS_WITHOUT_FOLLOWUP
    assert "clarifying_idk" in INTENTS_WITHOUT_FOLLOWUP
    assert "correct_answer" not in INTENTS_WITHOUT_FOLLOWUP
    assert "informative" not in INTENTS_WITHOUT_FOLLOWUP
```

- [ ] **Step 4: Update or delete overseas algo test**

In `tests/test_overseas_algo_simple_edits.py` (lines 10-17), the test asserts `curiosity_attribute_response_prompt` exists. Since we deleted it, update the test to assert on the unified prompt instead.

**Before:**
```python
def test_curiosity_beat_2_anchor_constraint():
    """CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT BEAT 2 must amplify the child's specific question."""
    prompts = pp.get_prompts()
    text = prompts.get("curiosity_attribute_response_prompt", "")
    # The ANCHOR CHECK must contain the strong constraint language
    assert "Your WOW detail MUST amplify the answer to *that question*" in text, (
        "CURIOSITY BEAT 2 anchor constraint missing"
    )
```

**After:**
```python
def test_curiosity_beat_2_anchor_constraint():
    """CURIOSITY_INTENT_PROMPT BEAT 2 must amplify the child's specific question."""
    prompts = pp.get_prompts()
    text = prompts.get("curiosity_intent_prompt", "")
    # The ANCHOR CHECK must contain the strong constraint language
    assert "Your WOW detail MUST amplify the answer to *that question*" in text, (
        "CURIOSITY BEAT 2 anchor constraint missing"
    )
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/test_attribute_discovery_pipeline.py tests/test_overseas_algo_simple_edits.py -v
```

Expected: All tests pass.

---

## Task 6: Full Test Suite Verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass. Any failures are due to the changes above — fix before proceeding.

- [ ] **Step 2: Verify no stale references**

```bash
grep -rn "curiosity_attribute_response_prompt" --include="*.py" .
```

Expected: No matches (except possibly in `.pyc` cache or git history).

---

## Self-Review Checklist

1. **Spec coverage:**
   - [x] Delete `CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT` — Task 2
   - [x] Unify follow-up rules — Tasks 1 + 3
   - [x] Clean up dead lookup in response_generators — Task 4
   - [x] Update tests — Task 5

2. **Placeholder scan:** No TBD, TODO, or "implement later" in the plan above.

3. **Type consistency:** All function signatures and variable names match the current codebase.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-08-unify-curiosity-prompt-followup.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review

Which approach?
