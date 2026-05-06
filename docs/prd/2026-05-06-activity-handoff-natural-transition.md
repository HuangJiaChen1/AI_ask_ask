# PRD: Natural Conversation-to-Activity Handoff

> Created: 2026-05-06
> Status: Draft
> Depends on: Activity Tag Block & Progression Guide (v0.1, 2026-04-30)

## Overview

The current system has two parallel conversation lanes (attribute and category) that both end at the same point: an `activity_ready` flag plus an `activity_target` string. What happens next is undefined — the frontend shows a modal, but there is no structured path from "child is ready" to "child is doing an activity."

This PRD closes that gap by introducing an **Activity Selection and Runtime layer** that sits immediately after the conversation pipelines. It consumes the handoff signal, selects an appropriate activity from a catalog, renders it for the current context, and runs it. The design is heavily informed by the Activity Tag Block & Progression Guide, which defines how activities are declared, matched, and progressed.

The handoff must feel **natural** to the child. They should not experience a jarring context switch. The activity should flow from the conversation topic as if the learning companion simply suggested the next thing to explore.

## Goals

1. **Activity Catalog**: Introduce a YAML-based activity catalog using the Tag Block schema. Each activity declares its eligibility rules, runtime templates, and progression metadata.
2. **Upstream Selection Engine**: Given a handoff context (`activity_target`, `object_name`, `entity` from photo, `tier`, `conversation_signature`), select the best matching activity from the catalog using eligibility + coherence + progression fit.
3. **Natural Transition Prompting**: Before handing off, the LLM generates a child-facing transition message that bridges the conversation topic to the activity. No abrupt "Now let's play a game."
4. **Activity Runtime**: Render the selected activity's templates with runtime entity/property values, stream the activity prompt to the child via SSE, and accept child responses.
5. **Progression State (V1 Stub)**: Record per-child, per-axis, per-rung progression events after activity completion. V1 stores these events; the full scoring algorithm is a future project.
6. **Sibling-Axis Routing (V1 Stub)**: When a child reaches L3 on an axis, the selector prefers activities on a sibling axis rather than inventing L4.
7. **Debuggability**: Every selection decision emits a compact `selection_reason` with explicit codes for why an activity was chosen or rejected.

## Out of Scope

1. **Full progression scoring algorithm**: V1 records evidence and actions but does not implement bounded exponential smoothing or full guardrails. That lives in a separate future PRD.
2. **Parent dashboard / growth path UI**: We emit events; downstream surfaces consume them later.
3. **Dynamic activity authoring**: Activities are static YAML in V1. No runtime generation of new activities.
4. **Replacing attribute/category pipelines**: Those pipelines remain unchanged. This PRD only defines what happens *after* they signal readiness.
5. **Multi-turn activity runtime with complex state machines**: V1 activities are single-prompt interactions (one question or one challenge). Multi-step activity orchestration is future work.

## Success Criteria

1. Given `activity_ready=True` and a handoff context, the system selects an activity from the catalog within 200ms (local YAML scan + scoring).
2. The transition message is streamed via SSE with `response_type="activity_transition"` and sounds natural when read aloud.
3. The activity runtime renders all `{entity}`, `{color}`, `{property}` placeholders with actual values from the conversation context or photo entity.
4. If no activity matches eligibility, the system gracefully falls back to general chat with `response_type="activity_fallback"` and logs the fallback reason.
5. Every activity selection emits a debug payload containing: `selected_activity_id`, `selection_reason`, `rejected_activities` (top-3 with reasons), `progression_target_axis`, `progression_target_rung`.
6. After activity completion, a `progression_event` is appended to the session state with `topic_axis`, `rung`, `evidence_summary`, and `action`.
7. Existing attribute and category pipeline tests continue to pass unchanged.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONVERSATION LAYER (existing)                         │
│  ┌─────────────┐   ┌─────────────┐                                          │
│  │  Attribute  │   │  Category   │                                          │
│  │   Pipeline  │   │   Pipeline  │                                          │
│  │  (activity  │   │  (activity  │                                          │
│  │   _target)  │   │   _target)  │                                          │
│  └──────┬──────┘   └──────┬──────┘                                          │
│         │                 │                                                 │
│         └────────┬────────┘                                                 │
│                  ▼                                                          │
│         ┌─────────────────┐                                                 │
│         │  activity_ready │  ← existing flag                                │
│         │  activity_target│  ← e.g. "exploring the color of objects"        │
│         │  object_name    │  ← e.g. "red pen"                               │
│         │  conversation   │  ← last N messages                              │
│         │    _signature   │                                                 │
│         └────────┬────────┘                                                 │
│                  │                                                          │
└──────────────────┼──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ACTIVITY HANDOFF LAYER (new)                             │
│                                                                              │
│  ┌─────────────────────┐                                                    │
│  │  Transition Prompt  │  ← LLM-generated bridge from chat to activity      │
│  │     Generator       │    ("You noticed the pen is red... can you find    │
│  │                     │     another red thing nearby?")                     │
│  └──────────┬──────────┘                                                    │
│             │                                                                │
│             ▼                                                                │
│  ┌─────────────────────┐                                                    │
│  │  Activity Selector  │  ← upstream matcher (eligibility → coherence)      │
│  │   (upstream matcher)│                                                    │
│  └──────────┬──────────┘                                                    │
│             │                                                                │
│             ▼                                                                │
│  ┌─────────────────────┐                                                    │
│  │  Activity Runtime   │  ← template rendering + SSE streaming              │
│  │   (runtime layer)   │                                                    │
│  └──────────┬──────────┘                                                    │
│             │                                                                │
│             ▼                                                                │
│  ┌─────────────────────┐                                                    │
│  │  Progression Event  │  ← record outcome, update per-child state stub     │
│  │     Recorder        │                                                    │
│  └─────────────────────┘                                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

**D1: Single handoff point.** Both attribute and category pipelines converge on the same `activity_ready` flag. The handoff layer does not need to know which pipeline produced the signal. It only needs the handoff context.

**D2: Catalog is local YAML, not a database.** Per the Tag Block guide, tag blocks are "catalog-time static declarations." We store them as YAML files in `activities/catalog/`. This keeps V1 simple and version-controlled.

**D3: Selection is deterministic, not LLM-driven.** The upstream matcher uses hard filters and a scoring function. No LLM call during selection. This keeps latency low and decisions auditable.

**D4: Progression is event-sourced.** V1 stores events (`child_responded`, `evidence_vector`, `action_taken`) but defers the scoring algorithm. This lets us collect training data for the future learning model.

**D5: Activity families, not bespoke per-cell activities.** Per the Tag Block guide §6.7.2, we use "activity families with elastic rung variants." One YAML file defines a family; `rung_variants` provides prompt variations for L1/L2/L3.

---

## 1. Activity Catalog (Tag Block Schema)

Activities are stored in `activities/catalog/<family_id>.yaml`. The schema is a simplified version of the full Tag Block spec, keeping only the fields we need for V1.

### 1.1 YAML Schema (V1 Simplified)

```yaml
# activities/catalog/color_scout.yaml
activity_id: "color_scout"
family_id: "color_scout"
version: 1

# ── Matchability (eligibility) ──
matchability:
  active: true
  tier_range:
    span: [0, 1, 2]           # T0, T1, T2
  entity_binding:
    mode: "parameterized"     # bound | parameterized | agnostic
    required_property: "color" # null for agnostic
  entity_class_filter: []     # empty = wide (any safe observable thing)

# ── Activity Signature (coherence) ──
activity_signature:
  observation_angle: "color"  # what the child observes
  thinking_move: "collect"    # what the child does
  dominant_property: "color"  # primary property involved

# ── Runtime Presentation ──
runtime_presentation:
  templates:
    transition: |
      You noticed that {entity} is {color}! 
      Can you look around and find something else that is {color}?
    prompt: |
      Great job! Now let's play a quick game.
      Point to something near you that is the same color as {entity}.
    confirmation: |
      Nice finding! {found_entity} is indeed {matched_color}.

# ── Progression Declaration ──
progression:
  topic_axis: "form"          # the axis this activity trains
  difficulty_level: 1         # rung: 1, 2, or 3
  evidence_type: "color_naming_and_matching"
  sibling_axes:               # where to route when L3 is reached
    - "connection"
    - "causation"

# ── Rung Variants (elastic prompts) ──
rung_variants:
  l1:
    prompt_addendum: "Just name the color you see."
  l2:
    prompt_addendum: "Can you also tell me another thing that has this color?"
  l3:
    prompt_addendum: "Why do you think {entity} is {color}? Is there a reason?"
```

### 1.2 Catalog Directory Structure

```
activities/
  catalog/
    _index.yaml              # registry: list all activity_ids with file paths
    color_scout.yaml
    shape_finder.yaml
    pattern_match.yaml
    sound_hunt.yaml
    texture_touch.yaml
    size_sorter.yaml
    connection_bridge.yaml
    causation_why.yaml
    # ... more families
  _schema/
    tag_block_v1.schema.json # JSON Schema for validation
```

### 1.3 Catalog Index (`_index.yaml`)

```yaml
# activities/catalog/_index.yaml
activities:
  color_scout:
    file: "color_scout.yaml"
    axes: ["form"]
    rungs: [1, 2, 3]
    properties: ["color"]
  shape_finder:
    file: "shape_finder.yaml"
    axes: ["form"]
    rungs: [1, 2, 3]
    properties: ["shape"]
  # ...
```

The index allows the selector to scan eligibility without parsing every YAML file.

---

## 2. Upstream Selection Engine

### 2.1 Input: Handoff Context

The selector receives a `HandoffContext` dataclass:

```python
@dataclass
class HandoffContext:
    activity_target: str           # e.g. "exploring the color of objects"
    object_name: str               # e.g. "red pen"
    entity: str | None = None      # photo-detected entity (may differ from object_name)
    color: str | None = None       # extracted property
    shape: str | None = None
    pattern: str | None = None
    child_age: int = 6
    child_tier: int = 1            # 0, 1, 2
    conversation_signature: str | None = None  # e.g. "color_discussion"
    progression_target_axis: str | None = None # e.g. "form"
    progression_target_rung: int | None = None # e.g. 2
    used_activity_ids: list[str] = field(default_factory=list)  # freshness
```

### 2.2 Selection Pipeline

Per the Tag Block guide §3, selection has two layers:

#### Layer 1: Eligibility (Hard Filters)

An activity is eligible if ALL of the following are true:

1. `matchability.active == true`
2. `child_tier` is in `matchability.tier_range.span`
3. Entity binding is satisfied:
   - `mode == "agnostic"`: always passes
   - `mode == "bound"`: photo entity must match `entity_class_filter`
   - `mode == "parameterized"`: photo entity must have the `required_property` extractable
4. Safety/runtime checks pass (V1: always true; placeholder for future policy)

#### Layer 2: Coherence Scoring

For each eligible activity, compute a score:

```python
def score_activity(activity: TagBlock, context: HandoffContext) -> float:
    score = 0.0

    # Progression target (strong preference, not hard promise)
    if context.progression_target_axis:
        if activity.progression.topic_axis == context.progression_target_axis:
            score += 3.0
        elif activity.progression.topic_axis in activity.progression.sibling_axes:
            score += 1.5  # sibling is acceptable fallback

    # Conversation coherence
    if context.conversation_signature:
        sig = context.conversation_signature.lower()
        if activity.activity_signature.observation_angle in sig:
            score += 2.0
        if activity.activity_signature.dominant_property in sig:
            score += 1.5

    # Property match
    if context.color and activity.activity_signature.dominant_property == "color":
        score += 1.0
    if context.shape and activity.activity_signature.dominant_property == "shape":
        score += 1.0

    # Freshness penalty
    if activity.activity_id in context.used_activity_ids:
        score -= 1.0

    return score
```

The activity with the highest score is selected. Ties are broken by:
1. Higher `difficulty_level` (closer to target rung)
2. Lexicographic `activity_id` (deterministic)

### 2.3 Selection Output

```python
@dataclass
class ActivitySelection:
    activity_id: str
    family_id: str
    selected_rung: int
    selection_reason: str           # human-readable
    selection_code: str             # machine-readable code
    score: float
    rejected: list[dict]            # top-3 rejected with reasons
```

---

## 3. Natural Transition Prompting

Before presenting the activity, the system generates a child-facing transition message. This is the critical "natural handoff" moment.

### 3.1 Transition Prompt Template

```python
ACTIVITY_TRANSITION_PROMPT = """You are a warm learning companion for a {age}-year-old child.

The child has been chatting about {object_name}. The conversation topic was: {activity_target}.

Now you want to gently suggest a fun next step. Do NOT say "Let's play a game" or "Now for an activity." Instead, build directly on what the child just talked about.

Selected activity: {activity_title}
Activity description: {activity_description}

YOUR TASK:
Write ONE short, natural sentence that bridges from the chat topic to this activity. It should sound like a continuation of the conversation, not a mode switch.

Example (good):
"You noticed the pen is red — can you find another red thing nearby?"

Example (bad):
"Now let's do an activity about colors."

Respond with ONLY the transition sentence. No extra text.
"""
```

### 3.2 Streaming Contract

The transition is streamed as a new SSE chunk type:

```json
{
  "type": "activity_transition",
  "text": "You noticed the pen is red — can you find another red thing nearby?",
  "activity_id": "color_scout",
  "selection_reason": "progression_target: form L2, conversation_angle: color",
  "sequence_number": 7,
  "chat_phase_complete": false
}
```

After the transition streams, the activity prompt itself is sent as:

```json
{
  "type": "activity_prompt",
  "text": "Great job! Now let's play a quick game...",
  "activity_id": "color_scout",
  "rung": 2,
  "sequence_number": 8
}
```

---

## 4. Activity Runtime

### 4.1 Template Rendering

The runtime takes the selected activity's `runtime_presentation.templates` and renders placeholders:

| Placeholder | Source |
|-------------|--------|
| `{entity}` | `handoff_context.object_name` or photo-detected entity |
| `{color}` | Extracted color property |
| `{shape}` | Extracted shape property |
| `{pattern}` | Extracted pattern property |
| `{matched_color}` | Confirmed color from child's answer |
| `{found_entity}` | Entity the child found in response |

Rendering rules (per Tag Block guide §4):
- Never invent facts not present in the photo or child-confirmed answers
- For photo-limited properties (smell, taste, sound, temperature), use child-confirmed phrasing or avoid claiming

### 4.2 Runtime State Machine (V1 — Single Turn)

```
[activity_selected]
    │
    ▼
[stream_transition] ──► child sees transition message
    │
    ▼
[stream_activity_prompt] ──► child sees activity prompt
    │
    ▼
[await_child_response] ◄─── child sends /api/continue
    │
    ▼
[record_outcome] ──► progression_event appended
    │
    ▼
[route_next] ──► either next activity or back to general chat
```

V1 activities are single-turn: one prompt, one response, one outcome. Multi-turn activities are out of scope.

### 4.3 Outcome Recording

After the child responds, the system records:

```python
@dataclass
class ActivityOutcome:
    activity_id: str
    topic_axis: str
    rung: int
    child_response_text: str
    evidence_summary: str       # e.g. "named_color_correctly", "needed_hint"
    action_taken: str           # "hold" | "soft_reframe" | "promote" | "support"
    timestamp: str              # ISO 8601
```

This becomes a `progression_event` in the session state.

---

## 5. Progression Integration (V1 Stub)

### 5.1 Event Storage

Per the Tag Block guide §6.7.1, progression state commits **after** the activity ends, not during. V1 stores events in the session:

```python
# On PaixuejiAssistant
self.progression_events: list[ActivityOutcome] = []
self.progression_state_stub: dict = {}  # per-axis, per-rung placeholder
```

### 5.2 Sibling-Axis Routing

Per the Tag Block guide §6.7.3, when a child has stable L3 evidence on an axis, the selector should prefer sibling axes. V1 implements this as a simple rule:

```python
def _is_axis_at_ceiling(axis: str, events: list[ActivityOutcome]) -> bool:
    # V1 heuristic: 3+ L3 outcomes on same axis = ceiling
    l3_count = sum(1 for e in events if e.topic_axis == axis and e.rung >= 3)
    return l3_count >= 3
```

If ceiling is detected, the selector boosts sibling axis scores by +2.0.

### 5.3 Action Policy (V1 Simplified)

Per the Tag Block guide §6.5, V1 uses a minimal action enum:

| Action | When |
|--------|------|
| `hold` | Child engaged but no clear evidence of mastery |
| `soft_reframe` | Child slightly off-track, needs gentle redirection |
| `promote` | Child demonstrated clear mastery (2+ strong responses) |
| `support` | Child struggled, needs scaffolding |

V1 uses a simple heuristic on the child's response text (length, keyword matching) to pick an action. The full classifier is future work.

---

## 6. API Changes

### 6.1 New SSE Chunk Types

| Type | When | Fields |
|------|------|--------|
| `activity_transition` | After activity selected | `activity_id`, `selection_reason` |
| `activity_prompt` | Transition complete | `activity_id`, `rung`, `rendered_text` |
| `activity_outcome` | Child responded | `activity_id`, `action_taken`, `evidence_summary` |
| `activity_fallback` | No eligible activity | `fallback_reason`, `suggestion` |

### 6.2 Debug Payload Additions

The per-turn debug payload gains an `activity_selection` block:

```json
{
  "activity_selection": {
    "selected_activity_id": "color_scout",
    "selected_rung": 2,
    "selection_score": 7.5,
    "selection_reason": "progression_target: form L2, conversation_angle: color",
    "selection_code": "PROGRESSION_MATCH",
    "rejected": [
      {"activity_id": "shape_finder", "reason": "no_shape_property", "score": 2.0},
      {"activity_id": "pattern_match", "reason": "freshness_penalty", "score": 1.5}
    ],
    "handoff_context": {
      "activity_target": "exploring the color of objects",
      "object_name": "red pen",
      "progression_target_axis": "form",
      "progression_target_rung": 2
    }
  }
}
```

### 6.3 Endpoint Changes

No new endpoints. The handoff is handled within the existing `/api/continue` flow. When `activity_ready` becomes true, the graph routes to a new `node_activity_handoff` instead of ending the chat phase.

---

## 7. Files to Create / Modify

### New Files

| File | Purpose |
|------|---------|
| `activities/catalog/_index.yaml` | Catalog registry |
| `activities/catalog/color_scout.yaml` | First activity family |
| `activities/catalog/shape_finder.yaml` | Second activity family |
| `activities/_schema/tag_block_v1.schema.json` | JSON Schema validation |
| `activity_catalog.py` | Catalog loader, validator, indexer |
| `activity_selector.py` | Upstream matcher (eligibility + scoring) |
| `activity_runtime.py` | Template renderer, outcome recorder |
| `activity_transition.py` | LLM transition prompt generator |
| `tests/test_activity_catalog.py` | Catalog loading tests |
| `tests/test_activity_selector.py` | Selection logic tests |
| `tests/test_activity_runtime.py` | Template rendering tests |

### Modified Files

| File | Change |
|------|--------|
| `graph.py` | Add `node_activity_handoff`, router to it when `activity_ready` |
| `paixueji_assistant.py` | Add `progression_events`, `progression_state_stub` |
| `paixueji_app.py` | Handle new SSE chunk types, pass handoff context to selector |
| `schema.py` | Add `StreamChunk` variants for activity types |

---

## 8. Worked Example: Red Pen → Color Scout

**Conversation context:**
- Child chatted about a red pen for 3 turns
- Attribute pipeline selected `color` attribute
- `activity_target`: "exploring the color of objects"
- `activity_ready`: true

**Handoff context:**
```python
HandoffContext(
    activity_target="exploring the color of objects",
    object_name="red pen",
    color="red",
    child_age=6,
    child_tier=1,
    conversation_signature="color_discussion",
    progression_target_axis="form",
    progression_target_rung=2,
)
```

**Eligibility check:**
- `color_scout`: tier_range=[0,1,2] ✓, mode=parameterized, required_property=color ✓ → **eligible**
- `shape_finder`: required_property=shape ✗ (no shape in context) → **not eligible**
- `texture_touch`: agnostic ✓ → **eligible**

**Scoring:**
- `color_scout`: progression_match(+3) + color_angle(+2) + color_property(+1) = **6.0**
- `texture_touch`: no_progression_match(0) + no_angle_match(0) = **0.0**

**Selection:** `color_scout`, rung=2 (matches target)

**Transition:**
> "You noticed the pen is red — can you find another red thing nearby?"

**Activity prompt (rendered):**
> "Great job! Now let's play a quick game. Point to something near you that is the same color as the red pen. Can you also tell me another thing that has this color?"

**Child responds:** "My backpack is red too!"

**Outcome recorded:**
```python
ActivityOutcome(
    activity_id="color_scout",
    topic_axis="form",
    rung=2,
    child_response_text="My backpack is red too!",
    evidence_summary="named_color_and_found_example",
    action_taken="promote",
)
```

**Next selection:** Form L3 or sibling axis if Form ceiling reached.

---

## 9. Implementation Phases

### Phase 1: Catalog + Selector (1-2 days)
- Create catalog structure and first 2 activity families
- Implement `activity_catalog.py` loader and validator
- Implement `activity_selector.py` with eligibility + scoring
- Unit tests for catalog and selector

### Phase 2: Runtime + Transition (2-3 days)
- Implement `activity_runtime.py` template renderer
- Implement `activity_transition.py` LLM prompt generator
- Wire into `graph.py` as new node
- Add new SSE chunk types to `schema.py` and `paixueji_app.py`
- Integration tests with mocked LLM

### Phase 3: Progression Stub + Debug (1 day)
- Add `ActivityOutcome` recording
- Add progression event to session state
- Add selection debug payload
- End-to-end test through `/api/continue`

---

## 10. References

- Activity Tag Block & Progression Guide, v0.1 (2026-04-30) — the foundational design document this PRD implements
- PRD: Category → Activity Pipeline (2026-04-23) — the conversation pipeline that feeds this handoff layer
- docs/superpowers/specs/2026-04-27-attribute-hook-design.md — observable-only hook design that informs activity selection
- docs/superpowers/plans/2026-04-27-activity-handoff-reason.md — `REASON:` line design for auditable handoffs
