# Completeness Checklist - 51 Production-Critical Scenarios

## Overview
This checklist ensures the action flow graph covers ALL edge cases for production incident debugging. Each scenario maps to specific locations in the Mermaid diagram and code.

**Purpose**: During production incidents, use this checklist to:
1. Identify which scenario matches the observed behavior
2. Locate the relevant diagram section
3. Find the exact code location
4. Understand expected vs. actual behavior

---

## Validation Edge Cases (9 scenarios)

### 1. Empty User Input
- **Scenario**: User submits empty message
- **Expected**: FE validation prevents submission
- **Diagram**: Phase 1 → A2 (Validate Input) → A14 (FE_show_error)
- **Code**: static/app.js:333-337 (sendMessage validation)
- **Outcome**: Error message "Please enter a message"

### 2. "I don't know" Detection
- **Scenario**: Child types "idk", "dunno", "I don't know", "not sure", "help me"
- **Expected**: is_engaged = False
- **Diagram**: Phase 4 → D7 (VALIDATE_unified_ai) → D13 → E2_Explanation path
- **Code**: paixueji_stream.py:911-1160 (decide_topic_switch_with_validation)
- **Outcome**: Explanation response, no increment to correct_count

### 3. Wrong Answer but Engaged
- **Scenario**: Child provides substantive but incorrect answer
- **Expected**: is_engaged = True, is_factually_correct = False
- **Diagram**: Phase 4 → D13 → E5_Correction path
- **Code**: paixueji_stream.py:2222-2226
- **Outcome**: Gentle correction, followup question, no increment

### 4. Correct Answer, No Switch
- **Scenario**: Child answers correctly, no topic change
- **Expected**: is_factually_correct = True, decision = CONTINUE
- **Diagram**: Phase 4 → D13 → E4_Feedback path
- **Code**: paixueji_stream.py:2213-2217
- **Outcome**: Celebration, correct_count += 1, followup question

### 5. Correct Answer with Topic Switch
- **Scenario**: Child names new object in answer, AI decides to switch
- **Expected**: is_factually_correct = True, decision = SWITCH, new_object = "X"
- **Diagram**: Phase 4 → D13 → E3_TopicSwitch path
- **Code**: paixueji_stream.py:2205-2212
- **Outcome**: Celebration, object switch, categories updated, correct_count += 1

### 6. Explicit Switch Request without Object
- **Scenario**: Child says "let's talk about something else" without naming object
- **Expected**: decision = SWITCH, new_object = null
- **Diagram**: Phase 4 → D13 → E1_ExplicitSwitch path
- **Code**: paixueji_stream.py:2197-2204
- **Outcome**: AI generates 3-4 suggested objects in response text, user types their choice as next message (natural language selection)

### 7. Child Mentions Object in Answer (Direct Response)
- **Scenario**: Q: "What do monkeys eat?" A: "Bananas" (not topic switch)
- **Expected**: decision = CONTINUE (answer to question, not new topic)
- **Diagram**: Phase 4 → D7 validation detects direct answer
- **Code**: paixueji_stream.py:1003-1018 (validation prompt: "Is this just the answer?")
- **Outcome**: Continue on current object, don't switch to "bananas"

### 8. Validation API Call Timeout
- **Scenario**: Gemini API timeout during decide_topic_switch_with_validation
- **Expected**: Exception caught, safe defaults applied
- **Diagram**: Phase 4 → D7 → D8 (Validation Success?) → D9 (Error) → safe defaults
- **Code**: paixueji_stream.py:1149-1160 (exception handler)
- **Outcome**: {engaged=True, correct=True, CONTINUE} → feedback path

### 9. Validation JSON Parse Error
- **Scenario**: Gemini returns malformed JSON
- **Expected**: Exception caught, safe defaults applied
- **Diagram**: Phase 4 → D8 → D9
- **Code**: paixueji_stream.py:1149-1160
- **Outcome**: Same as #8, conversation continues safely

---

## Streaming Edge Cases (7 scenarios)

### 10. SSE Connection Abort Mid-Stream
- **Scenario**: User clicks "Stop" while response streaming
- **Expected**: FE aborts, BE receives GeneratorExit
- **Diagram**: Phase 9 → I1 (Stream Abort) → I2 → I3 → I4 → I5
- **Code**: static/app.js:300-314 (stopStreaming), paixueji_stream.py:2299-2303 (GeneratorExit)
- **Outcome**: Partial response visible, stream cleaned up, send button re-enabled

### 11. Gemini API Timeout (Response Generation)
- **Scenario**: AI_stream_feedback/explanation/correction times out
- **Expected**: Exception caught, fallback response used
- **Diagram**: Phase 5 (any path) → Gemini error → fallback
- **Code**: paixueji_stream.py:206-210, 273-277, 385-389, etc. (exception handlers)
- **Outcome**: Fallback: "I see!" or "Great job!" or similar

### 12. Gemini API Timeout (Question Generation)
- **Scenario**: AI_stream_followup_question times out
- **Expected**: Exception caught, fallback question used
- **Diagram**: Phase 6 → F_QuestionSuccess → F_Fallback
- **Code**: paixueji_stream.py:654-658 (exception handler)
- **Outcome**: Fallback: "What else can you tell me about {object}?"

### 13. Empty Response from AI
- **Scenario**: Gemini returns empty string (rare)
- **Expected**: Warning logged, continue with accumulated response
- **Diagram**: Any AI_stream_* action
- **Code**: paixueji_stream.py:183-188 (check chunk_text)
- **Outcome**: Use fallback if full_response still empty

### 14. Final Chunk Shorter than Streamed Text
- **Scenario**: StreamChunk.finish=true but response < accumulated text
- **Expected**: Keep streamed version (longer)
- **Diagram**: Phase 7 → G12 (Finalize message) → compare lengths
- **Code**: static/app.js:527-556 (handleStreamChunk finish logic)
- **Outcome**: Log warning, display longer version

### 15. Concurrent Requests (New Message While Streaming)
- **Scenario**: User sends new message before prior stream completes
- **Expected**: Abort old stream, start new stream
- **Diagram**: ConversationLoop → D0 → D0A (Already streaming?) → D0B (Abort) → D1
- **Code**: static/app.js:337-340 (sendMessage abort check)
- **Outcome**: Old stream aborted, new stream begins

### 16. SSE Buffer Incomplete Event
- **Scenario**: Chunk received without '\n\n' delimiter
- **Expected**: Keep in buffer until complete
- **Diagram**: Phase 7 → G2 (FE_buffer_sse_data) → G3 checks for '\n\n'
- **Code**: static/app.js:243-247 (buffer accumulation)
- **Outcome**: Wait for more data, parse when complete

---

## Classification Edge Cases (3 scenarios)

### 17. Object Not in Any Category
- **Scenario**: User enters "spaceship" (not in predefined categories)
- **Expected**: Classification returns level2 = "none"
- **Diagram**: Phase 1 → A5 → A6 → A8 (not found) → manual selection
- **Code**: paixueji_assistant.py:237-314 (classify_object_sync), returns null if not found
- **Outcome**: User manually selects "none of the above" or skips classification

### 18. Classification Timeout (1 second)
- **Scenario**: AI_classify_object exceeds 1s
- **Expected**: ThreadPoolExecutor timeout, continue anyway
- **Diagram**: Phase 1 → A5 → A6 (Timeout) → A8 → continue with null categories
- **Code**: app.py:532-541, 589-598, 165-170 (concurrent.futures timeout)
- **Outcome**: Warning logged, categories remain null, conversation continues

### 19. Classification API Error
- **Scenario**: Gemini API failure during classification
- **Expected**: Exception caught, continue with null categories
- **Diagram**: Phase 1 → A6 (Error) → A8
- **Code**: paixueji_assistant.py:307-314 (exception handler)
- **Outcome**: Categories not populated, user can select manually

---

## Session Edge Cases (3 scenarios)

### 20. Session Not Found (404)
- **Scenario**: API_POST_/continue with invalid/expired session_id
- **Expected**: HTTP 404 response
- **Diagram**: Phase 4 → D1 → D2 (Session Exists?) → D3 (404)
- **Code**: app.py:312-318 (lookup), 385-386 (404 handler on FE)
- **Outcome**: FE shows "Session not found. Please restart conversation."

### 21. Server Restart (All Sessions Cleared)
- **Scenario**: Server restarts, in-memory sessions lost
- **Expected**: All subsequent requests return 404
- **Diagram**: Phase 4 → D2 → D3
- **Code**: sessions = {} on restart
- **Outcome**: Users must restart conversations

### 22. Invalid Session ID Format
- **Scenario**: Malformed session_id in request
- **Expected**: Backend validation error OR 404 (not found)
- **Diagram**: Phase 4 → D2 → D3
- **Code**: app.py:312 (sessions.get returns None)
- **Outcome**: HTTP 404

---

## Object Switching Edge Cases (5 scenarios)

### 23. AI Detects Object but Decides CONTINUE
- **Scenario**: Validation detects object mention but decides it's the answer, not switch
- **Expected**: detected_object_name set, decision = CONTINUE
- **Diagram**: Phase 4 → D7 validation → detected but CONTINUE → Phase 7 → G15 (detected_object_name?) → G16 (FE_show_switch_panel)
- **Code**: paixueji_stream.py:1060-1075 (detected vs switching logic)
- **Outcome**: FE shows manual override panel, user can force switch

### 24. User Forces Switch to Detected Object
- **Scenario**: User clicks "Switch to X" in manual override panel
- **Expected**: POST /force-switch, object updated
- **Diagram**: ManualActions → J1 → J2 → J3 → J4
- **Code**: static/app.js:968-1015 (forceSwitch), app.py:520-577 (force-switch endpoint)
- **Outcome**: Object switched, system message shown, debug panel updated

### 25. User Dismisses Switch Panel
- **Scenario**: User clicks "Stay on current topic"
- **Expected**: Panel hidden, no action
- **Diagram**: ManualActions (implied: dismiss action)
- **Code**: static/app.js:1020-1024 (dismissSwitchPanel)
- **Outcome**: detectedObject cleared, panel hidden, continue on current object

### 26. Topic Switch Classification Timeout
- **Scenario**: Object switch triggers classification with 1s timeout
- **Expected**: Continue with null categories
- **Diagram**: Phase 5 → E3_Classify → E3_ClassifyResult (Timeout) → E3_Continue
- **Code**: app.py:537-541, 594-598 (ThreadPoolExecutor timeout)
- **Outcome**: Object switched, categories null, conversation continues

### 27. Invalid/Nonsense Object Name
- **Scenario**: Child names nonsense object "blorgflorp"
- **Expected**: Validation detects, likely decides CONTINUE
- **Diagram**: Phase 4 → D7 validation → check if real object
- **Code**: paixueji_stream.py:1089-1105 (object validation in prompt)
- **Outcome**: decision = CONTINUE, don't switch to nonsense

---

## System-Managed Focus Edge Cases (6 scenarios)

### 28. Depth Target Reached (4-5 Questions)
- **Scenario**: depth_questions_count >= depth_target
- **Expected**: Switch to random width_* category
- **Diagram**: Phase 8 → H3_Depth → H6 (depth >= target) → H7 (Switch to WIDTH)
- **Code**: paixueji_stream.py:1731-1746 (decide_next_focus_mode)
- **Outcome**: current_focus_mode = 'width_color' OR 'width_shape' OR 'width_category'

### 29. 3 Consecutive Wrong WIDTH Answers
- **Scenario**: width_wrong_count >= 3
- **Expected**: Trigger natural_topic_completion
- **Diagram**: Phase 8 → H9_Width → H13 (wrong_count >= 3) → H15 → H16 (object_selection)
- **Code**: paixueji_stream.py:1788-1795 (threshold check)
- **Outcome**: AI asks "What else would you like to learn about?"

### 30. Width Category Switch (Color → Shape → Category)
- **Scenario**: Width category exhausted, try next
- **Expected**: Switch to unused width_* category
- **Diagram**: Phase 8 → H9_Width → check width_categories_tried
- **Code**: paixueji_stream.py:1797-1827 (category rotation)
- **Outcome**: current_focus_mode updates, width_categories_tried appends

### 31. All Width Categories Tried
- **Scenario**: width_categories_tried = ['color', 'shape', 'category']
- **Expected**: Trigger natural_topic_completion
- **Diagram**: Phase 8 → H9_Width → all categories tried → natural completion
- **Code**: paixueji_stream.py:1815-1827 (check len(tried) == 3)
- **Outcome**: AI asks "What else would you like to learn about?" (natural language, user types choice)

### 32. User Switches to Manual Focus Mode Mid-Session
- **Scenario**: User changes dropdown from system_managed to manual
- **Expected**: system_managed option disabled, manual mode active
- **Diagram**: Phase 1 → A1 (USER_change_focus) → disable system_managed
- **Code**: static/app.js:151-156 (onChange handler)
- **Outcome**: No further automatic focus transitions

### 33. Correct WIDTH Answer (Reset Wrong Count)
- **Scenario**: is_factually_correct = True during width phase
- **Expected**: width_wrong_count = 0
- **Diagram**: Phase 8 → H9_Width → H10 (correct) → H11 (reset count)
- **Code**: paixueji_stream.py:1786 (reset on correct)
- **Outcome**: Counter reset, continue in width mode

---

## Progress Tracking Edge Cases (4 scenarios)

### 34. Correct Answer Increments Count
- **Scenario**: is_factually_correct = True AND chunk.finish = True
- **Expected**: correct_answer_count += 1
- **Diagram**: Phase 6 → F_IncrementCheck → F_Increment
- **Code**: app.py:348-363 (increment logic)
- **Outcome**: correct_answer_count updated in session and StreamChunk

### 35. Wrong Answer Does NOT Increment
- **Scenario**: is_factually_correct = False
- **Expected**: correct_answer_count unchanged
- **Diagram**: Phase 6 → F_IncrementCheck (No) → F_Complete
- **Code**: app.py:348-363 (conditional increment)
- **Outcome**: Count remains same

### 36. "I don't know" Does NOT Increment
- **Scenario**: is_engaged = False
- **Expected**: correct_answer_count unchanged, is_factually_correct = null
- **Diagram**: Phase 4 → E2_Explanation path, Phase 6 → F_IncrementCheck (No)
- **Code**: app.py:348-363 (check is_factually_correct)
- **Outcome**: No increment for stuck answers

### 37. Progress Bar Never Reaches Completion (Infinite Mode)
- **Scenario**: correct_answer_count can go beyond 4
- **Expected**: Progress bar shows count but never triggers completion
- **Diagram**: Phase 7 → G19 (FE_update_progress_bar)
- **Code**: static/app.js:506-509 (update display), no completion logic
- **Outcome**: Conversation continues infinitely

---

## Frontend State Edge Cases (3 scenarios)

### 38. Page Refresh (Lose Session State)
- **Scenario**: User refreshes browser
- **Expected**: Frontend state reset, session still exists on server but inaccessible
- **Diagram**: Phase 1 restart (no session_id)
- **Code**: static/app.js:15-28 (state initialization)
- **Outcome**: User must start new conversation

### 39. LocalStorage Persistence (Tone, Focus)
- **Scenario**: User closes/reopens browser
- **Expected**: Tone and focus preferences restored
- **Diagram**: Phase 1 → A1 (USER_fill_form) → load from localStorage
- **Code**: static/app.js:136 (tone), 910 (focus), 932 (onLoad)
- **Outcome**: Form pre-filled with saved preferences

### 40. Multiple Tabs (Independent Sessions)
- **Scenario**: User opens two tabs
- **Expected**: Each tab has own sessionId, independent conversations
- **Diagram**: Each tab follows full flow from Phase 1
- **Code**: sessionId = null per tab
- **Outcome**: Two separate sessions on server

---

## HTTP Error Paths (5 scenarios)

### 41. HTTP 400 (Missing Required Fields)
- **Scenario**: POST /api/start without object_name
- **Expected**: Backend validation fails
- **Diagram**: Phase 1 → A12 (Backend Validation) → A13 (400)
- **Code**: app.py:109-115 (validation)
- **Outcome**: HTTP 400 {"error": "object_name is required"}

### 42. HTTP 404 (Session Not Found)
- **Scenario**: POST /api/continue with expired session_id
- **Expected**: Session lookup fails
- **Diagram**: Phase 4 → D2 (Session Exists?) → D3 (404)
- **Code**: app.py:312-318
- **Outcome**: FE shows "Session not found. Please restart."

### 43. HTTP 500 (Server Error)
- **Scenario**: Unhandled exception in backend
- **Expected**: Flask returns 500
- **Diagram**: Phase 9 → I6 → I7 (500) → I10 → I11
- **Code**: app.py exception handlers
- **Outcome**: FE shows "Server error. Please try again."

### 44. Network Timeout (Fetch Timeout)
- **Scenario**: Slow network, fetch exceeds browser timeout
- **Expected**: Fetch promise rejects
- **Diagram**: Phase 9 → network error
- **Code**: static/app.js:385-446 (exception handlers)
- **Outcome**: FE shows error, user can retry

### 45. CORS Error (Unlikely in Same-Origin)
- **Scenario**: CORS policy violation (if deployed)
- **Expected**: Fetch blocked by browser
- **Diagram**: Phase 9 → CORS error
- **Code**: Fetch exception handling
- **Outcome**: FE shows network error

---

## Conversation History Edge Cases (3 scenarios)

### 46. Very Long Conversation (1000+ Messages)
- **Scenario**: User has extended conversation
- **Expected**: Unbounded growth, potential memory issues
- **Diagram**: Not explicitly shown (state mutation)
- **Code**: paixueji_assistant.py:conversation_history appends
- **Outcome**: Performance degradation possible, no truncation implemented

### 47. Message Cleanup for API (Remove Internal Fields)
- **Scenario**: Prepare messages for Gemini API
- **Expected**: Remove tracking fields
- **Diagram**: Phase 3 → C2 (BE_prepare_messages)
- **Code**: paixueji_stream.py:64-93 (clean_messages_for_api)
- **Outcome**: Only {role, content} sent to API

### 48. Shallow Copy for Performance
- **Scenario**: Avoid deep copy on long histories
- **Expected**: Shallow copy of message list
- **Diagram**: Phase 3 → C2
- **Code**: paixueji_stream.py:66 (messages.copy())
- **Outcome**: 10-100x faster than deep copy

---

## Flow Tree Debugging Edge Cases (3 scenarios)

### 49. Flow Tree Disabled (flow_tree=None)
- **Scenario**: Debugging disabled in config
- **Expected**: Skip flow tree tracking
- **Diagram**: Not in main flow (optional debugging)
- **Code**: app.py:364 (if assistant.flow_tree)
- **Outcome**: No performance impact, no tracking

### 50. Mermaid Diagram Generation
- **Scenario**: GET /api/debug/flow-tree/{session_id}?format=mermaid
- **Expected**: Generate Mermaid syntax from flow tree
- **Diagram**: API_GET_/debug/flow-tree
- **Code**: app.py:516-672 (generate_mermaid_diagram)
- **Outcome**: Returns Mermaid syntax for visualization

### 51. Download Debug Logs
- **Scenario**: GET /api/debug/logs/{session_id}
- **Expected**: Return session-specific logs
- **Diagram**: API_GET_/debug/logs
- **Code**: app.py:647-672
- **Outcome**: JSON array of log entries

---

## Usage During Production Incidents

### Step 1: Identify Symptom
Match observed behavior to scenario number above

### Step 2: Locate in Diagram
Use "Diagram" reference to find exact location in master-flow.mmd

### Step 3: Check Code
Use "Code" reference to examine implementation

### Step 4: Verify Expected Outcome
Compare actual behavior to "Outcome"

### Step 5: Debug
- Check logs for error messages
- Verify state values at decision points
- Trace SSE events in browser DevTools
- Examine StreamChunk metadata

---

## Priority Scenarios for Monitoring

**Critical (monitor in production)**:
- #8, #9: Validation failures (silent fallback to safe defaults)
- #10, #15: Stream aborts (user experience impact)
- #18, #26: Classification timeouts (degraded categorization)
- #20, #21: Session loss (requires restart)
- #46: Memory growth (unbounded history)

**High (alert on occurrence)**:
- #11, #12: AI timeouts (fallback responses)
- #13: Empty AI responses (quality issue)
- #43: HTTP 500 errors (backend failures)
- #44: Network timeouts (infrastructure issue)

**Medium (track metrics)**:
- #2: "I don't know" frequency (engagement metric)
- #3: Wrong answer rate (difficulty tuning)
- #5: Topic switch rate (interest tracking)
- #34-37: Correct answer progression (success metric)

---

## Notes

- **Missing Branch = Critical Error**: If production scenario doesn't match any of these 51, diagram is incomplete
- **Silent Failures**: Watch for scenarios with safe defaults (#8, #9) - they mask underlying issues
- **Performance**: Monitor #46 (unbounded history), #48 (shallow copy critical for performance)
- **User Experience**: Prioritize #10, #15 (stream aborts), #20-22 (session loss)
