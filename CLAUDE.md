# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Child Learning Assistant** is an educational chatbot for young children (ages 4-8) that uses the Qwen AI model to generate suggestive questions about everyday objects. The assistant encourages curiosity and learning through interactive conversations.

The project features:
- A core conversation engine using OpenAI-compatible API (Qwen)
- Flask REST API for web/mobile integration
- SQLite-based session persistence
- Dynamic prompt management system supporting A/B testing
- State machine with LLM-based stuck detection and validation loop
- Mastery/reward system tracking correct answers

## Development Commands

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Configure API key (required before first run)
# Edit config.json and set your Qwen API key
```

### Running the Application
```bash
# Run Flask API server (default port 5001)
python app.py

# Run interactive CLI demo
python demo.py

# Test the API (ensure app.py is running first)
python test_api.py
```

### Database
The SQLite database `sessions.db` is created automatically on first run. It stores:
- Session data with conversation history
- Production prompts (system and user prompts)

No manual database setup is required.

## Architecture

### Core Components

**1. ChildLearningAssistant** (`child_learning_assistant.py`)
- Manages conversation state and history
- Handles communication with Qwen API via OpenAI client
- Uses `config.json` for API configuration
- Methods:
  - `start_new_object(object_name, category, system_prompt, user_prompt_template)`: Initialize conversation with custom prompts
  - `continue_conversation(child_response)`: Process child's response and get next question
  - `get_conversation_history()`: Returns full message history
  - `reset()`: Clear conversation state

**2. Flask API** (`app.py`)
- RESTful endpoints for session management
- Runs on port 5001 (not 5000 as documented)
- CORS enabled for frontend integration
- Key endpoints:
  - `POST /api/start`: Create new session (production or test mode)
  - `POST /api/continue`: Continue conversation
  - `GET /api/history/<session_id>`: Retrieve conversation history
  - `POST /api/update_prompt`: Update production prompts
  - `POST /api/reset`: Delete session
  - `GET /api/sessions`: List all active sessions
  - `GET /api/health`: Health check

**3. Database Layer** (`database.py`)
- SQLite persistence for sessions and prompts
- Two main tables:
  - `sessions`: Stores conversation history as JSON
  - `prompts`: Stores production system/user prompts (single row, id=1)
- All sessions are persisted to disk and survive server restarts

### Conversation Flow

1. **Session Start**: Client calls `/api/start` with object name and category
2. **Prompt Selection**:
   - Production mode (default): Loads prompts from `prompts` table
   - Test mode (`is_test=true`): Uses prompts from request body
3. **Initial Question**: System formats user prompt template with `{object_name}` and `{category}`, sends to Qwen API
4. **Conversation Loop**: Client repeatedly calls `/api/continue` with `session_id` and child's response
5. **State Persistence**: After each exchange, session is saved to database with updated conversation history

### Prompt System Architecture

The application supports two prompt modes:
- **Production Mode**: Uses prompts from database (managed via `/api/update_prompt`)
- **Test Mode**: Accepts prompts directly in `/api/start` request for A/B testing

This allows testing new prompt variations without affecting production users.

### Session Management

- Each session has unique UUID
- Sessions store: `session_id`, `current_object`, `current_category`, `conversation_history` (JSON array)
- Frontend MUST store and pass `session_id` with every `/api/continue` request
- Sessions persist in SQLite database across server restarts

## Configuration

**config.json** contains:
- `qwen_api_key`: Alibaba Cloud Qwen API key (required)
- `model_name`: Model to use (default: "qwen-plus")
- `api_base_url`: Qwen OpenAI-compatible endpoint
- `temperature`: Response randomness (0.0-1.0)
- `max_tokens`: Maximum response length

The OpenAI Python client is used with `base_url` parameter to connect to Qwen's OpenAI-compatible API.

## Mastery/Reward System

The assistant includes a reward system that tracks correct answers and celebrates mastery:

1. **Correctness Tracking**: The LLM evaluates each response and includes an `is_correct` field in its JSON output
2. **Progress Counter**: `assistant.correct_count` tracks total correct answers
3. **Mastery Threshold**: Default is 4 correct answers (configurable via `assistant.mastery_threshold`)
4. **Mastery Response**: When threshold is reached, returns a celebration message and sets `mastery_achieved=True`
5. **API Integration**: `/api/continue` returns both `correct_count` and `mastery_achieved` flags for frontend use

**Key Files:**
- `child_learning_assistant.py`: Mastery logic in `continue_conversation()`
- `app.py`: API response includes mastery flags
- See `MASTERY_SYSTEM.md` for complete documentation

**Frontend Usage:**
```javascript
const response = await fetch('/api/continue', {...});
const data = await response.json();

if (data.mastery_achieved) {
  // Trigger custom reward UI (confetti, badges, etc.)
}
// Update progress: data.correct_count / 4
```

## Important Implementation Notes

### API Design Patterns

1. **Session ID is Critical**: Frontend must store `session_id` from `/api/start` response and include it in all subsequent `/api/continue` calls. Without this, conversations cannot continue.

2. **Prompt Template Requirements**: User prompt templates MUST include `{object_name}` and `{category}` placeholders. These are formatted using Python's `.format()` method.

3. **Error Handling**: All endpoints return consistent JSON:
   ```json
   {"success": true/false, ...}
   ```

4. **Port Configuration**: Despite documentation showing port 5000, the actual server runs on port 5001 (see `app.py:350`).

### Database Access Pattern

Do not instantiate `ChildLearningAssistant` objects outside of:
- `database.py` functions (for deserialization)
- Flask endpoint handlers (for new sessions)

Sessions should be loaded via `database.load_session()` which reconstructs the full assistant state from JSON.

### Conversation History Structure

The conversation history is an array of message dictionaries:
```python
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."},
  ...
]
```

This format matches OpenAI's chat completion API structure.

### State Machine & Hint System

The assistant uses a state machine with dedicated prompts for different scenarios:

**ConversationState Enum** (child_learning_assistant.py:23):
- `INITIAL_QUESTION`: Starting state
- `AWAITING_ANSWER`: Waiting for child's response
- `GIVING_HINT_1`: First hint after "I don't know"
- `GIVING_HINT_2`: Stronger hint after second "I don't know"
- `REVEALING_ANSWER`: Reveals answer after third "I don't know"
- `CELEBRATING`: Positive reinforcement state
- `MASTERY_ACHIEVED`: Child reached 4 correct answers

**Key Architecture Decision**: Instead of complex validation to prevent direct answers, the system uses **dedicated, single-purpose prompts** for hint states:
- When child is stuck → `_generate_hint_only()` with focused hint prompt
- When revealing answer → `_generate_reveal_answer()` with focused reveal prompt
- When child attempts answer → `_get_model_response_with_validation()` with structured JSON

This approach is simpler, faster (1 LLM call vs 2-5), and more reliable than multi-layer validation.

See `DEDICATED_HINT_SYSTEM.md` for complete architecture documentation.

### JSON Response Structure

The LLM is instructed to return structured JSON for normal responses (when child attempts to answer):

```json
{
  "reaction": "Your immediate reaction to child's answer",
  "hint_or_info": "Your hint, clue, or information",
  "next_question": "Your next question to continue learning",
  "main_question": "The PRIMARY question you're asking (simple, one sentence)",
  "should_give_answer": false,
  "is_correct": false
}
```

**Critical Field: `main_question`**
- The model explicitly provides the core question it's asking
- Stored in `self.current_main_question` for hint generation
- **Why needed**: Responses contain multiple questions (rhetorical examples like "Is it red? Blue? Green?"). Without explicit main_question, hint extraction would reference wrong questions.
- Example:
  - Full response: "🍎 What color is it? Is it red? Blue? Maybe yellow?"
  - main_question: "What color is it?" (stored for hints)

When child says "I don't know", hints reference `self.current_main_question` instead of parsing decorated text.

**Implementation**:
- Initial question: `_get_initial_question()` requests JSON with {main_question, full_response}
- Subsequent questions: All JSON responses include main_question field
- Hint generation: Uses `self.current_main_question` directly

## Testing

### API Integration Test

The `test_api.py` script provides a complete integration test:
- Tests all API endpoints in sequence
- Simulates a full conversation flow
- Requires Flask server to be running first

Run tests with:
```bash
# Terminal 1
python app.py

# Terminal 2
python test_api.py
```

### Hint System Diagnostic

The `diagnose_validation.py` script tests the hint generation system:
- Simulates a child saying "I don't know" three times
- Verifies state transitions: initial → awaiting → hint1 → hint2 → reveal
- Shows main_question extraction and hint generation
- Requires database initialization (prompts must be in database)

Run diagnostic with:
```bash
python diagnose_validation.py
```

**Expected output**:
```
[Main question set]: What do you think happens inside an apple tree...
State: initial → hint1 → hint2 → reveal
[Generated subtle hint for]: What do you think happens inside an apple tree...
[Generated stronger hint for]: What do you think happens inside an apple tree...
[Revealed answer for]: What do you think happens inside an apple tree...
```

This verifies that hints reference the correct main_question, not rhetorical examples.
