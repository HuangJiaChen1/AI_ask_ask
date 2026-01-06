# System State Models

## Overview
This document defines the 3 explicit state models in the Paixueji system:
1. **Frontend UI State** - Browser/JavaScript runtime state
2. **Session State** - Backend session object (PaixuejiAssistant)
3. **Streaming State** - Transient per-request state during SSE streaming

---

## 1. Frontend UI State

**Location**: `static/app.js` (global variables, lines 15-28)
**Lifecycle**: Created on page load, persists until page refresh
**Persistence**: Partial (tone + focus saved to localStorage)

### State Schema

```javascript
{
  // Session Identification
  sessionId: string | null
    // UUID assigned by backend on first chunk
    // null until first response received
    // Set at: app.js:499-502 (handleStreamChunk)

  // Streaming State
  isStreaming: boolean
    // true when SSE stream active
    // false when idle or stream complete
    // Set at: app.js:165 (startConversation), 344 (sendMessage),
    //         307 (stopStreaming), 470 (handleSSEEvent complete)

  currentStreamController: AbortController | null
    // AbortController for current SSE stream
    // Used to cancel stream mid-flight
    // Created at: app.js:202 (startConversation), 369 (sendMessage)
    // Cleared at: app.js:307 (stopStreaming), 434 (abort handler)

  currentMessageDiv: HTMLElement | null
    // DOM reference to current streaming message bubble
    // Used to append text chunks
    // Created at: app.js:516-521 (handleStreamChunk first chunk)
    // Cleared at: app.js:532 (handleStreamChunk finish)

  // Progress Tracking
  correctAnswerCount: number
    // Count of correct answers (0-4)
    // Never reaches completion in infinite mode
    // Updated at: app.js:506 (handleStreamChunk)

  conversationComplete: boolean
    // Always false in infinite mode
    // Legacy field, not actively used
    // Set at: app.js:17 (init to false)

  // Object & Topic Management
  currentObject: string
    // Current object being discussed
    // Updated when object switches
    // Set at: app.js:560 (handleStreamChunk new_object_name)

  detectedObject: string | null
    // Object AI detected but decided to CONTINUE
    // Used for manual override panel
    // Set at: app.js:580 (handleStreamChunk detected_object_name)
    // Cleared at: app.js:1022 (dismissSwitchPanel)

  awaitingObjectSelection: boolean
    // true when system presents object choices
    // false normally
    // Set at: app.js:1033 (handleObjectSelection)
    // Cleared at: app.js:1105 (selectObject success)

  // Configuration
  categoryData: object
    // Loaded category hierarchy from object_prompts.py
    // Structure: {level1_categories: [...], level2_categories: {...}, level3_categories: {...}}
    // Loaded at: app.js:38-112 (loadCategories)

  currentTone: string
    // Assistant tone preference
    // Options: friendly, excited, teacher, pirate, robot, storyteller
    // Persisted to: localStorage.paixueji_tone (app.js:136, 923)

  currentFocusMode: string
    // Active focus strategy
    // Options: system_managed, depth, width_shape, width_color, width_category
    // Persisted to: localStorage.paixueji_focus (app.js:910, 932)

  systemManagedMode: boolean
    // true if using system-managed focus transitions
    // false if manual focus mode
    // Set at: app.js:561 (handleStreamChunk system_focus_mode)
}
```

### State Lifecycle

#### Initialization (Page Load)
```javascript
// app.js:15-28
sessionId = null
isStreaming = false
currentStreamController = null
correctAnswerCount = 0
conversationComplete = false
categoryData = null  // Loaded async
detectedObject = null
systemManagedMode = false
awaitingObjectSelection = false
currentObject = ""
currentTone = localStorage.getItem('paixueji_tone') || "friendly"
currentFocusMode = localStorage.getItem('paixueji_focus') || "system_managed"
currentMessageDiv = null
```

#### Session Start
```javascript
// After USER_click_start → API_POST_/start
isStreaming = true
currentStreamController = new AbortController()
sessionId = null  // Wait for first chunk

// After first chunk received
sessionId = chunk.session_id  // UUID
currentMessageDiv = createElement('div')  // First message bubble
correctAnswerCount = chunk.correct_answer_count
currentObject = chunk.current_object_name
```

#### During Streaming
```javascript
// Each chunk
if (!currentMessageDiv) {
  currentMessageDiv = createElement('div')  // Create bubble
}
currentMessageDiv.textContent += chunk.response  // Append text

// Finish chunk
if (chunk.finish) {
  currentMessageDiv = null  // Ready for next message
  isStreaming = false
  currentStreamController = null
}
```

#### Object Switch
```javascript
// When new_object_name in chunk
currentObject = chunk.new_object_name
updateDebugPanel()

// When detected_object_name in chunk (but CONTINUE decision)
detectedObject = chunk.detected_object_name
showSwitchPanel()  // Manual override UI
```

#### Stream Abort
```javascript
// USER_click_stop
currentStreamController.abort()
currentStreamController = null
isStreaming = false
currentMessageDiv = null  // Partial message remains visible
```

#### Page Refresh
```javascript
// All state lost EXCEPT localStorage
sessionId = null  // Session still exists on server but inaccessible
// User must restart conversation
```

---

## 2. Session State (PaixuejiAssistant)

**Location**: `paixueji_assistant.py:39-99` (class attributes)
**Lifecycle**: Created on API_POST_/start, persists until server restart or API_POST_/reset
**Storage**: In-memory dict `sessions[session_id]` in app.py
**Persistence**: None (lost on server restart)

### State Schema

```python
class PaixuejiAssistant:
    # Core Identification
    session_id: str
        # UUID for this session
        # Generated at: app.py:123
        # Used as: dict key in sessions{}

    # Object & Category State
    object_name: str
        # Current object being discussed
        # Set at: __init__ or reset_object_state
        # Updated at: topic switch, object selection, force switch

    level1_category: str | None
        # Top-level category (e.g., "foods", "animals")
        # Set at: __init__ or classify_object_sync
        # Can be None if classification timeout/error

    level2_category: str | None
        # Mid-level category (e.g., "fruits", "pets")
        # Set at: __init__ or classify_object_sync
        # Can be None if classification timeout/error

    level3_category: str | None
        # Specific category (e.g., "red_fruits", "domestic_animals")
        # Set at: __init__
        # Can be None if user selects "none of the above"

    # User Configuration
    age: int | None
        # Child's age (3-8)
        # Set at: __init__
        # Used for: age-appropriate prompts, simplifications

    tone: str | None
        # Assistant tone ("friendly", "excited", "teacher", "pirate", "robot", "storyteller")
        # Set at: __init__
        # Used for: tone_prompt in system message

    # Progress Tracking
    correct_answer_count: int
        # Count of correct answers
        # Incremented at: increment_correct_answers() (app.py:348-363)
        # Never triggers completion (infinite mode)
        # Range: 0 to infinity

    # Conversation History
    conversation_history: list[dict]
        # OpenAI-style message list
        # Format: [{"role": "system"|"user"|"assistant", "content": str}, ...]
        # Updated at:
        #   - __init__: [system_prompt]
        #   - API_POST_/continue: append user message
        #   - call_paixueji_stream: append assistant response
        # Unbounded growth (memory leak potential on very long sessions)

    # System-Managed Focus Mode State
    system_managed_focus: bool
        # true: AI controls focus transitions (depth → width → object_selection)
        # false: User controls focus mode manually
        # Set at: __init__
        # Used at: decide_next_focus_mode (paixueji_stream.py:1696)

    current_focus_mode: str
        # Active focus strategy
        # Values: "depth" | "width_color" | "width_shape" | "width_category" | "object_selection"
        # Set at: __init__ ("depth"), decide_next_focus_mode
        # Reset at: reset_object_state (new object → "depth")

    depth_questions_count: int
        # Questions asked during depth phase for current object
        # Incremented: Only for engaged answers (paixueji_stream.py:1737)
        # Reset at: reset_object_state (new object → 0)
        # Range: 0 to depth_target

    depth_target: int
        # Random target for depth phase (4 or 5)
        # Set at: __init__, reset_object_state
        # Randomized: random.randint(4, 5) per object
        # Used for: depth phase completion check

    width_wrong_count: int
        # Consecutive wrong/not-engaged answers in width phase
        # Incremented: On wrong or not engaged in width phase
        # Reset: On correct answer in width phase (paixueji_stream.py:1786)
        # Threshold: >= 3 triggers natural_topic_completion
        # Reset at: reset_object_state (new object → 0)

    width_categories_tried: list[str]
        # Width categories completed for current object
        # Values: subset of ["color", "shape", "category"]
        # Appended: When switching width category
        # Reset at: reset_object_state (new object → [])

    # Debugging
    flow_tree: ConversationFlowTree | None
        # Tracks complete conversation flow for debugging
        # Created at: __init__ if debugging enabled
        # Updated at: app.py:364-424 (add_node)
        # Used by: /api/debug/flow-tree endpoint

    # AI Client
    client: genai.Client
        # Gemini API client instance
        # Created at: __init__
        # Configured: Vertex AI, project, location

    # Cached Prompts
    prompts: dict
        # Cached prompt templates
        # Keys: system_prompt, age_prompts, tone_prompts, focus_prompts, category_prompts
        # Set at: __init__
        # Used for: Message preparation
```

### State Lifecycle

#### Session Creation (API_POST_/start)
```python
# app.py:123-179
session_id = str(uuid.uuid4())
assistant = PaixuejiAssistant(
    object_name=request_data['object_name'],
    level1_category=request_data.get('level1_category'),
    level2_category=request_data.get('level2_category'),
    level3_category=request_data.get('level3_category'),
    age=request_data.get('age'),
    tone=request_data.get('tone')
)

# PaixuejiAssistant.__init__
self.conversation_history = [{"role": "system", "content": system_prompt}]
self.correct_answer_count = 0
self.system_managed_focus = (focus_mode == 'system_managed')
self.current_focus_mode = 'depth'
self.depth_questions_count = 0
self.depth_target = random.randint(4, 5)
self.width_wrong_count = 0
self.width_categories_tried = []
self.flow_tree = ConversationFlowTree(session_id) if debugging else None

sessions[session_id] = assistant
```

#### Message Processing (API_POST_/continue)
```python
# app.py:312-318
assistant = sessions.get(session_id)
if not assistant:
    return 404

# Append user message
assistant.conversation_history.append({
    "role": "user",
    "content": child_input
})

# After streaming complete
assistant.conversation_history.append({
    "role": "assistant",
    "content": full_response  # Part1 + Part2 combined
})

# If correct answer
if chunk.is_factually_correct and chunk.finish:
    assistant.increment_correct_answers()  # correct_answer_count += 1
```

#### Object Switch
```python
# Topic switch during conversation
assistant.object_name = new_object
assistant.classify_object_sync(new_object)  # Updates level1/level2_category

# If system-managed mode
assistant.reset_object_state(new_object)
# Resets:
#   - depth_questions_count = 0
#   - width_wrong_count = 0
#   - width_categories_tried = []
#   - current_focus_mode = 'depth'
#   - depth_target = random.randint(4, 5)
```

#### System-Managed Focus Transitions
```python
# Depth phase (decide_next_focus_mode)
if current_focus_mode == 'depth':
    if is_engaged:
        depth_questions_count += 1

    if depth_questions_count >= depth_target:
        # Switch to width
        current_focus_mode = random.choice(['width_color', 'width_shape', 'width_category'])
        width_categories_tried.append(current_focus_mode.split('_')[1])

# Width phase
if current_focus_mode.startswith('width_'):
    if not is_engaged or not is_factually_correct:
        width_wrong_count += 1
    else:
        width_wrong_count = 0  # Reset on correct

    if width_wrong_count >= 3:
        # Trigger natural completion
        current_focus_mode = 'object_selection'
```

#### Session Deletion
```python
# API_POST_/reset
del sessions[session_id]
# All state lost, conversation history gone
```

#### Server Restart
```python
# All sessions lost
sessions = {}
# Clients will get 404 on next request
```

---

## 3. Streaming State (Per-Request Transient)

**Location**: `paixueji_stream.py:call_paixueji_stream` (local variables)
**Lifecycle**: Created per API call, destroyed when generator completes
**Persistence**: None (exists only during SSE streaming)

### State Schema

```python
{
    # Request Identification
    request_id: str
        # UUID for this specific request
        # Generated at: call_paixueji_stream start
        # Used for: logging, correlation

    # SSE Chunk Tracking
    sequence_number: int
        # Chunk number in this stream (0, 1, 2, ...)
        # Incremented: Each StreamChunk yield
        # Used for: StreamChunk.sequence_number field

    buffer: str
        # SSE accumulator on frontend (app.js:232, 243-247)
        # Accumulates: Incomplete SSE events until '\n\n'
        # Cleared: When complete event parsed
        # Not in backend (backend sends complete chunks)

    # Response Accumulation (Backend)
    full_response: str
        # Complete assistant response (Part1 + Part2 combined)
        # Used for: conversation_history append
        # Set at: End of streaming (paixueji_stream.py:2266, 2291)

    full_response_text: str
        # Part 1: Feedback/explanation/correction/switch message
        # Accumulated at: AI_stream_feedback/explanation/correction/topic_switch
        # Used for: question_messages context

    full_question_text: str
        # Part 2: Follow-up question
        # Accumulated at: AI_stream_followup_question
        # Used for: final full_response = Part1 + Part2

    # Validation Results (from VALIDATE_unified_ai)
    is_engaged: bool | None
        # Child is trying to answer (not stuck)
        # Set at: decide_topic_switch_with_validation
        # null if validation error
        # Used for: routing, StreamChunk field

    is_factually_correct: bool | None
        # Answer matches reality
        # Set at: decide_topic_switch_with_validation
        # null if not engaged or validation error
        # Used for: routing, increment_correct_count, StreamChunk field

    correctness_reasoning: str | None
        # Why answer is right/wrong
        # Set at: decide_topic_switch_with_validation
        # Used for: StreamChunk field, logging

    # Object Switching State
    new_object_name: str | None
        # Object to switch to (from validation)
        # Set at: decide_topic_switch_with_validation (if SWITCH + named)
        # Used for: assistant.object_name update, StreamChunk field

    detected_object_name: str | None
        # Object AI detected but decided CONTINUE
        # Set at: decide_topic_switch_with_validation (if detected but not switching)
        # Used for: StreamChunk field → FE shows manual override panel

    switch_decision_reasoning: str | None
        # Why AI decided to SWITCH or CONTINUE
        # Set at: decide_topic_switch_with_validation
        # Used for: StreamChunk field, logging

    # Response Type Routing
    response_type: str
        # One of: "introduction", "feedback", "explanation", "correction",
        #         "topic_switch", "explicit_switch", "natural_completion"
        # Set at: VALIDATE_route_decision
        # Used for: routing to correct AI streaming function

    # Focus Mode State (computed per request)
    focus_mode: str
        # User-selected or system-decided focus strategy
        # Passed from: API request OR decided by VALIDATE_system_focus
        # Used for: focus_prompt in AI calls

    system_focus_mode: str | None
        # AI-decided focus mode (only if system_managed)
        # Set at: decide_next_focus_mode
        # Used for: StreamChunk field → FE debug display

    # Performance Tracking
    start_time: float
        # Request start timestamp (time.time())
        # Set at: call_paixueji_stream start
        # Used for: duration calculation

    duration: float
        # Request processing time in seconds
        # Calculated at: End of stream
        # Used for: StreamChunk field, slow query logging

    token_usage: dict | None
        # Token consumption stats (not available in streaming mode)
        # Always null for streaming calls
        # Format: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
}
```

### State Lifecycle

#### Request Start
```python
# paixueji_stream.py:2027-2029
request_id = str(uuid.uuid4())
sequence_number = 0
start_time = time.time()

# Initialize accumulators
full_response = ""
full_response_text = ""
full_question_text = ""
is_engaged = None
is_factually_correct = None
correctness_reasoning = None
new_object_name = None
detected_object_name = None
switch_decision_reasoning = None
response_type = None
```

#### Validation Phase
```python
# VALIDATE_unified_ai
validation_result = decide_topic_switch_with_validation(...)
# Returns:
{
    "decision": "SWITCH" | "CONTINUE",
    "new_object": str | null,
    "switching_reasoning": str,
    "is_engaged": bool,
    "is_factually_correct": bool | null,
    "correctness_reasoning": str
}

# Extract to streaming state
is_engaged = validation_result['is_engaged']
is_factually_correct = validation_result['is_factually_correct']
correctness_reasoning = validation_result['correctness_reasoning']
new_object_name = validation_result['new_object']  # If SWITCH + named
switch_decision_reasoning = validation_result['switching_reasoning']
```

#### Routing Phase
```python
# VALIDATE_route_decision
if decision == "SWITCH" and not new_object:
    response_type = "explicit_switch"
elif not is_engaged:
    response_type = "explanation"
elif is_factually_correct and decision == "SWITCH":
    response_type = "topic_switch"
elif is_factually_correct:
    response_type = "feedback"
else:
    response_type = "correction"
```

#### Response Streaming (Part 1)
```python
# AI_stream_feedback/explanation/correction/topic_switch
async for chunk_text in streaming_generator:
    full_response_text += chunk_text  # Accumulate

    yield StreamChunk(
        session_id=session_id,
        sequence_number=sequence_number,
        response=chunk_text,
        finish=False,  # Not done yet
        is_engaged=is_engaged,
        is_factually_correct=is_factually_correct,
        correctness_reasoning=correctness_reasoning,
        ...
    )
    sequence_number += 1
```

#### Question Streaming (Part 2)
```python
# AI_stream_followup_question
async for chunk_text in streaming_generator:
    full_question_text += chunk_text  # Accumulate

    yield StreamChunk(
        sequence_number=sequence_number,
        response=chunk_text,
        finish=False,
        response_type="followup_question",  # Distinguish from Part 1
        ...
    )
    sequence_number += 1
```

#### Request Complete
```python
# Combine parts
full_response = full_response_text + " " + full_question_text

# Calculate duration
duration = time.time() - start_time

# Final chunk
yield StreamChunk(
    sequence_number=sequence_number,
    response=full_response,  # Complete text
    finish=True,  # Done
    duration=duration,
    token_usage=None,  # Not available in streaming
    ...
)

# State destroyed (generator completes)
```

#### Stream Abort
```python
# Frontend calls AbortController.abort()
# Backend receives GeneratorExit exception
except GeneratorExit:
    logger.info(f"Stream aborted | request_id={request_id}")
    # Cleanup (if stream is not None: del stream)
    # State destroyed, partial response visible on frontend
```

---

## State Relationships

### Frontend ↔ Session
```
FE.sessionId → BE.sessions[session_id] → Session State
FE.currentObject → Session.object_name
FE.correctAnswerCount → Session.correct_answer_count
FE.systemManagedMode → Session.system_managed_focus
FE.currentFocusMode → Session.current_focus_mode (if manual)
```

### Session ↔ Streaming
```
Session.conversation_history → Streaming.prepare_messages → AI calls
Session.object_name → Streaming.response generation context
Session.current_focus_mode → Streaming.focus_prompt
Streaming.full_response → Session.conversation_history.append
Streaming.is_factually_correct → Session.correct_answer_count increment
```

### Streaming ↔ Frontend
```
Streaming.StreamChunk → SSE event → FE.buffer → FE.parse_sse_event
StreamChunk.session_id → FE.sessionId
StreamChunk.new_object_name → FE.currentObject
StreamChunk.detected_object_name → FE.detectedObject
StreamChunk.correct_answer_count → FE.correctAnswerCount
StreamChunk.response → FE.currentMessageDiv.textContent
```

---

## State Mutation Summary

| State Model | Mutable By | Mutation Frequency | Persistence |
|-------------|------------|-------------------|-------------|
| Frontend UI | User actions, SSE chunks | High (every interaction, chunk) | localStorage only (tone, focus) |
| Session | API endpoints, streaming generators | Medium (per message, topic switch) | In-memory only |
| Streaming | Validation, AI generators | Very High (per chunk) | None (transient) |

---

## Notes

- **Frontend State**: Optimistic updates (assume success), errors shown reactively
- **Session State**: Single source of truth for conversation, unbounded history growth
- **Streaming State**: Ephemeral, destroyed after each request, no persistence
- **Synchronization**: Session state changes reflected in StreamChunk → frontend updates reactively
- **Race Conditions**: Frontend abort can race with backend streaming (handled gracefully)
- **Memory Leaks**: Long conversations accumulate unbounded history (no pagination/truncation)
