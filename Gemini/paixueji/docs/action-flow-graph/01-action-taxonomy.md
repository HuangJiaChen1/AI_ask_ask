# Action Type Taxonomy

## Overview
This document enumerates ALL actions in the Paixueji system, categorized by actor/layer. Each action includes:
- **Description**: What the action does
- **Source**: File and approximate line numbers
- **Type**: USER/FE/API/BE/VALIDATE/AI

**Total Actions**: 54

---

## USER_ Actions (7 total)
**Actor**: End user (parent/child)
**Layer**: Browser UI interaction

### USER_fill_form
- **Description**: User enters age, object name, categories, tone, and focus mode in initialization form
- **Source**: static/index.html:18-67 (form fields)
- **Trigger**: Page load, user typing
- **State Impact**: Populates FE form state

### USER_click_start
- **Description**: User clicks "Start Learning!" button to initiate conversation
- **Source**: static/index.html:69 (button), static/app.js:120-295 (handler: startConversation)
- **Trigger**: Button click
- **State Impact**: Creates session, begins SSE stream

### USER_click_classify
- **Description**: User clicks "Classify" button to auto-populate category dropdowns
- **Source**: static/index.html:49 (button), static/app.js:714-782 (handler: classifyObject)
- **Trigger**: Button click
- **State Impact**: Calls classification API, updates dropdowns

### USER_send_message
- **Description**: User types answer and presses Enter or clicks Send button
- **Source**: static/index.html:124-129 (input + button), static/app.js:329-453 (handler: sendMessage)
- **Trigger**: Enter key or Send button click
- **State Impact**: Sends message to backend, initiates SSE stream

### USER_click_stop
- **Description**: User clicks "Stop" button to abort ongoing SSE stream
- **Source**: static/index.html:130 (button), static/app.js:300-314 (handler: stopStreaming)
- **Trigger**: Button click while streaming
- **State Impact**: Aborts stream, re-enables input

### USER_force_switch
- **Description**: User clicks "Switch to X" button in manual override panel to force topic change
- **Source**: static/index.html:89 (button), static/app.js:968-1015 (handler: forceSwitch)
- **Trigger**: Button click when AI detected different object
- **State Impact**: Forces object switch on backend

### USER_change_focus
- **Description**: User changes focus mode dropdown during conversation
- **Source**: static/index.html:114-120 (dropdown), static/app.js:151-156 (onChange handler)
- **Trigger**: Dropdown selection change
- **State Impact**: Updates active focus mode, disables system_managed option

---

## FE_ Actions (12 total)
**Actor**: Frontend JavaScript (app.js)
**Layer**: Browser state management and UI rendering

### FE_validate_input
- **Description**: Validates form fields (age, object name) before submission
- **Source**: static/app.js:145-148 (startConversation validation), 719-723 (classifyObject validation), 333-337 (sendMessage validation)
- **Trigger**: Before API call
- **State Impact**: Prevents invalid requests

### FE_create_session_id
- **Description**: Extracts session_id from first StreamChunk and stores in global state
- **Source**: static/app.js:499-502 (handleStreamChunk)
- **Trigger**: First SSE chunk received
- **State Impact**: Sets sessionId global variable

### FE_open_sse_connection
- **Description**: Initiates fetch() with streaming response for SSE
- **Source**: static/app.js:202-240 (startConversation), 369-438 (sendMessage)
- **Trigger**: POST /api/start or /api/continue
- **State Impact**: Creates currentStreamController (AbortController)

### FE_create_message_bubble
- **Description**: Creates new message div element for assistant response
- **Source**: static/app.js:516-521 (handleStreamChunk)
- **Trigger**: First chunk of new message (currentMessageDiv == null)
- **State Impact**: Sets currentMessageDiv, appends to messagesContainer

### FE_buffer_sse_data
- **Description**: Accumulates SSE chunks in buffer until complete event ('\n\n')
- **Source**: static/app.js:243-247 (SSE parsing loop)
- **Trigger**: Each chunk read from response.body.getReader()
- **State Impact**: Updates buffer string

### FE_parse_sse_event
- **Description**: Parses buffered SSE data into event type and JSON data
- **Source**: static/app.js:246-263 (parseSSE logic)
- **Trigger**: Buffer contains '\n\n' delimiter
- **State Impact**: Extracts event type (chunk/complete/error/interrupted) and data object

### FE_render_text_chunk
- **Description**: Appends text chunk to current message bubble
- **Source**: static/app.js:524-526 (handleStreamChunk: displayChunk)
- **Trigger**: chunk.finish == false
- **State Impact**: Updates message bubble textContent

### FE_update_progress_bar
- **Description**: Updates progress indicator with correct answer count
- **Source**: static/app.js:506-509 (handleStreamChunk)
- **Trigger**: chunk.correct_answer_count received
- **State Impact**: Updates correctAnswerCount, updates progress display

### FE_show_switch_panel
- **Description**: Displays manual topic switch panel with detected object
- **Source**: static/app.js:580-601 (handleStreamChunk)
- **Trigger**: chunk.detected_object_name present
- **State Impact**: Sets detectedObject, shows switchPanel

### FE_show_selection_panel
- **Description**: Shows suggested objects in AI response (natural language selection, not UI buttons)
- **Source**: static/app.js:574-576 (triggers based on chunk.suggested_objects)
- **Trigger**: chunk.suggested_objects present (explicit switch without named object)
- **State Impact**: User reads suggestions in AI response text, types their choice as next message
- **Note**: Disabled UI panel; using conversational selection instead

### FE_abort_stream
- **Description**: Calls AbortController.abort() to cancel ongoing SSE stream
- **Source**: static/app.js:305-308 (stopStreaming), 337-340 (sendMessage: abort prior stream)
- **Trigger**: User clicks Stop OR sends new message while streaming
- **State Impact**: Sets currentStreamController = null, isStreaming = false

### FE_update_debug_panel
- **Description**: Updates debug panel with current session state
- **Source**: static/app.js:284-286 (startConversation), 560-577 (handleStreamChunk)
- **Trigger**: Session start, object switch, state change
- **State Impact**: Updates debug panel DOM elements

---

## API_ Actions (6 total)
**Actor**: HTTP endpoints (Flask routes)
**Layer**: API boundary between frontend and backend

### API_POST_/start
- **Description**: Initializes new conversation session, returns SSE stream with introduction question
- **Source**: app.py:104-295
- **HTTP**: POST /api/start
- **Payload**: {age, object_name, level1_category, level2_category, level3_category, tone, focus_mode, system_managed}
- **Response**: SSE stream (event: chunk, data: StreamChunk JSON)

### API_POST_/continue
- **Description**: Processes child's answer, returns SSE stream with response + next question
- **Source**: app.py:300-453
- **HTTP**: POST /api/continue
- **Payload**: {session_id, child_input, focus_mode}
- **Response**: SSE stream (event: chunk, data: StreamChunk JSON)

### API_POST_/classify
- **Description**: Classifies object into level2 category using AI
- **Source**: app.py:473-515
- **HTTP**: POST /api/classify
- **Payload**: {object_name}
- **Response**: JSON {level1_category, level2_category}

### API_POST_/force-switch
- **Description**: Manual topic switch override when user disagrees with AI decision
- **Source**: app.py:520-577
- **HTTP**: POST /api/force-switch
- **Payload**: {session_id, new_object}
- **Response**: JSON {success, message, current_object, categories}

### API_GET_/debug/flow-tree
- **Description**: Retrieves conversation flow tree for debugging (JSON or Mermaid format)
- **Source**: app.py:444-512
- **HTTP**: GET /api/debug/flow-tree/{session_id}?format=mermaid
- **Response**: JSON {flow_tree} or {mermaid_diagram}

### API_GET_/debug/logs
- **Description**: Retrieves debug logs for a session
- **Source**: app.py:647-672
- **HTTP**: GET /api/debug/logs/{session_id}
- **Response**: JSON {logs: [...]}

---

## BE_ Actions (14 total)
**Actor**: Backend orchestration layer (app.py, paixueji_stream.py)
**Layer**: Session management, SSE streaming, message formatting

### BE_validate_request
- **Description**: Validates required fields in HTTP request body
- **Source**: app.py:109-115 (start), 305-311 (continue), 478-480 (classify)
- **Trigger**: HTTP request received
- **State Impact**: Returns 400 if validation fails

### BE_lookup_session
- **Description**: Retrieves PaixuejiAssistant instance from sessions dict by session_id
- **Source**: app.py:312-318 (continue), 525-531 (force-switch), 587-593 (select-object)
- **Trigger**: API endpoint with session_id
- **State Impact**: Returns 404 if session not found

### BE_create_event_loop
- **Description**: Creates new asyncio event loop for SSE streaming
- **Source**: app.py:193-196 (get_event_loop function)
- **Trigger**: Before streaming generator invocation
- **State Impact**: Creates isolated event loop per request

### BE_call_paixueji_stream
- **Description**: Main orchestrator async generator for streaming conversation flow
- **Source**: paixueji_stream.py:2010-2304 (call_paixueji_stream)
- **Trigger**: API_POST_/start or API_POST_/continue
- **State Impact**: Yields StreamChunk objects, updates conversation_history

### BE_route_to_introduction
- **Description**: Routes to introduction question flow for first interaction
- **Source**: paixueji_stream.py:2063-2088
- **Trigger**: correct_answer_count == 0 AND no assistant messages yet
- **State Impact**: Calls ask_introduction_question_stream

### BE_route_to_dual_parallel
- **Description**: Routes to dual-parallel flow (validation → response + question)
- **Source**: paixueji_stream.py:2148-2304
- **Trigger**: Follow-up interaction (has_asked_questions == True)
- **State Impact**: Calls VALIDATE_unified_ai, then response/question generators

### BE_prepare_messages
- **Description**: Cleans conversation history and appends age/category prompts to system message
- **Source**: paixueji_stream.py:64-93 (prepare_messages_for_streaming)
- **Trigger**: Before AI streaming call
- **State Impact**: Returns cleaned message list (shallow copy)

### BE_convert_to_gemini
- **Description**: Converts OpenAI-style messages to Gemini format
- **Source**: paixueji_stream.py:95-132 (convert_to_gemini_format)
- **Trigger**: Before Gemini API call
- **State Impact**: Returns {system_instruction, contents} dict

### BE_emit_sse_chunk
- **Description**: Formats StreamChunk as SSE event and yields to response stream
- **Source**: app.py:200-225 (generate function wrapper)
- **Trigger**: Each chunk from async generator
- **State Impact**: Yields 'event: chunk\ndata: {JSON}\n\n'

### BE_emit_sse_complete
- **Description**: Sends SSE completion event
- **Source**: app.py:226-227 (generate function: on success)
- **Trigger**: Async generator completes without error
- **State Impact**: Yields 'event: complete\ndata: {"success": true}\n\n'

### BE_emit_sse_error
- **Description**: Sends SSE error event
- **Source**: app.py:244-247 (generate function: exception handler)
- **Trigger**: Exception during streaming
- **State Impact**: Yields 'event: error\ndata: {"message": "..."}\n\n'

### BE_update_conversation_history
- **Description**: Appends assistant message (response + question combined) to conversation_history
- **Source**: paixueji_stream.py:2266-2270, 2291-2295 (append full_response)
- **Trigger**: After question generation complete (or explicit switch)
- **State Impact**: Updates assistant.conversation_history

### BE_increment_correct_count
- **Description**: Increments correct_answer_count in session state
- **Source**: app.py:348-363 (continue endpoint), paixueji_assistant.py:331-333
- **Trigger**: chunk.finish == True AND chunk.is_factually_correct == True
- **State Impact**: assistant.correct_answer_count += 1

### BE_update_flow_tree
- **Description**: Adds node to conversation flow tree for debugging
- **Source**: app.py:364-424 (continue endpoint: add_node call)
- **Trigger**: After each turn (if flow_tree enabled)
- **State Impact**: Updates assistant.flow_tree with turn data

---

## VALIDATE_ Actions (4 total)
**Actor**: Validation and routing logic (paixueji_stream.py)
**Layer**: AI-powered decision making

### VALIDATE_unified_ai
- **Description**: 3-dimensional AI validation: engagement, correctness, topic switching
- **Source**: paixueji_stream.py:911-1160 (decide_topic_switch_with_validation)
- **Trigger**: Every follow-up message (API_POST_/continue)
- **Output**: {decision: SWITCH/CONTINUE, new_object, switching_reasoning, is_engaged, is_factually_correct, correctness_reasoning}
- **Fallback**: On error → {engaged=True, correct=True, CONTINUE}

### VALIDATE_route_decision
- **Description**: Routes to 1 of 5 response generators based on validation results
- **Source**: paixueji_stream.py:2197-2226
- **Trigger**: After VALIDATE_unified_ai completes
- **Decision Logic**:
  - decision == SWITCH AND new_object == null → explicit_switch
  - is_engaged == False → explanation
  - is_factually_correct AND decision == SWITCH → topic_switch
  - is_factually_correct → feedback
  - else → gentle_correction
- **Output**: response_type string

### VALIDATE_system_focus
- **Description**: Determines next focus mode in system-managed mode (depth → width → object_selection)
- **Source**: paixueji_stream.py:1696-1836 (decide_next_focus_mode)
- **Trigger**: Before response generation, if system_managed_focus == True
- **Decision Logic**:
  - If depth_questions_count < depth_target → continue depth
  - If depth complete → switch to random width_* category
  - If width_wrong_count >= 3 → natural_topic_completion
  - Else → continue current width_* category
- **State Impact**: Updates current_focus_mode, depth_questions_count, width_wrong_count

### VALIDATE_width_wrong
- **Description**: Tracks wrong answer count in width phase, handles threshold
- **Source**: paixueji_stream.py:1765-1836 (handle_width_wrong_answer logic within decide_next_focus_mode)
- **Trigger**: After validation, if current_focus_mode startswith 'width_'
- **Decision Logic**:
  - If not is_engaged OR not is_factually_correct → width_wrong_count += 1
  - If is_factually_correct → width_wrong_count = 0
  - If width_wrong_count >= 3 → trigger natural completion
- **State Impact**: Updates width_wrong_count, possibly triggers object_selection mode

---

## AI_ Actions (11 total)
**Actor**: Gemini AI model (via API)
**Layer**: Content generation (streaming and synchronous)

### AI_classify_object
- **Description**: Synchronous Gemini call to classify object into level2 category
- **Source**: paixueji_assistant.py:237-314 (classify_object_sync)
- **API Config**: temperature=0.1, max_output_tokens=50
- **Trigger**: API_POST_/classify, topic switch, object selection
- **Timeout**: 1 second (background thread with Future)
- **Fallback**: On timeout/error → categories remain null

### AI_validate_answer
- **Description**: Gemini call in JSON mode for 3-part validation
- **Source**: paixueji_stream.py:911-1160 (decide_topic_switch_with_validation)
- **API Config**: temperature=0.1, response_mime_type="application/json"
- **Trigger**: Every follow-up message
- **Output**: JSON with is_engaged, is_factually_correct, decision, new_object, reasoning
- **Fallback**: On error → safe defaults

### AI_generate_suggestions
- **Description**: Gemini call in JSON mode to generate 3-4 suggested objects
- **Source**: paixueji_stream.py:1839-1885 (generate_object_suggestions)
- **API Config**: temperature=0.7 (higher for variety), response_mime_type="application/json"
- **Trigger**: Explicit switch (no object named)
- **Output**: JSON array of object names
- **Fallback**: On error → ["cat", "tree", "ball"]

### AI_stream_introduction
- **Description**: Streams first question about object
- **Source**: paixueji_stream.py:134-196 (ask_introduction_question_stream)
- **API Config**: temperature=0.3, max_output_tokens=200
- **Trigger**: First interaction (correct_count==0, no questions yet)
- **Yields**: Text chunks
- **Fallback**: "Tell me about {object}!"

### AI_stream_feedback
- **Description**: Streams celebratory feedback for correct answer (Part 1)
- **Source**: paixueji_stream.py:376-434 (generate_feedback_response_stream)
- **API Config**: temperature=0.3, max_output_tokens=100
- **Trigger**: is_factually_correct == True, decision == CONTINUE
- **Yields**: Text chunks (celebration/praise)
- **Fallback**: "Great job!"

### AI_stream_explanation
- **Description**: Streams gentle explanation for stuck/not engaged answers (Part 1)
- **Source**: paixueji_stream.py:199-261 (generate_explanation_response_stream)
- **API Config**: temperature=0.3, max_output_tokens=150
- **Trigger**: is_engaged == False
- **Yields**: Text chunks (explanation + encouragement)
- **Fallback**: "Let me help you with that!"

### AI_stream_correction
- **Description**: Streams gentle correction for wrong answer (Part 1)
- **Source**: paixueji_stream.py:264-334 (generate_correction_response_stream)
- **API Config**: temperature=0.3, max_output_tokens=150
- **Trigger**: is_engaged == True, is_factually_correct == False
- **Yields**: Text chunks (correction with accurate info)
- **Fallback**: "Actually, let me tell you more!"

### AI_stream_topic_switch
- **Description**: Streams celebration + introduction of new object (Part 1)
- **Source**: paixueji_stream.py:437-503 (generate_topic_switch_response_stream)
- **API Config**: temperature=0.3, max_output_tokens=150
- **Trigger**: is_factually_correct == True, decision == SWITCH, new_object present
- **Yields**: Text chunks
- **Fallback**: "Great! Let's talk about {new_object}!"

### AI_stream_explicit_switch
- **Description**: Streams acknowledgment + suggested objects for selection (Part 1, no Part 2)
- **Source**: paixueji_stream.py:713-779 (generate_explicit_switch_response_stream)
- **API Config**: temperature=0.3, max_output_tokens=150
- **Trigger**: decision == SWITCH, new_object == null
- **Yields**: Text chunks (includes suggested_objects in prompt)
- **Fallback**: "Sure! What would you like to learn about?"

### AI_stream_natural_completion
- **Description**: Streams congratulations + asks what to explore next (replaces standard question)
- **Source**: paixueji_stream.py:782-854 (generate_natural_topic_completion_stream)
- **API Config**: temperature=0.3, max_output_tokens=150
- **Trigger**: System-managed mode, width_wrong_count >= 3 OR depth complete + all width tried
- **Yields**: Text chunks
- **Fallback**: "Great work! What else would you like to learn about?"

### AI_stream_followup_question
- **Description**: Streams next question based on focus mode (Part 2)
- **Source**: paixueji_stream.py:506-710 (generate_followup_question_stream)
- **API Config**: temperature=0.3, max_output_tokens=200
- **Trigger**: After all response types EXCEPT explicit_switch and natural_completion
- **Yields**: Text chunks (question based on depth/width_*/category strategy)
- **Fallback**: "What else can you tell me about {object}?"

---

## Summary Statistics

| Category | Count | Primary Actors |
|----------|-------|----------------|
| USER_    | 7     | Parent/child browser interaction |
| FE_      | 12    | JavaScript (app.js) state + UI |
| API_     | 6     | Flask endpoints (app.py) |
| BE_      | 14    | Backend orchestration (app.py, paixueji_stream.py) |
| VALIDATE_| 4     | AI-powered validation + routing |
| AI_      | 11    | Gemini model content generation |
| **TOTAL**| **54**| |

---

## Action Flow Paths

### Happy Path (Correct Answer, Continue Topic)
1. USER_send_message
2. API_POST_/continue
3. BE_lookup_session
4. BE_call_paixueji_stream
5. VALIDATE_unified_ai → {engaged=True, correct=True, CONTINUE}
6. VALIDATE_route_decision → feedback
7. AI_stream_feedback → BE_emit_sse_chunk → FE_parse_sse_event → FE_render_text_chunk
8. AI_stream_followup_question → BE_emit_sse_chunk → FE_render_text_chunk
9. BE_update_conversation_history
10. BE_increment_correct_count
11. BE_emit_sse_complete

### Topic Switch Path (Correct Answer, Switch Detected)
1. USER_send_message ("I want to learn about dogs" after talking about cats)
2. API_POST_/continue
3. BE_lookup_session
4. BE_call_paixueji_stream
5. VALIDATE_unified_ai → {engaged=True, correct=True, SWITCH, new_object="dogs"}
6. VALIDATE_route_decision → topic_switch
7. AI_classify_object (background, 1s timeout)
8. AI_stream_topic_switch → BE_emit_sse_chunk → FE_render_text_chunk
9. FE_update_debug_panel (new_object_name in chunk)
10. AI_stream_followup_question (about dogs)
11. BE_update_conversation_history
12. BE_increment_correct_count
13. BE_emit_sse_complete

### Error Path (Stream Abort)
1. USER_send_message
2. API_POST_/continue
3. BE_call_paixueji_stream
4. AI_stream_feedback (starts yielding chunks)
5. FE_render_text_chunk (partial response visible)
6. USER_click_stop
7. FE_abort_stream → currentStreamController.abort()
8. BE sees GeneratorExit exception
9. BE logs disconnect, cleans up
10. FE re-enables send button

---

## Notes

- **Naming Convention**: ACTION_verb_noun (e.g., USER_click_start, AI_stream_feedback)
- **Prefixes**: Indicate layer ownership for debugging
- **Fallbacks**: Every AI_ action has explicit fallback behavior
- **Timeouts**: Classification has 1s timeout, streaming has no timeout (manual abort only)
- **State Mutations**: Only BE_, VALIDATE_, and AI_classify_object mutate session state
- **Idempotency**: FE_ actions are generally idempotent (can retry safely)
