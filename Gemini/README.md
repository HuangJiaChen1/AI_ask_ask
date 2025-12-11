# Child Learning Assistant - Gemini Version

This is a **Gemini-powered version** of the Child Learning Assistant. It replicates all functionality from the original Qwen-based implementation but uses Google's Gemini API instead.

## Key Differences from Original

- **LLM Model**: Uses Google Gemini (gemini-2.5-pro) instead of Qwen
- **API Client**: Uses `requests` library directly instead of OpenAI Python client
- **API Endpoint**: Connects to https://api.shubiaobiao.cn/v1/chat/completions
- **Configuration**: Uses `gemini_api_key` instead of `qwen_api_key` in config.json

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure API Key**:
   Edit `config.json` and replace `YOUR_GEMINI_API_KEY_HERE` with your actual Gemini API key:
   ```json
   {
     "gemini_api_key": "your-actual-api-key",
     "model_name": "gemini-2.5-pro",
     "api_base_url": "https://api.shubiaobiao.cn/v1/chat/completions",
     "temperature": 0.7,
     "max_tokens": 1000
   }
   ```

## Running the Application

### Interactive CLI Demo
```bash
python demo.py
```

### Flask API Server
```bash
python app.py
```
Server runs on http://localhost:5001 (not 5000 as documented)

### Testing
```bash
# Test state machine
python test_state_machine.py

# Test stuck detection
python test_stuck_detection.py

# Test hint generation
python diagnose_validation.py

# Test API (requires app.py to be running)
python test_api.py
```

## Architecture

All core functionality is preserved from the original implementation:
- **State Machine**: 7-state conversation flow (initial, awaiting, hint1, hint2, reveal, celebrating, mastery)
- **Stuck Detection**: LLM-based detection of when children need help
- **Hint System**: Dedicated prompts for hints at different difficulty levels
- **Mastery Tracking**: Tracks correct answers (threshold: 4)
- **Session Persistence**: SQLite database for session storage
- **A/B Testing**: Support for production vs test prompts

## API Endpoints

Same as original implementation:
- `POST /api/start` - Start new conversation
- `POST /api/continue` - Continue conversation
- `GET /api/history/<session_id>` - Get conversation history
- `POST /api/reset` - Delete session
- `GET /api/sessions` - List active sessions
- `POST /api/update_prompt` - Update production prompts
- `GET /api/health` - Health check

## Implementation Details

### API Integration

The main difference is in `child_learning_assistant.py`:

**Original (Qwen with OpenAI client)**:
```python
from openai import OpenAI

client = OpenAI(
    api_key=config["qwen_api_key"],
    base_url=config["api_base_url"]
)

completion = client.chat.completions.create(
    model=config["model_name"],
    messages=messages
)
```

**Gemini (requests library)**:
```python
import requests

response = requests.post(
    config["api_base_url"],
    headers={"Authorization": f"Bearer {config['gemini_api_key']}"},
    json={
        "model": config["model_name"],
        "messages": messages
    }
)
```

All other files (database.py, app.py, demo.py, test files) are functionally identical to the original implementation.

## File Structure

```
Gemini/
├── config.json                    # Gemini API configuration
├── child_learning_assistant.py    # Core conversation engine (Gemini API)
├── database.py                    # SQLite persistence layer
├── app.py                         # Flask REST API
├── demo.py                        # Interactive CLI demo
├── test_api.py                    # API integration tests
├── test_state_machine.py          # State machine tests
├── test_stuck_detection.py        # Stuck detection tests
├── diagnose_validation.py         # Hint generation diagnostic
├── requirements.txt               # Python dependencies
├── README.md                      # This file
└── sessions.db                    # SQLite database (auto-created)
```

## Notes

- The database is **separate** from the original implementation (uses local `sessions.db`)
- All prompts are identical to the original implementation
- The Flask server runs on **port 5001** (same as original)
- JSON mode is handled by appending "Respond with valid JSON only." to messages
- Error handling and fallbacks mirror the original implementation

## Troubleshooting

### API Key Error
If you see `Please set your API key in config.json`:
- Open `config.json`
- Replace `YOUR_GEMINI_API_KEY_HERE` with your actual key

### Connection Errors
If API calls fail:
- Check your internet connection
- Verify the API endpoint is accessible
- Ensure your API key is valid

### Database Errors
If you see database-related errors:
- Delete `sessions.db` and restart the app to recreate it
- Run `database.init_db()` manually in Python shell

## Credits

This is a Gemini-powered port of the original Child Learning Assistant project. All core logic, prompts, and architecture remain unchanged - only the LLM API integration has been modified.
