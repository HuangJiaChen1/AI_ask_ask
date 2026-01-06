# Phase 1: Initialization

## Overview
This phase covers the user journey from page load to clicking "Start Learning!", including optional object classification.

**Entry Point**: User loads page (GET /)
**Exit Point**: API_POST_/start begins SSE stream
**Duration**: 10-60 seconds (user interaction time)

---

## Transition Table

| Action | Trigger | State Read | Decision Logic | State Written | Output | Next Actions (Success) | Next Actions (Error) |
|--------|---------|------------|----------------|---------------|--------|----------------------|---------------------|
| **USER_fill_form** | Page load, user typing | localStorage (tone, focus) | - | FE: form fields populated | Form values | USER_click_classify OR USER_click_start | - |
| **FE_validate_input** (for classify) | USER clicks "Classify" | FE: object_name input value | object_name not empty? | - | - | API_POST_/classify | FE_show_error("Please enter object name") |
| **USER_click_classify** | Click "Classify" button | FE: object_name | - | - | - | FE_validate_input | - |
| **API_POST_/classify** | Fetch POST from FE | Request body: {object_name} | object_name valid string? | - | HTTP response | AI_classify_object | HTTP 400 (missing object_name) |
| **AI_classify_object** | Classification API call | object_name | Object in level2_categories? | - | JSON {level1_category, level2_category} | FE_update_dropdowns | FE_show_error (timeout 1s) OR "none" fallback |
| **FE_update_dropdowns** | Classify API success | Response: {level1, level2} | - | FE: level1/level2 dropdown selected | Dropdowns auto-selected | USER_click_start | - |
| **FE_validate_input** (for start) | USER clicks "Start Learning!" | FE: object_name, age | object_name not empty? | - | - | API_POST_/start | FE_show_error("Please enter object name") |
| **USER_click_start** | Click "Start Learning!" button | FE: form fields | - | - | - | FE_validate_input | - |
| **API_POST_/start** | Fetch POST from FE | Request body: {age, object, categories, tone, focus, system_managed} | object_name present? age valid? | BE: sessions[session_id] = new PaixuejiAssistant | HTTP 200, SSE headers | BE_create_session | HTTP 400 (validation error) |
| **BE_create_session** | API handler | Request data | - | Session: all fields, conversation_history=[system_prompt], correct_count=0 | session_id (UUID) | BE_create_event_loop | - |
| **BE_create_event_loop** | Before streaming | - | - | - | asyncio event loop | BE_call_paixueji_stream | - |

---

## Decision Points

### 1. Classification Optional
```
USER has object name
├─ Option A: Click "Classify" → API auto-fills categories → USER clicks "Start"
└─ Option B: Skip classification → Manually select categories → USER clicks "Start"
```

### 2. Classification Timeout (1 second)
```
AI_classify_object call
├─ Success (< 1s): Return {level1, level2} → FE updates dropdowns
└─ Timeout (>= 1s): Continue anyway → FE shows warning, dropdowns remain manual
```

### 3. Classification Not Found
```
Object not in any level2_category
├─ Return: {level1: null, level2: "none"}
└─ FE: Select "none of the above" option → allows custom objects
```

### 4. Form Validation
```
object_name empty?
├─ Yes: Show error "Please enter an object name"
└─ No: Proceed to API_POST_/start
```

---

## State Transitions

### Frontend State
```
BEFORE:
  sessionId = null
  isStreaming = false
  currentTone = localStorage OR "friendly"
  currentFocusMode = localStorage OR "system_managed"

AFTER (ready to stream):
  isStreaming = true
  currentStreamController = new AbortController()
  All form values captured
```

### Session State
```
BEFORE:
  sessions = {}

AFTER:
  sessions[session_id] = PaixuejiAssistant {
    object_name: "apple"
    level1_category: "foods"
    level2_category: "fruits"
    level3_category: "red_fruits"
    age: 5
    tone: "friendly"
    conversation_history: [system_prompt]
    correct_answer_count: 0
    system_managed_focus: true
    current_focus_mode: "depth"
    depth_target: 4  # random(4, 5)
  }
```

---

## Error Paths

| Error | Trigger | Handler | Recovery |
|-------|---------|---------|----------|
| Empty object name | USER_click_start with empty input | FE_validate_input | Show error, re-enable button |
| Classification timeout (1s) | AI_classify_object exceeds timeout | ThreadPoolExecutor timeout | Show warning, continue with manual selection |
| Classification API error | Gemini API failure | Exception handler | Show error status, continue with manual selection |
| Invalid age (not 3-8) | USER selects invalid age | Backend validation | HTTP 400 response |
| Missing required fields | Malformed POST /api/start | Backend validation | HTTP 400 response |

---

## Code References

| Action | File | Lines |
|--------|------|-------|
| USER_fill_form | static/index.html | 18-67 |
| USER_click_classify | static/app.js | 714-782 (classifyObject) |
| API_POST_/classify | app.py | 473-515 |
| AI_classify_object | paixueji_assistant.py | 237-314 (classify_object_sync) |
| FE_update_dropdowns | static/app.js | 750-773 |
| USER_click_start | static/app.js | 120-295 (startConversation) |
| API_POST_/start | app.py | 104-295 |
| BE_create_session | app.py | 123-179 |
| BE_create_event_loop | app.py | 193-196 (get_event_loop) |

---

## Notes

- **Classification is optional**: User can skip and manually select categories
- **Timeout strict**: 1 second max for classification to avoid UX delay
- **Session ID generation**: UUID4 ensures uniqueness
- **LocalStorage**: Tone and focus preferences persist across page refreshes
- **Form reset**: Not implemented (refresh page to restart)
