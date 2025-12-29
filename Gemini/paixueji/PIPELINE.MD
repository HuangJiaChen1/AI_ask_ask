 PAIXUEJI (Learning by Asking) - Complete System Pipeline

  SYSTEM OVERVIEW

  This is an educational conversation system where an AI asks questions about objects to children (ages 3-8), and children provide answers. The system uses streaming responses and can dynamically switch topics.

  ---
  1. INITIALIZATION FLOW

  ┌─────────────────────────────────────────────────────────────────┐
  │                    APPLICATION STARTUP                          │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  app.py: Flask Server Initialization                            │
  │  - Load CORS configuration                                      │
  │  - Initialize in-memory sessions dict {}                        │
  │  - Set up routes                                                │
  │  INPUT: None                                                    │
  │  OUTPUT: Flask app running on http://localhost:5001            │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  PaixuejiAssistant.__init__() (paixueji_assistant.py)          │
  │  - Load config.json (project, location, model_name, etc.)      │
  │  - Load age_prompts.json (age-specific guidance 3-8)           │
  │  - Load object_prompts.json (category-based prompts)           │
  │  - Load paixueji_prompts.py (system/intro/question prompts)   │
  │  - Initialize Google Gemini client (VertexAI)                  │
  │  INPUT: config_path, age_prompts_path, object_prompts_path    │
  │  OUTPUT: PaixuejiAssistant instance with client & config       │
  └─────────────────────────────────────────────────────────────────┘

  ---
  2. START CONVERSATION FLOW (/api/start)

  ┌─────────────────────────────────────────────────────────────────┐
  │  CLIENT REQUEST: POST /api/start                                │
  │  INPUT JSON:                                                    │
  │  {                                                              │
  │    "age": 6,                       // Optional (3-8)           │
  │    "object_name": "apple",         // REQUIRED                 │
  │    "level1_category": "foods",     // Optional                 │
  │    "level2_category": "fresh_ing", // Optional                 │
  │    "level3_category": null,        // Optional                 │
  │    "tone": "friendly",             // Optional                 │
  │    "focus_mode": "depth"           // Optional (default: depth)│
  │  }                                                              │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  app.py: start_conversation() - Validation                     │
  │  - Validate object_name exists                                 │
  │  - Validate age (3-8) or set to None                          │
  │  - Generate session_id (UUID)                                  │
  │  - Generate request_id (UUID)                                  │
  │  OUTPUT: Validated params + session_id + request_id            │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Create PaixuejiAssistant Instance for Session                 │
  │  - sessions[session_id] = assistant                            │
  │  - Store: age, object_name, level1/2/3_category, tone         │
  │  - Initialize: correct_answer_count = 0                        │
  │  - Initialize: conversation_history = []                       │
  │  OUTPUT: Session stored in memory                              │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Build System Prompt (Multi-layer composition)                 │
  │  1. Base: prompts['system_prompt']                             │
  │  2. + get_age_prompt(age) if age exists                       │
  │  3. + get_tone_prompt(tone) if tone exists                    │
  │  4. + get_category_prompt(l1, l2, l3) if categories exist     │
  │  5. + get_focus_prompt(focus_mode)                            │
  │  OUTPUT: Complete system_prompt string                         │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Initialize Conversation History                                │
  │  conversation_history = [                                       │
  │    {"role": "system", "content": system_prompt}                │
  │  ]                                                              │
  │  OUTPUT: conversation_history with system prompt               │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Create Event Loop & Start SSE Stream                          │
  │  - loop = asyncio.new_event_loop()                             │
  │  - introduction_content = f"Start conversation about {object}" │
  │  - Call async generator: stream_introduction()                 │
  │  OUTPUT: SSE stream to client                                  │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  call_paixueji_stream() [paixueji_stream.py]                  │
  │  INPUT:                                                         │
  │  - messages (conversation_history)                             │
  │  - content (introduction trigger)                              │
  │  - correct_answer_count = 0                                    │
  │  - age, object_name, categories, prompts                       │
  │  - config, client                                              │
  │  - focus_mode, focus_prompt                                    │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Route to Introduction Stream (correct_answer_count == 0)      │
  │  ask_introduction_question_stream()                            │
  │  - Format INTRODUCTION_PROMPT with:                            │
  │    * object_name, category_prompt, age_prompt, focus_prompt   │
  │  - Append to messages as user message                          │
  │  - Clean messages (remove non-standard fields)                 │
  │  - Convert to Gemini format (system_instruction + contents)    │
  │  OUTPUT: Prepared messages for Gemini API                      │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Gemini API Call (Streaming)                                   │
  │  client.models.generate_content_stream(                        │
  │    model="gemini-2.0-flash-exp",                               │
  │    contents=contents,                                          │
  │    config={temperature: 0.3, max_tokens: 2000, system_inst}   │
  │  )                                                              │
  │  OUTPUT: Stream of text chunks from Gemini                     │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Stream Processing Pipeline (call_paixueji_stream)            │
  │  For each chunk from Gemini:                                   │
  │  1. Buffer text                                                │
  │  2. Parse & remove <analysis>...</analysis> (hidden thinking)  │
  │  3. Parse & extract <new_topic>...</new_topic> (topic switch)  │
  │  4. Yield clean text as StreamChunk                            │
  │  OUTPUT: StreamChunk objects                                   │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  StreamChunk Structure (schema.py)                             │
  │  {                                                              │
  │    response: "Hi! Let's learn about apples! What color...",   │
  │    session_finished: false,                                    │
  │    duration: 0.0,              // Only in final chunk         │
  │    token_usage: null,          // Only in final chunk         │
  │    finish: false,              // true in final chunk          │
  │    sequence_number: 1,                                         │
  │    timestamp: 1234567890.123,                                  │
  │    session_id: "uuid",                                         │
  │    request_id: "uuid",                                         │
  │    correct_answer_count: 0,                                    │
  │    conversation_complete: false,                               │
  │    focus_mode: "depth",                                        │
  │    is_correct: null,                                           │
  │    new_object_name: null       // If topic switch detected    │
  │  }                                                              │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  SSE Event Formatting (app.py: sse_event())                    │
  │  - Serialize StreamChunk to JSON (optimized with model_dump_json)│
  │  - Format as SSE: "event: chunk\ndata: {json}\n\n"            │
  │  OUTPUT: SSE-formatted string sent to client                   │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Update Conversation History (on final chunk)                  │
  │  assistant.conversation_history.append({                       │
  │    "role": "assistant",                                        │
  │    "content": full_response                                    │
  │  })                                                             │
  │  OUTPUT: Updated conversation_history for next turn            │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Send Completion Event                                          │
  │  event: complete                                                │
  │  data: {"success": true}                                       │
  │  OUTPUT: Client knows stream is complete                       │
  └─────────────────────────────────────────────────────────────────┘

  ---
  3. CONTINUE CONVERSATION FLOW (/api/continue)

  ┌─────────────────────────────────────────────────────────────────┐
  │  CLIENT REQUEST: POST /api/continue                             │
  │  INPUT JSON:                                                    │
  │  {                                                              │
  │    "session_id": "uuid-from-start",                            │
  │    "child_input": "It's red and round",                        │
  │    "focus_mode": "depth"  // Can change between turns          │
  │  }                                                              │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Validate & Retrieve Session                                   │
  │  - Check session_id exists in sessions dict                    │
  │  - Retrieve assistant = sessions[session_id]                   │
  │  - Generate new request_id for this turn                       │
  │  ERROR: 404 if session_id not found                           │
  │  OUTPUT: assistant instance with full state                    │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Retrieve Session State                                         │
  │  - age, object_name, categories from assistant                 │
  │  - correct_answer_count from assistant                         │
  │  - conversation_history from assistant                         │
  │  OUTPUT: Current session state                                 │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Rebuild Prompts (may have changed)                            │
  │  - age_prompt = get_age_prompt(age)                            │
  │  - category_prompt = get_category_prompt(l1, l2, l3)          │
  │  - focus_prompt = get_focus_prompt(focus_mode)                │
  │  OUTPUT: Current prompts for this turn                         │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Answer Validation (paixueji_stream.py: is_answer_reasonable) │
  │  INPUT: child_input                                            │
  │  LOGIC:                                                         │
  │  - Too short? (<=3 chars) → False                             │
  │  - Contains stuck phrases? ("don't know", "idk") → False      │
  │  - Has letters? (<2 letters) → False                          │
  │  - Otherwise → True (be encouraging!)                          │
  │  OUTPUT: answer_is_reasonable (bool)                           │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Update Correct Answer Count (if reasonable)                   │
  │  if answer_is_reasonable:                                      │
  │    assistant.increment_correct_answers()                       │
  │    // correct_answer_count += 1                                │
  │  OUTPUT: Updated correct_answer_count                          │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Create Event Loop & Start SSE Stream                          │
  │  - loop = asyncio.new_event_loop()                             │
  │  - Call async generator: stream_response()                     │
  │  OUTPUT: SSE stream to client                                  │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  call_paixueji_stream() [paixueji_stream.py]                  │
  │  INPUT:                                                         │
  │  - messages (conversation_history)                             │
  │  - content (child_input)                                       │
  │  - correct_answer_count (current count)                        │
  │  - age, object_name, categories, prompts                       │
  │  - config, client                                              │
  │  - focus_mode, focus_prompt                                    │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Add User Input to Conversation History                        │
  │  messages.append({                                             │
  │    "role": "user",                                             │
  │    "content": child_input                                      │
  │  })                                                             │
  │  OUTPUT: Updated messages for this turn                        │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Route to Follow-up Stream (correct_answer_count > 0)          │
  │  ask_followup_question_stream()                                │
  │  - Format QUESTION_PROMPT with:                                │
  │    * child_answer, object_name, correct_count                 │
  │    * age, category_prompt, age_prompt, focus_prompt           │
  │  - Append to messages as user message                          │
  │  - Clean messages (remove non-standard fields)                 │
  │  - Convert to Gemini format (system_instruction + contents)    │
  │  OUTPUT: Prepared messages for Gemini API                      │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Gemini API Call (Streaming)                                   │
  │  client.models.generate_content_stream(                        │
  │    model="gemini-2.0-flash-exp",                               │
  │    contents=contents,                                          │
  │    config={temperature: 0.3, max_tokens: 2000, system_inst}   │
  │  )                                                              │
  │  OUTPUT: Stream of text chunks from Gemini                     │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  TWO-STEP DECISION ARCHITECTURE (Updated)                      │
  │                                                                 │
  │  STEP 1: Topic Switch Decision (Structured Output)             │
  │  ─────────────────────────────────────────────────────────────  │
  │  Function: decide_topic_switch() [paixueji_stream.py]          │
  │  Input:                                                         │
  │    - Child's answer                                            │
  │    - Current object, focus mode, correct count                 │
  │  Process:                                                       │
  │    - Build decision prompt with context                        │
  │    - Call Gemini API with JSON mode (response_mime_type)       │
  │    - Temperature: 0.1, Max tokens: 100                         │
  │  Output:                                                        │
  │    {                                                            │
  │      "decision": "SWITCH" | "CONTINUE",                        │
  │      "new_object": "ObjectName" | null,                        │
  │      "reasoning": "Brief explanation"                          │
  │    }                                                            │
  │  Latency: ~100-200ms                                            │
  │                                                                 │
  │  STEP 2: Handle Decision & Classify (if switching)             │
  │  ─────────────────────────────────────────────────────────────  │
  │  if decision == "SWITCH":                                       │
  │    1. Update assistant.object_name = new_object                │
  │    2. Classify synchronously with 1s timeout:                  │
  │       - Call assistant.classify_object_sync()                  │
  │       - Wait max 1 second for completion                       │
  │       - Updates level1/level2/level3 categories                │
  │    3. Rebuild category_prompt and focus_prompt                 │
  │  Latency: ~800ms-1s (for classification)                       │
  │                                                                 │
  │  STEP 3: Generate Response                                      │
  │  ─────────────────────────────────────────────────────────────  │
  │  - Use updated object_name and prompts                         │
  │  - Stream response generation (existing logic)                 │
  │  - Simple buffering (no tag parsing needed)                    │
  │                                                                 │
  │  Benefits:                                                      │
  │    ✓ 100% reliable topic switching (structured JSON)           │
  │    ✓ No XML tag parsing from free text                         │
  │    ✓ Clear audit trail in logs                                 │
  │    ✓ Separation of decision from response generation           │
  │                                                                 │
  │  Total Added Latency: ~200-300ms per turn                      │
  │  OUTPUT: StreamChunk objects with new_object_name if switched  │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Send StreamChunks via SSE                                     │
  │  For each chunk:                                               │
  │    event: chunk                                                │
  │    data: {StreamChunk JSON with new_object_name if switched}  │
  │  Final chunk (finish=true):                                    │
  │    - Contains duration, full_response                          │
  │    - token_usage (null for Gemini streaming)                   │
  │  OUTPUT: Real-time streaming to client                         │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Update Conversation History (on final chunk)                  │
  │  assistant.conversation_history.append({                       │
  │    "role": "assistant",                                        │
  │    "content": full_response                                    │
  │  })                                                             │
  │  OUTPUT: Updated conversation_history for next turn            │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Send Completion Event                                          │
  │  event: complete                                                │
  │  data: {"success": true}                                       │
  │  OUTPUT: Client knows stream is complete                       │
  └─────────────────────────────────────────────────────────────────┘

  ---
  4. PROMPT COMPOSITION SYSTEM

  ┌─────────────────────────────────────────────────────────────────┐
  │                    PROMPT LAYERING SYSTEM                       │
  │  (Multi-dimensional prompt composition)                         │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 1: Base System Prompt (paixueji_prompts.py)            │
  │  SOURCE: SYSTEM_PROMPT                                         │
  │  CONTENT:                                                       │
  │  - Role: "curious and encouraging learning companion"          │
  │  - Task: ASK questions about objects                           │
  │  - Principles: age-appropriate, encouraging, simple, fun       │
  │  OUTPUT: Base behavior definition                              │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 2: Age-Specific Guidance (age_prompts.json)            │
  │  INPUT: age (3-8)                                              │
  │  MAPPING:                                                       │
  │  - Age 3-4: "WHAT questions only, 3-5 word sentences"         │
  │  - Age 5-6: "WHAT/HOW questions, 5-8 word sentences"          │
  │  - Age 7-8: "WHAT/HOW/WHY questions, complex thinking"        │
  │  METHOD: get_age_prompt(age)                                   │
  │  OUTPUT: Age-appropriate question complexity guidance          │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 3: Tone Customization (paixueji_prompts.py)            │
  │  INPUT: tone ("friendly", "excited", "teacher", etc.)         │
  │  OPTIONS:                                                       │
  │  - friendly: "Warm, encouraging, gentle"                       │
  │  - excited: "Enthusiastic, high energy, use !!!"              │
  │  - teacher: "Educational, patient, structured"                 │
  │  - pirate: "Ahoy matey! Sea-related metaphors"                │
  │  - robot: "Beep boop, precise but friendly"                   │
  │  - storyteller: "Magical, descriptive language"               │
  │  METHOD: get_tone_prompt(tone)                                 │
  │  OUTPUT: Communication style guidance                          │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 4: Category Guidance (object_prompts.json)             │
  │  INPUT: level1/2/3_category                                    │
  │  FALLBACK CHAIN:                                               │
  │  1. Try level3_category (most specific)                        │
  │  2. Fall back to level2_category                               │
  │  3. Fall back to level1_category                               │
  │  4. Default: "Ask about appearance, properties, uses"          │
  │  EXAMPLE:                                                       │
  │  - foods/fresh_ingredients: "Ask about taste, texture, where   │
  │    grown, how eaten"                                           │
  │  METHOD: get_category_prompt(l1, l2, l3)                       │
  │  OUTPUT: Domain-specific question focus                        │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 5: Focus Strategy (paixueji_prompts.py)                │
  │  INPUT: focus_mode                                             │
  │  STRATEGIES:                                                    │
  │  - depth: "Dive deeper into current object details"           │
  │  - width_shape: "Find OTHER objects with same SHAPE"          │
  │  - width_color: "Find OTHER objects with same COLOR"          │
  │  - width_category: "Find OTHER objects in same CATEGORY"      │
  │  CRITICAL INSTRUCTION:                                         │
  │  "If child mentions NEW valid object, output                   │
  │   <new_topic>ObjectName</new_topic> and switch to it"         │
  │  METHOD: get_focus_prompt(focus_mode)                          │
  │  OUTPUT: Exploration strategy guidance                         │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  FINAL SYSTEM PROMPT ASSEMBLY                                  │
  │  system_prompt = BASE_SYSTEM_PROMPT                            │
  │                + "\n\nAGE-SPECIFIC GUIDANCE:\n" + age_prompt   │
  │                + "\n\nTONE GUIDANCE:\n" + tone_prompt          │
  │                + "\n\nCATEGORY GUIDANCE:\n" + category_prompt  │
  │  (focus_prompt used in user message, not system)              │
  │  OUTPUT: Complete system instruction for Gemini                │
  └─────────────────────────────────────────────────────────────────┘

  ---
  5. FOCUS MODES & TOPIC SWITCHING

  ┌─────────────────────────────────────────────────────────────────┐
  │                    FOCUS MODE DECISION TREE                     │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Focus Mode: DEPTH                                              │
  │  BEHAVIOR:                                                      │
  │  - Stay on current object                                      │
  │  - Ask detailed questions about it                             │
  │  SWITCH CONDITION:                                             │
  │  - Only if child EXPLICITLY mentions new object                │
  │  EXAMPLE:                                                       │
  │  Object: Apple                                                 │
  │  Q: "What color is the apple?"                                 │
  │  A: "Red"                                                      │
  │  Q: "What does the inside of an apple look like?"              │
  │  A: "It has a banana inside" → SWITCH to Banana               │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Focus Mode: WIDTH_COLOR                                        │
  │  BEHAVIOR:                                                      │
  │  - Ask child to find objects with same COLOR                   │
  │  SWITCH CONDITION:                                             │
  │  - When child provides valid object with that color            │
  │  EXAMPLE:                                                       │
  │  Object: Apple (red)                                           │
  │  Q: "What else is red like an apple?"                          │
  │  A: "A firetruck" → SWITCH to Firetruck                        │
  │  Q: "What does a firetruck do?"                                │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Focus Mode: WIDTH_SHAPE                                        │
  │  BEHAVIOR:                                                      │
  │  - Ask child to find objects with same SHAPE                   │
  │  SWITCH CONDITION:                                             │
  │  - When child provides valid object with that shape            │
  │  EXAMPLE:                                                       │
  │  Object: Ball (round)                                          │
  │  Q: "What else is round like a ball?"                          │
  │  A: "The moon" → SWITCH to Moon                                │
  │  Q: "What do you see on the moon at night?"                    │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Focus Mode: WIDTH_CATEGORY                                     │
  │  BEHAVIOR:                                                      │
  │  - Ask child to find objects in same CATEGORY                  │
  │  SWITCH CONDITION:                                             │
  │  - When child provides valid object in that category           │
  │  EXAMPLE:                                                       │
  │  Object: Apple (fruits)                                        │
  │  Q: "What other fruits do you know?"                           │
  │  A: "Banana" → SWITCH to Banana                                │
  │  Q: "What color is a banana?"                                  │
  └─────────────────────────────────────────────────────────────────┘

  ---
  6. LLM RESPONSE PARSING PIPELINE

  ╔═════════════════════════════════════════════════════════════════╗
  ║                    ⚠️  DEPRECATED - OLD FLOW  ⚠️                 ║
  ║                                                                 ║
  ║  This section documents the OLD XML tag parsing approach       ║
  ║  that has been REPLACED by the two-step decision architecture. ║
  ║                                                                 ║
  ║  Problem: LLM would sometimes forget to output <new_topic>     ║
  ║  tags even when intending to switch, causing fallback bugs.    ║
  ║                                                                 ║
  ║  Solution: Separated decision-making (structured JSON) from    ║
  ║  response generation (free text). See Section 3 for new flow.  ║
  ║                                                                 ║
  ║  Kept for historical reference only.                           ║
  ╚═════════════════════════════════════════════════════════════════╝

  OLD FLOW (Deprecated):

  ┌─────────────────────────────────────────────────────────────────┐
  │                  GEMINI RESPONSE STRUCTURE                      │
  │  (What the LLM was instructed to output)                        │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  EXPECTED FORMAT (from old QUESTION_PROMPT):                    │
  │  <analysis>                                                     │
  │  1. Current Focus Strategy: WIDTH-COLOR                         │
  │  2. Child's Answer: "firetruck"                                │
  │  3. Did they name a NEW object? Yes                            │
  │  4. Does it fit strategy? Yes (firetruck is red)               │
  │  5. DECISION: SWITCH TOPIC                                     │
  │  </analysis>                                                    │
  │  <new_topic>Firetruck</new_topic>                              │
  │  Yes! A firetruck is red too! 🚒 What does a firetruck do?     │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  PARSING STAGE 1: Analysis Block Removal (REMOVED)             │
  │  INPUT: Buffered chunks from Gemini stream                     │
  │  DETECTION: if "<analysis>" in buffer:                         │
  │  ACTION:                                                        │
  │  - Set is_in_analysis = True                                   │
  │  - Buffer all text until "</analysis>" found                   │
  │  - Extract analysis content (for logging)                      │
  │  - Remove entire <analysis>...</analysis> from output          │
  │  - DO NOT yield to client (hidden internal reasoning)          │
  │  OUTPUT: Buffer without analysis block                         │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  PARSING STAGE 2: Topic Tag Extraction (REMOVED)               │
  │  INPUT: Buffer after analysis removal                          │
  │  DETECTION: if "<new_topic>" in buffer:                        │
  │  ACTION:                                                        │
  │  - Wait for "</new_topic>" to arrive                           │
  │  - Extract object name between tags                            │
  │  - Set new_object_name = extracted_name                        │
  │  - Remove <new_topic>...</new_topic> from output              │
  │  - DO NOT yield tag to client (control signal only)            │
  │  - Set new_object_detected = True                              │
  │  OUTPUT: Clean text + new_object_name metadata                 │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  PARSING STAGE 3: Clean Text Yielding                          │
  │  INPUT: Buffer with tags removed                               │
  │  BUFFERING STRATEGY:                                           │
  │  - If still waiting for tag completion: hold in buffer         │
  │  - If buffer > 50 chars and no '<': flush to avoid latency     │
  │  - Otherwise: yield text immediately                            │
  │  OUTPUT: Clean visible response text                           │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  RESULT: StreamChunk with Metadata                             │
  │  {                                                              │
  │    response: "Yes! A firetruck is red too! 🚒 What does...",   │
  │    new_object_name: "Firetruck",  // Only in first chunk      │
  │    finish: false,                                              │
  │    sequence_number: 5,                                         │
  │    ...                                                         │
  │  }                                                              │
  │  CLIENT RECEIVES: Clean conversational text                    │
  │  APP RECEIVES: new_object_name signal for state update         │
  └─────────────────────────────────────────────────────────────────┘

  ---
  7. ASYNC/THREADING ARCHITECTURE

  ┌─────────────────────────────────────────────────────────────────┐
  │                    CONCURRENCY MODEL                            │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Flask Request Thread (per client request)                      │
  │  - Handles HTTP request                                        │
  │  - Creates new asyncio event loop (get_event_loop())           │
  │  - Avoids "loop already running" errors                        │
  │  - Each request gets isolated loop                             │
  │  OUTPUT: Dedicated event loop for this request                 │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Async Generator (stream_introduction/stream_response)         │
  │  - Runs async Gemini API calls                                │
  │  - Yields chunks asynchronously                                │
  │  - Lives in event loop                                         │
  │  OUTPUT: Async generator of StreamChunks                       │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Sync Bridge (async_gen_to_sync)                               │
  │  PATTERN: Queue-based bridge                                   │
  │  1. Background thread runs event loop                          │
  │     - Consumes async generator                                 │
  │     - Puts chunks into queue.Queue()                           │
  │  2. Main thread (SSE generator)                                │
  │     - Blocks on queue.get() waiting for chunks                 │
  │     - Yields chunks to Flask SSE response                      │
  │  WHY: Flask needs sync generator, Gemini API is async          │
  │  OUTPUT: Sync generator for Flask Response                     │
  └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Background Classification Thread (when topic switches)        │
  │  TRIGGER: chunk.new_object_name detected                       │
  │  ACTION:                                                        │
  │  threading.Thread(                                             │
  │    target=assistant.classify_object_sync,                      │
  │    args=(new_object_name,),                                    │
  │    daemon=True                                                 │
  │  ).start()                                                      │
  │  EFFECT:                                                        │
  │  - Runs Gemini classification API call in background           │
  │  - Does NOT block current response stream                      │
  │  - Updates assistant categories for NEXT turn                  │
  │  OUTPUT: Non-blocking category classification                  │
  └─────────────────────────────────────────────────────────────────┘

  ---
  8. ERROR TRACING POINTS

  Key places to check for errors:

  A. Session Errors

  - Location: app.py:276-282 (continue_conversation)
  - Check: session_id in sessions dict
  - Error: 404 "Session not found"
  - Cause: Session expired, wrong ID, or server restarted

  B. Validation Errors

  - Location: app.py:112-116 (start), app.py:260-274 (continue)
  - Check: Required fields (object_name, child_input)
  - Error: 400 "Missing required fields"
  - Cause: Client didn't send required data

  C. Age Validation

  - Location: app.py:119-127
  - Check: Age is int 3-8
  - Effect: Invalid age → set to None, fallback to default

  D. Gemini API Errors

  - Location: paixueji_stream.py:187-217 (introduction), :310-343 (followup)
  - Check: Exception during stream
  - Error: Logged and yielded as partial response
  - Cause: Network, API quota, invalid credentials

  E. Classification Errors

  - Location: paixueji_assistant.py:191-268 (classify_object_sync)
  - Check: Exception during background classification
  - Effect: Categories set to None, fallback to default
  - Cause: API error, invalid object_prompts.json

  F. Streaming Errors

  - Location: paixueji_stream.py:619-709 (parsing pipeline)
  - Check: Incomplete tags, malformed response
  - Effect: Tags not detected, text not cleaned properly
  - Cause: LLM didn't follow format, stream interrupted

  G. Message Format Errors

  - Location: paixueji_stream.py:96-122 (convert_messages_to_gemini_format)
  - Check: Invalid message roles or structure
  - Effect: API call fails
  - Cause: Corrupted conversation_history

  H. Event Loop Errors

  - Location: app.py:28-43 (get_event_loop)
  - Check: "RuntimeError: This event loop is already running"
  - Effect: New loop created per request
  - Cause: Concurrent requests sharing loop (now prevented)

  ---
  9. DATA FLOW SUMMARY

  CLIENT REQUEST
       ↓
  [Validation] → Error 400/404 if invalid
       ↓
  [Session Retrieval/Creation] → sessions dict
       ↓
  [Prompt Composition] → Multi-layer prompt building
       ↓
  [Conversation History Update] → Add user message
       ↓
  [Event Loop Creation] → New loop per request
       ↓
  [Async Generator] → call_paixueji_stream()
       ↓
  [Route to Stream Function] → introduction OR followup
       ↓
  [Gemini API Call] → generate_content_stream()
       ↓
  [Stream Processing] → Parse tags, clean text
       ↓
  [StreamChunk Creation] → Pydantic model with metadata
       ↓
  [SSE Formatting] → event: chunk\ndata: {json}\n\n
       ↓
  [Async→Sync Bridge] → Queue-based threading
       ↓
  [Flask Response] → SSE stream to client
       ↓
  [History Update] → Save assistant response
       ↓
  [Topic Switch Detection] → Background classification
       ↓
  [Completion Event] → event: complete
       ↓
  CLIENT RECEIVES RESPONSE

  ---
  10. KEY FILES & RESPONSIBILITIES

  | File                  | Responsibility                                                         |
  |-----------------------|------------------------------------------------------------------------|
  | app.py                | Flask routes, SSE streaming, session management, event loops           |
  | paixueji_assistant.py | Session state, client initialization, prompt retrieval, classification |
  | paixueji_stream.py    | Async streaming logic, Gemini API calls, response parsing              |
  | paixueji_prompts.py   | Prompt templates (system, intro, question, completion, tone, focus)    |
  | schema.py             | Pydantic models (StreamChunk, TokenUsage, etc.)                        |
  | config.json           | Gemini configuration (project, location, model, temperature)           |
  | age_prompts.json      | Age-based guidance (3-4, 5-6, 7-8)                                     |
  | object_prompts.json   | Category hierarchy & prompts (level1/2/3)                              |

  ---