# Child Learning Assistant - API Documentation

## Base URL
```
http://localhost:5000
```

## Overview
This REST API provides endpoints to interact with Curious Fox, an educational AI assistant for children aged 4-8. The API manages conversation sessions and allows children to learn about different objects through interactive questions.

---

## Web Frontend Integration Workflow

Integrating this API with a web frontend (like a React, Vue, or Angular application) follows a typical chat application pattern. The core responsibility of the frontend is to manage the `session_id` to maintain conversation state.

Here is the typical user flow:

1.  **Starting a Conversation:**
    *   The user initiates a new topic (e.g., by filling out a form or clicking a button for "Banana").
    *   The frontend sends a `POST` request to `/api/start` with the `object_name` and `category`.
    *   The API responds with a unique `session_id` and the first `response` (question) from the assistant.
    *   **Crucially, the frontend must store this `session_id`** (e.g., in component state, React Context, or browser local storage) to use in subsequent requests.

2.  **Continuing the Conversation:**
    *   The frontend displays the assistant's question and a text input for the child's answer.
    *   When the child submits their answer, the frontend sends a `POST` request to `/api/continue`.
    *   This request **must** include the stored `session_id` and the `child_response`.
    *   The API returns the next `response` from the assistant, which the frontend then displays.
    *   This request-response cycle continues for the duration of the conversation.

3.  **Displaying History:**
    *   To show the full chat history (e.g., when reloading a session), the frontend can send a `GET` request to `/api/history/<session_id>`, which returns an array of all messages in the conversation.

By following this pattern, the frontend can create a stateful, interactive learning experience powered by the backend service.

---

## API Endpoints

### 1. Health Check
Check if the service is running.

**Endpoint:** `GET /api/health`

**Response:**
```json
{
  "status": "healthy",
  "service": "Child Learning Assistant",
  "version": "1.0"
}
```

---

### 2. Start New Conversation
Start a new learning session. This endpoint can be used in two modes:

- **Production Mode (default):** Uses the prompts currently stored in the database.
- **Test Mode:** Uses prompts provided directly in the request body, allowing for A/B testing without changing the production prompts.

**Endpoint:** `POST /api/start`

**Request Headers:**
```
Content-Type: application/json
```

**Request Body (Production Mode):**
```json
{
  "object_name": "Banana",
  "category": "Fruit"
}
```

**Request Body (Test Mode):**
```json
{
  "object_name": "Banana",
  "category": "Fruit",
  "is_test": true,
  "system_prompt": "You are a robot assistant. Beep boop.",
  "user_prompt": "The user wants to learn about {object_name}. Start by saying beep boop."
}
```

**Arguments:**
- `object_name` (string, required): The name of the object to learn about.
- `category` (string, required): The category/type of the object.
- `is_test` (boolean, optional): Set to `true` to enable test mode. Defaults to `false`.
- `system_prompt` (string, required in test mode): The system prompt to use for the session.
- `user_prompt` (string, required in test mode): The user prompt template to use. Must include `{object_name}` and `{category}` placeholders.

**Response (201 Created):**
```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "WOW hi explorer!! 🌟 Ooh a banana! Do you know where bananas grow?",
  "object": "Banana",
  "category": "Fruit"
}
```

**Error Response (400 Bad Request):**
```json
{
  "success": false,
  "error": "In test mode, both system_prompt and user_prompt are required"
}
```

---

### 3. Continue Conversation
Continue an existing conversation with the child's response.

**Endpoint:** `POST /api/continue`

**Request Headers:**
```
Content-Type: application/json
```

**Request Body:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",  // Required
  "child_response": "I don't know"                       // Required
}
```

**Arguments:**
- `session_id` (string, required): The session ID from `/api/start`.
- `child_response` (string, required): What the child said/typed.

**Response (200 OK):**
```json
{
  "success": true,
  "response": "That's okay! Bananas grow up HIGH on special banana trees!",
  "mastery_achieved": false,
  "correct_count": 2
}
```

**Response Fields:**
- `success`: Whether the request succeeded
- `response`: The assistant's message to display
- `mastery_achieved`: Boolean - true if child just achieved mastery (answered 4 questions correctly)
- `correct_count`: Number of correct answers given so far in this session

**Error Response (404 Not Found):**
```json
{
  "success": false,
  "error": "Invalid or expired session_id"
}
```

---

### 4. Get Conversation History
Retrieve the full conversation history for a session.

**Endpoint:** `GET /api/history/<session_id>`

**URL Parameters:**
- `session_id` (string, required): The session ID.

**Response (200 OK):**
```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "object": "Banana",
  "category": "Fruit",
  "history": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

---

### 5. Update Production Prompts
Update the system and user prompts that are used by default in production mode.

**Endpoint:** `POST /api/update_prompt`

**Request Body:**
```json
{
  "system_prompt": "You are Wenwen, The Red Panda...",
  "user_prompt": "The child wants to learn about: {object_name}..."
}
```

**Arguments:**
- `system_prompt` (string, required): The new system prompt.
- `user_prompt` (string, required): The new user prompt template.

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Prompts updated successfully"
}
```

---

### 5. Reset Session
Delete/reset a conversation session.

**Endpoint:** `POST /api/reset`

**Request Body:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Arguments:**
- `session_id` (string, required): Session ID to reset/delete

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Session reset successfully"
}
```

---

### 6. List Active Sessions
Get all active sessions (useful for monitoring/debugging).

**Endpoint:** `GET /api/sessions`

**Response (200 OK):**
```json
{
  "success": true,
  "active_sessions": 3,
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "object": "Banana",
      "category": "Fruit"
    },
    {
      "session_id": "660e8400-e29b-41d4-a716-446655440001",
      "object": "Cat",
      "category": "Animal"
    }
  ]
}
```

---

## Mastery System

The assistant tracks when children answer questions correctly and rewards them after 4 correct answers.

### How It Works

1. **Automatic Evaluation**: Each response is evaluated for correctness by the AI
2. **Progress Tracking**: `correct_count` increments when child answers correctly
3. **Mastery Achievement**: After 4 correct answers, `mastery_achieved` becomes true
4. **Custom Rewards**: Use the `mastery_achieved` flag to trigger custom UI (confetti, badges, sounds, etc.)

### Example Progression

```bash
# Question 1 - Correct
POST /api/continue {"session_id": "...", "child_response": "Red"}
Response: {"correct_count": 1, "mastery_achieved": false}

# Question 2 - Incorrect
POST /api/continue {"session_id": "...", "child_response": "I don't know"}
Response: {"correct_count": 1, "mastery_achieved": false}

# Question 3 - Correct
POST /api/continue {"session_id": "...", "child_response": "On trees"}
Response: {"correct_count": 2, "mastery_achieved": false}

# Question 4 - Correct
POST /api/continue {"session_id": "...", "child_response": "Sweet"}
Response: {"correct_count": 3, "mastery_achieved": false}

# Question 5 - Correct (MASTERY!)
POST /api/continue {"session_id": "...", "child_response": "Round"}
Response: {
  "correct_count": 4,
  "mastery_achieved": true,
  "response": "🎉 WOW! You have now mastered the Apple! Congratulations! You answered 4 questions correctly! You're amazing! 🎉"
}
```

### Frontend Integration

```javascript
if (data.mastery_achieved) {
  // Show custom reward UI
  showConfetti();
  displayBadge(sessionData.object);
  playSuccessSound();
}

// Update progress bar
const progress = (data.correct_count / 4) * 100;
updateProgressBar(progress);
```

See [MASTERY_SYSTEM.md](MASTERY_SYSTEM.md) for complete documentation.

---

## Complete Usage Example

### Starting a Conversation

```bash
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{
    "object_name": "Rainbow",
    "category": "Nature"
  }'
```

**Response:**
```json
{
  "success": true,
  "session_id": "abc-123-def",
  "response": "WOW a rainbow! Have you ever seen one in the sky? What colors do you remember seeing?",
  "object": "Rainbow",
  "category": "Nature"
}
```

### Continuing the Conversation

```bash
curl -X POST http://localhost:5000/api/continue \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "abc-123-def",
    "child_response": "Red and blue and yellow"
  }'
```

**Response:**
```json
{
  "success": true,
  "response": "YES!! You have such good eyes! Red, blue, and yellow! You know what's amazing? There are actually SEVEN colors in a rainbow! Can you guess what other colors might be hiding in there?"
}
```

---

## Frontend Integration Examples

### JavaScript (Fetch API)

```javascript
// Start conversation
async function startLearning(objectName, category) {
  const response = await fetch('http://localhost:5000/api/start', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      object_name: objectName,
      category: category
    })
  });

  const data = await response.json();
  console.log('Session ID:', data.session_id);
  console.log('First Question:', data.response);
  return data;
}

// Continue conversation
async function sendResponse(sessionId, childResponse) {
  const response = await fetch('http://localhost:5000/api/continue', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
      child_response: childResponse
    })
  });

  const data = await response.json();
  console.log('Curious Fox says:', data.response);
  return data;
}

// Usage
const session = await startLearning('Apple', 'Fruit');
const reply = await sendResponse(session.session_id, 'Red!');
```

### Python (Requests)

```python
import requests

BASE_URL = 'http://localhost:5000'

# Start conversation
def start_learning(object_name, category):
    response = requests.post(f'{BASE_URL}/api/start', json={
        'object_name': object_name,
        'category': category
    })
    return response.json()

# Continue conversation
def send_response(session_id, child_response):
    response = requests.post(f'{BASE_URL}/api/continue', json={
        'session_id': session_id,
        'child_response': child_response
    })
    return response.json()

# Usage
session = start_learning('Dog', 'Animal')
print(f"Session ID: {session['session_id']}")
print(f"Question: {session['response']}")

reply = send_response(session['session_id'], 'I don\'t know')
print(f"Reply: {reply['response']}")
```

---

## Error Handling

All endpoints return consistent error responses:

```json
{
  "success": false,
  "error": "Error message here"
}
```

**HTTP Status Codes:**
- `200` - Success (GET, POST operations)
- `201` - Created (new session)
- `400` - Bad Request (missing/invalid parameters)
- `404` - Not Found (invalid session_id)
- `500` - Internal Server Error

---

## Session Management

- Sessions are stored persistently in an SQLite database file (`sessions.db`).
- Each session is identified by a unique `session_id` (UUID).
- Because sessions are stored on disk, they will persist even if the server restarts.

---

## Important Notes

1. **CORS is enabled** - Frontend can call from any origin
2. **Session IDs must be stored** by the frontend/client
3. **No authentication** - Add authentication for production
4. **Persistent storage** - Sessions are stored in an SQLite database and are not lost on restart.
5. **API Key** - Ensure `config.json` has valid Qwen API key

---

## Production Recommendations

1. Add authentication (JWT, API keys)
2. Use Redis for session storage
3. Add rate limiting
4. Enable HTTPS
5. Add request validation middleware
6. Implement session expiration
7. Add logging and monitoring
8. Use environment variables for configuration
