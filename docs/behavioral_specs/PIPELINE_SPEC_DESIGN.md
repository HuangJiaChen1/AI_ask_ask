# Paixueji Behavioral Spec Design Document

## 1. Pipeline Inventory

The Paixueji system has **six conversation pipelines**. Each pipeline is triggered by different conditions and produces different user-visible behavior.

| Pipeline | Trigger | User-visible purpose |
|----------|---------|---------------------|
| **Introduction** | `/api/start` called with `object_name` | First greeting + opening question about the object |
| **General Chat** (Ordinary Chat) | Child replies to any assistant message | Respond to child's intent, then ask a follow-up question |
| **Bridge** | Child names an unsupported object that maps to a supported "anchor" | Gently guide conversation from surface object to anchor object |
| **Attribute Activity** | `/api/start` called with `attribute_pipeline_enabled=true` | Focus conversation on one specific attribute (e.g., color, texture) of the object |
| **Category Activity** | `/api/start` called with `category_pipeline_enabled=true` | Focus conversation on the object's domain/category (e.g., "animals", "food") |
| **Exploration / Guide Mode** | Child answers 2+ questions correctly about a supported anchor | Classify IB PYP theme and guide toward key concept understanding |

### Pipeline Relationships

```
/api/start
    |
    +-- attribute_pipeline_enabled=true  --> Attribute Activity Pipeline
    +-- category_pipeline_enabled=true   --> Category Activity Pipeline
    +-- neither enabled
            |
            +-- object is supported anchor       --> Introduction (supported)
            +-- object maps to anchor (high conf) --> Introduction (anchor_bridge)
            +-- object maps to anchor (med conf)  --> Introduction (anchor_confirmation)
            +-- object is unknown/unresolved      --> Introduction (unknown_object)

/api/continue (child replies)
    |
    +-- attribute_lane_active      --> Attribute Activity Pipeline (bypasses graph)
    +-- category_lane_active       --> Category Activity Pipeline (bypasses graph)
    +-- bridge_phase=activation    --> Bridge Activation Pipeline (bypasses graph)
    +-- bridge_phase=pre_anchor    --> Bridge Pre-Anchor Pipeline (bypasses graph)
    +-- anchor_confirmation_needed --> Anchor Confirmation Pipeline (bypasses graph)
    +-- none of the above          --> General Chat Pipeline (runs LangGraph)
```

---

## 2. Behavioral Descriptions (User-Experience Level)

### 2.1 Introduction Pipeline

**Trigger:** User calls `/api/start` with an object name.

**What the user sees:**
1. The AI greets the child with a short, warm opening about the object.
2. The opening has 4 "beats": excited reaction, object confirmation, optional sensory detail, one easy question.
3. The question is concrete and directly answerable (NOT a knowledge test like "What color is it?").
4. If the object is supported in the knowledge base, the intro uses grounded facts.
5. If the object is unknown, the intro stays generic and safe.

**Data that flows out:**
- `response_type`: `"introduction"` (or `"attribute_intro"`, `"category_intro"`)
- `selected_hook_type`: the conversational style chosen for this session (e.g., "情绪投射", "创意改造")
- `question_style`: `"open_ended"` or `"concrete"`

**Transitions to:** Whatever pipeline is active on the next `/api/continue` call.

---

### 2.2 General Chat Pipeline (LangGraph)

**Trigger:** Child sends any reply when no special lane is active.

**Graph flow:**
```
START --> [route_from_start] --> analyze_input --> [route_from_analyze_input] --> (one of 15 intent nodes) --> finalize --> END
```

**What the user sees at each step:**

| Node | What the user sees | Behavioral rule |
|------|-------------------|-----------------|
| `analyze_input` | Nothing (silent) | Classifies child's reply into one of 13 intents. Tracks struggle count (IDK/wrong answers). |
| `curiosity` | Direct answer + one wow fact + one playful closing question | Child asked "why/how/what". No "That's a great question!" allowed. |
| `correct_answer` | Confirmation + wow fact, THEN a follow-up question | If this is the 2nd correct answer and learning anchor is active, triggers `classify_theme` first. |
| `informative` | Genuine celebration + wow extension, THEN follow-up question | Child shared unprompted knowledge. |
| `clarifying_idk` | "That's okay!" + scaffold clue + low-pressure handoff | First IDK. If previous question was open-ended, uses different prompt. |
| `give_answer_idk` | "That's okay!" + direct answer, THEN follow-up question | 2nd+ IDK or wrong. Struggle counter resets. |
| `clarifying_wrong` | Warm acknowledgment + gentle correction + re-engagement invite | Child tried but was incorrect. |
| `clarifying_constraint` | Validation + imaginative redirect + open question | "I don't have one", "I've never seen one". |
| `play` | Full embrace of imagination + optional secret connection + fun action | Child being silly. |
| `emotional` | Direct empathy + gentle path forward | Child expressed feeling (scared, cute, gross). |
| `avoidance` | Pure acceptance + one gentle option | Child wants to stop. If they named a new object, topic switch happens. |
| `boundary` | Validate curiosity + brief safety reason + exciting alternative | "Can I eat it?", "Can I throw it?" |
| `action` | Honor the command directly | Repeat, new question, vague request, or topic switch. |
| `social` | Honest playful answer + redirect through child | "How old are you?", "Are you real?" |
| `social_acknowledgment` | Brief natural reaction (1 sentence) | "wow", "cool", "i didn't know that". Then follow-up question. |
| `concept_confusion` | Explain simply + bridge back + re-ask the question | "What's a feline?", "lions are not cats". |
| `fallback_freeform` | Natural response without intent assumptions | Classifier failed. |
| `classify_theme` | Silent (runs before `correct_answer`) | After 2 correct answers on a supported anchor, classifies IB PYP theme from conversation history. |
| `finalize` | Final SSE chunk with `finish=true` | Assembles full response, sends metadata. |

**Key behavioral rule:** Most intent nodes produce a response, then a separate follow-up question is generated. The follow-up question MUST grow from the last assistant message (same detail, same attribute, or one-hop nearby idea).

**Data that flows between nodes:**
- `intent_type`: the classified intent
- `correct_answer_count`: increments on correct answers
- `chat_phase_complete`: set to `true` after theme classification
- `used_kb_item`: which KB fact was used (debug only)

---

### 2.3 Bridge Pipeline

**Purpose:** When a child names an object not directly in the knowledge base (e.g., "cat food"), the system resolves it to a supported "anchor" (e.g., "cat"). The bridge gently moves the conversation from the surface object to the anchor.

**Phases:**

#### Phase 1: Pre-Anchor Bridge (`bridge_phase=pre_anchor`)
**Trigger:** `anchor_status="anchored_high"` on session start.

**What the user sees:**
1. The intro question already stays inside the "bridge lane" (doesn't ask about surface-only details).
2. On each child reply, the system classifies whether the child "followed" the bridge toward the anchor.
3. If followed: transition to Bridge Activation.
4. If clarification/IDK/off-lane: up to 2 support turns (scaffold, clarify, steer) without consuming bridge attempts.
5. If missed: up to 2 bridge retry attempts with new angles.
6. If all retries exhausted: fall back to `unresolved` (surface-only mode).

#### Phase 2: Bridge Activation (`bridge_phase=activation`)
**Trigger:** Child followed the bridge, OR child reopened a dormant bridge by mentioning anchor-side content.

**What the user sees:**
1. The AI acknowledges the child's reply and asks an anchor-side question using latent KB grounding.
2. The question is validated against the anchor's KB. If it's KB-backed and "handoff-ready", the system waits for the child to answer it.
3. If the child answers the handoff-ready question: commit to `anchor_general` (ordinary chat about the anchor).
4. If not: continue activation for up to 4 turns, then timeout fallback to unresolved.

**Key behavioral rule:** The child does NOT know a bridge is happening. The conversation feels natural. The system tracks `activation_turn_count` and `activation_handoff_ready` internally.

---

### 2.4 Attribute Activity Pipeline

**Trigger:** `/api/start` with `attribute_pipeline_enabled=true`.

**What the user sees:**
1. **Intro:** The AI opens with a greeting that makes a specific attribute feel naturally noticeable (e.g., "It looks so bright and fresh!" for color). The question is open-ended ("What do you notice first?"), NOT a quiz.
2. **Continuation:** On each child reply, the AI classifies intent, then:
   - Responds using the normal intent prompt (but with an attribute coherence hint).
   - Generates a follow-up question with an `ATTRIBUTE_SOFT_GUIDE` appended.
3. **Soft guide techniques:**
   - **A) Salience:** Include an attribute-related sensory word in the question.
   - **B) Frame weaving:** When child noticed something else, offer a choice that includes the attribute.
   - **C) Natural bridge:** When enough depth is reached, extend toward the activity target and emit `[ACTIVITY_READY]` (invisible to child).
4. **Activity ready:** When `[ACTIVITY_READY]` is detected AND the REASON line contains direct quotes from the child's messages, the `activity_ready` flag is set. The next turn invites the child to the activity.

**Key behavioral rule:** The attribute is NEVER forced. The conversation can wander, but the follow-up questions gently lean toward the attribute when it fits naturally.

**Data that flows:**
- `attribute_label`: the focused attribute (e.g., "body color")
- `activity_target`: what the child will eventually do (e.g., "noticing and describing what apple looks like")
- `activity_ready`: true when the system decides to hand off to the activity

---

### 2.5 Category Activity Pipeline

**Trigger:** `/api/start` with `category_pipeline_enabled=true`.

**What the user sees:**
1. **Intro:** The AI opens by framing the object as part of a bigger category (e.g., "I see a little cat! Cats are part of the animal family."). Ends with one easy category-level question.
2. **Continuation:** On each child reply, the system classifies the reply type:
   - `uncertainty` -> scaffold with a category clue
   - `constraint_avoidance` -> low-pressure repair
   - `activity_command` -> acknowledge but stay in category
   - `curiosity` -> answer and reconnect to category
   - `category_drift` -> accept comparison, keep category
   - `aligned` -> continue category lane
3. **Activity readiness:** After 2 counted turns of coherent category engagement, `activity_ready` is set. The next response invites the child to the category activity.

**Key behavioral rule:** The conversation stays at the category level, not drilling into a single attribute.

**Data that flows:**
- `category_label`: the inferred category (e.g., "Animals")
- `activity_target`: category-level exploration goal
- `turn_count`: counted turns toward readiness threshold (default: 2)

---

### 2.6 Exploration / Guide Mode Pipeline

**Trigger:** Child has given 2 correct answers (`GUIDE_MODE_THRESHOLD = 2`) about a supported anchor object while `learning_anchor_active=true`.

**What the user sees:**
1. On the 2nd correct answer, the system silently classifies the conversation into an IB PYP theme (e.g., "How the World Works").
2. The `correct_answer` node still produces a confirmation + wow fact + follow-up question.
3. On subsequent turns, the system enters "guide mode" where responses are steered toward the `key_concept` associated with the object/theme.
4. The theme classification is exposed in the final SSE chunk metadata.

**Key behavioral rule:** The child does not know guide mode has started. The conversation feels continuous. The theme is derived from conversation history, not just the object name.

---

## 3. Proposed OpenSpec Structure

### Directory Layout

```
docs/behavioral_specs/
  PIPELINE_SPEC_DESIGN.md          # This document
  openspec/
    _index.yaml                    # Registry of all spec files
    common/
      voice_contract.yaml          # Shared voice/personality rules
      intent_taxonomy.yaml         # All 13 intents with definitions
      state_schema.yaml            # Shared state fields across pipelines
    pipelines/
      introduction.yaml
      general_chat.yaml
      bridge.yaml
      attribute_activity.yaml
      category_activity.yaml
      guide_mode.yaml
    nodes/
      analyze_input.yaml
      curiosity.yaml
      correct_answer.yaml
      clarifying_idk.yaml
      give_answer_idk.yaml
      # ... one per intent node
    fragments/
      followup_question_rules.yaml
      bridge_activation_rules.yaml
      attribute_soft_guide.yaml
```

### Spec File Format (YAML-based OpenSpec)

Each pipeline spec should contain:

```yaml
spec_version: "1.0"
pipeline_id: "general_chat"
description: "Ordinary conversation responding to child intent and asking follow-up questions"

triggers:
  - condition: "child sends a reply"
    excludes:
      - "attribute_lane_active"
      - "category_lane_active"
      - "bridge_phase in [pre_anchor, activation]"
      - "anchor_confirmation_needed"

entry_point:
  node: "analyze_input"

nodes:
  analyze_input:
    type: "classifier"
    description: "Classify child utterance into one of 13 communicative intents"
    inputs:
      - child_answer
      - last_model_response
      - object_name
    outputs:
      - intent_type
      - new_object_name  # only for ACTION/AVOIDANCE
      - classification_status
    user_visible: false
    routing:
      - intent: "correct_answer"
        condition: "correct_answer_count + 1 >= 2 AND learning_anchor_active"
        next: "classify_theme"
      - intent: "clarifying_idk"
        condition: "consecutive_struggle_count >= 2"
        next: "give_answer_idk"
      - default: "intent_type"

  curiosity:
    type: "response_generator"
    description: "Child asked why/what/how -- answer directly with one wow fact and a playful closing question"
    structure:
      - beat: "direct_answer"
        rule: "Lead with the answer immediately. No 'That's a great question!'"
      - beat: "wow_detail"
        rule: "One surprising fact that amplifies the answer. Use numbers, comparisons, sensory images."
      - beat: "closing_question"
        rule: "One fun imaginative question growing from the wow detail. NOT knowledge-testing."
    outputs:
      - full_response_text
    user_visible: true

  correct_answer:
    type: "response_generator"
    description: "Child answered correctly -- confirm, wow fact, then follow-up question"
    structure:
      - beat: "confirm"
        rule: "Paraphrase the child's answer. Do NOT echo verbatim."
      - beat: "wow_fact"
        rule: "One surprising fact from KB only. Must relate to the hook in child's answer."
    follow_up:
      generator: "ask_followup_question_stream"
      rule: "Question must grow from the last assistant message"
    outputs:
      - full_response_text
      - correct_answer_count
    user_visible: true

  # ... etc for all nodes

termination:
  node: "finalize"
  action: "Send final SSE chunk with finish=true, update conversation history"
```

---

## 4. Example Spec Snippet (Correct Answer Node)

```yaml
# openspec/nodes/correct_answer.yaml
spec_version: "1.0"
node_id: "correct_answer"
pipeline: "general_chat"

description: |
  The child directly answered the AI's previous question with meaningful content
  (correct, complete, or substantially on-target). The AI confirms their answer,
  rewards them with one surprising related fact, and then asks a follow-up question.

triggers:
  - intent_type: "CORRECT_ANSWER"
  - route_condition: "Not at guide mode threshold, or learning_anchor_active is false"

inputs:
  - name: child_answer
    type: string
    description: "The child's reply text"
  - name: last_model_response
    type: string
    description: "The AI's previous full message (response + question)"
  - name: object_name
    type: string
  - name: knowledge_context
    type: string
    description: "KB facts for grounding. BEAT 2 must use only facts from this block."
  - name: age
    type: integer
    range: [3, 8]

behavior:
  step_0_find_hook:
    description: "Read the child's answer. Identify the most specific or emotionally loaded element."
    rule: "The wow fact in BEAT 2 MUST relate to this hook."
    examples:
      - child: "No! He will eat me"
        hook: "fear of being eaten / hunting / sharp teeth"
        good_wow: "Lions hunt in groups -- the females do most of the chasing!"
        bad_wow: "A lion's roar can be heard from five miles away."

  beat_1_confirm:
    description: "Warm confirmation that acknowledges the child's specific answer"
    rules:
      - "Paraphrase -- do NOT echo their exact words verbatim"
      - "Avoid hollow praise like 'That's a great answer!'"
    examples:
      - child: "I feel sweet" -> "Yes! Apples taste sweet -- you got it!"
      - child: "It's red" -> "That's right -- that bright red is the first thing everyone notices!"

  beat_2_wow_fact:
    description: "One surprising related fact as a declarative statement"
    rules:
      - "Must use only facts from GROUNDING block"
      - "NEVER start with 'Did you know...?' -- state as direct sentence"
      - "Must NOT repeat anything from the immediately preceding model message"
      - "Must NOT echo any phrase from BEAT 1"
    age_scaling:
      - "Ages 3-5: One short, concrete, sensory fact"
      - "Ages 6-8: One fact with a brief 'why' or comparison"

  follow_up_question:
    description: "Generated separately by ask_followup_question_stream"
    rules:
      - "Must grow from the last assistant message (same detail or one-hop nearby)"
      - "Concrete, directly answerable, easy to answer right now"
      - "Never echo or repeat any phrase from the previous assistant message"
      - "No lead-in exclamation or celebration before the question"

outputs:
  - name: full_response_text
    type: string
    composition: "beat_1 + ' ' + beat_2 + ' ' + follow_up_question"
  - name: correct_answer_count
    type: integer
    description: "Incremented if learning_anchor_active is true"
  - name: used_kb_item
    type: dict
    description: "Debug-only mapping of which KB item was used"

prohibitions:
  - "Do NOT ask 'How did you know that?'"
  - "Do NOT echo exact words as celebration"
  - "Do NOT use 'Did you know...?' anywhere"
  - "Do NOT ask a question within the intent response (only in follow-up)"
```

---

## 5. Gaps in Understanding

The following areas could not be fully determined from code review alone:

1. **Theme Navigator / Guide Mode detailed behavior:** The `theme_navigator_rules` prompt exists in `paixueji_prompts.py`, but the actual `stream/theme_guide.py` file was not found in the codebase. The full guide-mode turn logic (post-theme-classification) is referenced but not fully traceable.

2. **Exploration activities (post-chat-phase):** The specs describe what happens during the chat phase. What happens AFTER `activity_ready` or `chat_phase_complete` is true (the actual "activity" the child is invited to) appears to be outside this codebase.

3. **Object resolution (`object_resolver.py`):** The exact YAML lookup and LLM-based resolution logic for mapping surface objects to anchors was not fully read. The resolution result shapes are understood, but the resolution algorithm itself is a black box.

4. **KB context building (`kb_context.py`):** The exact format of `physical_dimensions` and `engagement_dimensions` context strings was not examined.

5. **Stream chunk metadata full semantics:** Some fields in `StreamChunk` (e.g., `activation_child_reply_type`, `counted_turn_reason`) are populated in complex conditional branches. A complete state machine of all possible values would require deeper tracing.

6. **Hook type selection algorithm:** The `select_hook_type` function in `stream/utils.py` was not read. The age-weighted sampling and history-based exclusion logic is referenced but not understood.

7. **Fun fact integration:** The `node_generate_fun_fact` exists in `graph.py` but the current intro path in `paixueji_app.py` does not appear to call it. It may be dead code or used in a different entry point.

8. **Test scenarios:** The `tests/scenarios/` directory was mentioned in git status but not explored. These may contain valuable behavioral examples.
