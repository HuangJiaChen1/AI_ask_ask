# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Child Learning Assistant (Gemini Version)** is an educational chatbot for young children (ages 3-8) that uses the Gemini AI model to generate age-appropriate questions about everyday objects. The assistant encourages curiosity and learning through interactive conversations.

This is a **Gemini-powered port** of the original Qwen-based implementation. All core logic, prompts, and architecture remain unchanged - only the LLM API integration has been modified.

## Key Features

- **Age-Adaptive Learning**: Automatically adjusts question complexity based on child's age (3-4: "what", 5-6: "what+how", 7-8: "what+how+why")
- **Category-Aware Prompting**: Specialized prompts for 9 object categories across Foods/Animals/Plants
- **State Machine with Hint System**: 7-state conversation flow with intelligent stuck detection and progressive hints
- **Mastery Tracking**: Celebrates achievement when child answers 4 questions correctly
- **Session Persistence**: SQLite database for conversation continuity across server restarts
- **LLM-Based Classification**: Automatic object categorization using Gemini API

## Development Commands

### Setup
```bash
pip install -r requirements.txt
# Edit config.json and set your Gemini API key
```

### Running the Application
```bash
# Interactive CLI demo
python demo.py

# Flask API server (port 5001)
python app.py

# Web interface (requires app.py running)
# Open browser to http://localhost:5001
```

### Testing
```bash
# State machine tests
python test_state_machine.py

# Stuck detection tests
python test_stuck_detection.py

# API integration tests (requires app.py running)
python test_api.py
```

## Architecture

### Core Components

**1. ChildLearningAssistant** (`child_learning_assistant.py`)
- Main conversation engine using Gemini API via `requests` library
- Implements ConversationState enum with 7 states:
  - `INITIAL_QUESTION`: Starting state
  - `AWAITING_ANSWER`: Waiting for child's response
  - `GIVING_HINT_1`: First progressive hint
  - `GIVING_HINT_2`: Stronger progressive hint
  - `REVEALING_ANSWER`: Reveals answer after 3 "I don't know"s
  - `RECONNECTING`: Bridges hint answer back to original question
  - `CELEBRATING`: Positive reinforcement after correct answer
  - `MASTERY_ACHIEVED`: Child reached 4 correct answers

**2. Prompt System** (`prompts.py`, `age_prompts.json`, `category_prompts.json`)
- Hardcoded base prompts in `prompts.py` (system, user, hints, reveal, state instructions)
- Age-specific guidance in `age_prompts.json` (3-4, 5-6, 7-8 year groups)
- Category-specific guidance in `category_prompts.json` (Level 1: Foods/Animals/Plants, Level 2: 9 subcategories)
- **Prompt Construction**: System prompt = base + age guidance + category guidance

**3. Flask API** (`app.py`)
- RESTful endpoints for web/mobile integration
- Runs on port 5001 (not 5000)
- CORS enabled
- Endpoints:
  - `POST /api/classify`: LLM-based object classification
  - `POST /api/start`: Create new session (production or test mode)
  - `POST /api/continue`: Continue conversation
  - `GET /api/history/<session_id>`: Retrieve conversation history
  - `POST /api/reset`: Delete session
  - `GET /api/sessions`: List active sessions
  - `GET /api/health`: Health check

**4. Database Layer** (`database.py`)
- SQLite persistence for sessions (no prompts table - prompts are hardcoded)
- Sessions table stores: `session_id`, `current_object`, `current_category`, `conversation_history`, `state`, `stuck_count`, `question_count`, `correct_count`, `current_main_question`, `expected_answer`, `question_before_hint`, `answer_before_hint`
- All state machine fields are persisted for session resumption

**5. Object Classifier** (`object_classifier.py`)
- LLM-based classification into 9 Level 2 categories
- Categories: `fresh_ingredients`, `processed_foods`, `beverages_drinks`, `vertebrates`, `invertebrates`, `human_raised_animals`, `ornamental_plants`, `useful_plants`, `wild_natural_plants`
- Auto-detection of Level 1 category from Level 2

### Conversation Flow

1. **Session Start**: Client calls `/api/start` with `object_name`, `category`, optional `age`, `level2_category`
2. **Prompt Assembly**: System loads base prompts, adds age-specific guidance (if age provided), adds category-specific guidance (if categories provided)
3. **Initial Question**: LLM returns structured JSON: `{main_question, expected_answer, full_response, audio_output}`
4. **Conversation Loop**: Client calls `/api/continue` with `session_id` and child's response
5. **State Machine Update**: `_update_state()` uses LLM to detect if child is stuck, transitions between states
6. **Response Generation**: Different response strategies based on state:
   - Hints: Dedicated prompt asking a DIFFERENT, easier question with same answer
   - Reveal: Dedicated prompt to reveal answer and ask new question
   - Reconnect: Dedicated prompt to bridge hint answer back to original question
   - Normal: Structured JSON with celebration + next question
7. **Session Persistence**: After each exchange, full state saved to database

### State Machine Architecture

**Key Design Decision**: The system uses **dedicated, single-purpose prompts** for hint states instead of validation loops:

- When child is stuck → `_generate_hint_only()` with focused hint prompt
- When revealing answer → `_generate_reveal_answer()` with focused reveal prompt
- When reconnecting → `_generate_reconnect_response()` with focused reconnect prompt
- When child attempts answer → `_get_model_response_with_validation()` with structured JSON

This approach is simpler, faster (1 LLM call vs 2-5), and more reliable than multi-layer validation.

**State Transitions**:
- States can cascade (e.g., `CELEBRATING` → `AWAITING_ANSWER` → `GIVING_HINT_1` in single update)
- `stuck_count` increments when LLM detects child is stuck (via `_is_child_stuck()`)
- `stuck_count` resets to 0 when child attempts an answer

**Question Tracking**:
- `current_main_question`: The PRIMARY question being asked (extracted from JSON, not rhetorical examples)
- `expected_answer`: Answer the LLM is looking for
- `question_before_hint`: Saved when entering hint states, used for reconnecting
- `answer_before_hint`: Saved when entering hint states, used for reconnecting

### Stuck Detection

Uses LLM-based classification (`_is_child_stuck()`) instead of keyword matching:
- Prompt: "Is the child stuck/confused or attempting to answer?"
- Returns: A (stuck) or B (attempting)
- Fallback to keywords if LLM fails: "don't know", "idk", "dunno", "what", "huh", "?"

### JSON Response Structure

The LLM returns structured JSON for normal responses (when child attempts to answer):

```json
{
  "reaction": "Immediate reaction to child's answer",
  "next_question": "Next question to continue learning",
  "main_question": "Core question (not rhetorical examples)",
  "expected_answer": "Answer being looked for",
  "is_correct": true/false,
  "audio_output": "Full text without emojis for TTS"
}
```

**Why `main_question` is Critical**:
- Responses contain multiple questions (rhetorical examples like "Is it red? Blue? Green?")
- Without explicit `main_question`, hint extraction would reference wrong questions
- `main_question` is stored for hint generation to reference the correct question

### Mastery/Reward System

- `correct_count` tracks total correct answers (tracked via `is_correct` in JSON)
- `mastery_threshold` = 4 correct answers
- When threshold reached: Returns celebration message, sets `mastery_achieved=True`, deletes session
- API returns: `{correct_count, mastery_achieved, is_correct, is_neutral}` for frontend progress tracking

## Gemini API Integration

**Key Difference from Original**: Uses `requests` library instead of OpenAI Python client

```python
# API call pattern
headers = {"Authorization": f"Bearer {config['gemini_api_key']}"}
payload = {
    "model": "gemini-2.5-pro",
    "messages": messages,
    "temperature": 0.7,
    "max_tokens": 2000  # Increased for reasoning tokens
}
response = requests.post(api_base_url, headers=headers, json=payload)
```

**JSON Mode Handling**: Appends strong JSON instruction to last message instead of using `response_format` parameter

**Response Extraction**: Uses `extract_json_from_response()` to handle markdown code blocks and extra text around JSON

**Reasoning Tokens**: `max_tokens=2000` to account for Gemini's reasoning tokens (not visible but consume tokens)

## Important Implementation Notes

### API Design Patterns

1. **Session ID is Critical**: Frontend MUST store `session_id` from `/api/start` and include in all `/api/continue` calls
2. **Prompt Template Requirements**: User prompt templates MUST include `{object_name}` and `{category}` placeholders
3. **Two Prompt Modes**:
   - Production mode (default): Uses hardcoded prompts from `prompts.py`
   - Test mode (`is_test=true`): Accepts prompts in request body for A/B testing
4. **Category Auto-Detection**: If `level2_category` provided without `level1_category`, parent is auto-detected
5. **Audio Output**: All responses include `audio_output` field with emojis removed for TTS

### Database Access Pattern

- Do not instantiate `ChildLearningAssistant` objects outside of:
  - `database.py` functions (for deserialization)
  - Flask endpoint handlers (for new sessions)
- Load sessions via `database.load_session()` which reconstructs full assistant state from JSON
- All state machine fields are persisted and restored on session load

### Conversation History Structure

Array of message dictionaries matching OpenAI chat completion format:
```python
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."},
  ...
]
```

### Emoji Handling

- User-facing responses include emojis (e.g., "🍎 What color is it?")
- `audio_output` field has emojis removed via `remove_emojis()` for clean TTS
- API adds ✅/❌ prefix to responses (not hints/mastery message) based on `is_correct`

## Configuration

**config.json**:
- `gemini_api_key`: Gemini API key (REQUIRED)
- `model_name`: "gemini-2.5-pro"
- `api_base_url`: "https://api.shubiaobiao.cn/v1/chat/completions"
- `temperature`: 0.7 (default)
- `max_tokens`: 2000 (increased for reasoning tokens)

**IMPORTANT**: Never commit API keys. Current key in repo should be rotated.

## Common Debugging Scenarios

### JSON Parsing Failures
- Check `extract_json_from_response()` output in logs
- Gemini sometimes returns markdown code blocks: ` ```json\n{...}\n``` `
- Look for `[DEBUG extract_json]` logs showing extraction steps

### State Machine Issues
- Check `[DEBUG] State BEFORE/AFTER update` logs
- Verify `stuck_count` increments/resets correctly
- Ensure `question_before_hint` is saved when entering hint states

### Missing `main_question` or `expected_answer`
- These are set during initial question and each JSON response
- If None during hint generation, check structured response parsing
- Look for `[DEBUG _generate_hint_only]` logs showing None values

### Session Not Found
- Sessions are deleted after mastery achievement
- Check `sessions.db` or call `/api/sessions` to list active sessions

### Truncated Responses
- Check for `finish_reason: MAX_TOKENS` in logs
- Increase `max_tokens` if needed (already at 2000)
- Gemini uses reasoning tokens that don't appear in response but consume tokens

## Web Interface

Located in `static/` folder:
- `index.html`: Web demo interface
- `app.js`: Frontend JavaScript
- Served at `http://localhost:5001` when running `app.py`
- Uses Fetch API to call backend endpoints
