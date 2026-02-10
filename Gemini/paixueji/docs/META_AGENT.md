# Meta-Agent Evolution System — Technical Reference

> **Purpose:** Automatically translates critic report failures into tested architectural improvements.
> Takes an AIF or HF report → identifies failing nodes → diagnoses root causes → proposes and **verifies** prompt changes.
>
> **Last updated:** 2026-02-10

---

## 1. Architecture Overview

The meta-agent is a **three-stage pipeline with a verification loop**:

```
                         ┌──────────────────────────────────┐
                         │          Meta-Agent Loop          │
                         │                                   │
  Critic Report (.md) ──►│  Stage 1: Report Analyzer         │
                         │    → ReportAnalysis (JSON)        │
                         │                                   │
                         │  Stage 2: Architecture Diagnoser  │
                         │    + architecture context         │
                         │    → ArchitectureDiagnosis (JSON) │
                         │                                   │
                         │  Stage 3: Verification Loop       │
                         │    ├─ Filter MODIFY_PROMPT changes │
                         │    ├─ Apply prompt patches         │
                         │    ├─ Run scenario (ScenarioRunner)│
                         │    ├─ Critique new output          │
                         │    └─ Compare: better?             │
                         │         ├─ YES → accept change     │
                         │         └─ NO → re-run Stage 1+2   │
                         │              with failure context   │
                         │              (max N iterations)     │
                         │                                   │
                         │  Final Output:                     │
                         │    verified_changes[] (tested)     │
                         │    proposed_changes[] (untested)   │
                         └──────────────────────────────────┘
```

### Two Tiers of Output

| Tier | What | Auto-applied? |
|------|------|---------------|
| **Verified changes** | Prompt modifications that were applied, tested via ScenarioRunner, and proven to improve effectiveness score | Safe to auto-apply |
| **Proposed changes** | Structural changes (new nodes, router modifications) that cannot be auto-tested | Requires human review |

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
# Full evolution with defaults (3 iterations, threshold 5.0)
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md

# Custom iteration limit and threshold
python -m meta_agent evolve reports/AIF/banana_20260209_102935.md --max-iterations 5 --threshold 10

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
| `--threshold` | evolve | 5.0 | Min effectiveness gain (points) to accept a change |
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

## 4. How Verification Works

Stage 3 only tests `MODIFY_PROMPT` changes. For each change:

```
1. BUILD SCENARIO     — Convert report exchanges into a Scenario object
2. PATCH PROMPT       — Monkey-patch paixueji_prompts module constant
3. RUN SCENARIO       — ScenarioRunner.run_scenario() with real graph
4. CRITIQUE OUTPUT    — PedagogicalCritiquePipeline.critique_scenario()
5. COMPARE SCORES     — new_effectiveness vs original + threshold
6. DECIDE             — Accept (verified) or Reject (feed failure back to Stage 1+2)
7. RESTORE PROMPT     — Always restore original (in finally block)
```

### On Rejection (the learning loop)

When a change fails to improve effectiveness, the system:
1. Records the attempt (old score, new score, new failure types)
2. Injects this context into the Stage 1+2 prompts as `PREVIOUS ATTEMPTS`
3. Re-runs Stage 1+2 with explicit instructions: "DO NOT repeat these failed approaches"
4. The reasoning model (with thinking enabled) is forced to explore different strategies

This continues up to `max_iterations` per prompt target.

### Safety

- Prompts are **always** restored in a `finally` block, even if the scenario crashes
- Structural changes (CREATE_NODE, MODIFY_ROUTER) are never auto-applied
- Each prompt is patched and restored independently

---

## 5. File Layout

```
meta_agent/
  __init__.py                  # Public exports + evolve() orchestrator
  __main__.py                  # Entry: python -m meta_agent
  schema.py                    # All Pydantic models (Stage 1, 2, 3)
  architecture_manifest.py     # Graph topology + node→prompt mapping + context builder
  report_parser.py             # AIF/HF markdown → ParsedReport
  prompts.py                   # LLM prompt templates (Stage 1 + 2)
  stage1_analyzer.py           # Report → ReportAnalysis (Gemini 2.5 Pro + thinking)
  stage2_diagnostician.py      # Analysis + arch context → ArchitectureDiagnosis
  stage3_verifier.py           # Verification loop: apply → test → compare → accept/reject
  cli.py                       # argparse CLI
```

---

## 6. LLM Configuration

Both Stage 1 and Stage 2 use **Gemini 2.5 Pro with extended thinking**:

```python
config = GenerateContentConfig(
    temperature=0.2,
    response_mime_type="application/json",
    thinking_config={"thinking_budget": 8192},
)
```

The thinking budget gives the model space for chain-of-thought reasoning before outputting structured JSON. This is critical for Stage 2's root cause diagnosis, where the model needs to trace failure mechanisms through multiple architectural layers.

---

## 7. Key Dependencies

The meta-agent reuses existing Paixueji infrastructure:

| Dependency | Used In | Purpose |
|------------|---------|---------|
| `paixueji_prompts` | Stage 3 | Monkey-patch target for prompt changes |
| `tests.quality.scenario_runner.ScenarioRunner` | Stage 3 | Runs scenarios through the real graph |
| `tests.quality.pipeline.PedagogicalCritiquePipeline` | Stage 3 | Critiques new output after prompt patch |
| `tests.quality.schema.Scenario` | Stage 3 | Scenario data model for test runs |
| `google.genai` (Vertex AI) | Stage 1, 2, 3 | LLM calls + scenario execution |

---

## 8. Examples

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
...

============================================================
STAGE 2: Architecture Diagnosis
============================================================
...

============================================================
STAGE 3: Verification Loop
============================================================
  Testable prompt changes: 2
  Structural proposals (untestable): 1

  Testing: explanation_response_prompt (P1)
    Iteration 1/3
      Patching EXPLANATION_RESPONSE_PROMPT...
      Running scenario...
      Critiquing new output...
      New effectiveness: 72.0 (baseline: 55.0)
      ACCEPTED! Delta: +17.0
      Restored EXPLANATION_RESPONSE_PROMPT

==================================================
EVOLUTION RESULT
==================================================
Verified changes: 1
Unverified proposals: 1
Rejected attempts: 0
Final effectiveness: 72.0/100

Results saved to: evolution.md
```
