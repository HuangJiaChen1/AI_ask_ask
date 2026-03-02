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

## Phase 0 — Parse Input

`$ARGUMENTS` is either:
- A **file path** (starts with `/`, `./`, `~/`, or ends with `.md`, `.txt`, `.log`) → Read the file
- **Inline flaw description text** → Use it directly as the flaw report

Extract and state clearly:
- What was the **observed (wrong) behaviour**?
- What was the **expected behaviour**?
- What did the child/user say that **triggered the bug**?
- Which **intent / node / route** was involved (if discernible)?

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

---

## Phase 2 — Root Cause Diagnosis

Produce a short (≤ 5 bullets) diagnosis covering:
- Which classifier/prompt made the wrong decision
- Why (what wording is missing, ambiguous, or absent)
- Which downstream node/prompt received the misrouted intent
- Whether the fix is: **prompt-only / routing change / new node / deleted node / combination**

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

Present Phase 3 + Phase 3.5 together to the user. The user must confirm the expected output
matches their mental model **before** implementation begins.

---

## Phase 4 — Verification Plan

1. **Integration test (real LLM)**: After implementing the fix, run the conversation history
   from the flaw report through the live pipeline via `tests/integration_runner.py`.
   Compare response against the Phase 3.5 expected output and property checklist.
   (See Phase 5 step 4 for execution details.)
2. **Unit test**: What to assert in `tests/test_intent_fixes.py` (structural prompt assertions — no LLM calls)
3. **Regression command**: `pytest tests/` — expected: all passing
4. (Optional) Similar edge-case inputs to verify don't regress

---

## Phase 5 — Implement (with user confirmation)

Present Phases 2–3.5 to the user. Ask: "Shall I implement this fix now?"

If yes:
1. Apply all edits in `paixueji_prompts.py` and/or `graph.py` as specified in Phase 3
2. Run `python -m py_compile paixueji_prompts.py graph.py` to catch syntax errors immediately
3. Run `pytest tests/` to confirm no regressions
4. **Run real-LLM integration test:**
   a. Extract the conversation history from the flaw report as a JSON object:
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
   b. Write this JSON to `/tmp/paixueji_integration.json`
   c. Resolve credentials, then run. The runner requires GOOGLE_APPLICATION_CREDENTIALS.
      Check whether it is already set; if not, use Application Default Credentials (ADC):
        GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json \
          python tests/integration_runner.py /tmp/paixueji_integration.json
      ADC is always available at ~/.config/gcloud/application_default_credentials.json on
      this machine (gcloud auth application-default login has already been run).
   d. Capture stdout (the model's response)
   e. Check each property from the Phase 3.5 checklist against the response
   f. If all properties pass → report ✓ Integration test passed
      If any property fails → report the failing property and show the actual response.
      Do NOT automatically re-implement. Present findings to the user.
5. Invoke the `test-writer-verifier` agent to write structural tests for the new behaviour
   and append them to `tests/test_intent_fixes.py`
