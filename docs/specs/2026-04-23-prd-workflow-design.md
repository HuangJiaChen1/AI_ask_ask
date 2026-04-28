# PRD Workflow Skill — Design Document

> Created: 2026-04-23
> Status: Draft

## Summary

A global Qoder skill workflow (`prd`) that helps users create detailed Product Requirement Documents through multi-turn dialogue. The workflow is composed of 5 skills: 1 orchestrator + 4 phase skills. It uses a three-layer behavior deviation framework to systematically enumerate user behavior branches at every interaction point, ensuring PRDs capture not just "what to build" but "how users might deviate and how the system should respond."

## Motivation

Writing PRDs by having an LLM "think deeply" produces shallow results — it lists 2-3 approaches and stops. Real product complexity lives in user behavior branches: what happens when a user doesn't understand, refuses, answers differently than expected, or accumulates a pattern over time. These branches are discovered through iterative testing in practice, but a structured framework can surface most of them before implementation.

Example: the paixueji codebase's intent-based pipeline has 13+ intent nodes, each with internal branching (open-ended vs concrete questions, consecutive struggle counters, topic-switch vs intent-response paths). These were discovered through iteration. The three-layer framework can surface the same branches systematically.

## Architecture

```
~/.qoder/skills/
  prd/
    SKILL.md                              # Orchestrator: gates + workflow + phase dispatch
    references/
      prd-template.md                     # Full PRD template (all sections)
      deviation-probe.md                  # Three-layer framework detailed guide
    assets/
      completeness-checklist.md           # Post-completion self-check
  prd-scoping/
    SKILL.md                              # Phase 1: scope + goals + success criteria
  prd-detailing/
    SKILL.md                              # Phase 2: interaction points + three-layer deviation + behavior trees
  prd-constraints/
    SKILL.md                              # Phase 3: constraints + assumptions + expectations
  prd-ops-planning/
    SKILL.md                              # Phase 4: test strategy + monitoring + rollback + performance
```

### Skill Types

| Skill | Type | Invoked by |
|-------|------|-----------|
| `prd` | Orchestrator workflow | User directly (`/prd`) |
| `prd-scoping` | Phase skill | `prd` orchestrator |
| `prd-detailing` | Phase skill | `prd` orchestrator |
| `prd-constraints` | Phase skill | `prd` orchestrator |
| `prd-ops-planning` | Phase skill | `prd` orchestrator |

Phase skills can also be invoked independently if the user only needs one phase.

## Orchestrator Workflow (`prd`)

```
1. Receive feature description
2. Ask for PRD save path (default: docs/prd/YYYY-MM-DD-<feature-slug>.md)
3. Create PRD file skeleton from references/prd-template.md
4. Enter 4 phases sequentially:
   a. Invoke phase skill
   b. Phase skill conducts multi-turn dialogue for its sections
   c. Phase skill writes content to PRD file
   d. User confirms output (gate)
   e. Pass -> next phase; Fail -> continue current phase
5. After all 4 phases pass, run completeness-checklist self-check
6. Present self-check results, fill gaps
7. Final confirmation -> PRD complete
```

### Orchestrator Responsibilities

**Does:** Dispatch phases, check gates, create/save PRD file, run self-check
**Does not:** Participate in substantive discussion, write content for phase skills, skip gates

### Non-Negotiable Gates

| Gate | Rule | Rationale |
|------|------|-----------|
| Scope gate | Scoping must define "out of scope", not just "in scope" | PRDs without boundaries expand indefinitely during implementation |
| Detailing gate | Every interaction point must complete all 3 layers of the deviation probe | Skipping layers = unhandled user behavior branches = bugs in implementation |
| Constraint gate | Must have at least 1 hard constraint | No hard constraints = all decisions are negotiable = no design intent |
| Ops gate | Must define a rollback plan | No rollback = can only improvise when things go wrong |
| Completion gate | All 4 phases must write output to PRD file before self-check | Checking against memory, not documentation, is unreliable |

## Three-Layer Behavior Deviation Framework

The core innovation of this PRD workflow. Applied during the `prd-detailing` phase.

### Layer 1: Behavior Deviation (5 Dimensions)

For each interaction point, systematically probe 5 orthogonal dimensions:

| Dimension | Question | Example (Education App) | Example (Payment System) |
|-----------|----------|------------------------|--------------------------|
| Understanding | Did the user understand what the system presented? | Child didn't understand the question | User didn't see the amount clearly |
| Intent | Is the user's intent aligned with what the system expects? | Child wants to talk about a different object | User wants to cancel, not pay |
| Capability | Can the user perform the expected action? | Child lacks knowledge to answer | User has insufficient balance |
| Willingness | Is the user willing to follow the system's guidance? | Child says "idk" and won't cooperate | User dismisses the dialog and leaves |
| Boundary | Did the user's response exceed the system's expected range? | Child gives an unexpectedly advanced answer | User enters a negative amount |

Each dimension is product-agnostic. The specific manifestations emerge during dialogue with product context.

For each dimension, the skill asks: "At this interaction point, what happens if [dimension] deviates?"

### Layer 2: Context Sensitivity

For each branch discovered in Layer 1,追问:

- "Does this behavior mean the same thing early vs late in the conversation?"
- "Should this behavior be treated differently on first occurrence vs repetition?"
- "Is there any system state that would cause the same behavior to require a different response?"

### Layer 3: State Accumulation

For key behaviors,追问:

- "What happens if this behavior occurs N times consecutively?"
- "What happens if this behavior combines with another behavior?"
- "At what point of accumulation should the system switch to a different strategy?"

### Validation Against Real System

Tested against paixueji's intent-based pipeline:

| Existing Intent | Captured by Framework | Layer |
|----------------|----------------------|-------|
| CLARIFYING_IDK | Understanding dimension | L1 |
| CLARIFYING_WRONG | Intent dimension | L1 |
| CONCEPT_CONFUSION | Intent dimension | L1 |
| CORRECT_ANSWER | Boundary dimension | L1 |
| INFORMATIVE | Boundary dimension | L1 |
| PLAY | Intent dimension | L1 |
| EMOTIONAL | Understanding dimension | L1 |
| AVOIDANCE | Willingness dimension | L1 |
| ACTION | Intent dimension | L1 |
| SOCIAL | Intent dimension | L1 |
| BOUNDARY | Boundary dimension | L1 |
| CURIOSITY | Intent dimension | L1 |
| fallback_freeform | Boundary dimension (classifier failure) | L1 |
| IDK open-ended vs concrete distinction | Context sensitivity | L2 |
| Consecutive IDK -> answer reveal | State accumulation | L3 |
| AVOIDANCE with new_object -> topic switch | Context sensitivity | L2 |

Coverage: 13/14 intents directly from L1; the remaining nuance (open-ended distinction, consecutive counters, conditional routing) from L2 and L3.

**Limitation:** SOCIAL_ACKNOWLEDGMENT and CLARIFYING_CONSTRAINT don't naturally emerge from "deviation" framing — they're discovered by asking "are there user behaviors we haven't classified yet?" after the framework pass. This question is included as the final step of the detailing phase.

## Phase Skills

### prd-scoping (Phase 1)

**Dialogue flow:**
1. User describes feature
2. What problem does it solve?
3. Who uses it? In what scenario?
4. What's the success criteria?
5. Skill proposes "possibly related but out of scope" items for user confirmation
6. Write scope document (goals + out of scope + success criteria)
7. User confirms

**PRD sections written:** Overview, Goals, Out of Scope, Success Criteria

**Gate:** Out of Scope >= 1 item; Success Criteria >= 1 verifiable criterion

### prd-detailing (Phase 2)

**Dialogue flow:**
1. Identify all interaction points from Goals
2. For each interaction point, run three-layer deviation probe (using deviation-probe.md as reference)
3. Generate behavior decision tree per interaction point (min depth 2)
4. After all interaction points: "Are there user behaviors we haven't classified?"
5. Derive implementation approach from decision trees

**PRD sections written:** Interaction Points, Behavior Decision Trees, Implementation Approach

**Gate:** All 5 dimensions must be addressed for every interaction point (answering "this dimension won't deviate" with reasoning is acceptable; skipping is not)

### prd-constraints (Phase 3)

**Dialogue flow:**
1. Review scoping and detailing output
2. Hard constraints: "What must never be violated?"
3. Soft constraints: "What should be satisfied but can be compromised? Under what conditions?"
4. Assumptions: "What are we assuming? What if the assumption is wrong?" -> fallback strategy per assumption
5. Expectations: "What behavior characteristics should this feature exhibit?"
6. For each item: "If this isn't written in the PRD, would an implementer know it?"
7. For each assumption: "If violated, how should the system handle it?"

**PRD sections written:** Hard Constraints, Soft Constraints, Assumptions (with fallback), Expectations

**Gate:** Hard Constraints >= 1; every Assumption has a fallback strategy

### prd-ops-planning (Phase 4)

**Dialogue flow:**
1. Review behavior decision trees from detailing
2. Identify critical branches per tree (most common + most error-prone)
3. Test strategy: How to verify critical paths? Manual/automated/A/B? Edge coverage level?
4. Monitoring: What metrics indicate normal/abnormal? What to instrument?
5. Rollback plan: How to disable? What's affected? Any irreversible operations?
6. Performance expectations: Latency? Throughput? Cost budget?

**PRD sections written:** Test Strategy, Monitoring, Rollback Plan, Performance Expectations

**Gate:** Rollback Plan is not empty; Test Strategy covers critical branches from detailing

## PRD Template

See `references/prd-template.md` — contains all sections with HTML comments indicating which phase skill writes each section.

## Completeness Checklist

See `assets/completeness-checklist.md` — covers:
- Per-phase minimum requirements
- Cross-section consistency checks (Goals vs Out of Scope, Decision Trees vs Hard Constraints, Test Strategy vs Success Criteria, Assumption fallbacks vs Hard Constraints)

## File Save Convention

- Default path: `docs/prd/YYYY-MM-DD-<feature-slug>.md`
- User can override path at workflow start
- The `prd` orchestrator creates the skeleton and each phase appends to the same file
- PRD status tracked in frontmatter: Draft -> In Review -> Approved

## Example Usage

### Starting a PRD for "Attribute Pipeline"

```
User: /prd I want to build an attribute pipeline that lets the model
      drift between objects as long as attributes match

prd: I'll create a PRD for the Attribute Pipeline feature.
     Save path: docs/prd/2026-04-23-attribute-pipeline.md (OK?)

User: yes

prd: Starting Phase 1: Scoping.
     [invokes prd-scoping]

prd-scoping: What problem does the Attribute Pipeline solve?

User: Right now the model is locked to one object. But kids naturally
      connect ideas across objects — a red ball and a red fire truck
      share the "red" attribute. We want the conversation to follow
      attributes, not just objects.

prd-scoping: Who uses this? In what scenario?

User: Children 3-8 in the chat system. When they're exploring an object
      and mention an attribute that connects to another object, the model
      should be able to drift naturally.

prd-scoping: What's the success criteria?

User: 1) Model can drift to a related object when the child's response
      centers on a shared attribute. 2) The drift feels natural, not
      like a hard topic switch. 3) The model stays grounded — it
      shouldn't drift to unrelated objects.

prd-scoping: Here are some things that might be related but could be
     out of scope:
     - Drift triggered by the model (not the child) — is this in scope?
     - Drift back to the original object — is this in scope?
     - Multi-hop drift (A -> B -> C) — is this in scope?

User: Model-triggered drift: out of scope for now.
      Drift back: in scope, it should work naturally.
      Multi-hop: out of scope for v1.

prd-scoping: Writing scope document...
     [writes to PRD file]
     Phase 1 complete. Confirm? (y/n)

User: y

prd: Phase 1 passed. Starting Phase 2: Detailing.
     [invokes prd-detailing]

prd-detailing: From your goals, I see these interaction points:
     1. Child mentions an attribute while discussing object A
     2. System decides whether to drift to object B
     3. System presents the drift to the child
     4. Child responds after drift

     Let's start with interaction point 1.
     5-dimension probe for "Child mentions an attribute":

     UNDERSTANDING: Can the child mention an attribute without
     understanding they're doing so? (e.g., "it's shiny" without
     knowing "shiny" is an attribute)

     ... [continues through all 5 dimensions, then L2, then L3]
```

This example shows the key difference from a typical PRD approach: instead of writing "use attribute matching to enable drift", the skill forces a systematic walk through every way the user interaction can deviate from the expected path.
