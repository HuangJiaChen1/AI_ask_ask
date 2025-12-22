# Ask Ask Assistant - Detailed Pipeline Documentation

## Table of Contents
1. [High-Level Architecture](#high-level-architecture)
2. [Session Start Pipeline](#session-start-pipeline)
3. [Continue Conversation Pipeline](#continue-conversation-pipeline)
4. [Data Flow Diagrams](#data-flow-diagrams)
5. [Component Details](#component-details)
6. [Error Handling](#error-handling)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Browser)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  index.html  │  │   app.js     │  │     style.css        │  │
│  │  (UI Layer)  │  │ (SSE Client) │  │  (Presentation)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP/SSE
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND (Flask Server)                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                         app.py                           │   │
│  │  ┌────────────┐  ┌────────────┐  ┌──────────────────┐   │   │
│  │  │ /api/start │  │/api/continue│  │  /api/sessions   │   │   │
│  │  └────────────┘  └────────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │                                        │
│  ┌──────────────────────┴────────────────────────────────────┐  │
│  │             ask_ask_assistant.py                          │  │
│  │  (Session Manager, Config, Client Holder)                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                        │
│  ┌──────────────────────┴────────────────────────────────────┐  │
│  │             ask_ask_stream.py                             │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  call_ask_ask_stream() [Main Orchestrator]          │  │  │
│  │  │    ├─> answer_question_stream()                     │  │  │
│  │  │    └─> suggest_topics_stream()                      │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         │                                        │
│  ┌──────────────────────┴────────────────────────────────────┐  │
│  │                   schema.py                               │  │
│  │  (StreamChunk, CallAskAskRequest, TokenUsage)             │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │ Gemini SDK
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Google Gemini API (Vertex AI)                   │
│                    Model: gemini-2.5-flash                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Session Start Pipeline

### Step-by-Step Flow

```
USER ACTION: Clicks "Start Conversation" Button
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: Frontend Initiation (app.js:63-153)                     │
├─────────────────────────────────────────────────────────────────┤
│ 1.1 User selects age (optional: 3-8) or leaves blank            │
│ 1.2 app.js:startConversation() called                           │
│ 1.3 Clear previous messages, disable UI controls                │
│ 1.4 POST request to /api/start with:                            │
│     {                                                            │
│       "age": 6  // or null                                      │
│     }                                                            │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: Backend Receives Request (app.py:57-162)                │
├─────────────────────────────────────────────────────────────────┤
│ 2.1 Flask endpoint /api/start receives POST                     │
│ 2.2 Validate age (3-8 or None)                                  │
│ 2.3 Generate session_id = uuid.uuid4()                          │
│ 2.4 Create AskAskAssistant instance                             │
│     - Loads config.json                                         │
│     - Initializes Gemini client (Vertex AI)                     │
│     - Loads age_prompts.json                                    │
│     - Loads prompts from ask_ask_prompts.py                     │
│ 2.5 Store assistant in sessions[session_id]                     │
│ 2.6 Store age in assistant.age                                  │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: Build System Prompt (app.py:100-112)                    │
├─────────────────────────────────────────────────────────────────┤
│ 3.1 Get base system prompt from ask_ask_prompts.py              │
│     "You are an enthusiastic learning companion..."             │
│                                                                  │
│ 3.2 If age provided:                                            │
│     - Get age-specific prompt from age_prompts.json             │
│     - Append to system prompt                                   │
│                                                                  │
│ 3.3 Initialize conversation_history with system message:        │
│     [                                                            │
│       {                                                          │
│         "role": "system",                                       │
│         "content": "<base_prompt>\n\nAGE-SPECIFIC:\n<age_prompt>"│
│       }                                                          │
│     ]                                                            │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: Call Streaming Orchestrator (app.py:122-131)            │
├─────────────────────────────────────────────────────────────────┤
│ 4.1 Prepare introduction_content = prompts['introduction_prompt']│
│     "Greet the child warmly, say they can ask about anything..." │
│                                                                  │
│ 4.2 Call async call_ask_ask_stream() with:                      │
│     - age: int | None                                           │
│     - messages: conversation_history (copy)                     │
│     - content: introduction_content                             │
│     - status: "normal"                                          │
│     - session_id: uuid string                                   │
│     - config: assistant.config dict                             │
│     - client: Gemini client instance                            │
│     - age_prompt: age-specific guidance string                  │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 5: Streaming Orchestrator (ask_ask_stream.py:249-376)      │
├─────────────────────────────────────────────────────────────────┤
│ 5.1 Append user message to messages:                            │
│     messages.append({                                           │
│       "role": "user",                                           │
│       "content": introduction_content                           │
│     })                                                          │
│                                                                 │
│ 5.2 Check if child is stuck:                                    │
│     stuck = is_child_stuck(content)  # False for intro          │
│                                                                 │
│ 5.3 Prepare messages for streaming:                             │
│     - Deep copy messages                                        │
│     - Clean internal fields (keep only role/content)            │
│     - Append age_prompt to system message if provided           │
│                                                                 │
│ 5.4 Route to appropriate stream generator:                      │
│     IF stuck == True:                                           │
│       stream_generator = suggest_topics_stream()                │
│     ELSE:                                                       │
│       stream_generator = answer_question_stream()  ← INTRO PATH │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 6: Answer Question Stream (ask_ask_stream.py:96-164)       │
├─────────────────────────────────────────────────────────────────┤
│ 6.1 Build answer prompt:                                        │
│     prompts['answer_question_prompt'].format(                   │
│       child_question=introduction_content                       │
│     )                                                           │
│     "The child asked: <intro_prompt>\n\nIMPORTANT: Follow..."   │
│                                                                 │
│ 6.2 Append answer prompt to messages                            │
│                                                                 │
│ 6.3 Convert messages to Gemini format:                          │
│     OpenAI style: [{"role": "system"/"user"/"assistant", ...}]  │
│     ↓                                                           │
│     Gemini style:                                               │
│       system_instruction = "combined system messages"           │
│       contents = [                                              │
│         {"role": "user", "parts": [{"text": "..."}]},           │
│         {"role": "model", "parts": [{"text": "..."}]}           │
│       ]                                                         │
│                                                                 │
│ 6.4 Create GenerateContentConfig:                               │
│     - temperature: 0.3 (from config)                            │
│     - max_output_tokens: 2000                                   │
│     - system_instruction: combined system prompts               │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 7: Gemini Streaming API Call (ask_ask_stream.py:139-148)   │
├─────────────────────────────────────────────────────────────────┤
│ 7.1 Call Gemini streaming API:                                  │
│     stream = client.models.generate_content_stream(             │
│       model="gemini-2.5-flash",                                 │
│       contents=contents,                                        │
│       config=gen_config                                         │
│     )                                                            │
│                                                                  │
│ 7.2 FOR EACH chunk from Gemini:                                 │
│     IF chunk.text exists:                                       │
│       full_response += chunk.text                               │
│       YIELD (chunk.text, None, full_response)                   │
│       ↓ (goes back to orchestrator)                             │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 8: Orchestrator Processes Chunks (ask_ask_stream.py:341-359)│
├─────────────────────────────────────────────────────────────────┤
│ 8.1 FOR EACH (chunked_text, token_usage, full_text) from stream:│
│                                                                  │
│     IF chunked_text is not empty:                               │
│       sequence_number += 1                                      │
│       CREATE StreamChunk:                                       │
│         response = chunked_text  # e.g., "H", "i", "!", etc.    │
│         session_finished = False                                │
│         duration = 0.0  # Will be set in final chunk            │
│         token_usage = None  # Only in final chunk               │
│         finish = False                                          │
│         sequence_number = 1, 2, 3...                            │
│         timestamp = time.time()                                 │
│         session_id = session_id                                 │
│         is_stuck = False  # (stuck was False for intro)         │
│                                                                  │
│       YIELD StreamChunk  ↓ (goes to Flask)                      │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 9: Flask Wraps in SSE (app.py:132-142)                     │
├─────────────────────────────────────────────────────────────────┤
│ 9.1 Receive StreamChunk from orchestrator                       │
│                                                                  │
│ 9.2 Convert to dict: chunk.model_dump()                         │
│                                                                  │
│ 9.3 Wrap in SSE format:                                         │
│     event: chunk                                                │
│     data: {                                                     │
│       "response": "H",                                          │
│       "session_finished": false,                                │
│       "duration": 0.0,                                          │
│       "token_usage": null,                                      │
│       "finish": false,                                          │
│       "sequence_number": 1,                                     │
│       "timestamp": 1734567890.123,                              │
│       "session_id": "abc-123-def-456",                          │
│       "is_stuck": false                                         │
│     }                                                            │
│                                                                  │
│ 9.4 YIELD to HTTP response stream  ↓                            │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 10: Frontend Receives SSE (app.js:103-132)                 │
├─────────────────────────────────────────────────────────────────┤
│ 10.1 SSE stream reader receives chunk                           │
│                                                                  │
│ 10.2 Decode and buffer:                                         │
│      buffer += decoder.decode(value)                            │
│                                                                  │
│ 10.3 Split by '\n\n' to get complete events                     │
│                                                                  │
│ 10.4 Parse event type and data:                                 │
│      eventType = "chunk"                                        │
│      data = JSON.parse(dataMatch[1])                            │
│                                                                  │
│ 10.5 Call handleSSEEvent(eventType, data)  ↓                    │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 11: Handle Stream Chunk (app.js:292-335)                   │
├─────────────────────────────────────────────────────────────────┤
│ 11.1 IF first chunk with session_id:                            │
│      sessionId = chunk.session_id  // Store globally            │
│                                                                  │
│ 11.2 IF chunk.is_stuck == true:                                 │
│      console.log("Child appears stuck - suggesting topics")     │
│                                                                  │
│ 11.3 IF !chunk.finish && chunk.response:  ← TEXT CHUNKS         │
│      displayChunk(currentMessageDiv, chunk.response)            │
│      → Appends "H", then "i", then "!" to message bubble        │
│      → Auto-scrolls to bottom                                   │
│                                                                  │
│ 11.4 IF chunk.finish:  ← FINAL CHUNK                            │
│      - Set full response text (in case of missed chunks)        │
│      - Display duration: "Response time: 2.34s"                 │
│      - Log token usage (if available)                           │
│      - Check if session_finished                                │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 12: Final Chunk Processing (ask_ask_stream.py:366-376)     │
├─────────────────────────────────────────────────────────────────┤
│ 12.1 Calculate total duration = time.time() - start_time        │
│                                                                  │
│ 12.2 Create FINAL StreamChunk:                                  │
│      response = full_response  # Complete intro text            │
│      session_finished = False  # Never finishes in Ask Ask      │
│      duration = 2.345  # Actual elapsed time                    │
│      token_usage = None  # Gemini streaming doesn't provide     │
│      finish = True  ← MARKS END OF STREAM                       │
│      sequence_number = last_number + 1                          │
│      timestamp = time.time()                                    │
│      session_id = session_id                                    │
│      is_stuck = False                                           │
│                                                                  │
│ 12.3 YIELD final chunk  ↓                                        │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 13: Backend Updates History (app.py:136-140)               │
├─────────────────────────────────────────────────────────────────┤
│ 13.1 When chunk.finish == True:                                 │
│      assistant.conversation_history.append({                    │
│        "role": "assistant",                                     │
│        "content": chunk.response  # Full introduction           │
│      })                                                          │
│                                                                  │
│ 13.2 Send completion event:                                     │
│      event: complete                                            │
│      data: {"success": true}                                    │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 14: Frontend Cleanup (app.js:142-152)                      │
├─────────────────────────────────────────────────────────────────┤
│ 14.1 Re-enable controls (input field, send button)              │
│ 14.2 Hide age selector (session has started)                    │
│ 14.3 Focus on input field                                       │
│ 14.4 User can now type questions!                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Continue Conversation Pipeline

### Step-by-Step Flow

```
USER ACTION: Types question and clicks "Send" or presses Enter
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: Frontend Sends Message (app.js:158-253)                 │
├─────────────────────────────────────────────────────────────────┤
│ 1.1 Get text from input field                                   │
│ 1.2 Validate: text exists, sessionId exists, not already streaming│
│ 1.3 Add user message to UI (blue bubble)                        │
│ 1.4 Clear input field                                           │
│ 1.5 Disable controls                                            │
│ 1.6 POST to /api/continue with:                                 │
│     {                                                            │
│       "session_id": "abc-123-def-456",                          │
│       "child_input": "Why is the sky blue?"                     │
│     }                                                            │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: Backend Validates Session (app.py:165-205)              │
├─────────────────────────────────────────────────────────────────┤
│ 2.1 Parse JSON body                                             │
│ 2.2 Extract session_id and child_input                          │
│ 2.3 Validate required fields exist                              │
│ 2.4 Lookup assistant = sessions.get(session_id)                 │
│ 2.5 IF not found → 404 error "Session not found"                │
│ 2.6 Get age_prompt if assistant.age is set                      │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: Call Streaming (app.py:221-230)                         │
├─────────────────────────────────────────────────────────────────┤
│ 3.1 Call async call_ask_ask_stream() with:                      │
│     - age: assistant.age (from session)                         │
│     - messages: assistant.conversation_history.copy()           │
│     - content: child_input ("Why is the sky blue?")             │
│     - status: "normal"                                          │
│     - session_id: session_id                                    │
│     - config: assistant.config                                  │
│     - client: assistant.client                                  │
│     - age_prompt: age_prompt string                             │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: Stuck Detection (ask_ask_stream.py:213-248)             │
├─────────────────────────────────────────────────────────────────┤
│ 4.1 Append user message to messages:                            │
│     messages.append({                                           │
│       "role": "user",                                           │
│       "content": "Why is the sky blue?"                         │
│     })                                                           │
│                                                                  │
│ 4.2 Run stuck detection: is_child_stuck(content)                │
│     input_lower = content.lower().strip()                       │
│     = "why is the sky blue?"                                    │
│                                                                  │
│     Check if it's a question:                                   │
│       - Ends with '?' → YES                                     │
│       - Starts with 'why' → YES                                 │
│       → is_likely_question = True                               │
│                                                                  │
│     IF is_likely_question AND len > 5:                          │
│       RETURN False  ← NOT STUCK                                 │
│                                                                  │
│ 4.3 stuck = False                                               │
│ 4.4 Route to answer_question_stream()                           │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 5: Answer Question Stream (ask_ask_stream.py:96-164)       │
├─────────────────────────────────────────────────────────────────┤
│ 5.1 Get answer prompt template                                  │
│ 5.2 Format with child's question:                               │
│     "The child asked: Why is the sky blue?\n\n                  │
│      IMPORTANT: Follow the AGE-SPECIFIC GUIDANCE..."            │
│                                                                  │
│ 5.3 Append to messages                                          │
│ 5.4 Clean messages (remove internal fields)                     │
│ 5.5 Convert to Gemini format                                    │
│ 5.6 Stream from Gemini API                                      │
│ 5.7 FOR EACH chunk:                                             │
│     YIELD (chunk.text, None, full_response)                     │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 6: StreamChunk Generation (ask_ask_stream.py:341-359)      │
├─────────────────────────────────────────────────────────────────┤
│ 6.1 FOR EACH text chunk from answer_question_stream():          │
│                                                                  │
│     CREATE StreamChunk:                                         │
│       response = "🌤" (emoji chunk)                             │
│       session_finished = False                                  │
│       duration = 0.0                                            │
│       token_usage = None                                        │
│       finish = False                                            │
│       sequence_number = 1                                       │
│       timestamp = 1734567890.456                                │
│       session_id = "abc-123-def-456"                            │
│       is_stuck = False                                          │
│                                                                  │
│     YIELD StreamChunk                                           │
│                                                                  │
│     (Next chunks: " The", " sky", " is", " blue", ...)          │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 7: SSE Streaming to Frontend (app.py:232-241)              │
├─────────────────────────────────────────────────────────────────┤
│ 7.1 FOR EACH StreamChunk from orchestrator:                     │
│                                                                  │
│     Convert to SSE:                                             │
│     event: chunk                                                │
│     data: {<chunk.model_dump()>}                                │
│                                                                  │
│     YIELD to HTTP stream                                        │
│                                                                  │
│ 7.2 After all chunks, send:                                     │
│     event: complete                                             │
│     data: {"success": true}                                     │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 8: Frontend Displays Response (app.js:292-335)             │
├─────────────────────────────────────────────────────────────────┤
│ 8.1 Create assistant message bubble (gray bubble)               │
│                                                                  │
│ 8.2 FOR EACH chunk event:                                       │
│     IF !chunk.finish:                                           │
│       displayChunk(bubble, chunk.response)                      │
│       → Appends text character-by-character                     │
│       → "🌤" → "🌤 The" → "🌤 The sky" → ...                    │
│       → Auto-scrolls                                            │
│                                                                  │
│ 8.3 When chunk.finish == true:                                  │
│     - Update bubble with full response                          │
│     - Display response time: "Response time: 1.87s"             │
│     - Log token usage (if available)                            │
│                                                                  │
│ 8.4 Re-enable controls, focus input                             │
│ 8.5 User can ask next question                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stuck Detection Flow (When Child is Stuck)

```
USER TYPES: "I don't know" or "idk" or "dunno" or "help"
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stuck Detection Logic (ask_ask_stream.py:213-248)               │
├─────────────────────────────────────────────────────────────────┤
│ 1. input_lower = "i don't know"                                 │
│                                                                  │
│ 2. is_likely_question check:                                    │
│    - No '?' at end                                              │
│    - Doesn't start with question word                           │
│    → is_likely_question = False                                 │
│                                                                  │
│ 3. Check stuck phrases:                                         │
│    stuck_phrases = ["don't know", "dont know", "idk", ...]      │
│    "don't know" IN "i don't know" → YES                         │
│    → RETURN True  ← STUCK!                                      │
│                                                                  │
│ 4. stuck = True                                                 │
│ 5. Route to suggest_topics_stream()  ↓                          │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Suggest Topics Stream (ask_ask_stream.py:167-210)               │
├─────────────────────────────────────────────────────────────────┤
│ 1. Get suggest topics prompt:                                   │
│    "The child said they don't know what to ask..."              │
│                                                                  │
│ 2. Append to messages                                           │
│                                                                  │
│ 3. Convert to Gemini format                                     │
│                                                                  │
│ 4. Stream from Gemini API                                       │
│                                                                  │
│ 5. Gemini generates:                                            │
│    "🤗 That's okay! Want to learn about animals? Or space?..."  │
│                                                                  │
│ 6. Stream chunks with is_stuck = True                           │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Frontend Displays Suggestions (app.js:300-302)                  │
├─────────────────────────────────────────────────────────────────┤
│ 1. handleStreamChunk() receives chunk with is_stuck = true      │
│                                                                  │
│ 2. console.log("Child appears stuck - suggesting topics")       │
│                                                                  │
│ 3. Display streamed topic suggestions in gray bubble            │
│                                                                  │
│ 4. Child can pick a topic and ask about it                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagrams

### Complete Request/Response Cycle

```
Frontend (app.js)
    │
    │ HTTP POST /api/start or /api/continue
    │ {age: 6, session_id: "...", child_input: "..."}
    ▼
Flask Endpoint (app.py)
    │
    │ 1. Validate request
    │ 2. Get/create session
    │ 3. Get assistant instance
    ▼
Async Event Loop Bridge (app.py:_async_to_sync)
    │
    │ Convert sync Flask → async call_ask_ask_stream()
    ▼
Main Orchestrator (ask_ask_stream.py:call_ask_ask_stream)
    │
    ├──► is_child_stuck() → Bool
    │
    ├──► prepare_messages_for_streaming()
    │     │
    │     ├─► Deep copy messages
    │     ├─► Clean internal fields
    │     └─► Append age_prompt to system
    │
    ├──► IF stuck: suggest_topics_stream()
    │    ELSE: answer_question_stream()
    │         │
    │         ├─► Format prompt with question
    │         ├─► Convert to Gemini format
    │         ├─► Call Gemini streaming API
    │         └─► Yield text chunks
    │
    └──► FOR EACH chunk:
         └─► CREATE StreamChunk → YIELD
                │
                ▼
Flask Wraps in SSE (app.py:sse_event)
    │
    │ event: chunk
    │ data: {StreamChunk JSON}
    ▼
HTTP Stream Response
    │
    │ Real-time SSE stream over HTTP
    ▼
Frontend SSE Reader (app.js)
    │
    ├─► Parse SSE events
    ├─► Extract StreamChunk objects
    └─► handleStreamChunk()
         │
         ├─► Display text chunks
         ├─► Track stuck status
         └─► Show duration/tokens
```

### Message Flow Example

```
Conversation Start:
─────────────────

messages = []

↓ [Add system prompt]

messages = [
  {role: "system", content: "You are an enthusiastic...\n\nAGE-SPECIFIC: For 6-year-olds..."}
]

↓ [Add introduction request]

messages = [
  {role: "system", content: "..."},
  {role: "user", content: "Greet the child warmly..."}
]

↓ [Gemini responds: "👋 Hi! I'm so excited..."]

messages = [
  {role: "system", content: "..."},
  {role: "assistant", content: "👋 Hi! I'm so excited to learn with you!..."}
]

↓ [Child asks: "Why is the sky blue?"]

messages = [
  {role: "system", content: "..."},
  {role: "assistant", content: "👋 Hi! I'm so excited..."},
  {role: "user", content: "Why is the sky blue?"}
]

↓ [Add answer prompt]

messages = [
  {role: "system", content: "..."},
  {role: "assistant", content: "👋 Hi! I'm so excited..."},
  {role: "user", content: "Why is the sky blue?"},
  {role: "user", content: "The child asked: Why is the sky blue?\n\nIMPORTANT:..."}
]

↓ [Gemini responds: "🌤 The sky is blue because..."]

messages = [
  {role: "system", content: "..."},
  {role: "assistant", content: "👋 Hi! I'm so excited..."},
  {role: "user", content: "Why is the sky blue?"},
  {role: "assistant", content: "🌤 The sky is blue because..."}
]

↓ [Child says: "I don't know"]

messages = [
  {role: "system", content: "..."},
  {role: "assistant", content: "👋 Hi! I'm so excited..."},
  {role: "user", content: "Why is the sky blue?"},
  {role: "assistant", content: "🌤 The sky is blue because..."},
  {role: "user", content: "I don't know"}
]

↓ [is_child_stuck() = True → Add suggest prompt]

messages = [
  {role: "system", content: "..."},
  {role: "assistant", content: "👋 Hi! I'm so excited..."},
  {role: "user", content: "Why is the sky blue?"},
  {role: "assistant", content: "🌤 The sky is blue because..."},
  {role: "user", content: "I don't know"},
  {role: "user", content: "The child said they don't know...\n\nYour task: Suggest 2-3..."}
]

↓ [Gemini responds with is_stuck=True: "🤗 That's okay! Want to learn about..."]

messages = [
  {role: "system", content: "..."},
  {role: "assistant", content: "👋 Hi! I'm so excited..."},
  {role: "user", content: "Why is the sky blue?"},
  {role: "assistant", content: "🌤 The sky is blue because..."},
  {role: "user", content: "I don't know"},
  {role: "assistant", content: "🤗 That's okay! Want to learn about animals? Or space?..."}
]

... conversation continues infinitely (no termination) ...
```

---

## Component Details

### 1. AskAskAssistant (ask_ask_assistant.py)

**Purpose:** Lightweight session wrapper

**Responsibilities:**
- Initialize Gemini client (Vertex AI)
- Load configuration from config.json
- Load age prompts from age_prompts.json
- Load base prompts from ask_ask_prompts.py
- Store conversation history
- Provide age-specific prompt lookup

**Key Methods:**
- `__init__(config_path, age_prompts_path)` - Initialize
- `get_age_prompt(age)` - Get age-specific guidance
- `get_conversation_history()` - Return message list
- `reset()` - Clear state

**Does NOT:**
- Generate responses
- Call LLM APIs
- Handle streaming

---

### 2. Streaming Module (ask_ask_stream.py)

#### Main Orchestrator: `call_ask_ask_stream()`

**Input:**
```python
age: int | None                  # Child's age (3-8)
messages: list[dict]             # Conversation history
content: str                     # Child's input
status: str                      # "normal" or "over"
session_id: str                  # UUID
config: dict                     # Config from config.json
client: genai.Client             # Gemini client
age_prompt: str                  # Age-specific guidance
```

**Output:** `AsyncGenerator[StreamChunk, None]`

**Process:**
1. Append user message to history
2. Detect if child is stuck
3. Prepare messages (clean, deep copy, add age guidance)
4. Route to appropriate stream generator
5. FOR EACH chunk from generator:
   - Create StreamChunk object
   - Yield to Flask
6. Create final chunk with finish=True
7. Yield final chunk

#### Stream Generators

**`answer_question_stream()`**
- Used when child asks a real question
- Formats answer prompt with question
- Streams Gemini response
- Yields (text_chunk, token_usage, full_response)

**`suggest_topics_stream()`**
- Used when child is stuck
- Formats suggest topics prompt
- Streams Gemini response
- Yields (text_chunk, token_usage, full_response)

#### Helper Functions

**`is_child_stuck(child_input: str) -> bool`**

Detects stuck phrases:
- "don't know", "idk", "dunno", "not sure", "no idea"
- Very short inputs (≤3 chars)
- Single word stuck responses: "huh", "what", "nope", "help"

Returns False if input is a question (ends with ? or starts with question word)

**`prepare_messages_for_streaming(messages, age_prompt)`**
- Deep copy messages (no mutation)
- Remove internal tracking fields
- Append age_prompt to system message
- Return cleaned copy

**`convert_messages_to_gemini_format(messages)`**
- Convert OpenAI style → Gemini style
- Extract system messages → system_instruction
- Convert user/assistant → contents array
- Change "assistant" role → "model" role

---

### 3. Schema Module (schema.py)

#### StreamChunk

**Fields:**
```python
response: str                    # Text chunk or full response
session_finished: bool           # Always False (no termination)
duration: float                  # 0.0 for chunks, actual time for final
token_usage: TokenUsage | None  # Only in final chunk (usually None for Gemini)
finish: bool                     # True for final chunk only
sequence_number: int             # 1-based chunk index
timestamp: float                 # Unix timestamp
session_id: str                  # Session UUID
is_stuck: bool                   # True if suggesting topics
```

#### TokenUsage

**Fields:**
```python
input_tokens: int      # Prompt tokens
output_tokens: int     # Generated tokens
total_tokens: int      # Sum
```

**Note:** Gemini streaming API doesn't provide token usage, so usually None

#### CallAskAskRequest

**Fields:**
```python
age: int | None                  # 3-8 or None
messages: list[dict]             # Message history
content: str                     # User input
status: str                      # "normal" or "over"
session_id: str                  # UUID
```

---

### 4. Flask API (app.py)

#### Endpoints

**POST /api/start**
- Creates new session
- Initializes assistant
- Streams introduction
- Returns SSE stream of StreamChunk objects

**POST /api/continue**
- Validates session exists
- Streams response to child's input
- Returns SSE stream of StreamChunk objects

**POST /api/reset**
- Deletes session from memory
- Returns JSON success/error

**GET /api/sessions**
- Lists all active session IDs
- Returns JSON array

**GET /api/health**
- Health check
- Returns active session count

**GET /**
- Serves static/index.html

#### Session Storage

```python
sessions = {}  # In-memory dictionary

# Structure:
sessions[session_id] = AskAskAssistant instance
```

**WARNING:** Sessions lost on server restart (use Redis for production)

---

### 5. Frontend (static/app.js)

#### Key Functions

**`startConversation()`**
- POST to /api/start
- Read SSE stream
- Parse StreamChunk objects
- Display introduction

**`sendMessage()`**
- POST to /api/continue
- Read SSE stream
- Parse StreamChunk objects
- Display response

**`handleSSEEvent(eventType, data)`**
- Routes events: chunk, complete, error

**`handleStreamChunk(chunk)`**
- Stores session_id on first chunk
- Displays text chunks (!finish)
- Shows full response + metadata (finish)

**`displayChunk(element, text)`**
- Appends text to message bubble
- Auto-scrolls to bottom

---

## Error Handling

### Backend Errors

**Configuration Errors:**
```
FileNotFoundError: config.json not found
→ Check config.json exists in project root
```

**Session Errors:**
```
404 Session not found
→ Session expired or invalid session_id
→ Frontend should redirect to start new conversation
```

**Gemini API Errors:**
```
Exception: Gemini API error: <message>
→ Check API credentials in config.json
→ Check network connectivity
→ Check Vertex AI permissions
```

**Streaming Errors:**
```
event: error
data: {"message": "..."}
→ Logged in console
→ Displayed in red error message
```

### Frontend Errors

**Network Errors:**
```
Failed to fetch
→ Server not running
→ Wrong port (should be 5001)
→ CORS issue
```

**Parse Errors:**
```
JSON.parse() failed
→ Malformed SSE event
→ Check backend SSE formatting
```

**Session Lost:**
```
Session not found (404)
→ Show error message
→ Prompt user to start new conversation
```

---

## Performance Considerations

### Streaming Performance

**Time to First Token (TTFT):**
- Gemini API TTFT: ~0.5-2s
- Displayed in frontend metadata

**Chunk Latency:**
- Real streaming (not simulated)
- Chunks arrive as Gemini generates
- No artificial delays

**Total Response Time:**
- Depends on response length
- Typical: 2-5 seconds
- Logged in final chunk.duration

### Memory Management

**Session Storage:**
- Each session stores:
  - AskAskAssistant instance
  - Conversation history (grows unbounded)
  - Gemini client

**Memory Growth:**
- Conversation history grows with each turn
- No automatic cleanup
- Consider max message limit for production

### Logging

**Log Levels:**
- DEBUG: Message preparation, API calls
- INFO: Stream start/complete, routing decisions
- WARNING: Slow LLM calls (>5s)
- ERROR: API failures, exceptions

**Log Files:**
- Location: logs/ask_ask_YYYY-MM-DD.log
- Rotation: Daily at midnight
- Retention: 30 days

---

## Configuration

### config.json

```json
{
  "project": "your-gcp-project-id",
  "location": "us-central1",
  "model_name": "gemini-2.5-flash",
  "temperature": 0.3,
  "max_tokens": 2000
}
```

### age_prompts.json

```json
{
  "age_groups": {
    "3-4": {
      "prompt": "For ages 3-4:\n- Use very simple words...",
      "description": "..."
    },
    "5-6": {
      "prompt": "For ages 5-6:\n- Introduce WHAT and HOW...",
      "description": "..."
    },
    "7-8": {
      "prompt": "For ages 7-8:\n- Include WHY questions...",
      "description": "..."
    }
  }
}
```

---

## Testing the Pipeline

### Manual Testing Steps

1. **Start Server:**
```bash
cd "C:\Users\123\Documents\GitHub\AI_ask_ask\Gemini\Ask Ask"
python app.py
```

2. **Open Browser:**
```
http://localhost:5001
```

3. **Test Start:**
- Select age: 6
- Click "Start Conversation"
- Verify: Gray bubble appears with streaming introduction
- Check console: Look for StreamChunk objects

4. **Test Question:**
- Type: "Why is the sky blue?"
- Click Send
- Verify: Blue user bubble, then gray assistant bubble
- Check console: is_stuck should be false

5. **Test Stuck:**
- Type: "I don't know"
- Click Send
- Verify: Console shows "Child appears stuck - suggesting topics"
- Check: is_stuck should be true

6. **Test Session:**
- Open browser console
- Check: sessionId variable set
- Verify: All chunks have same session_id

### Backend Logging

Check logs for:
```
[INFO] call_ask_ask_stream started | session_id=...
[INFO] Routing to answer_question
[INFO] answer_question_stream started | question_length=...
[INFO] answer_question_stream completed | duration=2.34s
[INFO] call_ask_ask_stream completed | response_type=answer_question
```

---

## Summary

This pipeline documentation covers:

1. ✅ Complete session start flow (14 steps)
2. ✅ Complete continue conversation flow (8 steps)
3. ✅ Stuck detection and topic suggestion flow
4. ✅ Message history evolution
5. ✅ StreamChunk generation and SSE wrapping
6. ✅ Frontend SSE parsing and display
7. ✅ Component responsibilities
8. ✅ Data transformations
9. ✅ Error handling
10. ✅ Performance considerations

The system uses:
- **Async streaming** for real-time responses
- **StreamChunk** standardized format matching reference architecture
- **SSE** for frontend streaming
- **Gemini 2.5 Flash** for fast LLM responses
- **Age-adaptive prompting** for appropriate content
- **Stuck detection** for helpful topic suggestions
- **No termination** - infinite conversation support
