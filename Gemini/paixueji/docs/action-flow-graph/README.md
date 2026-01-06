# Paixueji Action Flow Graph Documentation

## Overview

This documentation provides an **exhaustive, debuggable, non-abstract** action flow graph for the Paixueji educational assistant system. It is designed for **production incident debugging**, enabling rapid diagnosis of unexpected behavior by mapping every action, state transition, and error path.

**Key Principles**:
- **Exhaustive**: All 56 actions enumerated, no implicit steps
- **Debuggable**: Every decision node shows ALL branches including errors
- **Non-Abstract**: Medium-level granularity includes validation, streaming, classification
- **Tree-Like**: Root node is "user clicks Start Conversation", flows linearly

---

## Quick Start

### Visualize the Diagram
**Copy [04-master-flow.mmd](./04-master-flow.mmd) → Paste into https://mermaid.live to see the complete tree**

### For Production Incidents
1. **Identify symptom** → Go to [05-completeness-checklist.md](./05-completeness-checklist.md)
2. **Find matching scenario** → Note scenario number (1-51)
3. **Locate in diagram** → Open [04-master-flow.mmd](./04-master-flow.mmd) at referenced location
4. **Check code** → Follow file:line references in checklist
5. **Debug** → Compare expected vs. actual behavior

### For Understanding the System
1. **Start with** → [01-action-taxonomy.md](./01-action-taxonomy.md) - Learn all 56 actions
2. **Understand state** → [02-state-models.md](./02-state-models.md) - 3 state models (Frontend, Session, Streaming)
3. **Trace flow** → [04-master-flow.mmd](./04-master-flow.mmd) - Visual tree diagram
4. **Deep dive** → [03-transition-tables/](./03-transition-tables/) - Phase-by-phase transition tables

---

## Documentation Structure

```
docs/action-flow-graph/
├── README.md (this file)
│
├── 01-action-taxonomy.md
│   └── 54 actions categorized into 6 types:
│       - USER_ (7): User interactions (click, type, submit)
│       - FE_ (12): Frontend state + UI rendering
│       - API_ (6): HTTP endpoints (Flask routes)
│       - BE_ (14): Backend orchestration (session, streaming, SSE)
│       - VALIDATE_ (4): AI-powered validation + routing
│       - AI_ (11): Gemini model content generation
│
├── 02-state-models.md
│   └── 3 explicit state models:
│       - Frontend UI State (app.js globals)
│       - Session State (PaixuejiAssistant instance)
│       - Streaming State (per-request transient)
│
├── 03-transition-tables/
│   ├── phase1-initialization.md
│   │   └── Form fill → classify → start button → API_POST_/start
│   ├── phase2-sse-setup.md
│   │   └── Session creation → event loop → orchestrator
│   ├── phase3-introduction.md
│   │   └── First question streaming (introduction flow)
│   ├── phase4-dual-parallel.md (TODO)
│   │   └── Validation → 5 routing paths → dual-parallel response+question
│   ├── phase5-response-streaming.md (TODO)
│   │   └── 5 response generators (explanation, feedback, correction, topic_switch, explicit_switch)
│   ├── phase6-question-streaming.md (TODO)
│   │   └── Follow-up question generation (Part 2)
│   ├── phase7-frontend-rendering.md (TODO)
│   │   └── SSE parsing → chunk rendering → state updates
│   ├── phase8-system-managed-focus.md (TODO)
│   │   └── Depth → width → object_selection transitions
│   └── phase9-error-handling.md (TODO)
│       └── All error paths + fallbacks
│
├── 04-master-flow.mmd
│   └── Single unified Mermaid diagram:
│       - Root: "👤 USER clicks Start Conversation"
│       - 9 phases as subgraphs (Phases 4-7 nested within ConversationLoop)
│       - Color-coded by actor (user/FE/BE/AI/validate/error/SSE)
│       - Inline error branches
│       - SSE streaming mechanics visible
│       - Manual override & object selection flows included
│
└── 05-completeness-checklist.md
    └── 51 production-critical scenarios:
        - Validation edge cases (9)
        - Streaming edge cases (7)
        - Classification edge cases (3)
        - Session edge cases (3)
        - Object switching edge cases (5)
        - System-managed focus edge cases (6)
        - Progress tracking edge cases (4)
        - Frontend state edge cases (3)
        - HTTP error paths (5)
        - Conversation history edge cases (3)
        - Flow tree debugging edge cases (3)
```

---

## How to Use This Documentation

### Scenario 1: Production Incident - "Session Not Found" Error

**Step 1**: Go to [05-completeness-checklist.md](./05-completeness-checklist.md#20-session-not-found-404)
- Find: **Scenario #20: Session Not Found (404)**

**Step 2**: Read expected behavior
- Expected: HTTP 404 response
- Outcome: FE shows "Session not found. Please restart conversation."

**Step 3**: Locate in diagram
- Diagram: Phase 4 → D1 → D2 (Session Exists?) → D3 (404)
- Open [04-master-flow.mmd](./04-master-flow.mmd), search for "D2" or "Session Exists"

**Step 4**: Check code
- Code: app.py:312-318 (lookup), static/app.js:385-386 (404 handler)
- Examine: `sessions.get(session_id)` returns None

**Step 5**: Debug
- Check: Server logs for session_id
- Verify: Was server restarted? (sessions cleared)
- Fix: User must restart conversation OR implement persistent session storage

### Scenario 2: Understanding "Why did the topic switch?"

**Step 1**: Identify the action
- Go to [01-action-taxonomy.md](./01-action-taxonomy.md#validate_-actions-4-total)
- Find: **VALIDATE_unified_ai** - 3-part validation

**Step 2**: Understand the decision logic
- Go to [04-master-flow.mmd](./04-master-flow.mmd)
- Locate: Phase 4 → D7 (VALIDATE_unified_ai) → D13 (Routing Logic)
- See 5 branches, one is "engaged + correct + SWITCH + new_object" → E3_TopicSwitch

**Step 3**: Read the code
- File: paixueji_stream.py:911-1160 (decide_topic_switch_with_validation)
- Logic: AI analyzes answer, determines:
  - Is child engaged? (not "I don't know")
  - Is answer factually correct?
  - Should we switch? (child named new object? off-topic?)
  - If yes to all → decision = SWITCH, new_object = "X"

**Step 4**: Trace the flow
- Phase 4 → E3_TopicSwitch path
- Updates object_name, classifies new object
- If system_managed → resets focus state
- Streams celebration + introduction of new object

### Scenario 3: Debugging SSE Streaming Issue

**Step 1**: Understand SSE mechanics
- Go to [02-state-models.md](./02-state-models.md#3-streaming-state-per-request-transient)
- Read: Streaming State lifecycle
- Understand: buffer accumulation, chunk parsing, finish flag

**Step 2**: Trace SSE flow in diagram
- Go to [04-master-flow.mmd](./04-master-flow.mmd)
- Phase 3 (Introduction) or Phase 5/6 (Dual-Parallel)
- Follow: ⚡ SSE Stream Loop → FE_buffer_sse_data → FE_parse_sse_event → FE_render_text_chunk

**Step 3**: Check transition table
- Go to [03-transition-tables/phase3-introduction.md](./03-transition-tables/phase3-introduction.md)
- See: Detailed state transitions per SSE chunk
- Understand: '\n\n' delimiter, event types (chunk/complete/error)

**Step 4**: Debug in browser
- Open DevTools → Network → find SSE connection
- Check: Event stream format
- Verify: Each event has "event: chunk\ndata: {...}\n\n"
- Inspect: StreamChunk JSON structure

---

## Color Legend (Mermaid Diagram)

| Color | Actor/Type | Example Actions |
|-------|-----------|----------------|
| 🔵 Blue (#e3f2fd) | USER_ actions | USER_fill_form, USER_click_start, USER_send_message |
| 🟣 Purple (#f3e5f5) | FE_ actions | FE_parse_sse_event, FE_render_text_chunk, FE_update_debug_panel |
| 🟡 Yellow (#fff9c4) | BE_ actions, API_ endpoints | BE_create_session, BE_emit_sse_chunk, API_POST_/continue |
| 🟢 Green (#e8f5e9) | AI_ streaming | AI_stream_feedback, AI_stream_followup_question, AI_validate_answer |
| 🔴 Red (#ffebee) | Error paths | Validation timeout, HTTP 404, Stream abort |
| 🟠 Orange (#fff3e0) | VALIDATE_ actions | VALIDATE_unified_ai, VALIDATE_route_decision, VALIDATE_system_focus |
| 💗 Pink (#fce4ec) | Decision nodes | Is engaged? Is correct? Session exists? |
| 🔷 Teal (#e0f2f1) | SSE streaming | SSE Stream Loop, BE_emit_sse_chunk, SSE complete |

---

## Key Concepts

### Dual-Parallel Streaming Architecture
**Phase 4-6**: Response and question generation are **decoupled**
1. **Part 1** (Response): AI_stream_feedback/explanation/correction/topic_switch
   - Celebrates, explains, or corrects based on validation
   - Streamed immediately, updates conversation_history
2. **Part 2** (Question): AI_stream_followup_question
   - Uses Part 1 as context, generates next question
   - Based on focus_mode (depth/width/category)
   - Streamed after Part 1 complete
3. **Combined**: full_response = Part1 + Part2 for history

**Exception**: explicit_switch and natural_completion skip Part 2 (response contains selection or completion message)

### 3-Part Unified Validation (VALIDATE_unified_ai)
**Phase 4 - Critical Decision Point**

Single AI call returns:
1. **Engagement**: Is child trying to answer? (not "I don't know")
2. **Correctness**: Is answer factually accurate? (only if engaged)
3. **Topic Switching**: Should we switch objects? (invited naming, off-topic, explicit request)

**Output**: {is_engaged, is_factually_correct, correctness_reasoning, decision (SWITCH/CONTINUE), new_object, switching_reasoning}

**Fallback**: On timeout/error → safe defaults (engaged=true, correct=true, CONTINUE)

### System-Managed Focus Mode Transitions
**Phase 8 - Automatic Learning Path**

```
DEPTH (4-5 questions) → WIDTH (compare objects) → OBJECT SELECTION (natural completion)
```

**Depth Phase**:
- Ask depth_target (random 4-5) questions about object features/uses
- Increment depth_questions_count only for engaged answers
- When target reached → switch to width

**Width Phase**:
- Explore objects with same color/shape/category
- Track width_wrong_count (consecutive wrong/stuck answers)
- Reset count on correct answer
- When wrong_count >= 3 → natural completion

**Object Selection**:
- Congratulate child
- Ask "What else would you like to learn about?"
- Natural language (no UI buttons)
- Next answer detected as SWITCH by validation

---

## Common Debugging Patterns

### Pattern 1: "Why didn't correct_answer_count increment?"
**Check**:
1. Was `is_factually_correct = True`? (Phase 4 validation)
2. Was `chunk.finish = True`? (Phase 6 final chunk)
3. Both must be true: app.py:348-363 (increment logic)

**Common Causes**:
- Answer marked wrong by validation
- "I don't know" → is_engaged=False → is_factually_correct=null
- Stream aborted before finish chunk

### Pattern 2: "Why did AI use fallback response?"
**Check**:
1. Gemini API timeout? (Phase 5, any AI_stream_* action)
2. Empty response? (rare)
3. Exception during streaming?

**Fallbacks**:
- Introduction: "Tell me about {object}!"
- Feedback: "Great job!"
- Explanation: "Let me help you with that!"
- Correction: "Actually, let me tell you more!"
- Question: "What else can you tell me about {object}?"

### Pattern 3: "Why did topic switch when it shouldn't?"
**Check**:
1. Validation result: decision = SWITCH, new_object = "X"
2. Was it invited naming? (Q: "Can you name another animal?" A: "dog")
3. Was it off-topic? (Child completely ignored question)
4. Was it explicit request? (Child said "let's talk about dogs")

**Not a switch**:
- Direct answer: Q: "What do monkeys eat?" A: "Bananas" → CONTINUE
- Category/part mention: "seeds", "skin" → CONTINUE
- In-passing mention: "red like cherry" → CONTINUE

### Pattern 4: "Stream aborted mid-response"
**Check**:
1. User clicked Stop? (USER_click_stop → FE_abort_stream)
2. User sent new message while streaming? (concurrent request abort)
3. Network issue? (rare)

**Recovery**:
- Partial response visible to user
- Backend sees GeneratorExit exception
- Stream cleaned up, send button re-enabled

---

## Maintenance Instructions

### Adding a New Action
1. Add to [01-action-taxonomy.md](./01-action-taxonomy.md) with description, source, trigger
2. Determine which phase it belongs to
3. Add to appropriate transition table in [03-transition-tables/](./03-transition-tables/)
4. Add node to [04-master-flow.mmd](./04-master-flow.mmd) with correct color class
5. If edge case, add scenario to [05-completeness-checklist.md](./05-completeness-checklist.md)

### Adding a New Decision Point
1. Enumerate ALL possible branches (success + all error paths)
2. Add decision node (rhombus) to Mermaid diagram
3. Document decision logic in transition table
4. Add test scenarios to completeness checklist

### Updating State Models
1. Update [02-state-models.md](./02-state-models.md) with new field
2. Document: Type, default value, when updated, lifecycle
3. Update state transition sections in relevant phase tables

---

## Limitations & Future Work

### Current Limitations
1. **Incomplete Transition Tables**: Phases 4-9 detailed tables pending
   - Phase 4: Dual-parallel validation & routing (most complex)
   - Phase 5-9: Response/question streaming, frontend rendering, focus transitions, error handling
   - **Workaround**: Use [04-master-flow.mmd](./04-master-flow.mmd) and [05-completeness-checklist.md](./05-completeness-checklist.md) for complete coverage

2. **Unbounded History**: No truncation/pagination implemented
   - Long conversations (1000+ messages) cause memory growth
   - See Scenario #46 in completeness checklist

3. **No Session Persistence**: In-memory sessions lost on server restart
   - See Scenarios #20-22 in completeness checklist

### Recommended Enhancements
1. **Complete Phase 4-9 Transition Tables**: Add detailed action → state tables for remaining phases
2. **Performance Metrics**: Add timing/token tracking to diagram
3. **Alternative Flows**: Document admin actions, debug endpoints
4. **Interactive Diagram**: HTML version with clickable nodes linking to code

---

## Quick Reference

### Files to Check During Incidents

| Symptom | Files to Check |
|---------|---------------|
| Session not found | app.py:312-318 (lookup), server logs |
| Wrong validation result | paixueji_stream.py:911-1160 (decide_topic_switch_with_validation) |
| Stream aborted | app.js:300-314 (stopStreaming), paixueji_stream.py:2299-2303 |
| Classification timeout | app.py:532-541, 589-598, paixueji_assistant.py:237-314 |
| Empty AI response | paixueji_stream.py (any AI_stream_* function exception handlers) |
| SSE parse error | app.js:243-263 (parseSSE logic) |
| Progress not updating | app.py:348-363 (increment_correct_answers) |
| Focus not switching | paixueji_stream.py:1696-1836 (decide_next_focus_mode) |

### Critical Code Locations

| Component | File:Lines |
|-----------|-----------|
| Main orchestrator | paixueji_stream.py:2010-2304 (call_paixueji_stream) |
| Unified validation | paixueji_stream.py:911-1160 (decide_topic_switch_with_validation) |
| SSE streaming loop | app.py:200-295 (generate function) |
| Frontend SSE handling | app.js:243-263 (parseSSE), 464-603 (handleStreamChunk) |
| Session state | paixueji_assistant.py:39-99 (class attributes) |
| System-managed focus | paixueji_stream.py:1696-1836 (decide_next_focus_mode) |

---

## Support

For questions or issues:
1. Check [05-completeness-checklist.md](./05-completeness-checklist.md) for matching scenario
2. Trace flow in [04-master-flow.mmd](./04-master-flow.mmd)
3. Examine code at file:line references
4. Check server logs for error messages
5. Inspect StreamChunk metadata in browser DevTools

---

**Last Updated**: 2026-01-06
**Status**: Core documentation complete (taxonomy, state models, master diagram, completeness checklist, phases 1-3 transition tables)
**Remaining**: Phases 4-9 detailed transition tables (optional - core functionality fully documented in diagram + checklist)
