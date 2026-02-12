# Meta-Agent Evolution System — Technical Reference

> **Purpose:** Automatically translates critic report failures into tested, generalized architectural improvements.
> Takes an AIF or HF report → identifies failing nodes → diagnoses root causes → proposes and **verifies** prompt changes through a 3-layer anti-hardcoding pipeline.
>
> **Last updated:** 2026-02-11

---

## 1. Architecture Overview

The meta-agent is a **three-stage pipeline with a 3-layer verification loop**:

```
                         ┌───────────────────────────────────────┐
                         │           Meta-Agent Loop              │
                         │                                        │
  Critic Report (.md) ──►│  Stage 1: Report Analyzer              │
                         │    → ReportAnalysis (JSON)             │
                         │                                        │
                         │  Stage 2: Architecture Diagnostician   │
                         │    + architecture context              │
                         │    + anti-hardcoding rules             │
                         │    → ArchitectureDiagnosis (JSON)      │
                         │                                        │
                         │  Stage 3: Verification (3-layer)       │
                         │    ├─ L1: Constraint (prompt rules)    │
                         │    ├─ L2: Detection (hardcoding scan)  │
                         │    ├─ L3: Cross-validation             │
                         │    │   ├─ Primary: original failures   │
                         │    │   │   eliminated? No new ones?    │
                         │    │   └─ CV scenarios: no regressions?│
                         │    └─ Result:                          │
                         │         ├─ ACCEPT → verified change    │
                         │         │   + auto-save scenario YAML  │
                         │         └─ REJECT → feedback to S1+S2  │
                         │              (HARDCODED / INEFFECTIVE   │
                         │               / OVERFITTING)            │
                         │              loop (max N iterations)    │
                         │                                        │
                         │  Final Output:                          │
                         │    verified_changes[] (generalized)     │
                         │    proposed_changes[] (structural)      │
                         └───────────────────────────────────────┘
```

### Two Tiers of Output

| Tier | What | Auto-applied? |
|------|------|---------------|
| **Verified changes** | Prompt modifications that passed all 3 layers: no hardcoding, all original failures eliminated, no cross-validation regressions | Safe to auto-apply |
| **Proposed changes** | Structural changes (new nodes, router modifications) that cannot be auto-tested | Requires human review |

### Acceptance Criteria (Failure-Based, Not Score-Based)

The system uses **failure-based** acceptance instead of score thresholds:

- **Primary scenario**: ALL original failure types must be eliminated, and NO new failure types introduced
- **Cross-validation**: NO new failure types vs unpatched baseline, total failure count must not increase

This prevents false positives from score fluctuations and ensures changes genuinely fix the identified problems.

---

## 2. CLI Usage

All commands run from the `paixueji/` directory:

```bash
python -m meta_agent <command> [options]
```

### Commands

#### `analyze` — Stage 1 Only

Parses a critic report and identifies suspected failing nodes with failure grouping.

```bash
# Basic analysis (prints JSON to stdout)
python -m meta_agent analyze reports/AIF/banana_20260209_102935.md

# Save to file
python -m meta_agent analyze reports/AIF/banana_20260209_102935.md -o analysis.json

# Verbose (prints intermediate steps)
python -m meta_agent analyze reports/AIF/banana_20260209_102935.md -v
```

**Output:** `ReportAnalysis` JSON with:
- `suspected_nodes[]` — which graph nodes caused failures, with confidence levels
- `failure_groups[]` — related failures grouped by category
- `severity_assessment` — "critical" / "moderate" / "minor"
- `consolidated_improvements[]` — deduplicated improvement suggestions

#### `diagnose` — Stage 1 + 2

Analyzes the report, then diagnoses root causes and proposes architectural changes.

```bash
# Basic diagnosis
python -m meta_agent diagnose reports/AIF/banana_20260209_102935.md

# Save to file with verbose output
python -m meta_agent diagnose reports/AIF/banana_20260209_102935.md -o diagnosis.json -v
```

**Output:** Combined JSON with both the analysis and diagnosis:
- `root_causes[]` — architectural mechanisms producing failures
- `proposed_changes[]` — specific changes with type, target, rationale, and priority
- For `MODIFY_PROMPT` changes: includes the full proposed replacement prompt text

#### `evolve` — Full Loop (Stage 1 + 2 + 3)

The complete evolution pipeline: analyze → diagnose → verify prompt changes.

```bash
# Full evolution with defaults (3 iterations)
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md

# Custom iteration limit
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md --max-iterations 5

# Skip verification (equivalent to diagnose, but output format matches evolve)
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md --no-verify

# Save as markdown report
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md -f markdown -o evolution_report.md

# Save as JSON
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md -o results.json

# Verbose mode (recommended for first runs — shows what's happening at each step)
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md -v
```

### Options Reference

| Option | Commands | Default | Description |
|--------|----------|---------|-------------|
| `-o, --output` | all | stdout | Output file path |
| `-v, --verbose` | all | off | Print intermediate results (recommended) |
| `-f, --format` | evolve | json | Output format: `json` or `markdown` |
| `--max-iterations` | evolve | 3 | Max verification attempts per prompt change |
| `--no-verify` | evolve | off | Skip Stage 3, output Stage 1+2 results only |

---

## 3. Report Compatibility

The parser auto-detects report type:

| Report Type | Detection Pattern | What's Extracted |
|-------------|-------------------|------------------|
| **AIF** | Contains `## Detailed Exchange Analysis` AND `### Overall Effectiveness` | Full metrics: effectiveness score, node traces with response_type, failure classifications, ideal responses, improvements |
| **HF** | Contains `#### Human Critique` | Human critique text, node traces, conversation exchanges |

AIF reports provide richer data (scores, failure types, node traces with state changes), leading to higher-confidence node attribution. HF reports lack scores, so the LLM must infer severity from the human critique text.

---

## 4. How Verification Works (3-Layer Anti-Hardcoding)

Stage 3 only tests `MODIFY_PROMPT` changes. Structural changes (CREATE_NODE, MODIFY_ROUTER, etc.) are passed through as human-reviewed proposals.

### The Hardcoding Problem

A naive diagnostician can "cheat" by embedding report-specific content into prompts:
- "If the child says 'no', respond with 'That's okay! A banana plant is very tall...'"
- "When discussing bananas, always mention that they turn yellow"

This solves the specific failure but teaches the system nothing. Three layers of defense prevent this.

### Layer 1: Constraint (Stage 2 Prompt Rules)

The Stage 2 diagnostician prompt includes explicit anti-hardcoding **GENERALIZATION RULES**:

1. NEVER reference specific objects from the report — use `{object_name}` placeholder
2. NEVER embed specific child answers or model responses from the report
3. NEVER add "if child says X, respond with Y" conditional rules
4. NEVER include content that only applies to one object/topic
5. Changes MUST be phrased as GENERAL PEDAGOGICAL PRINCIPLES
6. The modified prompt must work equally well for ANY object, ANY age, ANY child response

### Layer 2: Detection (Automated Hardcoding Scan)

Before running any scenario, `detect_hardcoding()` scans the proposed prompt for:

| Check | Method |
|-------|--------|
| **Object name** | Checks if the report's object name (e.g., "banana") appears outside `{object_name}` placeholders |
| **Verbatim phrases** | Extracts n-gram fingerprints (>15 chars) from child responses, model responses, and ideal responses in the report; checks for matches in the proposed prompt |
| **If-then rules** | Regex scan for patterns like `if.*child.*says.*"specific content"` |

If violations are found → **immediate HARDCODED rejection** without running any scenario. Feedback is sent to Stage 2 with the specific violations listed.

### Layer 3: Cross-Validation (Generalization Test)

This is the ML "train/test split" approach. The original report is "training data". Existing scenarios are "test data".

```
For each MODIFY_PROMPT change:
│
├─ 1. BUILD PRIMARY SCENARIO from report exchanges
│
├─ 2. PATCH PROMPT in-memory (monkey-patch paixueji_prompts constant)
│
├─ 3. RUN PRIMARY SCENARIO
│     ScenarioRunner.run_scenario() with real graph
│     PedagogicalCritiquePipeline.critique_scenario()
│
├─ 4. CHECK PRIMARY ACCEPTANCE (failure-based)
│     ✓ ALL original failure types eliminated?
│     ✓ NO new failure types introduced?
│     → Fail = INEFFECTIVE rejection
│
├─ 5. SELECT CROSS-VALIDATION SCENARIOS (2-4 from existing pool)
│     Heuristic mapping from prompt key → response types:
│     ┌─────────────────────────────────┬──────────────────────────────┐
│     │ Modified Prompt                 │ Select scenarios where...    │
│     ├─────────────────────────────────┼──────────────────────────────┤
│     │ EXPLANATION_RESPONSE_PROMPT     │ child DONT_KNOW or CONFUSED  │
│     │ CORRECTION_RESPONSE_PROMPT      │ child gives ANSWER (wrong)   │
│     │ FEEDBACK_RESPONSE_PROMPT        │ child gives ANSWER (correct) │
│     │ FOLLOWUP_QUESTION_PROMPT        │ any scenario (always runs)   │
│     │ INTRODUCTION_PROMPT             │ FIRST_TURN scenarios         │
│     └─────────────────────────────────┴──────────────────────────────┘
│
├─ 6. RUN CV SCENARIOS with patched prompt
│     Compare vs UNPATCHED BASELINE (cached once per evolve run)
│     ✓ No new failure types vs baseline?
│     ✓ Total failure count doesn't increase?
│     → Fail = OVERFITTING rejection
│
├─ 7. ACCEPT or REJECT
│     Accept → auto-save scenario YAML to generated/
│     Reject → feed specific failure context back to Stage 1+2
│
└─ 8. RESTORE original prompt (always, in finally block)
```

### Rejection Types

| Type | Meaning | What's fed back |
|------|---------|-----------------|
| **HARDCODED** | Proposed prompt contains report-specific content | Specific violations (object names, verbatim phrases) |
| **INEFFECTIVE** | Original failures not eliminated, or new failures introduced | Remaining failure types, newly introduced failure types |
| **OVERFITTING** | Fixed primary scenario but broke cross-validation scenarios | CV scenario IDs, new failures introduced in each |

### On Rejection (the learning loop)

When a change is rejected:
1. An `AttemptResult` is recorded with the rejection type and detailed failure context
2. The `EvolutionHistory` is passed back to Stage 2 (or Stage 1+2 for INEFFECTIVE/OVERFITTING)
3. The `format_feedback_injection()` function generates rejection-type-specific feedback
4. The reasoning model (Gemini 2.5 Pro with thinking) is forced to explore different strategies

Example feedback injection:
```
PREVIOUS ATTEMPTS (these failed — learn from them):

- Attempt 1 [OVERFITTING]: Changed explanation_response_prompt.
  Fixed the primary scenario but broke cross-validation scenarios:
  SCAFFOLD-WHY-002 (MISSED_SCAFFOLD), TEACH-PATIENCE-001 (ABANDONED_INTENT).
  Lesson: The change was too narrow. Propose a more general pedagogical principle.

- Attempt 2 [HARDCODED]: Changed explanation_response_prompt.
  Proposed prompt contained report-specific content. Violations:
  Contains specific object name 'banana'. Rejected BEFORE testing.
```

### Baseline Caching

Running CV scenarios with unpatched prompts is expensive. The `BaselineCache` class computes baselines once per evolve run and reuses them across iterations. If a baseline needs to be computed mid-verification, the system temporarily restores the original prompt, computes, then re-patches.

### Auto-Save Verified Scenarios (Test Set Growth)

After a prompt change is **verified** (all 3 layers pass), the primary scenario is automatically saved as a YAML file:

```
tests/quality/scenarios/generated/
  EVOLVE-banana-20260209-001.yaml
  EVOLVE-icecube-20260211-001.yaml
```

Each generated scenario includes:
- `setup`: object_name, key_concept, age from the original report
- `conversation`: child responses from the report exchanges
- `evaluation.must_do`: derived from eliminated failure types
- `evaluation.must_not_do`: derived from critical issues
- `metadata`: source, report_path, date, prompt_modified

These auto-saved scenarios become part of the cross-validation pool for future evolution runs. The test set grows organically — each verified fix adds a new regression test.

### Safety

- Prompts are **always** restored in a `finally` block, even if the scenario crashes
- Structural changes (CREATE_NODE, MODIFY_ROUTER) are never auto-applied
- Each prompt is patched and restored independently
- Hardcoding scan runs **before** any scenario execution (fast fail)

---

## 5. Two-Phase Evolution (Structural Changes)

When structural changes are proposed alongside prompt changes:

```
Phase A: Prompt Evolution (automated)
  Stage 1+2 → prompt changes + structural proposals
  Stage 3 → verify prompt changes (3-layer loop)
  Output: verified prompts + structural proposals
  → Print structural proposals prominently for human review

  ════════════════════════════════════════════════════
    STRUCTURAL CHANGES PROPOSED (requires human review)
  ════════════════════════════════════════════════════
  1. [CREATE_NODE] "validate_question_complexity"
     Purpose: Check question complexity before sending
     Position: After generate_question, before finalize
  ════════════════════════════════════════════════════

HUMAN DECISION POINT
  Human reviews and implements structural changes manually

Phase B: Re-evaluation (if structural changes were made)
  Option 1: Use the app normally → generates conversation naturally
  Option 2: Run an existing scenario:
    python -m tests.quality.cli run-and-critique -s <scenario_file>
  Option 3: Use the auto-saved scenario from generated/
  → Feed the NEW report into a fresh evolve loop
```

**Why a fresh report?** The original report was generated against the old architecture. After structural changes, failure modes may be completely different.

---

## 6. File Layout

```
meta_agent/
  __init__.py                  # Public exports + evolve() orchestrator
  __main__.py                  # Entry: python -m meta_agent
  schema.py                    # All Pydantic models (Stage 1, 2, 3)
  architecture_manifest.py     # Graph topology + node→prompt mapping + context builder
  report_parser.py             # AIF/HF markdown → ParsedReport
  prompts.py                   # LLM prompt templates (Stage 1 + 2 + feedback injection)
  stage1_analyzer.py           # Report → ReportAnalysis (Gemini 2.5 Pro + thinking)
  stage2_diagnostician.py      # Analysis + arch context → ArchitectureDiagnosis
  stage3_verifier.py           # 3-layer verification: hardcoding → primary → CV → auto-save
  cli.py                       # argparse CLI
```

---

## 7. Key Data Models

### Stage 1 Output: `ReportAnalysis`

```python
class ReportAnalysis(BaseModel):
    report_source: str                       # "AIF" or "HF"
    overall_effectiveness: float | None      # 0-100 (AIF only)
    total_exchanges: int
    failed_exchanges: int
    suspected_nodes: list[SuspectedNode]     # Ordered by confidence
    failure_groups: list[FailureGroup]       # Categorized failures
    consolidated_improvements: list[str]     # Deduplicated
    critical_issues: list[str]
    severity_assessment: str                 # "critical" / "moderate" / "minor"
    summary: str
```

### Stage 2 Output: `ArchitectureDiagnosis`

```python
class ArchitectureDiagnosis(BaseModel):
    root_causes: list[RootCause]
    proposed_changes: list[ProposedChange]   # Mix of MODIFY_PROMPT + structural
    summary: str
    estimated_impact: str
```

### Stage 3 Output: `EvolutionResult`

```python
class VerifiedChange(BaseModel):
    change: ProposedChange
    primary_failures_eliminated: list[str]   # FailureTypes fixed
    cv_scenarios_tested: list[str]           # Scenario IDs used for CV
    cv_regressions: int                      # 0 if clean
    iterations_needed: int
    saved_scenario_path: str                 # Path to auto-saved YAML

class EvolutionResult(BaseModel):
    verified_changes: list[VerifiedChange]        # Tested, generalized, proven
    unverified_proposals: list[ProposedChange]    # Structural (human review)
    rejected_attempts: list[AttemptResult]         # Failed attempts (learning record)
    summary: str
```

### Rejection Tracking: `AttemptResult`

```python
class AttemptResult(BaseModel):
    iteration: int
    change_applied: ProposedChange
    rejection_type: str              # "HARDCODED" / "INEFFECTIVE" / "OVERFITTING"

    # INEFFECTIVE-specific
    remaining_failures: list[str]    # Failure types still present
    new_failures: list[str]          # New failure types introduced

    # OVERFITTING-specific
    primary_passed: bool
    cv_regressions: list[dict]       # [{scenario_id, new_failures_introduced}]

    # HARDCODED-specific
    violations: list[str]            # From detect_hardcoding()
```

---

## 8. LLM Configuration

Both Stage 1 and Stage 2 use **Gemini 2.5 Pro with extended thinking**:

```python
config = GenerateContentConfig(
    system_instruction=STAGE_SYSTEM_PROMPT,
    temperature=0.2,
    response_mime_type="application/json",
    thinking_config={"thinking_budget": 8192},
)
```

The thinking budget gives the model space for chain-of-thought reasoning before outputting structured JSON. This is critical for Stage 2's root cause diagnosis, where the model needs to trace failure mechanisms through multiple architectural layers.

---

## 9. Key Dependencies

The meta-agent reuses existing Paixueji infrastructure:

| Dependency | Used In | Purpose |
|------------|---------|---------|
| `paixueji_prompts` | Stage 2 context, Stage 3 patching | Source of current prompts + monkey-patch target |
| `tests.quality.scenario_runner.ScenarioRunner` | Stage 3 | Runs scenarios through the real LangGraph |
| `tests.quality.pipeline.PedagogicalCritiquePipeline` | Stage 3 | Critiques output after prompt patch |
| `tests.quality.pipeline.ScenarioLoader` | Stage 3 | Loads CV scenarios from YAML files |
| `tests.quality.schema.Scenario` | Stage 3 | Scenario data model for test runs |
| `tests.quality.schema.ConversationCritique` | Stage 3 | Critique result with `failure_breakdown` |
| `google.genai` (Vertex AI) | All stages | LLM calls via `client.aio.models.generate_content()` |

---

## 10. Prompt Key → Module Constant Mapping

Stage 3 patches prompts by mapping the `prompt_key` from Stage 2's diagnosis to module-level constants in `paixueji_prompts`:

| prompt_key | Module Constant |
|------------|----------------|
| `system_prompt` | `SYSTEM_PROMPT` |
| `introduction_prompt` | `INTRODUCTION_PROMPT` |
| `feedback_response_prompt` | `FEEDBACK_RESPONSE_PROMPT` |
| `explanation_response_prompt` | `EXPLANATION_RESPONSE_PROMPT` |
| `correction_response_prompt` | `CORRECTION_RESPONSE_PROMPT` |
| `topic_switch_response_prompt` | `TOPIC_SWITCH_RESPONSE_PROMPT` |
| `followup_question_prompt` | `FOLLOWUP_QUESTION_PROMPT` |
| `completion_prompt` | `COMPLETION_PROMPT` |
| `fun_fact_grounding_prompt` | `FUN_FACT_GROUNDING_PROMPT` |
| `fun_fact_structuring_prompt` | `FUN_FACT_STRUCTURING_PROMPT` |

Monkey-patching works because `get_prompts()` reads module-level constants **at call time**, not at import time. No files are modified on disk — purely in-memory, process-scoped.

---

## 11. Examples

### Quick Analysis (what's failing?)

```bash
$ python -m meta_agent analyze reports/AIF/banana_20260209_102935.md -v

Parsed AIF report: banana
  Exchanges: 2, Failures: 2
Calling gemini-2.5-pro for Stage 1 analysis...
Analysis complete: 2 suspected nodes
  - generate_response (high): 2 failures
  - generate_question (medium): 1 failures

==================================================
Source: AIF
Severity: critical
Suspected nodes: 2
  - generate_response (high): 2 failures, types=['explanation', 'gentle_correction']
  - generate_question (medium): 1 failures, types=[]
```

### Full Evolution (fix what's broken)

```bash
$ python -m meta_agent evolve reports/AIF/banana_20260209_102935.md -v -f markdown -o evolution.md

============================================================
STAGE 1: Report Analysis
============================================================
Parsed AIF report: banana
  Exchanges: 2, Failures: 5
...

============================================================
STAGE 2: Architecture Diagnosis
============================================================
Built architecture context (4521 chars)
  Suspected nodes: [generate_response, generate_question]
Diagnosis complete: 2 root causes
  Proposed changes: 2
  - [MODIFY_PROMPT] explanation_response_prompt (P1, medium)
  - [CREATE_NODE] validate_question_complexity (P2, medium)

============================================================
STAGE 3: Verification Loop
============================================================
  Testable prompt changes: 1
  Structural proposals (untestable): 1

  Testing: explanation_response_prompt (P1)
    Iteration 1/3
      Patching EXPLANATION_RESPONSE_PROMPT...
      Running primary scenario...
      Primary failures: set()
      Remaining original: set()
      Newly introduced: set()
      Running 3 CV scenario(s)...
      ACCEPTED! Scenario saved to: tests/quality/scenarios/generated/EVOLVE-banana-20260211-001.yaml
      Restored EXPLANATION_RESPONSE_PROMPT

==================================================
EVOLUTION RESULT
==================================================
Verified changes: 1
  - explanation_response_prompt: eliminated MISSED_TEACHABLE_MOMENT, ABANDONED_INTENT
    Scenario saved: tests/quality/scenarios/generated/EVOLVE-banana-20260211-001.yaml
Unverified proposals: 1
Rejected attempts: 0

1 prompt change(s) verified and auto-saved. 1 structural change(s) proposed.

===========================================================
  STRUCTURAL CHANGES PROPOSED (requires human review)
===========================================================

1. [CREATE_NODE] "validate_question_complexity" (priority: 2, risk: medium)
   Purpose: Check question complexity before sending to child
   Position: After generate_question, before finalize
   Rationale: Questions consistently too complex for age group.

To continue evolution after implementing these changes:
  python -m meta_agent evolve <new_report>
===========================================================

Results saved to: evolution.md
```

### Rejection Example (learning loop in action)

```bash
  Testing: explanation_response_prompt (P1)
    Iteration 1/3
      REJECTED [HARDCODED]: Contains specific object name 'banana'
      Re-running Stage 2 with hardcoding feedback...
    Iteration 2/3
      Patching EXPLANATION_RESPONSE_PROMPT...
      Running primary scenario...
      REJECTED [OVERFITTING]: CV regression in SCAFFOLD-WHY-002
      Re-running Stage 1+2 with failure context...
    Iteration 3/3
      Patching EXPLANATION_RESPONSE_PROMPT...
      Running primary scenario...
      Running 3 CV scenario(s)...
      ACCEPTED!
```
