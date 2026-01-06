# Phase 2: SSE Setup

## Overview
This phase covers the backend setup for Server-Sent Events (SSE) streaming, from receiving the HTTP request to invoking the main orchestrator.

**Entry Point**: API_POST_/start HTTP request received
**Exit Point**: BE_call_paixueji_stream begins yielding StreamChunks
**Duration**: < 100ms (server-side setup)

---

## Transition Table

| Action | Trigger | State Read | Decision Logic | State Written | Output | Next Actions (Success) | Next Actions (Error) |
|--------|---------|------------|----------------|---------------|--------|----------------------|---------------------|
| **BE_validate_request** | HTTP POST received | Request body | object_name present? | - | - | BE_create_session | HTTP 400 response |
| **BE_create_session** | After validation | Request data | - | sessions[session_id] = PaixuejiAssistant(...) | session_id (UUID) | BE_prepare_system_prompts | - |
| **BE_prepare_system_prompts** | Session created | assistant.age, tone, categories, focus_mode | - | assistant.conversation_history = [system_prompt with all prompts] | System message content | BE_create_event_loop | - |
| **BE_create_event_loop** | Before async generator | - | - | - | asyncio.new_event_loop() | BE_call_paixueji_stream | - |
| **BE_call_paixueji_stream** | Async generator invoked | assistant.conversation_history | has_asked_questions? | - | - | BE_route_to_introduction (first) OR BE_route_to_dual_parallel (follow-up) | BE_emit_sse_error |

---

## Decision Points

### 1. Session Creation
```
session_id already exists?
├─ No: Create new PaixuejiAssistant → sessions[session_id]
└─ Yes (rare race condition): Overwrite existing session
```

### 2. First Interaction Detection
```
assistant.conversation_history has assistant messages?
├─ No AND correct_answer_count == 0: Route to introduction
└─ Yes: Route to dual-parallel
```

**Note**: This check happens in Phase 3, but decision logic starts here

---

## State Transitions

### Session State
```
BEFORE (just created):
  conversation_history = []

AFTER (ready for streaming):
  conversation_history = [
    {
      "role": "system",
      "content": (
        base_system_prompt +
        age_prompt (e.g., "Child is 5 years old...") +
        tone_prompt (e.g., "Use a friendly tone...") +
        category_prompt (e.g., "Topic: foods > fruits > red_fruits") +
        focus_prompt (e.g., "Dive deeper into features...")
      )
    }
  ]
```

### Event Loop State
```
BEFORE:
  No event loop in current thread

AFTER:
  loop = asyncio.new_event_loop()
  Ready to run async generators via async_gen_to_sync bridge
```

---

## Prompt Assembly Process

**Source**: `paixueji_assistant.py:__init__`, `paixueji_stream.py:prepare_messages_for_streaming`

### System Prompt Structure
```
BASE (paixueji_assistant.py:141-168)
  "You are a kind and engaging educational assistant..."
  [Core behavior instructions]

+ AGE PROMPT (lines 181-223)
  Age 3-4: "Keep language very simple, use 5-8 words..."
  Age 5-6: "Use simple sentences, 8-12 words..."
  Age 7-8: "Use slightly more complex sentences..."

+ TONE PROMPT (optional, lines 242-287)
  friendly: "Warm and encouraging..."
  excited: "Enthusiastic and energetic..."
  teacher: "Patient and educational..."
  pirate: "Use pirate language..."
  robot: "Use technical language..."
  storyteller: "Weave facts into mini-stories..."

+ CATEGORY PROMPT (lines 293-309)
  "Current topic context:
   - Object: {object_name}
   - Level 3 category: {level3_category}
   - Level 2 category: {level2_category}
   - Level 1 category: {level1_category}"

+ FOCUS PROMPT (lines 315-360)
  depth: "Dive deeper into {object} features, uses, parts..."
  width_color: "Explore other objects with same color..."
  width_shape: "Explore other objects with same shape..."
  width_category: "Explore other objects in same category..."
```

**Total System Prompt Length**: ~800-1200 tokens

---

## SSE Stream Setup

**Source**: `app.py:200-295 (generate function)`

### Headers
```python
@app.route('/api/start', methods=['POST'])
def start():
    # ... session creation ...

    def generate():
        # Wrapper for async_gen_to_sync
        ...

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'  # Disable nginx buffering
        }
    )
```

### Async-to-Sync Bridge
**Source**: `app.py:172-192 (async_gen_to_sync)`

```python
def async_gen_to_sync(async_gen, loop):
    chunk_queue = queue.Queue()

    def run_async():
        try:
            async def consume():
                async for item in async_gen:
                    chunk_queue.put(('chunk', item))
                chunk_queue.put(('done', None))
            loop.run_until_complete(consume())
        except Exception as e:
            chunk_queue.put(('error', e))

    thread = threading.Thread(target=run_async, daemon=True)
    thread.start()

    while True:
        msg_type, data = chunk_queue.get()
        if msg_type == 'chunk':
            yield data
        elif msg_type == 'done':
            break
        elif msg_type == 'error':
            raise data
```

**Why**: Flask is synchronous, Gemini SDK uses async generators. Bridge runs async code in separate thread.

---

## Error Paths

| Error | Trigger | Handler | Recovery |
|-------|---------|---------|----------|
| Missing object_name | POST body validation | BE_validate_request | HTTP 400 {"error": "object_name is required"} |
| Invalid age (not int 3-8) | POST body validation | BE_validate_request | HTTP 400 {"error": "age must be 3-8"} |
| Session creation failure | PaixuejiAssistant.__init__ exception | try-except in start() | HTTP 500 {"error": "Session creation failed"} |
| Event loop creation failure | asyncio error | try-except in generate() | HTTP 500, connection closed |
| Gemini client init failure | genai.Client() exception | PaixuejiAssistant.__init__ | HTTP 500 |

---

## Code References

| Component | File | Lines |
|-----------|------|-------|
| API_POST_/start | app.py | 104-295 |
| BE_validate_request | app.py | 109-115 |
| BE_create_session | app.py | 123-179 |
| System prompt assembly | paixueji_assistant.py | 141-360 (__init__) |
| prepare_messages_for_streaming | paixueji_stream.py | 64-93 |
| BE_create_event_loop | app.py | 193-196 (get_event_loop) |
| async_gen_to_sync bridge | app.py | 172-192 |
| generate function (SSE wrapper) | app.py | 200-295 |
| BE_call_paixueji_stream | paixueji_stream.py | 2010-2304 |

---

## Performance Considerations

- **Event Loop Isolation**: New loop per request prevents race conditions
- **Thread-Based Bridge**: Allows Flask to stream async generators
- **No Buffering**: X-Accel-Buffering header ensures immediate chunk delivery
- **Session Storage**: In-memory dict is fast but not persistent
- **Shallow Copy**: conversation_history copied shallowly for performance (paixueji_stream.py:66)

---

## Notes

- **Session ID**: UUID4 ensures uniqueness, no collision risk
- **Concurrent Requests**: Each gets own event loop, thread-safe
- **Memory**: Unbounded session growth until server restart
- **Timeout**: No request timeout (stream can run indefinitely)
- **Cleanup**: Event loop garbage collected after response complete
