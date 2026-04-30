# OpenSpec Integration Design

## Summary

Integrate OpenSpec as the structured file format for specs, changes, and test scenarios, while keeping the existing superpowers skills (`brainstorming`, `writing-plans`, `subagent-driven-development`, `verification-before-completion`) as the primary workflow engine. OpenSpec provides the directory structure and artifact schema; superpowers skills provide the AI-guided execution logic.

## Goals

- Give specs a structured home (`openspec/`) with version-controlled change tracking
- Enable simulation-based end-to-end testing from behavioral specs
- Make the brainstorming skill give concrete, opinionated architectural recommendations
- Preserve the existing superpowers skill chain that the team already uses

## Non-Goals

- Replace superpowers skills with OpenSpec's `/opsx:*` slash commands
- Require every project to adopt OpenSpec
- Change the existing Flask API or LangGraph structure
- Rewrite existing tests (they remain as-is)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         WORKFLOW ENGINE                              │
│              (superpowers skills — unchanged behavior)               │
│                                                                      │
│   brainstorming ──► writing-plans ──► subagent-driven-development ──► verify    │
│        │                │                  │                │        │
│        ▼                ▼                  ▼                ▼        │
│   reads/writes     reads/writes       reads/writes     reads       │
│   openspec/        openspec/          openspec/        openspec/    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         FILE FORMAT (OpenSpec)                       │
│                                                                      │
│   openspec/                                                          │
│   ├── specs/                    # Behavioral source of truth         │
│   │   ├── common/                                                    │
│   │   │   ├── voice_contract.md                                      │
│   │   │   ├── intent_taxonomy.md                                     │
│   │   │   └── state_schema.md                                        │
│   │   ├── pipelines/                                                 │
│   │   │   ├── introduction.md                                        │
│   │   │   ├── general_chat.md                                        │
│   │   │   ├── bridge.md                                              │
│   │   │   ├── attribute_activity.md                                  │
│   │   │   ├── category_activity.md                                   │
│   │   │   └── guide_mode.md                                          │
│   │   └── nodes/                                                     │
│   │       ├── correct_answer.md                                      │
│   │       ├── curiosity.md                                           │
│   │       ├── clarifying_idk.md                                      │
│   │       └── ...                                                    │
│   └── changes/                                                       │
│       ├── <change-name>/                                             │
│       │   ├── proposal.md                                            │
│       │   ├── design.md                                              │
│       │   ├── tasks.md                                               │
│       │   └── specs/                                                 │
│       │       └── <pipeline>/                                        │
│       │           └── spec.md         # Delta spec (ADDED/MODIFIED)  │
│       └── archive/                                                   │
│           └── <date>-<change-name>/                                  │
│                                                                      │
│   tests/e2e_scenarios/              # Simulation test scenarios      │
│   tests/harness/                    # Test harness (Layer 1-3)       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Subsystem 1: Opinionated Brainstorming

### Problem

The current `brainstorming` skill treats all decisions as collaborative choices. When the user asks architectural questions ("LangGraph or plain functions?", "how many intents?"), the skill presents A/B/C options rather than concrete recommendations. The user lacks the experience to judge these trade-offs and needs a mentor, not a menu.

### Changes

Modify `C:\Users\123\.claude\plugins\cache\claude-plugins-official\superpowers\5.0.7\skills\brainstorming\SKILL.md`:

1. **Add "Architectural Decision Mode" section** after "Exploring approaches":
   - When the user asks about architecture, framework choice, or system design:
     - DO NOT ask clarifying questions unless critical context is genuinely missing
     - DO NOT present A/B/C options for the user to pick
     - DO make a concrete recommendation with specific numbers, names, and configurations
     - DO include full trade-off analysis (gain, cost, risk, when to reconsider)
     - DO assume the user lacks experience to judge unless they demonstrate otherwise
   - Format: Recommendation → Why → Trade-offs → When to reconsider

2. **Strengthen "Exploring approaches"**:
   - Replace "Present options conversationally with your recommendation" with "Lead with your concrete recommendation — present alternatives only as supporting evidence"
   - Replace "Never ask 'which do you prefer?' unless the choice is purely aesthetic"

3. **Add expertise calibration clause**:
   - If user demonstrates expertise (specific technical vocabulary, prior architectural references) → engage as peer
   - If user demonstrates uncertainty (vague questions, "what do you think?", "I'm not sure") → engage as mentor, make the decision

4. **Modify "Key Principles"**:
   - Narrow "Multiple choice preferred" to aesthetic/preference decisions only
   - Add "Take a stance on architecture — uncertainty is worse than a wrong choice that can be revised"

### Risks

| Risk | Mitigation |
|------|-----------|
| Alienating expert users | Expertise calibration clause switches to peer mode |
| Wrong recommendations accepted uncritically | Mandatory "When to reconsider" section exposes failure conditions |
| Overfitting to this project | Changes scoped to architectural decisions; UI/UX brainstorming unchanged |

## Subsystem 2: Simulation Test Harness

### Problem

Current tests mock LLM calls and catch internal logic bugs, but miss interaction-level bugs (duplicate questions, REASON line leakage, wrong routing). The bug "why? → duplicated question" was obvious in production but invisible to tests.

### Design

Three-layer architecture:

**Layer 1: Session Driver** (`tests/harness/session_driver.py`)
- Wraps `app.test_client()` for SSE consumption
- Returns `TurnResult` with: full_response_text, final_chunk metadata, all chunks, duration, errors
- Validates every turn ends with `complete` or `error` event

**Layer 2: Scenario Engine** (`tests/harness/scenario_engine.py`)
- Parses OpenSpec Given/When/Then scenarios (YAML format)
- Maps `when` steps to HTTP calls, `then` steps to assertions
- Maintains cross-turn state for multi-turn scenarios

**Layer 3: Test Runner** (`tests/harness/runner.py`)
- Discovers `.yaml` scenarios in `tests/e2e_scenarios/`
- Runs each scenario N times (default 3 in CI) for stability
- Produces HTML/Markdown reports

### Scenario Format

```yaml
scenario: Why question does not duplicate the previous question
given:
  age: 6
  object_name: "apple"
when:
  - start_conversation
  - child_says: "Why?"
then:
  - response_type_is: "curiosity"
  - no_duplicate_questions: true
  - response_has_single_question: true
  - no_reason_leaked: true
```

### Assertion Registry

| Type | Examples | Implementation |
|------|----------|----------------|
| Structural | `intent_type_is`, `nodes_executed_include`, `no_reason_leaked` | Assert on `final_chunk` metadata |
| Content | `response_contains`, `no_duplicate_questions` | Text parsing and normalization |
| Cross-turn | `question_progresses`, `no_stuck_loop` | Compare across `TurnResult` history |
| Semantic | `response_is_encouraging` | LLM-as-judge (cheap model, cached) |

### Non-Determinism Handling

- **Retry logic**: Retry transient failures (e.g., streaming timeout) up to 2 times
- **Stability scoring**: Run 3× in CI, require ≥67% pass rate
- **Baseline diffing**: Record golden transcripts, flag deviations in nightly runs
- **Semantic assertions**: Use `gemini-2.0-flash-lite` as judge for quality criteria; cached

### Files Added

```
tests/
  e2e_scenarios/
    intro_attribute.yaml
    curiosity_why_no_duplicate.yaml
    idk_then_give_answer.yaml
    correct_answer_threshold.yaml
    bridge_activation.yaml
  harness/
    __init__.py
    session_driver.py
    scenario_engine.py
    assertions.py
    runner.py
    baseline.py
    judge.py
    report.py
  test_e2e_scenarios.py
```

### Execution Time Budget

| Mode | Turns | Time/Turn | Runs | Total/Scenario |
|------|-------|-----------|------|----------------|
| Fast (local) | 3-5 | ~3s | 1 | ~15s |
| Stability (CI) | 3-5 | ~3s | 3 | ~45s |
| Full suite (20 scenarios) | — | — | — | ~5-15 min |

## Subsystem 3: Behavioral Specs

### Problem

The user does not understand their own codebase due to AI coding. They need concise documentation that explains what each pipeline/node does at the user-experience level — what triggers it, what the user sees, and what data flows out.

### Structure

```
openspec/specs/
  common/
    voice_contract.md          # Shared personality and tone rules
    intent_taxonomy.md         # All 13 intents with definitions
    state_schema.md            # Shared state fields
  pipelines/
    introduction.md            # Entry points and triggers
    general_chat.md            # Full LangGraph flow
    bridge.md                  # Pre-anchor and activation phases
    attribute_activity.md      # Soft-guide mechanism
    category_activity.md       # Category lane logic
    guide_mode.md              # Theme classification and steering
  nodes/
    correct_answer.md          # Per-node behavioral contract
    curiosity.md
    clarifying_idk.md
    give_answer_idk.md
    ...
  fragments/
    followup_question_rules.md # Reusable behavioral fragments
    bridge_activation_rules.md
    attribute_soft_guide.md
```

### Spec Format (per node)

```markdown
# correct_answer

## Description
The child directly answered the AI's previous question with meaningful content.
The AI confirms their answer, rewards them with one surprising related fact,
and then asks a follow-up question.

## Trigger
- `intent_type`: `CORRECT_ANSWER`
- Route condition: Not at guide mode threshold, or `learning_anchor_active` is false

## Inputs
| Name | Type | Description |
|------|------|-------------|
| child_answer | string | The child's reply text |
| last_model_response | string | The AI's previous full message |
| object_name | string | Current conversation object |
| knowledge_context | string | KB facts for grounding |
| age | integer | 3-8 |

## Behavior

### Step 0: Find Hook
Read the child's answer. Identify the most specific or emotionally loaded element.
The wow fact in BEAT 2 MUST relate to this hook.

### BEAT 1: Confirm
- Paraphrase the child's answer
- Do NOT echo their exact words verbatim
- Avoid hollow praise ("That's a great answer!")

### BEAT 2: Wow Fact
- One surprising fact from KB only
- Must relate to the hook in child's answer
- NEVER start with "Did you know...?"
- Must NOT repeat anything from the previous model message

### Follow-up Question
- Generated separately by `ask_followup_question_stream`
- Must grow from the last assistant message
- Concrete, directly answerable, easy to answer right now

## Outputs
| Name | Type | Description |
|------|------|-------------|
| full_response_text | string | BEAT 1 + " " + BEAT 2 + " " + follow-up |
| correct_answer_count | integer | Incremented if learning_anchor_active |
| used_kb_item | dict | Debug-only KB mapping |

## Prohibitions
- Do NOT ask "How did you know that?"
- Do NOT echo exact words as celebration
- Do NOT use "Did you know...?" anywhere
- Do NOT ask a question within the intent response (only in follow-up)

## Transitions To
`finalize` (always)
```

### Gaps in Understanding

The following areas require follow-up investigation:

1. **Theme Navigator / Guide Mode detailed behavior:** `stream/theme_guide.py` was not found; post-theme-classification turn logic is referenced but not fully traceable.
2. **Exploration activities (post-chat-phase):** What happens AFTER `activity_ready` or `chat_phase_complete` appears to be outside this codebase.
3. **Object resolution algorithm:** `object_resolver.py` YAML lookup and LLM-based resolution logic was not fully read.
4. **KB context building:** Exact format of `physical_dimensions` and `engagement_dimensions` strings in `kb_context.py`.
5. **Hook type selection algorithm:** `stream/utils.py` age-weighted sampling and history-based exclusion.

## Integration Flow

When a new feature request arrives:

1. **brainstorming** skill activates (with opinionated mode)
   - Gives concrete architectural recommendation with trade-offs
   - Writes `proposal.md` and `design.md` to `openspec/changes/<name>/`

2. **writing-plans** skill activates
   - Reads the design, creates `tasks.md` in the same change folder
   - Also writes delta specs to `openspec/changes/<name>/specs/`

3. **subagent-driven-development** skill activates
   - Reads `tasks.md`, implements the code using parallel subagents
   - Generates simulation test scenarios from the delta specs

4. **verification-before-completion** skill activates
   - Runs `pytest tests/test_e2e_scenarios.py -k <change-name>`
   - If tests fail, returns to subagent-driven-development with failure context
   - If tests pass, runs `openspec archive <change-name>` to merge specs

## Migration Path

### Phase 1: Infrastructure (This PR)
- Install OpenSpec CLI globally
- Run `openspec init` in this project
- Create behavioral specs for 2 pilot pipelines (introduction + general_chat)
- Build test harness Layer 1 (Session Driver)

### Phase 2: Integration (Next PR)
- Modify brainstorming skill for opinionated mode
- Build test harness Layer 2-3 (Scenario Engine + Runner)
- Write 5-10 end-to-end scenarios for known bug classes
- Convert 2 existing changes from `docs/superpowers/` to `openspec/changes/`

### Phase 3: Backfill (Future)
- Write behavioral specs for remaining pipelines (bridge, attribute, category, guide_mode)
- Backfill existing `docs/superpowers/specs/` designs into `openspec/specs/`
- Expand e2e scenario coverage to 20+ scenarios

## Dependencies

### New Runtime Dependencies
- `@fission-ai/openspec` (global npm install)
- `pyyaml` (likely already present transitively)

### New Dev Dependencies
- `pytest-html` or `pytest-json-report` (for CI-friendly output)

### No New LLM Dependencies
- Harness reuses existing `genai.Client`
- Optional judge calls use same client with `gemini-2.0-flash-lite`

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OpenSpec CLI conflicts with existing `docs/` structure | Low | Medium | Keep `docs/superpowers/` as archive; new work goes to `openspec/` |
| Simulation tests are flaky due to LLM non-determinism | High | Medium | Stability scoring (2/3 pass), retry logic, semantic assertions |
| Opinionated brainstorming gives bad recommendations | Medium | High | Mandatory "When to reconsider" section; user can always push back |
| Behavioral specs drift from code | Medium | High | Archive process merges deltas; verification step runs before archive |
| Test harness adds 5-15 min to CI | Medium | Low | Run e2e tests only on PRs, not every push; fast mode for local dev |

## Success Criteria

- [ ] `openspec init` completes successfully in this project
- [ ] `openspec/changes/` directory can track a change through propose → apply → archive
- [ ] `brainstorming` skill gives at least one concrete recommendation (not A/B/C) when asked an architectural question
- [ ] A simulation test exists that would have caught the "why? → duplicated question" bug
- [ ] A new developer can read `openspec/specs/pipelines/introduction.md` and understand the intro flow without reading `graph.py`
