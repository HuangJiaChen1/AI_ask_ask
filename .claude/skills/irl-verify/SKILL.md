---
name: irl-verify
description: Run live LLM verification tests on recent implementations and generate a behavior report. Use after completing a development branch to verify that new features produce correct model outputs.
license: MIT
metadata:
  author: paixueji
  version: "2.0"
---

Run live LLM verification tests on recent implementations and generate a behavior report.

**When to use**: After finishing a development branch, before merging, to verify that prompt changes, new hook types, intent classifiers, or graph routing actually produce correct model outputs in practice.

**Input**: Optionally specify:
- A branch name: `overseas-algo-alignment`
- A commit range: `main..overseas-algo-alignment` or `HEAD~5..HEAD`
- Explicit features: "hook types 模仿引导 and 轻搞怪/无厘头, action subtype classifier"
- Or invoke with no arguments to auto-detect from recent commits

**Output**: Markdown report at `docs/verification/<prefix>-verification-<timestamp>.md` with actual model outputs and pass/fail checks.

---

## Workflow

This skill operates in two phases. **Phase 1 (Plan)** runs in the main session so the user can review what will be verified. **Phase 2 (Execute)** is dispatched to a subagent to conserve context and prevent drift.

### Phase 1: Build Verification Plan (Main Session)

#### Step 1 — Determine what to verify

**If user provided a branch or commits:**
```bash
git diff --name-only <commit-range>
git log --oneline <commit-range>
```

**If user provided explicit features:**
Use their description directly.

**If no input given:**
```bash
git log --oneline -10
```
Show the recent commits and ask the user which ones to verify.

#### Step 2 — Analyze changed files

Read the changed files to understand what was implemented:
- `paixueji_prompts.py` → new/modified prompts, constants, BEAT structures
- `hook_types.json` → new hook types
- `stream/validation.py` → new classifiers or validators
- `graph.py` → new routing or node logic
- `stream/*.py` → new generators or utilities

For each significant change, identify:
- What prompt template was added/modified
- What new constants were added (safety rules, character profiles)
- What new intent types or subtypes exist
- What new hook types or engagement patterns exist

#### Step 3 — Draft test cases

For each discovered feature, draft a test case entry with:
- `id`, `task_num`, `title`, `implemented` (1-sentence description)
- `scenario` (realistic child input)
- `generator` (one of: `ask_introduction_question_stream`, `ask_attribute_intro_stream`, `ask_followup_question_stream`, `generate_intent_response_stream`, `direct_prompt`)
- `params` (messages, age, object_name, etc.)
- `checks` (assert, assert_not, assert_in criteria)

**Do NOT create the JSON config yet.** Just list the test cases in the plan.

#### Step 4 — Present plan and exit plan mode

Write the plan to the plan file and present it to the user:

```
## IRL Verification Plan

**Scope:** <branch / commits / features>
**Tests:** <N> test cases
**Estimated calls:** <N> live LLM calls

### Test Cases
1. <Title> — <generator> — <scenario>
2. ...

### Safety Focus
- <any sensory or emotional safety checks>

Awaiting approval to proceed.
```

Call `ExitPlanMode` and stop. Do not proceed to execution until the user approves.

---

### Phase 2: Execute Verification (Subagent)

After the user approves the plan:

#### Step 5 — Generate JSON config

Create the JSON config for the generic harness at `/tmp/irl_verify_config_<timestamp>.json`.

Use deterministic naming: set `report_prefix` in the config (e.g., `overseas-algo`) and pass `--report-name <prefix>-verification-<date>` to the harness so re-runs overwrite the same file instead of creating duplicates.

Example test case structures:

**New hook type:**
```json
{
  "id": "hook_<name>",
  "task_num": 3,
  "title": "Hook Type — <name>",
  "implemented": "Added hook type '<name>' with concept and examples.",
  "scenario": "Object: toy dog | Intro mode: default | Age: 5",
  "generator": "ask_introduction_question_stream",
  "params": {
    "messages": [{"role": "assistant", "content": "Let's look at this toy dog together!"}],
    "object_name": "toy dog",
    "surface_object_name": null,
    "anchor_object_name": null,
    "intro_mode": "default",
    "age": 5,
    "hook_type_section": "<formatted section from hook_types.json>",
    "knowledge_context": ""
  },
  "checks": [
    {"criterion": "Generated a single question", "assert": "?"},
    {"criterion": "Question fits the hook's concept", "assert_in": ["<keyword1>", "<keyword2>"]}
  ]
}
```

**New intent classifier:**
```json
{
  "id": "classify_<intent>",
  "task_num": 1,
  "title": "<Intent> Classifier",
  "implemented": "Classifier extracts <field> from LLM output.",
  "scenario": "Child says: '<example utterance>'",
  "generator": "direct_prompt",
  "params": {
    "prompt": "<the actual classifier prompt with child_answer filled in>",
    "messages": [{"role": "assistant", "content": "<last model response>"}]
  },
  "checks": [
    {"criterion": "Classifier returned expected label", "assert": "<expected label>"},
    {"criterion": "Classification status is ok", "assert": "ok"}
  ]
}
```

**New/modified prompt:**
```json
{
  "id": "prompt_<name>",
  "task_num": 8,
  "title": "<Feature Name>",
  "implemented": "<description of what changed>",
  "scenario": "<test scenario>",
  "generator": "generate_intent_response_stream",
  "params": {
    "intent_type": "<intent>",
    "messages": [{"role": "assistant", "content": "<context>"}],
    "child_answer": "<child input>",
    "object_name": "<object>",
    "age": 5,
    "last_model_response": "<last response>"
  },
  "checks": [
    {"criterion": "Does NOT contain banned phrase", "assert_not": "<banned>"},
    {"criterion": "Contains expected element", "assert_in": ["<keyword>"]}
  ]
}
```

#### Step 6 — Dispatch subagent for execution

**CRITICAL**: Dispatch a subagent to run the harness. Do NOT run live LLM calls in the main session.

Use the `Agent` tool with these exact instructions in the prompt:

```
You are an IRL verification executor. Your ONLY job is to run the live LLM verification harness and return the report path.

**DO NOT**:
- Verify code strings, prompt contents, or JSON files
- Do code review or static analysis
- Run pytest or any code-side tests
- Make any code changes

**DO**:
- Run the harness with LIVE Vertex AI model calls
- Wait for all tests to complete
- Capture the report path
- Return ONLY the report path and a 1-line summary

Project: Paixueji children's education chatbot
Working directory: <project-root>
Python: Use .venv/Scripts/python.exe (Windows) or .venv/bin/python (Unix)

Run this exact command:
python scripts/irl_verify.py --config <config-path> --report-name <report-name> --overwrite

If rate limits are hit, the harness will retry automatically. Wait for it to finish.
Return the report file path when done.
```

Set `run_in_background: true` on the Agent call so the main session is not blocked.

#### Step 7 — Review the report

When the subagent returns, read the generated report and analyze:

**For each test case, verify:**
- Model output is present (not empty or error)
- Output matches the intended behaviour
- Safety constraints are respected
- BEAT structure is followed (correct number of beats)
- No unintended side effects

**Flag issues:**
- Safety violations (touch/smell/taste invitations despite bans)
- Prompt instructions ignored by model
- Missing expected elements
- Incorrect tone or age-appropriateness

#### Step 8 — Present findings

Show the user:

```
## IRL Verification Complete

**Report:** docs/verification/<report-name>.md
**Tests run:** N
**Passed:** X / N

### ✅ What Works
- <list of passing features>

### ⚠️ Issues Found
- <list of failing checks with model output excerpts>

### Recommendations
- <suggested fixes for issues>
```

If issues are found, suggest:
1. Tightening prompt constraints
2. Adding negative examples
3. Adding post-hoc filters
4. Moving instructions closer to output format

---

## Guardrails

- **Never skip live calls**: The whole point is to see real model behaviour, not just prompt strings
- **Run in subagent**: Always dispatch a subagent for execution. Never run live calls in the main session
- **Use plan mode**: Present the verification plan first. Only execute after user approval
- **Prevent duplicate files**: Use `--report-name` + `--overwrite` so re-runs update the same file
- **Handle rate limits gracefully**: Add delays, retries, and pause if limits persist
- **Document everything**: Every model output goes in the report verbatim
- **Flag safety issues prominently**: Any touch/smell/taste invitation or other safety violation is high priority
- **Keep test cases focused**: One feature per test case, clear pass/fail criteria
- **Use realistic child inputs**: Age-appropriate language, common utterances

---

## Example Invocation

```
User: /irl-verify overseas-algo-alignment

→ Skill enters plan mode
→ Analyzes git diff, finds hook_types.json, paixueji_prompts.py, graph.py changes
→ Presents plan: "Will verify 12 test cases: new hook types, action subtype classifier, BEAT prompts"
→ User approves
→ Dispatches subagent with config + explicit IRL-only instructions
→ Subagent runs harness, generates report
→ Presents: "3 issues found — 细节发现 invites touch, concept confusion re-asks, emotional extreme lacks trusted-grown-up suggestion"
```

```
User: /irl-verify

→ Skill enters plan mode
→ Shows last 10 commits, asks which to verify
→ User selects commits or describes features
→ Presents plan
→ User approves
→ Dispatches subagent
→ Proceeds with analysis and verification
```
