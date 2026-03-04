---
description: Diagnose a flaw report and produce a paixueji fix plan
argument-hint: "[flaw-report-file-or-description]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(pytest:*), Bash(python -m py_compile:*), Bash(python tests/integration_runner.py:*), Bash(GOOGLE_APPLICATION_CREDENTIALS:*), Task
model: sonnet
---

You are a senior engineer on the **paixueji** codebase — an educational AI app for young children
(ages 3–8) that uses a Gemini-backed LangGraph pipeline with a Flask SSE frontend.

Your job is to **diagnose a reported flaw and produce a concrete fix plan**, following the phases below.

---

## Phase −1 — Start: Create Full Task List (MANDATORY — do this before anything else)

Before reading any files, create all 9 tasks with TaskCreate. This is the authoritative
checklist. A phase is not done until its task is marked `completed`.

| Task # | subject |
|--------|---------|
| 1 | Phase 0 — Parse flaw input |
| 2 | Phase 1 — Codebase exploration |
| 3 | Phase 2 — Root cause diagnosis |
| 4 | Phase 3 — Fix proposal |
| 5 | Phase 3.5 — Expected output prediction + plan presentation |
| 6 | Phase 4 — Verification plan |
| 7 | Phase 5 — Implement fix |
| 8 | Phase 6 — Real-LLM integration test (MANDATORY) |
| 9 | Phase 7 — Write structural tests |

After creating all 9 tasks, mark task 1 `in_progress`. Then begin Phase 0.

---

## Phase 0 — Parse Input

`$ARGUMENTS` is either:
- A **file path** (starts with `/`, `./`, `~/`, or ends with `.md`, `.txt`, `.log`) → Read the file
- **Inline flaw description text** → Use it directly as the flaw report

Extract and state clearly:
- What was the **observed (wrong) behaviour**?
- What was the **expected behaviour**?
- What did the child/user say that **triggered the bug**?
- Which **intent / node / route** was involved (if discernible)?

Mark task 1 (`Phase 0`) `completed`. Mark task 2 (`Phase 1`) `in_progress`.

---

## Phase 1 — Codebase Exploration (parallel Explore agents)

Launch **2 Explore agents in parallel** using the Task tool:

**Agent A — Prompt & classifier path**
- Read `paixueji_prompts.py` fully
- Identify the prompt(s) that govern the intent classification step mentioned in the flaw
- Identify the response-generation prompt that handles the misrouted intent
- Return: exact prompt variable names, line ranges, and what they currently say

**Agent B — Graph & routing path**
- Read `graph.py` fully (nodes, conditional edges, `PaixuejiState` fields)
- Trace the node path from `analyze_input` through to the response node for the intent involved
- Identify whether the bug requires a new node, a deleted node, or just a routing condition change
- Return: node names, edge conditions, and relevant `PaixuejiState` fields

After both agents return, **read the specific files/lines they identify** before proceeding.

Mark task 2 (`Phase 1`) `completed`. Mark task 3 (`Phase 2`) `in_progress`.

---

## Phase 2 — Root Cause Diagnosis

Produce a short (≤ 5 bullets) diagnosis covering:
- Which classifier/prompt made the wrong decision
- Why (what wording is missing, ambiguous, or absent)
- Which downstream node/prompt received the misrouted intent
- Whether the fix is: **prompt-only / routing change / new node / deleted node / combination**

Mark task 3 (`Phase 2`) `completed`. Mark task 4 (`Phase 3`) `in_progress`.

---

## Phase 3 — Fix Proposal

Propose the **minimal effective fix**. For each change:

### If prompt-only (most common)
- State the exact prompt variable(s) to edit (`paixueji_prompts.py`)
- Show old text → replacement text in unified diff style
- Explain why each addition resolves the misclassification

### If routing change needed (`graph.py`)
- Name the conditional edge function to modify
- Show old condition logic → new condition logic
- Confirm no downstream nodes need updating

### If new node needed (`graph.py`)
- Propose node name, async function signature, and what it does
- Show where it connects (which edges come in, which go out)
- List new `PaixuejiState` fields required (if any)

### If node deletion needed
- Name the node to remove
- Show the re-wiring of edges that currently point to it

Always state: **which of the two pipelines (Chat / Critique / both) this fix affects**.

Mark task 4 (`Phase 3`) `completed`. Mark task 5 (`Phase 3.5`) `in_progress`.

---

## Phase 3.5 — Expected Output Prediction

Based on the fix proposed in Phase 3, write a concrete prediction of how the model should respond
to the exact input that triggered the flaw.

**Triggering input (from flaw report):**
> [exact child utterance, verbatim]

**Expected response (approximate, 2–4 sentences):**
> [write what a correct response should say — in age-appropriate language,
>  matching the child's name/age if known, showing the target behaviour]

**Verifiable properties — the real response must satisfy ALL of these:**
- [ ] [Property 1: e.g., "Does NOT open with 'Did you know'"]
- [ ] [Property 2: e.g., "Acknowledges child's correct answer before adding info"]
- [ ] [Property 3: e.g., "Stays on current topic, no topic switch"]
- [ ] [Property 4: e.g., "Ends with a question, not a statement"]

Present Phase 3 + Phase 3.5 to the user together with the complete remaining roadmap
so the user sees every remaining phase before approving. Use this exact structure:

---
### Complete Fix Roadmap

**Diagnosis:** [Phase 2 summary, 1–2 sentences]

**Fix (Phase 3):** [files and diffs]

**Expected output (Phase 3.5):** [prediction + property checklist]

**Phase 4 — Verification plan:**
- Integration test: `python tests/integration_runner.py /tmp/paixueji_integration.json`
  Credentials: `GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json`
- Unit test assertions in `tests/test_intent_fixes.py`
- Regression: `pytest tests/`

**Phase 5 — Implementation:** Edit `paixueji_prompts.py` / `graph.py`, compile-check, pytest

**Phase 6 — Real-LLM integration test (MANDATORY):**
  Write conversation JSON to `/tmp/paixueji_integration.json`, then run:
  ```
  GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json \
    python tests/integration_runner.py /tmp/paixueji_integration.json
  ```
  Verify every Phase 3.5 property against the live response.

**Phase 7 — Structural tests:** Invoke `test-writer-verifier` agent →
  append tests to `tests/test_intent_fixes.py`.

---

Ask: **"Does this expected output match what you intended? Shall I implement this fix?"**

After user confirms, mark task 5 (`Phase 3.5`) `completed`.
Mark task 6 (`Phase 4`) `in_progress`.

---

## Phase 4 — Verification Plan

1. **Integration test (real LLM)**: After implementing the fix, run the conversation history
   from the flaw report through the live pipeline via `tests/integration_runner.py`.
   Compare response against the Phase 3.5 expected output and property checklist.
   (See Phase 5 step 4 for execution details.)
2. **Unit test**: What to assert in `tests/test_intent_fixes.py` (structural prompt assertions — no LLM calls)
3. **Regression command**: `pytest tests/` — expected: all passing
4. (Optional) Similar edge-case inputs to verify don't regress

Mark task 6 (`Phase 4`) `completed`. Mark task 7 (`Phase 5`) `in_progress`.

---

## Phase 5 — Implement (with user confirmation)

Present Phases 2–3.5 to the user. Ask: "Shall I implement this fix now?"

If yes:
1. Apply all edits in `paixueji_prompts.py` and/or `graph.py` as specified in Phase 3
2. Run `python -m py_compile paixueji_prompts.py graph.py` to catch syntax errors immediately
3. Run `pytest tests/` to confirm no regressions

Mark task 7 (`Phase 5`) `completed`.

✋ CHECKPOINT — pytest passing is NOT sufficient. You MUST complete Phase 6 before this
fix is considered done. Mark task 8 (`Phase 6`) `in_progress`. Proceed to Phase 6 now.

---

## Phase 6 — Real-LLM Integration Verification (MANDATORY — do not skip)

⚠️ This phase is required. Do NOT invoke the test-writer-verifier or report the fix as complete
until all steps below are done.

1. Extract the conversation history from the flaw report as a JSON object:
   ```json
   {
     "child_name": "<name if known, else 'Leo'>",
     "age": "<age band if known, else 5>",
     "object_name": "<object being discussed>",
     "history": [
       {"role": "user", "content": "<first user turn>"},
       {"role": "assistant", "content": "<first ai turn>"},
       ...
     ],
     "user_input": "<the exact triggering input>"
   }
   ```
2. Write this JSON to `/tmp/paixueji_integration.json`
3. Resolve credentials, then run. The runner requires GOOGLE_APPLICATION_CREDENTIALS.
   Check whether it is already set; if not, use Application Default Credentials (ADC):
     GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json \
       python tests/integration_runner.py /tmp/paixueji_integration.json
   ADC is always available at ~/.config/gcloud/application_default_credentials.json on
   this machine (gcloud auth application-default login has already been run).
4. Capture stdout (the model's response)
5. Check each property from the Phase 3.5 checklist against the response
6. If all properties pass → mark task 8 (`Phase 6`) `completed`. Report ✓ Integration test passed.
   Mark task 9 (`Phase 7`) `in_progress`. Proceed to Phase 7 now.

   If any property fails → keep task 8 `in_progress`. Report the failing property and actual
   response. Do NOT automatically re-implement. Present findings to the user.

---

## Phase 7 — Write Structural Tests

Invoke the `test-writer-verifier` agent to write structural tests for the new behaviour
and append them to `tests/test_intent_fixes.py`

After the test-writer-verifier agent returns, mark task 9 (`Phase 7`) `completed`.
Run TaskList to confirm all 9 tasks show `completed`. Only then report the fix as done.
