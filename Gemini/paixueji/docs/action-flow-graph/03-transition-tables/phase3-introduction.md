# Phase 3: Introduction Flow

## Overview
Streams the first question about the object to the user.

**Entry Point**: BE_route_to_introduction (first interaction detected)
**Exit Point**: BE_emit_sse_complete, user sees first question
**Duration**: 2-5 seconds (Gemini API call + streaming)

---

## Transition Table

| Action | Trigger | State Read | Decision Logic | State Written | Output | Next Actions (Success) | Next Actions (Error) |
|--------|---------|------------|----------------|---------------|--------|----------------------|---------------------|
| **BE_route_to_introduction** | call_paixueji_stream detects first interaction | assistant: correct_count==0, no assistant messages | - | - | - | BE_prepare_messages | - |
| **BE_prepare_messages** | Before AI call | assistant.conversation_history, age | - | messages_copy (shallow copy) | Cleaned message list | BE_convert_to_gemini | - |
| **BE_convert_to_gemini** | Before Gemini API | messages (OpenAI format) | - | - | {system_instruction, contents} | AI_stream_introduction | - |
| **AI_stream_introduction** | Async generator | messages, object_name, prompts | Gemini API success? | - | Text chunks | BE_emit_sse_chunk (loop) | Fallback: "Tell me about {object}!" |
| **BE_emit_sse_chunk** | Each chunk from generator | chunk_text, sequence_number | - | - | SSE event format | FE_buffer_sse_data | - |
| **FE_buffer_sse_data** | SSE chunk received | buffer string | Contains '\n\n'? | buffer += chunk | - | FE_parse_sse_event | Keep in buffer |
| **FE_parse_sse_event** | Buffer complete | buffer content | event type? | Clear processed from buffer | {event, data} | FE_render_text_chunk (if chunk) | FE_show_error (if error) |
| **FE_render_text_chunk** | Parsed chunk event | StreamChunk.response, currentMessageDiv | chunk.finish? | currentMessageDiv.textContent += text | Updated UI | FE_render_text_chunk (next chunk) OR Complete | - |
| **BE_update_conversation_history** | AI stream complete | full_response (accumulated) | - | conversation_history.append(assistant message) | - | BE_emit_sse_complete | - |
| **BE_emit_sse_complete** | Stream finished | - | - | - | SSE complete event | FE_enable_send_button | - |

---

## Decision Points

### 1. First Interaction Detection
```
call_paixueji_stream checks:
├─ correct_answer_count == 0? YES
└─ conversation_history has assistant messages? NO
   → Route to introduction
```

**Source**: paixueji_stream.py:2063-2066

### 2. Gemini API Success
```
AI_stream_introduction API call
├─ Success: Stream chunks → BE_emit_sse_chunk loop
└─ Error/Timeout: Fallback response → "Tell me about {object}!"
```

---

## State Transitions

### Session State
```
BEFORE:
  conversation_history = [system_prompt]
  correct_answer_count = 0

AFTER:
  conversation_history = [
    system_prompt,
    {"role": "assistant", "content": "What color is an apple?"}
  ]
  correct_answer_count = 0 (unchanged)
```

### Frontend State
```
BEFORE:
  sessionId = null
  currentMessageDiv = null
  isStreaming = true

AFTER (first chunk):
  sessionId = "uuid-from-chunk"
  currentMessageDiv = HTMLElement (message bubble)

AFTER (complete):
  currentMessageDiv = null
  isStreaming = false
  User can now send messages
```

### Streaming State
```
CREATED:
  request_id = UUID
  sequence_number = 0
  full_response = ""
  start_time = time.time()

PER CHUNK:
  full_response += chunk_text
  sequence_number += 1
  StreamChunk yielded

COMPLETE:
  duration = time.time() - start_time
  Final StreamChunk with finish=True
  State destroyed
```

---

## StreamChunk Fields (Introduction)

```json
{
  "session_id": "uuid-generated-on-first-chunk",
  "sequence_number": 0, 1, 2, ...,
  "response": "What color is an apple?",
  "finish": false | true,
  "response_type": "introduction",
  "correct_answer_count": 0,
  "current_object_name": "apple",
  "duration": 2.345,  // Only on finish=true
  "token_usage": null,  // Not available in streaming
  "is_engaged": null,
  "is_factually_correct": null,
  "focus_mode": "depth",
  "system_focus_mode": "depth"  // If system_managed
}
```

---

## Error Paths

| Error | Trigger | Handler | Recovery |
|-------|---------|---------|----------|
| Gemini API timeout | AI_stream_introduction call exceeds time | Exception handler | Fallback: "Tell me about {object}!" |
| Gemini API error | API returns error | Exception handler | Fallback question + log error |
| Stream abort (user click) | FE_abort_stream called | GeneratorExit exception | Partial response visible, log disconnect |
| Empty response | Gemini returns empty string | Check in generator | Use fallback question |
| SSE parse error | Malformed SSE event | FE_parse_sse_event exception | Log error, skip event, continue |

---

## Code References

| Component | File | Lines |
|-----------|------|-------|
| BE_route_to_introduction | paixueji_stream.py | 2063-2088 |
| AI_stream_introduction | paixueji_stream.py | 134-196 |
| BE_prepare_messages | paixueji_stream.py | 64-93 |
| BE_convert_to_gemini | paixueji_stream.py | 95-132 |
| BE_emit_sse_chunk | app.py | 200-225 (generate wrapper) |
| FE_buffer_sse_data | static/app.js | 243-247 |
| FE_parse_sse_event | static/app.js | 246-263 |
| FE_render_text_chunk | static/app.js | 524-526 |
| BE_update_conversation_history | paixueji_stream.py | 2082-2086 |
| BE_emit_sse_complete | app.py | 226-227 |

---

## Prompt Structure (Introduction)

**Source**: paixueji_stream.py:152-174

```
You are about to have a conversation with a child about {object}.

Guidelines:
- Start by asking ONE simple question about {object}
- The question should be appropriate for a {age}-year-old
- Make it engaging and easy to answer
- Focus on basic observable features (color, shape, size, where found)
- Keep question to 10-15 words maximum

IMPORTANT:
- Output ONLY the question, nothing else
- No greetings, no explanations, just the question
- End with a question mark

Example for "apple" (age 5):
"What color is an apple?"

Now, ask your first question about {object}:
```

---

## Performance Tracking

**Source**: paixueji_stream.py:179-188

```python
start_time = time.time()

# ... streaming ...

duration = time.time() - start_time

if duration > SLOW_LLM_CALL_THRESHOLD:  # 5.0 seconds
    logger.warning(f"Slow LLM introduction | duration={duration:.3f}s")

logger.info(f"Introduction complete | object={object} | duration={duration:.3f}s")
```

---

## Notes

- **Single Question**: Introduction always asks ONE question only
- **No Validation**: No answer validation in introduction (just ask question)
- **Session ID Assignment**: Frontend extracts session_id from first chunk
- **Shallow Copy**: Messages copied shallowly for performance
- **Fallback Always Available**: Never fails completely, always has fallback question
