# Remove fun_fact Dead Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surgically remove the entire `fun_fact` (Google Search grounded fun-fact generation) feature from the codebase without breaking any existing functionality.

**Architecture:** The `fun_fact` feature consists of a `stream/fun_fact.py` module, a `node_generate_fun_fact` graph node, prompt templates, state schema fields, and prompt-optimizer preview logic. None of these are wired into the active conversation flow (`node_generate_fun_fact` is defined but never `add_node`-ed to the LangGraph workflow). Removal is a pure deletion with no replacement logic.

**Tech Stack:** Python 3.13, LangGraph, Pydantic v2, Flask SSE streaming, pytest.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `stream/fun_fact.py` | Delete | Fun-fact generation module (229 lines, dead code) |
| `stream/__init__.py` | Modify | Remove re-export of `generate_fun_fact` |
| `graph.py` | Modify | Remove `PaixuejiState` fields + orphaned `node_generate_fun_fact` |
| `paixueji_prompts.py` | Modify | Remove `FUN_FACT_*` prompt constants + dict entries |
| `paixueji_app.py` | Modify | Remove fun_fact fields from state init + optimizer example |
| `schema.py` | Modify | Remove fun_fact fields from `StreamChunk` Pydantic model |
| `prompt_optimizer.py` | Modify | Remove `_run_grounding` + fun_fact preview branches |
| `trace_schema.py` | Modify | Update docstring examples |
| `trace_assembler.py` | Modify | Remove fun_fact prompts from LLM prompt list |
| `tests/*` (6 files) | Modify | Remove fun_fact fields from test state dicts |
| `tests/test_dead_code_cleanup.py` | Create | Regression test: verify zero fun_fact code references |

---

## Task 1: Remove Core Module

**Files:**
- Delete: `stream/fun_fact.py`
- Modify: `stream/__init__.py:11-12, 67, 153`

- [ ] **Step 1: Delete `stream/fun_fact.py`**

```bash
git rm stream/fun_fact.py
```

- [ ] **Step 2: Remove import and `__all__` entry from `stream/__init__.py`**

Delete the duplicate docstring lines and the import:

```python
# BEFORE (lines 11-12):
- fun_fact: Grounded fun fact generation
- fun_fact: Grounded fun fact generation

# BEFORE (line 67):
from .fun_fact import generate_fun_fact

# BEFORE (line 153):
    'generate_fun_fact',
```

After deletion the docstring should read:

```python
- validation: Intent classification logic
```

(`fun_fact` lines are immediately after `- validation:` in the current file.)

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: delete fun_fact core module"
```

---

## Task 2: Remove Graph State Fields and Orphaned Node

**Files:**
- Modify: `graph.py:173-177` (state fields)
- Modify: `graph.py:589-615` (orphaned node)

- [ ] **Step 1: Remove four fields from `PaixuejiState` TypedDict**

```python
# In graph.py, delete lines 173-177:
    # --- Fun Fact (Grounded) ---
    fun_fact: Optional[str]
    fun_fact_hook: Optional[str]
    fun_fact_question: Optional[str]
    real_facts: Optional[str]
```

- [ ] **Step 2: Delete `node_generate_fun_fact` function**

```python
# In graph.py, delete the entire function (lines 589-615):
@trace_node
async def node_generate_fun_fact(state: PaixuejiState) -> dict:
    """
    Generate grounded fun facts for the introduction using Google Search.
    Only called on the introduction path.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Generate Fun Fact for '{state['object_name']}'")

    from stream.fun_fact import generate_fun_fact

    fact_data = await generate_fun_fact(
        object_name=state["object_name"],
        age=state["age"] or 6,
        config=state["config"],
        client=state["client"],
    )

    logger.info(f"[{state['session_id']}] Node: Generate Fun Fact finished in {time.time() - start_time:.3f}s")
    return {
        "fun_fact": fact_data.get("fun_fact", ""),
        "fun_fact_hook": fact_data.get("hook", ""),
        "fun_fact_question": fact_data.get("question", ""),
        "real_facts": fact_data.get("real_facts", "")
    }
```

- [ ] **Step 3: Commit**

```bash
git add graph.py && git commit -m "chore: remove fun_fact state fields and orphaned graph node"
```

---

## Task 3: Remove Prompt Templates

**Files:**
- Modify: `paixueji_prompts.py:882-917` (constants)
- Modify: `paixueji_prompts.py:2957-2958` (dict entries)

- [ ] **Step 1: Delete `FUN_FACT_GROUNDING_PROMPT` and `FUN_FACT_STRUCTURING_PROMPT` constants**

```python
# In paixueji_prompts.py, delete the entire block (lines 882-917):
FUN_FACT_GROUNDING_PROMPT = """Research "{object_name}" for a children's education app (child age: {age}).
Category: {category}

Provide:
1. KEY FACTS: What is {object_name}? List its main characteristics, notable traits, and interesting properties. Be specific and factual.
2. FUN FACTS: Give me 3 to 5 simple, verified, amazing fun facts about "{object_name}" that would delight a {age}-year-old child.

Requirements for ALL facts:
- TRUE and verifiable
- Safe for young children
- Simple words appropriate for age {age}
- Specific and concrete (not vague generalizations)"""

FUN_FACT_STRUCTURING_PROMPT = """Format these verified facts about "{object_name}" for a children's education app (age: {age}).

RESEARCH RESULTS:
{grounded_text}

Return JSON with this exact structure:
{{
  "is_safe_for_kids": boolean (false if ANY content mentions violence/death/danger/fear),
  "real_facts": string (2-4 sentence summary of key characteristics, written for a {age}-year-old),
  "fun_facts": [
    {{
      "fun_fact": string (rewrite for a {age}-year-old, start with "Did you know..."),
      "hook": string (short excited greeting, e.g. "Wow, look at this {object_name}!"),
      "question": string (engaging follow-up question for a {age}-year-old)
    }}
  ]
}}

Requirements:
- fun_facts array should have 3-5 items
- Each fun_fact must be distinct
- No emojis anywhere
- All text must be age-appropriate for {age}-year-old"""
```

- [ ] **Step 2: Remove dict entries from `get_prompts()` return value**

```python
# In paixueji_prompts.py, delete lines 2957-2958 from the get_prompts() dict:
        'fun_fact_grounding_prompt': FUN_FACT_GROUNDING_PROMPT,
        'fun_fact_structuring_prompt': FUN_FACT_STRUCTURING_PROMPT,
```

- [ ] **Step 3: Commit**

```bash
git add paixueji_prompts.py && git commit -m "chore: remove fun_fact prompt templates"
```

---

## Task 4: Remove HTTP Layer References

**Files:**
- Modify: `paixueji_app.py:3370-3374` (state init)
- Modify: `paixueji_app.py:~4287` (optimizer example)

- [ ] **Step 1: Remove fun_fact fields from `continue_conversation` state dict**

```python
# In paixueji_app.py, delete lines 3370-3374:
                        # Fun fact (not used in continue, but required by state schema)
                        "fun_fact": "",
                        "fun_fact_hook": "",
                        "fun_fact_question": "",
                        "real_facts": "",
```

- [ ] **Step 2: Find and replace `"culprit_name": "generate_fun_fact"` example**

Search for the exact line:

```bash
grep -n '"culprit_name": "generate_fun_fact"' paixueji_app.py
```

Replace with a real node name, e.g. `"generate_intro"`:

```python
# BEFORE:
"culprit_name": "generate_fun_fact",

# AFTER:
"culprit_name": "generate_intro",
```

- [ ] **Step 3: Commit**

```bash
git add paixueji_app.py && git commit -m "chore: remove fun_fact fields from HTTP state init"
```

---

## Task 5: Remove Schema Fields

**Files:**
- Modify: `schema.py:211-215`

- [ ] **Step 1: Remove four fields from `StreamChunk` Pydantic model**

```python
# In schema.py, delete lines 211-215:
    # Fun fact state
    fun_fact: Optional[str] = None
    fun_fact_hook: Optional[str] = None
    fun_fact_question: Optional[str] = None
    real_facts: Optional[str] = None
```

- [ ] **Step 2: Commit**

```bash
git add schema.py && git commit -m "chore: remove fun_fact fields from StreamChunk schema"
```

---

## Task 6: Remove Prompt Optimizer References

**Files:**
- Modify: `prompt_optimizer.py:279-302` (`_run_grounding`)
- Modify: `prompt_optimizer.py:668-675` (fun_fact preview branch)
- Modify: `prompt_optimizer.py:682-683` (introduction branch extra args)
- Modify: `prompt_optimizer.py:806` (error message)
- Modify: `prompt_optimizer.py:815` (phase check)

- [ ] **Step 1: Delete `_run_grounding` function and its section header**

```python
# In prompt_optimizer.py, delete the entire block (lines 279-302):
# ============================================================================
# Synchronous grounding helper (for fun_fact preview)
# ============================================================================

def _run_grounding(client, config: dict, object_name: str, age: int) -> str:
    """
    Run the grounding step synchronously (no Google Search tool in sync API).

    Falls back to a plain generate_content call with the grounding prompt so
    the optimizer gets real factual context for structuring the preview.
    """
    prompts = paixueji_prompts.get_prompts()
    grounding_prompt = prompts["fun_fact_grounding_prompt"].format(
        object_name=object_name,
        age=age,
        category="general",
    )
    model_name = config["model_name"]
    response = client.models.generate_content(
        model=model_name,
        contents=grounding_prompt,
        config=GenerateContentConfig(temperature=0.3, max_output_tokens=1000),
    )
    return response.text.strip()
```

- [ ] **Step 2: Delete `fun_fact_structuring_prompt` branch from `generate_preview_response`**

```python
# In prompt_optimizer.py, delete lines 668-675:
    if prompt_name == "fun_fact_structuring_prompt":
        # Re-run grounding so the new structuring prompt is tested against real facts
        grounded_text = _run_grounding(client, config, object_name, age)
        formatted = optimized_prompt.format(
            object_name=object_name,
            age=age,
            grounded_text=grounded_text,
        )
```

After deletion, the next `elif` becomes the first branch. Change `elif prompt_name == "introduction_prompt":` to `if prompt_name == "introduction_prompt":`.

- [ ] **Step 3: Remove dead `grounded_facts_section` and `fun_fact_instruction` args**

```python
# In prompt_optimizer.py introduction_prompt branch (lines 677-684), delete the two dead args:
# BEFORE:
    elif prompt_name == "introduction_prompt":
        formatted = optimized_prompt.format(
            object_name=object_name,
            age_prompt=_get_age_prompt(age),
            category_prompt=state.get("level1_category", ""),
            grounded_facts_section="",
            fun_fact_instruction="Ask an opening question about this object.",
        )

# AFTER:
    if prompt_name == "introduction_prompt":
        formatted = optimized_prompt.format(
            object_name=object_name,
            age_prompt=_get_age_prompt(age),
            category_prompt=state.get("level1_category", ""),
        )
```

- [ ] **Step 4: Update error message to remove `fun_fact_structuring_prompt`**

```python
# In prompt_optimizer.py line 806, change:
# BEFORE:
f"Supported prompts: fun_fact_structuring_prompt, introduction_prompt, "

# AFTER:
f"Supported prompts: introduction_prompt, "
```

- [ ] **Step 5: Update phase check to remove `fun_fact_structuring_prompt`**

```python
# In prompt_optimizer.py line 815, change:
# BEFORE:
    if prompt_name in ("fun_fact_structuring_prompt", "introduction_prompt"):

# AFTER:
    if prompt_name == "introduction_prompt":
```

- [ ] **Step 6: Commit**

```bash
git add prompt_optimizer.py && git commit -m "chore: remove fun_fact branches from prompt optimizer"
```

---

## Task 7: Update Trace Infrastructure

**Files:**
- Modify: `trace_schema.py:105-106`
- Modify: `trace_assembler.py:136`

- [ ] **Step 1: Update docstring examples in `trace_schema.py`**

```python
# In trace_schema.py, change lines 105-106:
# BEFORE:
    culprit_name: str                   # e.g. "generate_fun_fact"
    prompt_name: str                    # e.g. "fun_fact_structuring_prompt"

# AFTER:
    culprit_name: str                   # e.g. "generate_intro"
    prompt_name: str                    # e.g. "introduction_prompt"
```

- [ ] **Step 2: Update JSON schema prompt list in `trace_assembler.py`**

```python
# In trace_assembler.py line 136, remove the two fun_fact prompts from the long string:
# BEFORE snippet:
"prompt_template_name": "<exact key — pick from: fun_fact_structuring_prompt, fun_fact_grounding_prompt, introduction_prompt, ..."

# AFTER snippet:
"prompt_template_name": "<exact key — pick from: introduction_prompt, ..."
```

- [ ] **Step 3: Commit**

```bash
git add trace_schema.py trace_assembler.py && git commit -m "chore: remove fun_fact references from trace infrastructure"
```

---

## Task 8: Update Test Files

**Files:**
- Modify: `tests/integration_runner.py`
- Modify: `tests/integration_scenarios/fix4_two_idk_turns.py`
- Modify: `tests/integration_scenarios/run_all_real.py`
- Modify: `tests/test_correct_answer_tracking.py`
- Modify: `tests/test_fix_verification.py`
- Modify: `tests/test_open_ended_idk.py`
- Modify: `tests/test_intent_fixes.py`

- [ ] **Step 1: Remove fun_fact fields from all test state dicts**

Search for the pattern across all test files and delete the 3-4 lines in each:

```bash
grep -n -A1 '"fun_fact"' tests/*.py tests/integration_scenarios/*.py tests/integration_runner.py
```

In each file, delete the block matching this pattern:

```python
        "fun_fact": None,
        "fun_fact_hook": None,
        "fun_fact_question": None,
# (some files use "" instead of None — delete whichever is present)
```

- [ ] **Step 2: Update `test_intent_fixes.py` docstring**

```python
# In tests/test_intent_fixes.py line ~1082, change:
# BEFORE:
    'I don't know' / 'idk' after a 'Did you know?' fun-fact question."""

# AFTER:
    'I don't know' / 'idk' after a 'Did you know?' opening question."""
```

- [ ] **Step 3: Commit**

```bash
git add tests/ && git commit -m "chore: remove fun_fact fields from test fixtures"
```

---

## Task 9: Regression Test — Verify Zero Residual References

**Files:**
- Create: `tests/test_dead_code_cleanup.py`

- [ ] **Step 1: Write regression test**

```python
"""
Regression test: after fun_fact removal, no Python source file should contain
fun_fact-related identifiers (except documentation files).
"""
import subprocess
import pytest


def test_no_fun_fact_references_in_python_source():
    """
    Search the main source tree for any residual fun_fact references.
    Excludes docs/, .claude/, __pycache__/, and .pyc files.
    """
    result = subprocess.run(
        [
            "grep", "-r", "-n",
            "--include=*.py",
            "-E", r"fun.?fact|real_facts",
            "stream/", "graph.py", "paixueji_app.py", "schema.py",
            "prompt_optimizer.py", "trace_schema.py", "trace_assembler.py",
            "paixueji_prompts.py",
        ],
        capture_output=True,
        text=True,
    )

    # grep returns exit code 1 when no matches found (which is what we want)
    if result.returncode == 0:
        pytest.fail(
            f"fun_fact references still found in source:\n{result.stdout}"
        )
    assert result.returncode == 1, (
        f"grep failed unexpectedly: stderr={result.stderr}"
    )
```

- [ ] **Step 2: Run the test — expect PASS**

```bash
pytest tests/test_dead_code_cleanup.py -v
```

Expected output:

```
tests/test_dead_code_cleanup.py::test_no_fun_fact_references_in_python_source PASSED
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_dead_code_cleanup.py && git commit -m "test: add regression test for fun_fact dead code removal"
```

---

## Task 10: Full Test Suite + Manual Verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: ALL tests pass.

- [ ] **Step 2: Manual smoke test — verify `/api/start` still streams an introduction**

Start the server (however the project normally starts, e.g. `python paixueji_app.py` or `flask run`), then:

```bash
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{"object_name": "apple", "age": 5}'
```

Expected: SSE stream returns a normal introduction response. No `KeyError`, no `TypeError`, no mention of fun facts.

- [ ] **Step 3: Delete `__pycache__` artifacts**

```bash
rm -f stream/__pycache__/fun_fact.cpython-313.pyc
rm -f stream/__pycache__/fun_fact.cpython-310.pyc
```

- [ ] **Step 4: Final verification — zero residual references**

```bash
grep -r -n -E "fun.?fact|real_facts" --include="*.py" stream/ graph.py paixueji_app.py schema.py prompt_optimizer.py trace_schema.py trace_assembler.py paixueji_prompts.py tests/
```

Expected: no output (exit code 1).

- [ ] **Step 5: Final commit**

```bash
git add -A && git commit -m "chore: remove fun_fact dead code (completes removal)"
```

---

## Self-Review Checklist

- [ ] **Spec coverage:** Every fun_fact reference identified by the initial `grep` exploration is addressed in a task.
- [ ] **Placeholder scan:** No "TBD", "TODO", "similar to Task N", or "add appropriate error handling" in the plan.
- [ ] **Type consistency:** `StreamChunk` and `PaixuejiState` both lose the same four fields. Test fixtures use consistent state dict shapes.
- [ ] **Cross-file consistency:** `trace_assembler.py` prompt list, `trace_schema.py` examples, and `prompt_optimizer.py` error message all updated in lockstep.
