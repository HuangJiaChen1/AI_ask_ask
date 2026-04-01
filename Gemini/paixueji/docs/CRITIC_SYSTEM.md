# Critic System — Complete Technical Reference

> **Purpose:** Single source of truth for the Pedagogical Quality Critique System.
> A future agent should be able to implement any feature using only this document.
>
> **Last updated:** 2026-02-10

---

## 1. Architecture Overview

The Critic System evaluates whether the Paixueji AI's responses **actually advance children's learning** — going beyond checklist compliance to expert-level pedagogical analysis.

### Two Report Types

| Report | Trigger | Pipeline | Saved to |
|--------|---------|----------|----------|
| **AIF** (AI Feedback) | User clicks "AI Critique" in UI | `PedagogicalCritiquePipeline` → Gemini LLM | `reports/AIF/{object}_{timestamp}.md` |
| **HF** (Human Feedback) | User fills manual critique form in UI | No LLM — human text only | `reports/HF/{object}_{timestamp}.md` |

### Conversation Structure

Current sessions are recorded as a single chat-phase conversation:

- **Chat Phase** (`mode="chat"`) — Exploratory Q&A that may end with theme classification and activity handoff.

Human-feedback reports are generated as a single conversation critique. Historical reports may still contain legacy guide-phase sections.

### System Diagram

```
                          ┌─────────────────────────────────┐
                          │         paixueji_app.py          │
                          │                                   │
  UI (app.js)             │  POST /api/critique               │
  ─────────────────────►  │    → build transcript             │
  "AI Critique" button    │    → build transcript             │
                          │    → spawn background thread      │
                          │                                   │
                          │  run_critique_background()        │
                          │    └─ transcript ───────────────► PedagogicalCritiquePipeline.critique_transcript(mode="chat")
                          │                                   │
                          │  For EACH exchange (model→child→model):
                          │    1. PedagogicalAnalyzer.analyze()   ← extract context
                          │    2. ExpertCritic.critique()         ← "picky teacher" review
                          │                                   │
                          │  compile_conversation_critique()  │
                          │    → aggregate scores, failures    │
                          │                                   │
                          │  CritiqueReportGenerator          │
                          │    .to_combined_markdown()         │
                          │    → save to reports/AIF/          │
                          └─────────────────────────────────┘

  UI (app.js)             ┌──────────────────────────────────┐
  ─────────────────────►  │  POST /api/manual-critique        │
  "Manual Critique" form  │    → build_human_feedback_report() │
                          │    → save to reports/HF/           │
                          └──────────────────────────────────┘
```

---

## 2. File Map

All paths relative to `paixueji/`. Listed in dependency order (leaf modules first).

| File | Purpose |
|------|---------|
| `tests/quality/schema.py` | All Pydantic models, enums, and data structures |
| `tests/quality/pedagogical_analyzer.py` | `PedagogicalAnalyzer` — extracts teaching intent and knowledge gaps via LLM |
| `tests/quality/expert_critic.py` | `ExpertCritic` — the "picky teacher" LLM reviewer |
| `tests/quality/pattern_analyzer.py` | `MultiTurnPatternAnalyzer` — detects multi-turn patterns (repeated failures, stuck loops) |
| `tests/quality/critique_report.py` | `CritiqueReportGenerator` + `compile_conversation_critique()` — report formatting and aggregation |
| `tests/quality/scenario_runner.py` | `ScenarioRunner` + `ResponseCapture` — runs scenarios through the real graph |
| `tests/quality/pipeline.py` | `PedagogicalCritiquePipeline` + `ScenarioLoader` — main orchestrator |
| `tests/quality/cli.py` | CLI interface with 6 commands |
| `tests/quality/__init__.py` | Package exports (all public classes and functions) |
| `tests/quality/scenarios/scaffold_failures.yaml` | 4 scenarios testing scaffolding |
| `tests/quality/scenarios/explanation_gaps.yaml` | 4 scenarios testing explanations |
| `tests/quality/scenarios/teaching_effectiveness.yaml` | 6 scenarios testing adaptive teaching |
| `paixueji_app.py` (lines 1837–2553) | Flask endpoints + background worker for critique |
| `static/app.js` (lines 1279–1553) | Frontend: critique modal, exchange fetching, manual form |

---

## 3. Schema Reference

**File:** `tests/quality/schema.py`

### Enums

#### `QuestionType(str, Enum)`
| Value | Meaning |
|-------|---------|
| `WHY` | Causation, reasoning |
| `WHAT` | Description, identification |
| `HOW` | Process, mechanism |
| `WHERE` | Location, spatial |
| `WHEN` | Temporal |
| `WHICH` | Selection, comparison |
| `OPEN` | Open-ended exploration |
| `STATEMENT` | Not a question |

#### `ResponseType(str, Enum)`
| Value | Meaning |
|-------|---------|
| `ANSWER` | Attempted answer (right or wrong) |
| `PARTIAL` | Partially correct or incomplete |
| `CONFUSED` | Shows confusion or misunderstanding |
| `DONT_KNOW` | Explicit "I don't know" |
| `OFF_TOPIC` | Unrelated response |
| `QUESTION` | Child asks a question back |
| `ENGAGEMENT` | Shows interest but no answer |

#### `FailureType(str, Enum)`

**Single-turn failures:**
| Value | Meaning |
|-------|---------|
| `SAME_QUESTION_REPHRASED` | Same thing in different words without adding info |
| `MISSED_SCAFFOLD` | Failed to provide a hint when child was stuck |
| `WRONG_QUESTION_TYPE` | Changed question type inappropriately (e.g. WHY→WHAT) |
| `NO_NEW_INFO` | Adds nothing new to help understanding |
| `ABANDONED_INTENT` | Gave up on the teaching goal |
| `IGNORED_CONFUSION` | Didn't address apparent confusion |
| `TOO_COMPLEX` | Made it harder than necessary for the age |
| `TOO_SIMPLE` | Underestimated the child or was patronizing |
| `MISSED_TEACHABLE_MOMENT` | Had opportunity to teach but didn't |
| `OTHER` | Some other pedagogical failure |

**Multi-turn failures:**
| Value | Meaning |
|-------|---------|
| `REPEATED_SCAFFOLD_FAILURE` | Same scaffold approach 2+ times |
| `STUCK_LOOP` | Conversation circles without progress |
| `PREMATURE_ADVANCEMENT` | Moves on when child still confused |
| `ENGAGEMENT_DECLINE` | Child responses getting shorter/less engaged |
| `LOST_THREAD` | Abandoned original learning goal |

#### `Severity(str, Enum)`
| Value | Meaning |
|-------|---------|
| `CRITICAL` | Fundamentally breaks learning |
| `MAJOR` | Significantly impairs learning |
| `MINOR` | Small missed opportunity |

### Models

#### `PedagogicalContext(BaseModel)`
Extracted by `PedagogicalAnalyzer` for each exchange.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `question_type` | `QuestionType` | required | Type of question asked |
| `question_intent` | `str` | required | What the model is trying to get the child to understand |
| `target_knowledge` | `str` | required | Specific knowledge/concept being taught |
| `child_response_type` | `ResponseType` | required | How the child responded |
| `knowledge_gap` | `str` | required | What the child's response reveals they don't understand |
| `ideal_next_action` | `str` | required | What the model should do to advance learning |
| `acceptable_actions` | `list[str]` | `[]` | Alternative acceptable approaches |
| `unacceptable_actions` | `list[str]` | `[]` | Actions that would fail pedagogically |

#### `Failure(BaseModel)`

| Field | Type | Description |
|-------|------|-------------|
| `type` | `FailureType` | Category of failure |
| `description` | `str` | Specific description |
| `evidence` | `str` | Exact text showing the problem |
| `severity` | `Severity` | How serious |

#### `ExpectedVsActual(BaseModel)`

| Field | Type | Description |
|-------|------|-------------|
| `i_expected` | `str` | What a good response would do |
| `but_got` | `str` | What the model actually did |
| `this_is_problematic_because` | `str` | Why it fails pedagogically |

#### `ExchangeCritique(BaseModel)`
Critique of a single model→child→model exchange.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `turn_number` | `int` | required | Which turn in the conversation |
| `model_question` | `str` | required | What the model asked |
| `child_response` | `str` | required | What the child said |
| `model_actual` | `str` | required | How the model responded |
| `mode` | `str` | `"chat"` | Exchange mode: "chat" or "guide" |
| `nodes_executed` | `list[dict]` | `[]` | Node execution trace `[{node, time_ms, changes}]` |
| `context` | `PedagogicalContext` | required | Extracted pedagogical context |
| `advances_learning` | `bool` | required | Whether the response advances understanding |
| `addresses_knowledge_gap` | `bool` | required | Whether it addresses the identified gap |
| `effectiveness_score` | `int` (1-10) | required | Overall effectiveness |
| `failures` | `list[Failure]` | `[]` | Identified failures |
| `expected_vs_actual` | `ExpectedVsActual \| None` | `None` | Comparison if failures exist |
| `ideal_response` | `str` | required | What an ideal response would look like |
| `improvements` | `list[str]` | `[]` | Specific improvement suggestions |
| `picky_observations` | `list[str]` | `[]` | Detailed observations from the picky critic |

#### `ConversationCritique(BaseModel)`
Full critique of an entire conversation (or phase).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `scenario_id` | `str` | required | Scenario identifier (or "transcript" for live) |
| `scenario_name` | `str` | required | Human-readable name |
| `overall_effectiveness` | `float` (0-100) | required | Average effectiveness percentage |
| `total_exchanges` | `int` | required | Number of exchanges analyzed |
| `failed_exchanges` | `int` | required | Number with failures |
| `failure_breakdown` | `dict[str, int]` | `{}` | Count of each failure type |
| `exchange_critiques` | `list[ExchangeCritique]` | `[]` | Per-exchange details |
| `critical_failures` | `list[str]` | `[]` | Most important problems |
| `improvement_priorities` | `list[str]` | `[]` | Ordered list of what to fix first |

#### `MultiTurnPattern(BaseModel)`

| Field | Type | Description |
|-------|------|-------------|
| `pattern_type` | `FailureType` | Multi-turn failure type |
| `severity` | `Severity` | Pattern severity |
| `turns_affected` | `list[int]` | Which turn numbers exhibit this |
| `description` | `str` | Human-readable description |
| `evidence` | `str` | Specific examples from the conversation |

#### Scenario Models

**`ScenarioExchange(BaseModel)`**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `role` | `Literal["model", "child"]` | required | Speaker |
| `content` | `str` | required | What they said |
| `pedagogical_intent` | `str \| None` | `None` | Model turn: teaching intent |
| `question_type` | `QuestionType \| None` | `None` | Model turn: question type |
| `target_knowledge` | `str \| None` | `None` | Model turn: knowledge target |
| `response_type` | `ResponseType \| None` | `None` | Child turn: response type |
| `knowledge_gap` | `str \| None` | `None` | Child turn: gap revealed |

**`ScenarioEvaluation(BaseModel)`**

| Field | Type | Default |
|-------|------|---------|
| `must_do` | `list[str]` | `[]` |
| `must_not_do` | `list[str]` | `[]` |
| `ideal_response_pattern` | `str \| None` | `None` (regex pattern) |

**`ScenarioSetup(BaseModel)`**

| Field | Type | Default |
|-------|------|---------|
| `object_name` | `str` | required |
| `key_concept` | `str` | required |
| `age` | `int` (3-12) | required |
| `mode` | `str` | `"chat"` |

**`Scenario(BaseModel)`**

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | required |
| `name` | `str` | required |
| `description` | `str` | required |
| `setup` | `ScenarioSetup` | required |
| `conversation` | `list[ScenarioExchange]` | `[]` |
| `evaluation` | `ScenarioEvaluation` | required |

---

## 4. Pipeline Internals

### 4.1 PedagogicalAnalyzer

**File:** `tests/quality/pedagogical_analyzer.py`
**Purpose:** Extract structured pedagogical context from each exchange before the critic reviews it.

**Model config:** `temperature=0.1`, `response_mime_type="application/json"`
**Default model:** `gemini-2.5-pro`

#### Prompt Template (`ANALYZER_PROMPT`)

```
You are an educational expert analyzing a single exchange in a children's learning conversation.

CONTEXT:
- Object being discussed: {object_name}
- Key concept being taught: {key_concept}
- Child's age: {age}

EXCHANGE:
- Model said: "{model_utterance}"
- Child responded: "{child_response}"

Analyze this exchange and extract:
1. Question Type (WHY/WHAT/HOW/WHERE/WHEN/WHICH/OPEN/STATEMENT)
2. Question Intent
3. Target Knowledge
4. Child Response Type (ANSWER/PARTIAL/CONFUSED/DONT_KNOW/OFF_TOPIC/QUESTION/ENGAGEMENT)
5. Knowledge Gap
6. Ideal Next Action
7. Acceptable Actions
8. Unacceptable Actions

OUTPUT as JSON: { ... }
```

#### Methods

| Method | Signature | API Pattern |
|--------|-----------|-------------|
| `analyze()` | `async (model_utterance, child_response, setup) → PedagogicalContext` | `client.aio.models.generate_content()` with plain dict config |
| `analyze_sync()` | `sync (model_utterance, child_response, setup) → PedagogicalContext` | `client.models.generate_content()` with `GenerateContentConfig` |
| `from_scenario_metadata()` | `@staticmethod (exchange_model, exchange_child, setup) → PedagogicalContext` | No LLM call — uses pre-defined metadata |

**Error handling:** On `JSONDecodeError`/`KeyError`/`ValueError`, returns a default `PedagogicalContext` with `QuestionType.OPEN` and placeholder strings.

### 4.2 ExpertCritic

**File:** `tests/quality/expert_critic.py`
**Purpose:** The "picky teacher" — a strong reasoning LLM that reviews each exchange like a frustrated, demanding educational expert.

**Model config:** `temperature=0.3`, `response_mime_type="application/json"`
**Default model:** `gemini-2.5-pro`

#### Prompt Template (`EXPERT_CRITIC_PROMPT`)

```
You are a VERY PICKY educational expert reviewing a children's learning conversation.
You are easily frustrated when teaching is ineffective. Be critical, specific, and demanding.

CONTEXT:
- Object: {object_name}
- Key Concept: {key_concept}
- Child's Age: {age}

PEDAGOGICAL ANALYSIS (from pre-analysis):
- Question Type: {question_type}
- Question Intent: {question_intent}
- Target Knowledge: {target_knowledge}
- Child Response Type: {child_response_type}
- Knowledge Gap: {knowledge_gap}
- Ideal Next Action: {ideal_next_action}
- Acceptable Actions: {acceptable_actions}
- Unacceptable Actions: {unacceptable_actions}

SCENARIO REQUIREMENTS:
- Must do: {must_do}
- Must not do: {must_not_do}

ACTUAL EXCHANGE:
Model asked: "{model_question}"
Child responded: "{child_response}"
Model then said: "{model_actual_response}"

YOUR TASK: (4 review criteria)
1. Does the response ADVANCE learning?
2. Is this what the child NEEDED?
3. Specific Failures (be picky!)
4. What SHOULD have happened?

FAILURE TYPES to consider: (10 single-turn types listed)

OUTPUT FORMAT (JSON): { advances_learning, addresses_knowledge_gap,
  effectiveness_score, failures[], expected_vs_actual{}, ideal_response,
  improvement_suggestions[], picky_observations[] }
```

#### Methods

| Method | Signature | API Pattern |
|--------|-----------|-------------|
| `critique()` | `async (turn_number, model_question, child_response, model_actual_response, context, setup, evaluation) → ExchangeCritique` | `client.aio.models.generate_content()` with plain dict config |
| `critique_sync()` | Same args, sync | `client.models.generate_content()` with `GenerateContentConfig` |
| `_parse_critique()` | Internal — parses JSON response to `ExchangeCritique` | N/A |

**Score clamping:** `effectiveness_score` is clamped to `max(1, min(10, value))`.
**Error handling:** On `JSONDecodeError`, returns a default critique with score=1 and a single `OTHER` failure.

### 4.3 MultiTurnPatternAnalyzer

**File:** `tests/quality/pattern_analyzer.py`
**Purpose:** Detects patterns that only emerge over multiple turns.

**Model config:** `temperature=0.3`, `response_mime_type="application/json"`
**Minimum turns:** Requires `>= 2` exchange critiques, otherwise returns empty.

#### Key Method

```python
async def analyze_patterns(
    exchange_critiques: list[ExchangeCritique],
    setup: ScenarioSetup,
) -> tuple[list[MultiTurnPattern], str, str]
    # Returns: (patterns, trajectory, learning_progress)
    # trajectory: "improving" | "declining" | "stable" | "mixed" | "unknown"
```

#### `SimulationCritiqueSummary`

Helper class that combines per-turn critiques with pattern analysis:

| Property | Returns |
|----------|---------|
| `has_multi_turn_failures` | `bool` |
| `critical_patterns` | `list[MultiTurnPattern]` filtered to CRITICAL |
| `average_effectiveness` | `float` (average of effectiveness_score) |
| `to_markdown_summary()` | `str` — markdown section for the report |

### 4.4 PedagogicalCritiquePipeline

**File:** `tests/quality/pipeline.py`
**Purpose:** Main orchestrator — takes a scenario or transcript and produces a `ConversationCritique`.

#### Constructor

```python
PedagogicalCritiquePipeline(
    client: genai.Client,
    analyzer_model: str = "gemini-2.5-pro",
    critic_model: str = "gemini-2.5-pro",
)
```

Creates internal `PedagogicalAnalyzer` and `ExpertCritic` instances.

#### Methods

| Method | Purpose | Input | Output |
|--------|---------|-------|--------|
| `critique_scenario()` | Critique a scenario with provided model responses | `(scenario, model_responses: list[str])` | `ConversationCritique` |
| `critique_transcript()` | Critique a raw transcript (used by Flask app) | `(transcript, object_name, key_concept, age, mode)` | `ConversationCritique` |
| `run_and_critique()` | Run scenario through real graph, then critique | `(scenario)` | `ConversationCritique` |
| `_extract_exchanges()` | Extract `(model_q, child_r, model_actual)` tuples from scenario | Internal | `list[tuple[str, str, str]]` |

#### `critique_transcript()` Details (the one used by the Flask app)

When `mode="guide"`:
- `setup.guide_phase = "active"`
- `evaluation.must_do = ["Advance understanding toward the key concept", "Scaffold when child is stuck"]`
- `evaluation.must_not_do = ["Rephrase without adding information", "Abandon the key concept"]`
- `scenario_name = "Guide Phase Analysis"`

When `mode="chat"`:
- `setup.guide_phase = "chat"`
- `evaluation.must_do = ["Engage curiosity", "Ask age-appropriate questions", "Respond with encouragement and new information"]`
- `evaluation.must_not_do = ["Rephrase without adding information", "Ignore the child's responses"]`
- `scenario_name = "Chat Phase Analysis"`

Exchange extraction: Finds triplets `(transcript[i]=model, transcript[i+1]=child, transcript[i+2]=model)`, using `i += 2` to allow overlapping model responses. Attaches `nodes_executed` and `mode` from `transcript[i+2]`.

### 4.5 compile_conversation_critique()

**File:** `tests/quality/critique_report.py`
**Purpose:** Aggregate individual `ExchangeCritique`s into a `ConversationCritique`.

```python
def compile_conversation_critique(
    scenario_id: str,
    scenario_name: str,
    exchange_critiques: list[ExchangeCritique],
) -> ConversationCritique
```

**Aggregation logic:**
- `overall_effectiveness = (sum of effectiveness_scores / count) * 10` — scales 1-10 average to 0-100
- `failed_exchanges = count of exchanges where len(failures) > 0`
- `failure_breakdown = {failure_type: count}` across all exchanges
- `critical_failures = ["Exchange N: description"]` for all CRITICAL severity failures
- `improvement_priorities = first 5 unique improvement suggestions from exchanges`

**Empty case:** Returns a zeroed-out `ConversationCritique` if no exchanges.

---

## 5. Report Generation

**File:** `tests/quality/critique_report.py`
**Class:** `CritiqueReportGenerator`

All methods are `@staticmethod`.

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `to_json()` | `(critique) → str` | Calls `critique.model_dump_json(indent=2)` |
| `to_markdown()` | `(critique) → str` | Single-phase markdown report |
| `to_combined_markdown()` | `(chat_critique, guide_critique, key_concept=None) → str` | Two-phase combined report (used by Flask AIF) |
| `to_html()` | `(critique) → str` | Dark-themed HTML with inline CSS |
| `save_report()` | `(critique, output_path, format) → Path` | Saves to disk with correct extension |
| `_format_exchange_markdown()` | `(exchange) → list[str]` | Single exchange as markdown |
| `_format_node_trace()` | `(nodes_executed) → list[str]` | Node execution trace table |
| `_md_to_html()` | `(md) → str` | Simple markdown→HTML converter |

### Markdown Report Structure

```markdown
# Pedagogical Critique Report
**Generated:** YYYY-MM-DD HH:MM:SS

## Scenario: {name}
**ID:** `{id}`

### Overall Effectiveness: {emoji} {score}/100
- **Total Exchanges Analyzed:** N
- **Exchanges with Failures:** N

### Failure Breakdown (table)
### Critical Failures (list)
### Improvement Priorities (numbered list)

---

## Detailed Exchange Analysis

### Exchange N - {severity_marker}
  **Model asked:** "..."
  **Child said:** "..."
  **Model responded:** "..."
  **Effectiveness:** [█████░░░░░] 5/10
  - Advances Learning: ✅/❌
  - Addresses Knowledge Gap: ✅/❌

  #### Pedagogical Context (6 fields)
  #### Node Execution Trace (table, if available)
  #### Expected vs Actual (blockquote)
  #### Failures (numbered, with severity icons)
  #### Ideal Response (blockquote)
  #### Picky Observations (list)
  #### Improvement Suggestions (list)
```

### Combined Report (to_combined_markdown) Structure

```markdown
# Pedagogical Critique Report
**Generated:** YYYY-MM-DD HH:MM:SS
**Total Exchanges:** N (Chat: N, Guide: N)

## Chat Phase — AI Critique
> Exploratory Q&A. NOT evaluated for key concept guidance.
### Overall Effectiveness: ...
(exchanges)

---

## Guide Phase — AI Critique
> Key Concept: **{concept}**. Evaluated for concept advancement.
### Overall Effectiveness: ...
(exchanges)
```

### Severity Markers

| Condition | Marker |
|-----------|--------|
| Any CRITICAL failure | `🔴 CRITICAL` |
| Any MAJOR failure (no critical) | `🟠 MAJOR` |
| Only MINOR failures | `🟡 MINOR` |
| No failures | `🟢 OK` |

### Effectiveness Emoji

| Score | Emoji |
|-------|-------|
| >= 70 | ✅ |
| >= 40 | ⚠️ |
| < 40 | ❌ |

---

## 6. App Integration (paixueji_app.py)

### Global State

```python
critique_tasks: dict[str, dict] = {}
# Each task: {status, session_id, report_path, error, overall_effectiveness, started_at}
# status: "pending" | "running" | "completed" | "failed"
```

### Endpoints

#### `POST /api/critique` (line 1992)
Start background AI critique.

**Request:** `{"session_id": "uuid"}`
**Response:** `{"success": true, "task_id": "uuid", "message": "..."}`

**Logic:**
1. Validates session exists and has >= 3 transcript entries
2. Builds transcript from `assistant.conversation_history` (skips system messages)
3. Maps roles: `"assistant"` → `"model"`, `"user"` → `"child"`
4. Copies `nodes_executed` and `mode` from model messages
5. Captures `object_name`, `key_concept`, `ibpyp_theme_name`, `age` from session
6. Spawns daemon `threading.Thread` running `run_critique_background()`

#### `GET /api/critique/status/<task_id>` (line 2089)
Poll critique progress.

**Response:** `{success, task_id, status, session_id, report_path, overall_effectiveness, error, elapsed_seconds}`

#### `GET /api/exchanges/<session_id>` (line 2124)
Extract exchange triplets for the manual critique form.

**Response:**
```json
{
  "success": true,
  "exchanges": [
    {
      "index": 1,
      "model_question": "...",
      "child_response": "...",
      "model_response": "...",
      "nodes_executed": [...],
      "mode": "chat"
    }
  ],
  "object_name": "apple",
  "age": 6,
  "key_concept": "...",
  "ibpyp_theme_name": "..."
}
```

#### `POST /api/manual-critique` (line 2200)
Save human feedback critique.

**Request:**
```json
{
  "session_id": "uuid",
  "exchange_critiques": [
    {
      "exchange_index": 1,
      "model_question_expected": "...",
      "model_question_problem": "...",
      "model_response_expected": "...",
      "model_response_problem": "...",
      "conclusion": "..."
    }
  ],
  "global_conclusion": "..."
}
```

**Response:** `{"success": true, "report_path": "reports/HF/...", "exchanges_critiqued": N}`

#### `GET /api/critique/report/<task_id>` (line 2498)
Retrieve completed AIF report content.

**Response:** `{"success": true, "report_content": "# Critique Report...", "report_path": "...", "overall_effectiveness": 75.5}`

### Background Worker: `run_critique_background()` (line 1837)

```python
def run_critique_background(task_id, session_id, transcript, object_name,
                             key_concept, age, ibpyp_theme_name=None):
```

**Two-phase split logic:**
1. Iterate transcript looking for `model→child→model` triplets
2. Check `mode` on `transcript[i+2]` (the model's response message)
3. If `mode == "guide"` → append triplet to `guide_transcript`
4. Otherwise → append to `chat_transcript`

**Pipeline execution:**
1. Creates new `asyncio` event loop for the thread
2. Instantiates `PedagogicalCritiquePipeline(GLOBAL_GEMINI_CLIENT)`
3. Runs `pipeline.critique_transcript()` for chat (if chat exchanges exist)
   - `key_concept = f"general knowledge about {object_name}"`
4. Runs `pipeline.critique_transcript()` for guide (if guide exchanges exist)
   - Uses the actual `key_concept` from the session
5. Generates combined markdown via `CritiqueReportGenerator.to_combined_markdown()`

**Report construction:**
- Prepends header with object_name, session_id, age, IB PYP theme, key_concept, date
- Includes full conversation transcript with mode labels (`[CHAT]`/`[GUIDE]`) and node traces
- Appends the combined critique markdown

**Effectiveness calculation (weighted average):**
```python
combined = (chat_eff * chat_n + guide_eff * guide_n) / total_n
```

**Save path:** `reports/AIF/{safe_object_name}_{timestamp}.md`

### Human Feedback Report: `build_human_feedback_report()` (line 2339)

Structures into Chat Phase and Guide Phase sections, mirroring AIF. Classifies critiqued exchanges by `mode` field from `all_exchanges`.

### `_render_hf_exchange()` (line 2444)

Renders a single HF exchange including:
- Exchange text (model_question, child_response, model_response)
- Node execution trace table (if available)
- Human critique sections (expected/problem for question and response)
- Conclusion

---

## 7. Frontend (app.js)

### Critique Choice Modal (line 1279)

`showCritiqueModal()` — Shows a modal with two options:
- **AI Critique** → calls `startAICritique()`
- **Manual Critique** → calls `startManualCritique()`

### AI Critique Flow (line 1298)

`startAICritique()`:
1. `POST /api/critique` with `{session_id}`
2. Receives `task_id`
3. Polls `GET /api/critique/status/{task_id}` until completed/failed
4. On completion, fetches `GET /api/critique/report/{task_id}`
5. Displays report content

### Manual Critique Flow (line 1341)

`startManualCritique()`:
1. `GET /api/exchanges/{session_id}` → fetches all exchanges
2. **Phase grouping:**
   - `chatExchanges = exchanges.filter(e => (e.mode || 'chat') !== 'guide')`
   - `guideExchanges = exchanges.filter(e => (e.mode || 'chat') === 'guide')`
3. Renders phase headers:
   - Chat: `"Chat Phase (N exchanges — exploratory Q&A)"`
   - Guide: `"Guide Phase (N exchanges — key concept: {concept})"`
4. For each exchange, renders a card with checkbox and expandable form
5. Form fields per exchange: model_question_expected, model_question_problem, model_response_expected, model_response_problem, conclusion

### Form Rendering (line 1442)

`buildExchangeCritiqueFormHTML(exchange)`:
- Shows full text of model_question, child_response, model_response in colored boxes
- 4 textarea fields + 1 conclusion textarea
- Toggled by `toggleExchangeCritique(index)` when checkbox clicked

### Submission (line 1493)

`submitManualCritique()`:
1. Collects all checked exchanges with filled-in critique fields
2. Validates at least one exchange selected
3. `POST /api/manual-critique` with `{session_id, exchange_critiques, global_conclusion}`
4. Shows success message with report path

---

## 8. Scenario System

### YAML Format

```yaml
scenarios:
  - id: "SCAFFOLD-WHY-001"        # Unique ID (CATEGORY-TYPE-NNN)
    name: "Human-readable name"
    description: "What this scenario tests"

    setup:
      object_name: "banana"
      key_concept: "color change / ripening / oxidation"
      age: 5
      guide_phase: "active"       # "active", "exploration", "introduction"

    conversation:
      - role: "model"
        content: "Question text"
        pedagogical_intent: "What model is trying to teach"    # optional
        question_type: "WHY"                                    # optional
        target_knowledge: "Specific knowledge target"           # optional

      - role: "child"
        content: "Child response"
        response_type: "DONT_KNOW"                              # optional
        knowledge_gap: "What child doesn't understand"          # optional

    evaluation:
      must_do:
        - "Required action 1"
        - "Required action 2"
      must_not_do:
        - "Forbidden action 1"
      ideal_response_pattern: "regex|pattern"                   # optional
```

### All 14 Scenarios

#### `scaffold_failures.yaml` — 4 scenarios

| ID | Name | Object | Concept | Age | Response Type |
|----|------|--------|---------|-----|---------------|
| `SCAFFOLD-WHY-001` | Child says "I don't know" to WHY question | banana | color change / ripening / oxidation | 5 | DONT_KNOW |
| `SCAFFOLD-WHY-002` | Child gives wrong answer to WHY question | ice cube | melting / heat transfer | 6 | ANSWER |
| `SCAFFOLD-HOW-001` | Child is confused about a process | seed | plant growth | 5 | CONFUSED |
| `SCAFFOLD-PARTIAL-001` | Child gives partially correct answer | moon | moon phases | 7 | PARTIAL |

#### `explanation_gaps.yaml` — 4 scenarios

| ID | Name | Object | Concept | Age | Response Type |
|----|------|--------|---------|-----|---------------|
| `EXPLAIN-INCOMPLETE-001` | Child asks "why" and needs full explanation | rainbow | light refraction | 6 | QUESTION |
| `EXPLAIN-CURIOSITY-001` | Child shows genuine curiosity | caterpillar | metamorphosis | 5 | ENGAGEMENT |
| `EXPLAIN-ANALOGY-001` | Abstract concept needs concrete analogy | wind | air movement | 5 | QUESTION |
| `EXPLAIN-FOLLOWUP-001` | Child asks follow-up question | ant | ant behavior / teamwork | 6 | QUESTION |

#### `teaching_effectiveness.yaml` — 6 scenarios

| ID | Name | Object | Concept | Age | Response Type |
|----|------|--------|---------|-----|---------------|
| `TEACH-ADAPT-001` | Model should adapt to child's level | clock | telling time | 5 | PARTIAL |
| `TEACH-PATIENCE-001` | Multiple "I don't know" responses | shadow | light blocking | 5 | DONT_KNOW |
| `TEACH-CONNECT-001` | Model should connect to prior knowledge | snowflake | water states | 6 | ANSWER |
| `TEACH-PACE-001` | Model should not overwhelm with info | butterfly | life cycle | 5 | ENGAGEMENT |
| `TEACH-REDIRECT-001` | Model handles off-topic response | flower | pollination | 6 | OFF_TOPIC |

### ScenarioLoader

**File:** `tests/quality/pipeline.py` (class at line 289)

```python
class ScenarioLoader:
    def __init__(self, scenarios_dir: str | Path)
    def load_scenario(self, scenario_id: str) -> Scenario     # search all YAML files
    def load_all(self) -> list[Scenario]                        # all from all files
    def _load_yaml(self, path: Path) -> list[Scenario]          # parse single file
```

### ScenarioRunner

**File:** `tests/quality/scenario_runner.py`

Runs scenarios through the **real Paixueji graph** by:
1. Creating a `PaixuejiAssistant` instance
2. Setting `age`, `object_name` from scenario setup
3. For each child response in the scenario conversation:
   - Builds `PaixuejiState` dict (all state fields)
   - Creates `ResponseCapture` with async callback
   - Calls `await paixueji_graph.ainvoke(state)`
   - Captures full response text
4. Returns `list[str]` of model responses

**`ResponseCapture`** — Collects streaming chunks. Uses `chunk.finish` to detect final response. Falls back to concatenation if no finish chunk.

---

## 9. CLI

**File:** `tests/quality/cli.py`
**Invocation:** `python -m tests.quality.cli <command>`

### Commands

| Command | Description | Key Args |
|---------|-------------|----------|
| `demo` | Run a built-in demo critique (banana/ripening) | None |
| `list` | List all available scenarios | None |
| `critique` | Critique a specific scenario with provided responses | `-s SCENARIO_ID`, `-r responses.json`, `-o output`, `-f format` |
| `critique-all` | Critique all scenarios with pre-recorded responses | `-d responses-dir/`, `-o output` |
| `generate-responses` | Run scenarios through real Paixueji, save responses | `-s SCENARIO_ID` (optional), `-o output-dir` |
| `run-and-critique` | Run scenario through real system, then critique | `-s SCENARIO_ID` (required), `-o output`, `-f format`, `--save-responses path` |

### Demo Scenario (built-in)

- Object: banana, Concept: color change / ripening, Age: 5
- Model asks: "Why do you think the banana peel changes color as it gets older?"
- Child says: "I don't know"
- Tests with a BAD response: "Does the peel stay bright yellow, or does it start to get some brown spots?"
- Shows what a GOOD response would be: includes "air", "makes it change", "like an apple slice"

### Client Creation

`get_client()` loads `config.json` from project root for Vertex AI credentials:
```python
genai.Client(vertexai=True, project=config["project"], location=config["location"])
```

---

## 10. Data Flow Diagrams

### AIF (AI Feedback) Flow

```
User clicks "AI Critique"
        │
        ▼
app.js: POST /api/critique {session_id}
        │
        ▼
paixueji_app.py: critique_conversation()
        │
        ├─ Build transcript from assistant.conversation_history
        │   (skip system msgs, map roles, copy nodes_executed + mode)
        │
        ├─ Validate >= 3 entries
        │
        ├─ Create task in critique_tasks{}
        │
        └─ Spawn thread → run_critique_background()
                │
                ├─ Split transcript by mode:
                │   for each model→child→model triplet:
                │     mode = triplet[2].mode  (the model response's mode)
                │     → chat_transcript[] or guide_transcript[]
                │
                ├─ Chat phase (if non-empty):
                │   pipeline.critique_transcript(mode="chat")
                │     for each model→child→model triplet:
                │       1. PedagogicalAnalyzer.analyze()  → PedagogicalContext
                │       2. ExpertCritic.critique()         → ExchangeCritique
                │     compile_conversation_critique()       → ConversationCritique
                │
                ├─ Guide phase (if non-empty):
                │   pipeline.critique_transcript(mode="guide")
                │     (same sub-flow as chat)
                │
                ├─ CritiqueReportGenerator.to_combined_markdown(chat, guide)
                │
                ├─ Prepend header + transcript
                │
                ├─ Save to reports/AIF/{object}_{timestamp}.md
                │
                └─ Update critique_tasks[task_id] → status="completed"
                        │
        ┌───────────────┘
        ▼
app.js: Poll GET /api/critique/status/{task_id}
        │ (until status == "completed")
        ▼
app.js: GET /api/critique/report/{task_id}
        │
        └─ Display report_content in UI
```

### HF (Human Feedback) Flow

```
User clicks "Manual Critique"
        │
        ▼
app.js: GET /api/exchanges/{session_id}
        │
        ├─ Extract model→child→model triplets with mode
        │
        └─ Return {exchanges[], object_name, age, key_concept, ibpyp_theme_name}
                │
                ▼
app.js: Group by phase
        │
        ├─ chatExchanges  = exchanges where mode != "guide"
        ├─ guideExchanges = exchanges where mode == "guide"
        │
        └─ Render form with phase headers + exchange cards
                │
                ▼
User fills in critique fields, clicks Submit
        │
        ▼
app.js: POST /api/manual-critique {session_id, exchange_critiques[], global_conclusion}
        │
        ▼
paixueji_app.py: manual_critique()
        │
        ├─ Re-extract all exchanges (to match indices)
        │
        ├─ build_human_feedback_report()
        │   ├─ Classify critiqued exchanges by mode
        │   ├─ Render Chat Phase section (if any chat critiques)
        │   ├─ Render Guide Phase section (if any guide critiques)
        │   └─ Append global conclusion
        │
        └─ Save to reports/HF/{object}_{timestamp}.md
```

### Two-Phase Split Logic

```
Conversation History (assistant.conversation_history):
  [system, assistant(mode=chat), user, assistant(mode=chat), user, assistant(mode=guide), user, ...]

Transcript (after role mapping):
  [model(mode=chat), child, model(mode=chat), child, model(mode=guide), child, ...]

Split by triplets (model[i] → child[i+1] → model[i+2]):
  Triplet 1: model(chat) → child → model(chat)    → mode = chat   → chat_transcript
  Triplet 2: model(chat) → child → model(guide)   → mode = guide  → guide_transcript
  ...

Note: mode is determined by the RESPONDING model message (transcript[i+2]),
      not the questioning model message (transcript[i]).
      This means the first model message after a mode switch is what triggers
      the split — the transition exchange goes to the new phase.
```

---

## 11. Key Design Decisions

### Mode Stored Per-Message
Each model response in `conversation_history` carries its own `mode` field. This allows:
- Conversations to switch between chat and guide mid-conversation
- Accurate per-exchange phase classification for critique
- The split logic to use `transcript[i+2].mode` (the responding message)

### Two-Pipeline Split
Chat and guide phases are critiqued **separately** with different evaluation criteria:
- Chat: evaluated for engagement, curiosity, age-appropriateness
- Guide: evaluated for concept advancement, scaffolding, key concept focus
This prevents unfair penalization of chat exchanges for not advancing a specific concept.

### Weighted Effectiveness
Combined effectiveness uses weighted average by exchange count, not simple average:
```python
(chat_eff * chat_n + guide_eff * guide_n) / total_n
```
This ensures phases with more exchanges have proportionally more influence on the overall score.

### Analyzer → Critic Two-Step
The pipeline runs `PedagogicalAnalyzer` first to extract structured context, then passes it to `ExpertCritic`. This separation:
- Allows the analyzer to use a faster/cheaper model
- Gives the critic pre-analyzed context for more focused critique
- Makes the critic prompt more structured and less ambiguous

### Graceful Degradation
Both analyzer and critic return default/fallback objects on parse failure, never crashing the pipeline. The worst case is a low-quality critique, not a failed critique.

### Node Execution Traces
Every model response can carry `nodes_executed` — a list of `{node, time_ms, changes}` from the LangGraph execution. These are threaded through to the critique report for debugging which graph nodes ran and how long they took.

---

## 12. Extension Guide

### Adding a New Mode

1. **Schema:** No schema changes needed — `mode` is a plain `str` field on `ExchangeCritique`
2. **Conversation history:** Ensure the new mode is set on model messages in `assistant.conversation_history` as `msg["mode"] = "new_mode"`
3. **App split logic** (`run_critique_background`, line 1874): Add a third transcript list:
   ```python
   new_mode_transcript = []
   if mode == "new_mode":
       new_mode_transcript.extend(triplet)
   ```
4. **Pipeline evaluation criteria** (`critique_transcript`, line 200): Add a new `elif mode == "new_mode":` block with appropriate `setup`, `evaluation`, and `scenario_name`
5. **Report** (`to_combined_markdown`): Add a third section for the new mode
6. **Frontend** (`app.js`): Add a third filter in `startManualCritique()` and a third phase header

### Adding a New Failure Type

1. **Schema** (`schema.py`): Add to `FailureType` enum
2. **Expert Critic prompt** (`expert_critic.py`): Add the new type to `FAILURE TYPES to consider` section
3. **Pattern Analyzer** (`pattern_analyzer.py`): If multi-turn, add to `MULTI_TURN_FAILURE_DESCRIPTIONS`
4. No other changes needed — failure types are parsed dynamically from JSON

### Adding a New Evaluation Criterion

1. **Expert Critic prompt** (`expert_critic.py`): Add a new numbered item to `YOUR TASK` section
2. **Schema** (`schema.py`): Add field to `ExchangeCritique` if the criterion needs its own output field
3. **Expert Critic JSON output** (`expert_critic.py`): Add the new field to `OUTPUT FORMAT`
4. **`_parse_critique()`** (`expert_critic.py`): Parse the new field from JSON
5. **Report** (`critique_report.py`): Display the new field in `_format_exchange_markdown()`

### Adding a New Report Format

1. **`CritiqueReportGenerator`** (`critique_report.py`): Add a `to_{format}()` static method
2. **`save_report()`** (`critique_report.py`): Add an `elif format == "new_format":` branch
3. **CLI** (`cli.py`): Add to `choices=["json", "markdown", "html", "new_format"]` in argparse

### Adding a New Scenario

1. Create or edit a YAML file in `tests/quality/scenarios/`
2. Follow the YAML format documented in Section 8
3. Choose an appropriate ID pattern: `CATEGORY-TYPE-NNN`
4. The scenario will be auto-discovered by `ScenarioLoader.load_all()`
