# Paixueji System Architecture

> **Learning by Asking** - An AI-powered educational conversation system for children ages 3-8

## Table of Contents
1. [System Overview](#system-overview)
2. [User Interaction Flows](#user-interaction-flows)
3. [Focus Modes & Decision Logic](#focus-modes--decision-logic)
4. [State Management](#state-management)
5. [AI Decision Points](#ai-decision-points)
6. [Technical Architecture](#technical-architecture)
7. [Extension Guide](#extension-guide)

---

## System Overview

### What is Paixueji?

Paixueji is an interactive educational system where an AI assistant asks questions about everyday objects to help children (ages 3-8) develop observation and critical thinking skills. Unlike traditional Q&A systems where users ask questions, **the AI asks and the child answers**.

### Core Capabilities

- **Age-Adaptive Questioning**: Adjusts question complexity (WHAT/HOW/WHY) based on child's age
- **Focus Mode Strategies**: Four exploration strategies (depth, width by color/shape/category)
- **Dynamic Topic Switching**: Seamlessly transitions to new objects children mention
- **Real-Time Streaming**: SSE-based streaming for natural conversation flow
- **Multi-Layer Prompting**: Sophisticated prompt composition for context-aware responses

### Technology Stack

```mermaid
graph LR
    A[React/HTML Frontend] -->|SSE| B[Flask Backend]
    B -->|Async Streaming| C[Gemini 2.0 API]
    B --> D[In-Memory Sessions]
    C -->|JSON Mode| E[Classification Service]

    style A fill:#e1f5ff
    style B fill:#fff4e1
    style C fill:#f0f0f0
    style D fill:#ffe1e1
    style E fill:#e1ffe1
```

**Key Components:**
- **Frontend**: Vanilla JS with SSE event handling
- **Backend**: Flask with async/await streaming
- **AI**: Google Gemini 2.0 (VertexAI)
- **State**: In-memory session storage (Redis-ready)

---

## User Interaction Flows

### 1. Starting a Conversation

```mermaid
sequenceDiagram
    participant U as User (Child)
    participant F as Frontend
    participant B as Backend (Flask)
    participant A as AI (Gemini)

    U->>F: Enters object name + settings<br/>(age, focus mode, tone)
    F->>B: POST /api/start
    activate B
    B->>B: Create session ID
    B->>B: Initialize PaixuejiAssistant
    B->>B: Build multi-layer system prompt<br/>(age + tone + category + focus)
    B->>A: Stream request (Introduction)
    activate A
    A-->>B: Stream chunks
    B-->>F: SSE: chunk events
    F-->>U: Display streaming text
    deactivate A
    B->>B: Save conversation history
    B-->>F: SSE: complete event
    deactivate B
    F->>F: Enable input field
```

**What Happens:**
1. User fills out form (object name, age, focus mode, tone)
2. Backend validates input and creates unique session
3. System builds context-aware prompts from 5 layers:
   - Base system instructions
   - Age-specific guidance (3-4 / 5-6 / 7-8)
   - Tone style (friendly, excited, teacher, etc.)
   - Category context (if object classified)
   - Focus strategy (depth or width exploration)
4. AI generates first question using streaming
5. Conversation begins!

### 2. Continuing the Conversation

```mermaid
sequenceDiagram
    participant U as User (Child)
    participant F as Frontend
    participant B as Backend (Flask)
    participant D as Decision Engine
    participant A as AI (Gemini)
    participant C as Classifier

    U->>F: Types answer
    F->>B: POST /api/continue<br/>{session_id, child_input}
    activate B
    B->>B: Retrieve session state
    B->>B: Validate answer quality<br/>(is_answer_reasonable)

    alt Answer is reasonable
        B->>B: Increment correct_count
        B->>D: decide_topic_switch()
        activate D
        D->>A: JSON mode: analyze answer
        A-->>D: {decision: SWITCH/CONTINUE,<br/>new_object: "...", reasoning: "..."}
        deactivate D

        alt Decision = SWITCH
            B->>B: Update object_name
            B->>C: classify_object_sync(new_object)
            activate C
            C->>A: Classify into categories
            A-->>C: level2_category
            C->>B: Update categories
            deactivate C
            B->>B: Rebuild prompts
            B->>A: Stream with topic_switch_prompt
        else Decision = CONTINUE
            B->>A: Stream with question_prompt
        end
    else Answer is unreasonable ("I don't know")
        B->>B: Keep correct_count same
        B->>A: Stream with explanation_prompt
    end

    activate A
    A-->>B: Stream chunks
    B-->>F: SSE: chunk events
    F-->>U: Display streaming response
    deactivate A
    B->>B: Append to conversation history
    B-->>F: SSE: complete event
    deactivate B
```

**Key Decision Points:**
1. **Answer Validation**: Is the child's answer reasonable?
   - ✅ Reasonable → Celebrate + Continue
   - ❌ Unreasonable → Explain + Teach
2. **Topic Switch Detection**: Did child mention a new object?
   - Uses structured JSON output (100% reliable)
   - Classifies new object in background (1s timeout)
3. **Response Type Selection**:
   - Follow-up question (normal flow)
   - Topic switch celebration (new object)
   - Explanation + example (child stuck)

### 3. Topic Switching Scenarios

```mermaid
graph TD
    Start[Child gives answer] --> Valid{Answer<br/>reasonable?}

    Valid -->|No| Explain[Stream explanation_prompt<br/>Teach concept + Continue]

    Valid -->|Yes| Decision[decide_topic_switch<br/>Structured JSON call]

    Decision --> Analyze{Analyze focus mode<br/>+ child's answer}

    Analyze -->|DEPTH mode| DepthCheck{Mentioned<br/>different object?}
    DepthCheck -->|No| Continue[CONTINUE on same object]
    DepthCheck -->|Yes| Switch

    Analyze -->|WIDTH_COLOR| ColorCheck{Named object<br/>with same color?}
    ColorCheck -->|Yes| Switch[SWITCH to new object]
    ColorCheck -->|No| Continue

    Analyze -->|WIDTH_SHAPE| ShapeCheck{Named object<br/>with same shape?}
    ShapeCheck -->|Yes| Switch
    ShapeCheck -->|No| Continue

    Analyze -->|WIDTH_CATEGORY| CategoryCheck{Named object<br/>in same category?}
    CategoryCheck -->|Yes| Switch
    CategoryCheck -->|No| Continue

    Switch --> Classify[classify_object_sync<br/>Update categories]
    Classify --> Rebuild[Rebuild category_prompt<br/>+ focus_prompt]
    Rebuild --> StreamSwitch[Stream topic_switch_prompt<br/>Celebrate + Ask about new object]

    Continue --> StreamNormal[Stream question_prompt<br/>Continue with same object]

    Explain --> End[Complete turn]
    StreamSwitch --> End
    StreamNormal --> End

    style Start fill:#e1f5ff
    style Switch fill:#ffe1e1
    style Continue fill:#e1ffe1
    style Explain fill:#fff4e1
    style End fill:#f0f0f0
```

---

## Focus Modes & AI-Driven Topic Switching

### Focus Mode vs Switching Logic (Separation of Concerns)

**Focus modes** and **topic switching** are now **decoupled**:

| Concern | What It Controls | Examples |
|---------|------------------|----------|
| **Focus Mode** | Question style (HOW to ask) | DEPTH: "What are the parts?", WIDTH_COLOR: "What else is red?" |
| **Topic Switching** | When to switch topics (WHEN to switch) | AI analyzes conversation context, not hardcoded rules |

### Focus Mode Strategies

Each focus mode defines **question style only** (not switching behavior):

| Focus Mode | Question Style | Example Questions |
|------------|----------------|-------------------|
| **depth** | Deep dive into current object | "What are its parts?", "How does it work?", "What is it made of?" |
| **width_color** | Explore objects by shared color | "What else is red?", "Can you name another yellow thing?" |
| **width_shape** | Explore objects by shared shape | "What else is round?", "Can you think of something long like this?" |
| **width_category** | Explore objects in same category | "What other fruits do you know?", "Name another animal!" |

### AI-Driven Topic Switching (No Hardcoded Rules!)

Instead of rigid rules, the AI analyzes **conversation context** to decide when to switch:

#### Context Provided to AI:
1. **Last model question** - What did the model just ask?
2. **Child's answer** - How did the child respond?
3. **Current object** - What are we discussing?
4. **Focus mode** - For informational context only

#### Decision Guidelines (Not Rules):
1. **Invited Object Naming**: If AI asked child to name new object and they did → SWITCH
2. **Off-Topic Response**: If child answered with different object instead of answering question → SWITCH
3. **Explicit Request**: If child says "let's talk about X" → SWITCH
4. **Comparison Mention**: If child mentions object in passing ("red like cherry") → CONTINUE
5. **Normal Answer**: If child answered the question → CONTINUE
6. **Stuck/Uncertain**: If child says "I don't know" → CONTINUE

#### Example Decision Scenarios:

| Last Question | Child Answer | AI Decision | Reasoning |
|--------------|--------------|-------------|-----------|
| "What color is the apple?" | "red" | **CONTINUE** | Direct answer, no topic change |
| "Can you name another red fruit?" | "strawberry" | **SWITCH** | Invited naming, child responded |
| "What shape is it?" | "banana" | **SWITCH** | Off-topic, child wants to discuss banana |
| "What does it taste like?" | "sweet like candy" | **CONTINUE** | Comparison, not topic change request |
| "Where do apples grow?" | "Can we talk about dogs?" | **SWITCH** | Explicit request |

### Decision Algorithm (Contextual + Structured Output)

```mermaid
flowchart TD
    Input[Child's Answer] --> Extract[Extract last model question<br/>from conversation history]
    Extract --> Build[Build contextual decision prompt:<br/>- What was asked?<br/>- What was answered?<br/>- Current object<br/>- Focus mode context]
    Build --> Call[Call Gemini with<br/>JSON mode enabled]
    Call --> Parse[Parse structured output]

    Parse --> Output{{"JSON Output:<br/>decision, new_object, reasoning"}}

    Output --> Log[Log decision + reasoning]

    Log --> Route{decision?}
    Route -->|SWITCH| Action1[1. Update object_name<br/>2. Classify new object<br/>3. Rebuild prompts<br/>4. Use topic_switch_prompt]
    Route -->|CONTINUE| Action2[1. Keep object_name<br/>2. Use question_prompt<br/>3. If object detected: offer manual override]

    Action1 --> Return[Return to stream generation]
    Action2 --> Return

    style Input fill:#e1f5ff
    style Extract fill:#fff4e1
    style Output fill:#e1ffe1
    style Action1 fill:#ffe1e1
    style Action2 fill:#d1fae5
```

**Why AI-Driven (Not Hardcoded)?**
- ✅ **Natural**: Mimics how human teachers decide
- ✅ **Context-Aware**: Considers what was asked vs what was answered
- ✅ **Flexible**: Handles edge cases and nuanced scenarios
- ✅ **Transparent**: AI explains every decision
- ✅ **Fast**: Same ~100-200ms latency (1 API call)
- ✅ **User Control**: Manual override available

### Manual Override Feature

When AI detects an object but decides to CONTINUE, users can override:

**UI Panel Appears When:**
- AI detected object in child's answer (e.g., "cherry")
- AI decided to CONTINUE (e.g., "Mentioned as comparison, not topic change")

**User Options:**
1. **Switch to [detected_object]** - Force topic change
2. **Stay on current topic** - Dismiss panel and continue

**Backend Flow:**
1. Frontend calls `/api/force-switch` with detected object
2. Backend updates `assistant.object_name`
3. Backend classifies new object (1s timeout)
4. System message appears: "✨ Switched to cherry!"

### Focus Prompt Examples (Updated)

**Depth Mode:**
```
Focus Strategy: DEPTH.
Ask detailed questions about {object_name}'s specific features,
parts, materials, texture, uses, and functionality.
Dive deep into this one object.
```
*(Note: No switching instructions - that's handled by AI context)*

**Width Color Mode:**
```
Focus Strategy: WIDTH - COLOR.
Ask the child to think of OTHER objects that are the same COLOR as {object_name}.
Example: 'What else is red like an apple?' or 'Can you name something else that's yellow?'
```
*(Note: Questions invite new objects, but AI decides whether to switch based on context)*

---

## State Management

### Session State Architecture

```mermaid
classDiagram
    class Session {
        +string session_id
        +PaixuejiAssistant assistant
    }

    class PaixuejiAssistant {
        +int age
        +string object_name
        +string level1_category
        +string level2_category
        +string level3_category
        +string tone
        +int correct_answer_count
        +list conversation_history
        +Client client
        +dict config

        +get_age_prompt(age)
        +get_category_prompt(l1, l2, l3)
        +get_focus_prompt(focus_mode)
        +get_tone_prompt(tone)
        +increment_correct_answers()
        +classify_object_sync(object_name)
    }

    class ConversationHistory {
        +string role
        +string content
    }

    Session "1" --> "1" PaixuejiAssistant
    PaixuejiAssistant "1" --> "*" ConversationHistory

    note for Session "Stored in Flask sessions dict\n(In-memory, lost on restart)"
    note for PaixuejiAssistant "Holds all conversation state\nand Gemini client instance"
    note for ConversationHistory "OpenAI-style message format\nConverted to Gemini format on API calls"
```

### State Transitions

```mermaid
stateDiagram-v2
    [*] --> SessionCreated: POST /api/start

    SessionCreated --> AskingIntroduction: Build prompts
    AskingIntroduction --> WaitingForAnswer: Stream first question

    WaitingForAnswer --> ValidateAnswer: POST /api/continue

    ValidateAnswer --> CelebrateAnswer: Answer reasonable
    ValidateAnswer --> ExplainConcept: Answer unreasonable

    CelebrateAnswer --> DecideTopicSwitch: Run decision engine

    DecideTopicSwitch --> SwitchTopic: decision = SWITCH
    DecideTopicSwitch --> ContinueSameObject: decision = CONTINUE

    SwitchTopic --> ClassifyNewObject: Update object_name
    ClassifyNewObject --> AskAboutNewObject: Rebuild prompts

    ContinueSameObject --> AskFollowUp: Use same prompts
    ExplainConcept --> AskFollowUp: Teach + continue
    AskAboutNewObject --> WaitingForAnswer: Stream response
    AskFollowUp --> WaitingForAnswer: Stream response

    WaitingForAnswer --> SessionDeleted: POST /api/reset
    SessionDeleted --> [*]

    note right of ClassifyNewObject
        Runs in background with 1s timeout
        Updates level1/level2 categories
        Rebuilds category_prompt
    end note
```

### Conversation History Format

**Storage Format (OpenAI-style):**
```python
conversation_history = [
    {"role": "system", "content": "Complete system prompt with all layers..."},
    {"role": "user", "content": "Start conversation about apple"},
    {"role": "assistant", "content": "Hi! Let's learn about apples! What color is the apple?"},
    {"role": "user", "content": "Red"},
    {"role": "assistant", "content": "Yes! Apples can be red! What shape is the apple?"}
]
```

**Converted to Gemini Format:**
```python
system_instruction = "Complete system prompt with all layers..."
contents = [
    {"role": "user", "parts": [{"text": "Start conversation about apple"}]},
    {"role": "model", "parts": [{"text": "Hi! Let's learn about apples! What color is the apple?"}]},
    {"role": "user", "parts": [{"text": "Red"}]},
    {"role": "model", "parts": [{"text": "Yes! Apples can be red! What shape is the apple?"}]}
]
```

---

## AI Decision Points

### 1. Answer Validation

**Function:** `is_answer_reasonable(child_answer: str) -> bool`

**Logic:**
```mermaid
flowchart TD
    Input[Child's Answer] --> Length{Length > 3<br/>characters?}
    Length -->|No| Unreasonable[Return False]
    Length -->|Yes| Stuck{Contains stuck<br/>phrases?}

    Stuck -->|Yes: I don't know<br/>idk, dunno| Unreasonable
    Stuck -->|No| Letters{Has 2+<br/>letters?}

    Letters -->|No| Unreasonable
    Letters -->|Yes| Reasonable[Return True]

    Unreasonable --> Route1[Route to<br/>explanation_prompt]
    Reasonable --> Route2[Route to<br/>followup_prompt]

    style Reasonable fill:#e1ffe1
    style Unreasonable fill:#ffe1e1
```

**Purpose:** Decide between celebrating answer vs. providing help

**Example Classifications:**
- ✅ "red" → Reasonable
- ✅ "it's round and smooth" → Reasonable
- ❌ "idk" → Unreasonable
- ❌ "???" → Unreasonable (too short)
- ❌ "I don't know" → Unreasonable

### 2. Topic Switch Detection

**Function:** `decide_topic_switch(assistant, child_answer, focus_mode, object_name, correct_count, age) -> dict`

**Structured Output Schema:**
```json
{
  "decision": "SWITCH" | "CONTINUE",
  "new_object": "ObjectName" | null,
  "reasoning": "Brief explanation"
}
```

**Decision Rules by Focus Mode:**

```mermaid
graph TD
    Start[Analyze child's answer] --> Mode{Focus Mode?}

    Mode -->|depth| Rule1["Only SWITCH if child<br/>explicitly names<br/>DIFFERENT object"]
    Mode -->|width_color| Rule2["SWITCH if child names<br/>object with SAME color"]
    Mode -->|width_shape| Rule3["SWITCH if child names<br/>object with SAME shape"]
    Mode -->|width_category| Rule4["SWITCH if child names<br/>object in SAME category"]

    Rule1 --> Valid1{Valid new<br/>object?}
    Rule2 --> Valid2{Valid object<br/>+ correct color?}
    Rule3 --> Valid3{Valid object<br/>+ correct shape?}
    Rule4 --> Valid4{Valid object<br/>+ correct category?}

    Valid1 -->|Yes| Switch[decision: SWITCH<br/>new_object: ...]
    Valid1 -->|No| Continue[decision: CONTINUE<br/>new_object: null]

    Valid2 -->|Yes| Switch
    Valid2 -->|No| Continue

    Valid3 -->|Yes| Switch
    Valid3 -->|No| Continue

    Valid4 -->|Yes| Switch
    Valid4 -->|No| Continue

    style Switch fill:#ffe1e1
    style Continue fill:#e1ffe1
```

**API Call Parameters:**
```python
response = client.models.generate_content(
    model="gemini-2.0-flash-exp",
    contents=decision_prompt,
    config={
        "response_mime_type": "application/json",  # Force JSON
        "temperature": 0.1,  # Low temp for consistency
        "max_output_tokens": 100
    }
)
```

**Latency:** ~100-200ms per decision

### 3. Object Classification

**Function:** `classify_object_sync(object_name: str)`

**Purpose:** Determine object's category for context-aware questions

```mermaid
sequenceDiagram
    participant TS as Topic Switch Decision
    participant M as Main Thread
    participant BG as Background Thread (1s timeout)
    participant AI as Gemini API

    TS->>M: new_object detected
    M->>BG: Start classification thread
    activate BG
    BG->>AI: Generate classification prompt<br/>with all level2 categories
    AI-->>BG: Response: "fresh_ingredients"
    BG->>BG: Validate against categories
    BG->>BG: Update level2_category<br/>Derive level1_category
    BG->>M: Classification complete
    deactivate BG

    alt Timeout after 1s
        BG--xM: Timeout
        M->>M: Continue with categories=None
    end

    M->>M: Rebuild category_prompt<br/>with new categories
```

**Classification Prompt:**
```
Classify the object "{object_name}" into ONE of these categories:
- fresh_ingredients: Fresh fruits, vegetables, raw ingredients
- prepared_foods: Cooked dishes, packaged snacks
- ...

Respond with ONLY the category key, or "none" if it doesn't fit.
```

**Category Hierarchy:**
```
level1_category (broad)
  └─ level2_category (specific)
      └─ level3_category (very specific, optional)

Example:
foods
  └─ fresh_ingredients
      └─ tropical_fruits
```

**After Classification:**
- Updates `assistant.level1_category`, `level2_category`, `level3_category`
- Rebuilds `category_prompt` for next question
- Influences question topics (e.g., "taste" for foods, "sound" for animals)

---

## Technical Architecture

### API Endpoints

```mermaid
graph LR
    A[Client] -->|POST /api/start| B[Start Conversation]
    A -->|POST /api/continue| C[Continue Conversation]
    A -->|POST /api/reset| D[Delete Session]
    A -->|POST /api/force-switch| H[Force Topic Switch]
    A -->|GET /api/sessions| E[List Sessions]
    A -->|POST /api/classify| F[Classify Object]
    A -->|GET /api/health| G[Health Check]

    B -->|SSE Stream| A
    C -->|SSE Stream| A
    D -->|JSON| A
    H -->|JSON| A
    E -->|JSON| A
    F -->|JSON| A
    G -->|JSON| A

    style B fill:#e1f5ff
    style C fill:#e1f5ff
    style H fill:#fbbf24
```

### Request/Response Contracts

#### POST /api/start

**Request:**
```json
{
  "age": 6,
  "object_name": "apple",
  "level1_category": "foods",
  "level2_category": "fresh_ingredients",
  "level3_category": null,
  "tone": "friendly",
  "focus_mode": "depth"
}
```

**Response (SSE Stream):**
```
event: chunk
data: {"response":"Hi","session_finished":false,"duration":0.0,"token_usage":null,"finish":false,"sequence_number":1,"timestamp":1234567890.123,"session_id":"...","request_id":"...","correct_answer_count":0,"conversation_complete":false,"focus_mode":"depth","is_correct":null,"new_object_name":null}

event: chunk
data: {"response":"! Let's","session_finished":false,...}

event: chunk
data: {"response":" learn about apples!","session_finished":false,...}

event: complete
data: {"success":true}
```

#### POST /api/continue

**Request:**
```json
{
  "session_id": "uuid-from-start",
  "child_input": "It's red and round",
  "focus_mode": "depth"
}
```

**Response:** Same SSE format as `/api/start`, with additional fields:
- `new_object_name`: Set if topic switch detected
- `detected_object_name`: Set if object detected but AI didn't switch
- `switch_decision_reasoning`: AI's explanation for the decision

#### POST /api/force-switch

**Purpose:** Manually override AI's decision and force a topic switch

**Request:**
```json
{
  "session_id": "uuid-from-start",
  "new_object": "cherry"
}
```

**Response:**
```json
{
  "success": true,
  "previous_object": "apple",
  "new_object": "cherry",
  "message": "Switched to cherry"
}
```

**Use Case:**
- AI detected "cherry" in child's answer but decided to CONTINUE
- UI shows manual override panel with detected object
- User clicks "Switch to cherry" button
- This endpoint updates session state and classifies new object

**Error Response:**
```json
{
  "success": false,
  "error": "Session not found"
}
```

### StreamChunk Schema

```python
class StreamChunk(BaseModel):
    response: str                          # Text to display
    session_finished: bool                 # Session ended?
    duration: float                        # Total time (only in final chunk)
    token_usage: TokenUsage | None         # Token counts (only in final chunk)
    finish: bool                           # Is this final chunk?
    sequence_number: int                   # Chunk order
    timestamp: float                       # Unix timestamp
    session_id: str                        # Session UUID
    request_id: str                        # Request UUID
    correct_answer_count: int              # Progress tracking
    conversation_complete: bool            # Always False (infinite mode)
    focus_mode: str | None                 # Current focus mode
    is_correct: bool | None                # Answer validation feedback
    new_object_name: str | None            # New object if topic switched
    detected_object_name: str | None       # Object AI detected but didn't switch to (for manual override)
    switch_decision_reasoning: str | None  # AI's explanation for switch/continue decision
```

**New Fields for AI-Driven Switching:**
- `detected_object_name`: Set when AI detects an object in child's answer but decides to CONTINUE
  - Triggers manual override UI panel
  - Example: Child says "red like cherry", AI continues but detects "cherry"
- `switch_decision_reasoning`: AI's explanation for every decision
  - Example: "Child directly answered the question about color. No topic change needed."
  - Logged and displayed in override panel

### Streaming Architecture

```mermaid
sequenceDiagram
    participant Flask as Flask Thread
    participant EventLoop as Asyncio Event Loop
    participant Queue as Queue
    participant BG as Background Thread
    participant Gemini as Gemini API

    Flask->>EventLoop: Create new event loop
    Flask->>Queue: Create Queue()
    Flask->>BG: Start background thread
    activate BG

    BG->>EventLoop: loop.run_until_complete()
    EventLoop->>Gemini: generate_content_stream()
    activate Gemini

    loop For each chunk
        Gemini-->>EventLoop: yield chunk
        EventLoop->>Queue: queue.put(chunk)
        Queue-->>Flask: queue.get() [blocking]
        Flask-->>Flask: Yield SSE event
    end

    Gemini-->>EventLoop: Stream complete
    deactivate Gemini
    EventLoop->>Queue: queue.put(DONE)
    deactivate BG

    Queue-->>Flask: DONE signal
    Flask-->>Flask: Close SSE stream
```

**Why This Architecture?**
- Flask requires sync generators for SSE
- Gemini API is async-only
- Queue bridges async → sync without buffering
- Each request gets isolated event loop (prevents race conditions)

### Prompt Composition System

**5-Layer Architecture:**

```mermaid
flowchart TD
    Start[New Turn] --> Layer1[Layer 1: Base System Prompt<br/>Role + Core principles]

    Layer1 --> Layer2[Layer 2: Age Guidance<br/>Question types + Vocabulary]

    Layer2 --> Layer3[Layer 3: Tone Style<br/>Communication personality]

    Layer3 --> Layer4[Layer 4: Category Context<br/>Domain-specific focus]

    Layer4 --> Layer5[Layer 5: Focus Strategy<br/>Exploration mode]

    Layer5 --> Combine[Combine into<br/>system_instruction]

    Combine --> TurnPrompt[Add turn-specific prompt<br/>as user message]

    TurnPrompt --> Types{Turn Type?}

    Types -->|First turn| Intro[INTRODUCTION_PROMPT<br/>Greet + Ask first question]
    Types -->|Answer reasonable| Follow[QUESTION_PROMPT<br/>Celebrate + Follow-up]
    Types -->|Answer unreasonable| Explain[EXPLANATION_PROMPT<br/>Teach + Continue]
    Types -->|Topic switched| Switch[TOPIC_SWITCH_PROMPT<br/>Celebrate switch + Ask about new object]

    Intro --> Send[Send to Gemini API]
    Follow --> Send
    Explain --> Send
    Switch --> Send

    style Layer1 fill:#e1f5ff
    style Layer2 fill:#fff4e1
    style Layer3 fill:#ffe1e1
    style Layer4 fill:#e1ffe1
    style Layer5 fill:#f0f0f0
```

**Example Composition:**

```python
# Layer 1: Base
base = "You are a curious and encouraging learning companion..."

# Layer 2: Age (6 years old)
age_prompt = "Use WHAT and HOW questions. Keep sentences 5-8 words."

# Layer 3: Tone (friendly)
tone_prompt = "Use warm, encouraging language. Gentle and supportive."

# Layer 4: Category (fresh_ingredients)
category_prompt = "Ask about taste, texture, where grown, how eaten."

# Layer 5: Focus (width_color)
focus_prompt = "Ask child to think of OTHER objects with the same color."

# Final system instruction
system_instruction = f"{base}\n\nAGE GUIDANCE:\n{age_prompt}\n\nTONE:\n{tone_prompt}\n\nCATEGORY:\n{category_prompt}"

# Turn-specific prompt (added as user message)
turn_prompt = f"Child answered: 'red'. FOCUS STRATEGY: {focus_prompt}. Ask follow-up."
```

### Data Flow Summary

```mermaid
graph TD
    U[User Input] --> V[Validate Request]
    V --> S[Get/Create Session]
    S --> P[Build Prompts<br/>5-layer composition]
    P --> H[Update History]
    H --> R{Route by<br/>turn type}

    R -->|First turn| I[ask_introduction_question_stream]
    R -->|Answer reasonable| F[ask_followup_question_stream]
    R -->|Answer unreasonable| E[ask_explanation_question_stream]

    F --> D[decide_topic_switch]
    D -->|SWITCH| TS[Topic Switch Flow]
    D -->|CONTINUE| N[Normal Follow-up]

    TS --> CL[classify_object_sync]
    CL --> RP[Rebuild Prompts]
    RP --> G[Generate with Gemini]

    I --> G
    E --> G
    N --> G

    G --> ST[Stream Chunks]
    ST --> PA[Parse & Clean]
    PA --> SSE[Send SSE Events]
    SSE --> UP[Update History]
    UP --> Done[Complete Turn]

    style TS fill:#ffe1e1
    style CL fill:#fff4e1
```

---

## Extension Guide

### Adding a New Focus Mode

**Example: Add "width_function" mode (explore objects by what they do)**

1. **Define focus prompt** in `paixueji_prompts.py`:
```python
FOCUS_PROMPTS = {
    # ... existing modes
    "width_function": """
    Functional exploration starting from {object_name}:
    - Ask child to think of OTHER objects that do a SIMILAR thing
    - Example: hammer → "What else can you use to build things?"
    - If child names a valid object with related function → SWITCH to it
    - Celebrate functional connections!
    """
}
```

2. **Update decision rules** in `decide_topic_switch()`:
```python
# In paixueji_stream.py, line ~276
decision_prompt = f"""
...
DECISION RULES:
...
5. **WIDTH_FUNCTION mode**: SWITCH if child names ANY real object with SIMILAR FUNCTION
...
"""
```

3. **Add to frontend** `static/index.html`:
```html
<select id="nextQuestionFocus">
    <!-- ... existing options -->
    <option value="width_function">Width: Function (explore by what objects do)</option>
</select>
```

4. **Test the flow:**
```
Object: Hammer (width_function mode)
Q: "What does a hammer do?"
A: "It builds things"
Q: "Great! What else can you use to build things?"
A: "Screwdriver"
→ SWITCH to Screwdriver
```

### Adding a New Age Group

**Example: Add age 9-10 support**

1. **Add age prompts** in `age_prompts.json`:
```json
{
  "age_groups": {
    "9-10": {
      "prompt": "Use advanced WHY and complex HOW questions. Encourage critical thinking and comparison. Can use 12-15 word sentences with more complex vocabulary.",
      "question_types": ["WHAT", "HOW", "WHY", "COMPARE"],
      "example_questions": [
        "Why do you think this object was designed this way?",
        "How does this compare to similar objects you know?"
      ]
    }
  }
}
```

2. **Update age validation** in `paixueji_assistant.py`:
```python
def get_age_prompt(self, age):
    # ... existing code
    elif 9 <= age <= 10:
        return age_groups.get('9-10', {}).get('prompt', '')
```

3. **Update frontend range** in `static/index.html`:
```html
<input type="number" id="age" min="3" max="10" value="6">
```

### Adding Custom Categories

**Example: Add "vehicles" category with subcategories**

1. **Add to** `object_prompts.json`:
```json
{
  "level1_categories": {
    "vehicles": {
      "prompt": "Ask about how it moves, what it's used for, parts it has."
    }
  },
  "level2_categories": {
    "land_vehicles": {
      "parent": "vehicles",
      "prompt": "Ask about wheels, speed, where it drives, who uses it."
    },
    "air_vehicles": {
      "parent": "vehicles",
      "prompt": "Ask about wings, how it flies, where it goes, who pilots it."
    }
  }
}
```

2. **Update classification prompt** in `paixueji_prompts.py`:
```python
CLASSIFICATION_PROMPT = """
...
Available categories:
{categories_list}

Include the new categories in your classification logic.
"""
```

3. **Test classification:**
```python
# POST /api/classify
{
  "object_name": "airplane"
}

# Response:
{
  "level1_category": "vehicles",
  "level2_category": "air_vehicles"
}
```

### Implementing Session Persistence

**Current State:** Sessions stored in-memory (lost on restart)

**Migration to Redis:**

1. **Install Redis client:**
```bash
pip install redis
```

2. **Update** `app.py`:
```python
import redis
import pickle

# Replace in-memory dict
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=False)

# Store session
def save_session(session_id, assistant):
    redis_client.setex(
        f"session:{session_id}",
        3600,  # 1 hour TTL
        pickle.dumps(assistant)
    )

# Retrieve session
def get_session(session_id):
    data = redis_client.get(f"session:{session_id}")
    if data:
        return pickle.loads(data)
    return None
```

3. **Update endpoints:**
```python
@app.route('/api/start', methods=['POST'])
def start_conversation():
    # ... existing code
    assistant = PaixuejiAssistant()
    save_session(session_id, assistant)  # Changed

@app.route('/api/continue', methods=['POST'])
def continue_conversation():
    # ... existing code
    assistant = get_session(session_id)  # Changed
    if not assistant:
        return jsonify({"error": "Session expired"}), 404
```

### Adding Analytics & Logging

**Track conversation metrics:**

1. **Define metrics schema:**
```python
class ConversationMetrics(BaseModel):
    session_id: str
    total_turns: int
    correct_answers: int
    topic_switches: int
    focus_modes_used: list[str]
    objects_discussed: list[str]
    average_response_time: float
    completion_time: float
```

2. **Track in assistant:**
```python
class PaixuejiAssistant:
    def __init__(self):
        # ... existing code
        self.metrics = {
            "turns": 0,
            "switches": 0,
            "objects": [],
            "response_times": []
        }

    def track_turn(self, response_time):
        self.metrics["turns"] += 1
        self.metrics["response_times"].append(response_time)

    def track_switch(self, new_object):
        self.metrics["switches"] += 1
        self.metrics["objects"].append(new_object)
```

3. **Export on session end:**
```python
@app.route('/api/metrics/<session_id>', methods=['GET'])
def get_metrics(session_id):
    assistant = sessions.get(session_id)
    if not assistant:
        return jsonify({"error": "Session not found"}), 404

    return jsonify({
        "session_id": session_id,
        "metrics": assistant.metrics
    })
```

---

## Appendix: Key Files Reference

| File | Purpose | Key Functions |
|------|---------|---------------|
| `app.py` | Flask server, routes, SSE streaming | `start_conversation()`, `continue_conversation()`, `force_switch()`, `async_gen_to_sync()` |
| `paixueji_assistant.py` | Session state, client management | `get_age_prompt()`, `get_focus_prompt()`, `classify_object_sync()` |
| `paixueji_stream.py` | Streaming logic, AI calls | `ask_introduction_question_stream()`, `ask_followup_question_stream()`, `decide_topic_switch()` |
| `paixueji_prompts.py` | Prompt templates | `SYSTEM_PROMPT`, `QUESTION_PROMPT`, `EXPLANATION_PROMPT`, `FOCUS_PROMPTS` |
| `schema.py` | Pydantic models | `StreamChunk`, `TokenUsage` |
| `static/app.js` | Frontend SSE handling | `startConversation()`, `continueConversation()`, `forceSwitch()`, `dismissSwitchPanel()` |

---

## Version 2.0 Updates: AI-Driven Contextual Switching

### Key Architectural Changes (December 2025)

**What Changed:**
1. ✅ **Decoupled Concerns**: Focus modes now control question style ONLY, not switching behavior
2. ✅ **AI-Driven Decisions**: Topic switching uses conversation context instead of hardcoded rules
3. ✅ **Manual Override**: New UI panel allows users to override AI decisions
4. ✅ **Transparency**: AI explains every decision with reasoning

**Migration from v1.0:**
- **Removed**: Hardcoded switching rules in `FOCUS_PROMPTS` (e.g., "Only SWITCH if...")
- **Added**: Contextual decision prompt with last question + answer analysis
- **Added**: `/api/force-switch` endpoint for manual topic changes
- **Added**: `detected_object_name` and `switch_decision_reasoning` fields to `StreamChunk`

**Performance Impact:**
- ⚡ **Zero additional latency** - Same 1 API call, smarter prompt
- ✅ Decision time: ~100-200ms (unchanged)
- ✅ Same streaming performance

**Benefits:**
- 🎯 Natural conversation flow (mimics human teachers)
- 🧠 Context-aware decisions (what was asked vs answered)
- 🔧 User control (manual override when needed)
- 📊 Full transparency (AI explains every decision)
- 🚀 Handles edge cases better (no rigid rules)

---

**Document Version:** 2.0
**Last Updated:** 2025-12-31
**Major Update:** AI-Driven Contextual Topic Switching
**Maintained By:** Development Team

For questions or updates to this architecture, please update this document and commit changes to the repository.
