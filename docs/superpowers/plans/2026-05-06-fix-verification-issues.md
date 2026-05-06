# Fix Verification Issues — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 4 issues discovered in the overseas algorithm verification report (`docs/verification/overseas-algo-verification-2026-05-06-143241.md`).

**Architecture:** Four independent prompt/code fixes across `paixueji_prompts.py`, `hook_types.json`, `stream/response_generators.py`, and `stream/question_generators.py`. Each fix is self-contained and can be committed separately.

**Tech Stack:** Python, Gemini API, LangGraph, pytest

---

## File Map

| File | Responsibility | Changes |
|------|---------------|---------|
| `hook_types.json` | Hook type configuration | Rewrite touch-inviting example in 细节发现 |
| `paixueji_prompts.py` | All LLM prompts | Add safety rules placeholder to INTRODUCTION_PROMPT; fix contradictory concept confusion instruction; make trusted-grown-up mandatory in emotional prompt |
| `stream/question_generators.py` | Question stream generators | Pass sensory_safety_rules into introduction prompt format call |
| `stream/response_generators.py` | Intent response generator | Add character_profile parameter and pass it to format call |
| `graph.py` | LangGraph node definitions | Pass character_profile from node_social to generator |
| `tests/test_overseas_algo_*.py` | Existing verification tests | Add/update assertions for fixed behaviors |

---

## Task 1: Fix 细节发现 Hook Example — Remove Touch Invitation

**Files:**
- Modify: `hook_types.json:60-69`
- Test: `tests/test_hook_types_safety.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_hook_types_safety.py`:

```python
import json
import pytest


def load_hook_types():
    with open("hook_types.json", encoding="utf-8") as f:
        return json.load(f)


def test_detail_discovery_no_touch_invitation():
    """细节发现 hook examples must not invite physical touch."""
    hooks = load_hook_types()
    detail = hooks["细节发现"]
    for ex in detail["examples"]:
        assert "touch" not in ex.lower(), f"Example invites touch: {ex}"
        assert "feel" not in ex.lower() or "look" in ex.lower(), f"Example may invite touch: {ex}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_hook_types_safety.py -v
```

Expected: FAIL with `AssertionError: Example invites touch: The petals feel so soft, don't they? Did you touch it?`

- [ ] **Step 3: Fix the example in hook_types.json**

In `hook_types.json`, replace line 62:

```json
      "The petals feel so soft, don't they? Did you touch it?",
```

with:

```json
      "Look at how the light catches its fur — does it look shiny or matte?",
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_hook_types_safety.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hook_types.json tests/test_hook_types_safety.py
git commit -m "fix: remove touch-inviting example from 细节发现 hook"
```

---

## Task 2: Inject SENSORY_SAFETY_RULES into Introduction Prompt

**Files:**
- Modify: `paixueji_prompts.py:265-320`
- Modify: `stream/question_generators.py:65-98`
- Test: `tests/test_intro_safety_rules.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_intro_safety_rules.py`:

```python
import paixueji_prompts


def test_introduction_prompt_has_sensory_safety_placeholder():
    assert "{sensory_safety_rules}" in paixueji_prompts.INTRODUCTION_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_intro_safety_rules.py -v
```

Expected: FAIL with `AssertionError`

- [ ] **Step 3: Add placeholder to INTRODUCTION_PROMPT**

In `paixueji_prompts.py`, add the safety rules placeholder inside `INTRODUCTION_PROMPT`. Best location: right after the RULES section that starts around line 241, before the EXAMPLE SCRIPTS. Insert after line 253 (the last rule line):

```python
- Sound like an older-kid buddy, not a teacher.

{sensory_safety_rules}

EXAMPLE SCRIPTS:
```

Full context to replace (lines 251-254 in INTRODUCTION_PROMPT):

```
- Age {age}: very short sentences, easy words, warm buddy tone.
- Sound like an older-kid buddy exploring alongside the child — not a teacher.

EXAMPLE SCRIPTS:
```

Replace with:

```
- Age {age}: very short sentences, easy words, warm buddy tone.
- Sound like an older-kid buddy exploring alongside the child — not a teacher.

{sensory_safety_rules}

EXAMPLE SCRIPTS:
```

- [ ] **Step 4: Pass sensory_safety_rules in ask_introduction_question_stream**

In `stream/question_generators.py`, modify both `.format()` calls for `introduction_prompt`.

First call (around line 65-71, anchor_bridge branch):

```python
        base_prompt = prompts["introduction_prompt"].format(
            object_name=surface_object_name or object_name,
            age_prompt=age_prompt,
            age=age,
            hook_type_section=hook_type_section,
            knowledge_context=knowledge_context,
            sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
        )
```

Second call (around line 92-98, default branch):

```python
        introduction_prompt = prompts['introduction_prompt'].format(
            object_name=object_name,
            age_prompt=age_prompt,
            age=age,
            hook_type_section=hook_type_section,
            knowledge_context=knowledge_context,
            sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
        )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_intro_safety_rules.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add paixueji_prompts.py stream/question_generators.py tests/test_intro_safety_rules.py
git commit -m "fix: inject SENSORY_SAFETY_RULES into introduction prompt"
```

---

## Task 3: Fix Contradictory Concept Confusion Prompt

**Files:**
- Modify: `paixueji_prompts.py:1926-1939`
- Test: `tests/test_overseas_algo_concept_confusion.py` (existing)

- [ ] **Step 1: Examine existing test**

```bash
pytest tests/test_overseas_algo_concept_confusion.py -v
```

Note the current state — it may already pass since it only checks for presence of "DO NOT RE-ASK" text.

- [ ] **Step 2: Fix contradictory prohibition line**

In `paixueji_prompts.py`, remove line 1937:

```
- Do NOT ask a different question — re-ask the one from your last response
```

Also strengthen line 1926 for clarity. Change:

```
BEAT 3 — DO NOT RE-ASK. Choose ONE of these:
```

to:

```
BEAT 3 — DO NOT RE-ASK THE SAME QUESTION FROM YOUR LAST RESPONSE. Choose ONE of these:
```

- [ ] **Step 3: Update existing test if needed**

Verify `tests/test_overseas_algo_concept_confusion.py` still passes. The test at line 7 asserts:

```python
assert "DO NOT RE-ASK" in text or "do not re-ask" in text.lower(), "Should add no-re-ask rule"
```

This should still pass since we kept "DO NOT RE-ASK".

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_overseas_algo_concept_confusion.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py
git commit -m "fix: remove contradictory re-ask instruction from concept confusion prompt"
```

---

## Task 4: Make Trusted-Grown-Up Mandatory in Emotional Extreme Response

**Files:**
- Modify: `paixueji_prompts.py:1671-1678`
- Test: `tests/test_overseas_algo_emotional.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_overseas_algo_emotional.py`:

```python
import paixueji_prompts


def test_emotional_extreme_prompt_requires_trusted_grownup():
    """Type C emotional response MUST suggest talking to a trusted grown-up."""
    prompt = paixueji_prompts.EMOTIONAL_INTENT_PROMPT
    # Check that the prompt uses mandatory language for the trusted person suggestion
    assert "MUST include" in prompt or "both of these" in prompt, (
        "Prompt should make trusted-grown-up suggestion mandatory, not optional"
    )
    assert "grown-up you trust" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_emotional.py -v
```

Expected: FAIL — current prompt lists suggestions as optional bullet points, not mandatory.

- [ ] **Step 3: Restructure BEAT 2 for Type C**

In `paixueji_prompts.py`, replace lines 1671-1678:

```
BEAT 2 — for C (REAL-WORLD SUPPORT):
  - Gentle grounding or permission to stop: "We can pause here."
  - Suggest reaching out to a trusted person: "This might be a good time to talk to a grown-up you trust."
  TONE: Calm, simple, non-dramatic.
  PROHIBITIONS:
  - Do NOT try to fix the emotion within the system
  - Do NOT continue the {object_name} exploration
  - Do NOT ask any question
```

with:

```
BEAT 2 — for C (REAL-WORLD SUPPORT): You MUST include BOTH of these sentences:
  1. Gentle grounding or permission to stop: "We can pause here."
  2. Suggest reaching out to a trusted person: "This might be a good time to talk to a grown-up you trust."
  TONE: Calm, simple, non-dramatic.
  PROHIBITIONS:
  - Do NOT try to fix the emotion within the system
  - Do NOT continue the {object_name} exploration
  - Do NOT ask any question
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_emotional.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_emotional.py
git commit -m "fix: make trusted-grown-up suggestion mandatory in emotional extreme prompt"
```

---

## Task 5: Fix Social Intent Character Profile Parameter Passing

**Files:**
- Modify: `stream/response_generators.py:22-92`
- Modify: `graph.py:1440-1452`
- Test: `tests/test_social_intent_character_profile.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_social_intent_character_profile.py`:

```python
import inspect
from stream.response_generators import generate_intent_response_stream


def test_generate_intent_response_stream_accepts_character_profile():
    sig = inspect.signature(generate_intent_response_stream)
    assert "character_profile" in sig.parameters, (
        "generate_intent_response_stream must accept character_profile parameter"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_social_intent_character_profile.py -v
```

Expected: FAIL with `AssertionError: generate_intent_response_stream must accept character_profile parameter`

- [ ] **Step 3: Add character_profile parameter to generate_intent_response_stream**

In `stream/response_generators.py`, modify the function signature (line 22-36):

```python
async def generate_intent_response_stream(
    intent_type: str,
    messages: list[dict],
    child_answer: str,
    object_name: str,
    age: int,
    age_prompt: str,
    last_model_response: str,
    config: dict = None,
    client: genai.Client = None,
    knowledge_context: str = "",
    resolution_guardrails: str = "",
    surface_only_mode: bool = False,
    surface_object_name: str = "",
    character_profile: str = "",
) -> AsyncGenerator[tuple[str, TokenUsage | None, str], None]:
```

- [ ] **Step 4: Pass character_profile in the .format() call**

In `stream/response_generators.py`, modify the `.format()` call (lines 75-82):

```python
        prompt = prompt_template.format(
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt=age_prompt,
            last_model_response=last_model_response,
            knowledge_context=knowledge_context,
            character_profile=character_profile,
        )
```

- [ ] **Step 5: Pass character_profile from node_social**

In `graph.py`, modify the `node_social` call (around line 1440-1452). Add `character_profile=paixueji_prompts.CHARACTER_PROFILE` as the last argument:

```python
    generator = generate_intent_response_stream(
        intent_type="social",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
        knowledge_context=_grounding_context_for_intent(state, "social"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
        character_profile=paixueji_prompts.CHARACTER_PROFILE,
    )
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/test_social_intent_character_profile.py -v
```

Expected: PASS

- [ ] **Step 7: Run full test suite to catch regressions**

```bash
pytest tests/ -v
```

Expected: All tests pass. If any other callers of `generate_intent_response_stream` break due to the new parameter, fix them by adding `character_profile=""` (the default already handles this, but explicit is safer if there are positional arg issues).

- [ ] **Step 8: Commit**

```bash
git add stream/response_generators.py graph.py tests/test_social_intent_character_profile.py
git commit -m "fix: pass character_profile through generate_intent_response_stream for social intent"
```

---

## Self-Review

### 1. Spec Coverage

| Verification Issue | Task | Implementation |
|---|---|---|
| SAFETY — 细节发现 invites touch | Task 1 + Task 2 | Rewrote hook example; injected safety rules into intro prompt |
| Concept confusion re-asks | Task 3 | Removed contradictory prohibition; strengthened "DO NOT RE-ASK" |
| Emotional extreme lacks trusted-grown-up | Task 4 | Made both sentences mandatory with "MUST include BOTH" |
| Social intent character_profile gap | Task 5 | Added parameter, passed through format call and node_social |

All 4 issues are covered. No gaps.

### 2. Placeholder Scan

- No "TBD", "TODO", "implement later" — all steps contain actual code
- No vague instructions like "add appropriate error handling"
- No "Similar to Task N" — each task is self-contained
- Every code-changing step shows the exact code to write

### 3. Type Consistency

- `character_profile: str = ""` added to function signature — matches usage in `.format(character_profile=character_profile)`
- `paixueji_prompts.CHARACTER_PROFILE` is a string constant — type matches
- All format call keywords match template placeholders

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-06-fix-verification-issues.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
