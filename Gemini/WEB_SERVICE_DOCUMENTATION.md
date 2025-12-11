# Child Learning Assistant - Web Service Documentation

## Overview

The Child Learning Assistant provides both a **web interface** and a **REST API** for interactive educational conversations with young children (ages 3-8). The system uses AI to ask age-appropriate questions about everyday objects, encouraging curiosity and learning.

## What We Provide

### 1. 🌐 Web Interface (Interactive Demo)

**URL:** `http://localhost:5001`

A beautiful, user-friendly web application that allows:
- ✅ Starting learning sessions with any object
- ✅ Age-appropriate questioning (ages 3-8)
- ✅ Category-based prompting (foods, animals, plants)
- ✅ Real-time conversation with the AI
- ✅ Progress tracking (mastery system)
- ✅ Visual feedback and animations

**Features:**
- Responsive design (works on mobile and desktop)
- No login required
- Session-based conversations
- Progress bar showing correctanswer count
- Celebration animation on mastery achievement

### 2. 📡 REST API

**Base URL:** `http://localhost:5001/api`

A RESTful API for building custom applications:
- ✅ Start new learning sessions
- ✅ Continue conversations
- ✅ Retrieve conversation history
- ✅ Manage sessions (list, reset, delete)
- ✅ Health monitoring

**Authentication:** None required (development mode)

## Quick Start

### Start the Server

```bash
# Navigate to project directory
cd C:\Users\123\PycharmProjects\AI_ask_ask\Gemini

# Start the server
python app.py
```

**Output:**
```
============================================================
Child Learning Assistant - Flask Web Service (Gemini)
============================================================

🌐 Web Interface:
  http://localhost:5001

📡 API Endpoints:
  POST   /api/classify   - Classify object into category
  POST   /api/start      - Start new conversation
  POST   /api/continue   - Continue conversation
  GET    /api/history/<session_id> - Get history
  POST   /api/reset      - Reset session
  GET    /api/sessions   - List active sessions
  GET    /api/health     - Health check

============================================================
🚀 Server starting on http://localhost:5001
   Open your browser and visit the URL above!
============================================================
```

### Access the Web Interface

1. Open your browser
2. Navigate to `http://localhost:5001`
3. Fill in the form:
   - **Object name:** e.g., "banana"
   - **Child's age:** 3-8 (optional)
   - **Level 2 category:** e.g., "fresh_ingredients" (optional)
   - **Level 3 category:** e.g., "fruits" (optional)
4. Click "Start Learning!"
5. Chat with the AI assistant

## Web Interface Guide

### Starting a Session

**Step 1: Fill the Form**

![Form Fields]
- **Object Name** (required): The object to learn about
  - **Auto-Classification:** When you tab out of this field, AI automatically suggests a category!
  - Shows: "💡 We think 'apple' belongs to the 'Fresh Ingredients' category"
  - You can accept the suggestion or enter your own
- **Age** (optional): Child's age (3-8) for age-appropriate questions
  - Age 3-4: "What" questions (colors, shapes, sounds)
  - Age 5-6: "What" and "How" questions (processes, actions)
  - Age 7-8: "What", "How", and "Why" questions (reasoning, causes)
- **Level 2 Category** (optional): Choose from available categories
  - Foods: `fresh_ingredients`, `processed_foods`, `beverages_drinks`
  - Animals: `vertebrates`, `invertebrates`, `human_raised_animals`
  - Plants: `ornamental_plants`, `useful_plants`, `wild_natural_plants`
  - **Note:** Auto-fills if you accept the AI suggestion
- **Level 3 Category** (optional): For display purposes only

**Step 2: Chat**
- The AI asks questions about the object
- Type answers in the input box
- Press Enter or click "Send"
- AI provides feedback and asks follow-up questions

**Step 3: Master the Topic**
- Answer 4 questions correctly to achieve mastery
- Progress bar shows your advancement
- Celebration animation when mastery achieved!

### Features

**Progress Tracking**
- Visual progress bar (0/4 to 4/4)
- Green checkmark ✅ for correct answers
- Red X ❌ for incorrect answers

**Intelligent Hints System**
- Say "I don't know" to get hints
- First hint: Ask a different, easier question with the same answer
- Second hint: Ask an even easier question
- After hint is answered: **Reconnects back to original question**
- Third "I don't know": Answer is revealed
- **Example Flow:**
  1. "Why do onions have many layers?" → "I don't know"
  2. Hint: "Why do we cook onions?" → "because they're yummy"
  3. Reconnect: "Right! Those layers store all that flavor. So why do you think layers help?"
  4. Child answers the original question ✅

**Mastery Achievement**
- 4 correct answers triggers mastery
- Celebration banner appears
- Session automatically ends
- Can start new session immediately

## API Reference

### Base Information

- **Base URL:** `http://localhost:5001/api`
- **Content-Type:** `application/json`
- **Response Format:** JSON

### Endpoints

#### 1. Health Check

**GET /api/health**

Check if the service is running.

**Response:**
```json
{
  "status": "healthy",
  "service": "Child Learning Assistant (Gemini)",
  "version": "1.0"
}
```

---

#### 2. Classify Object

**POST /api/classify**

Automatically classify an object into a level2 category using AI.

**Request Body:**
```json
{
  "object_name": "apple"  // Required: Object to classify
}
```

**Response (Success):**
```json
{
  "success": true,
  "object_name": "apple",
  "recommended_category": "fresh_ingredients",
  "category_display": "Fresh Ingredients",
  "level1_category": "Foods"
}
```

**Response (No Classification):**
```json
{
  "success": true,
  "object_name": "computer",
  "recommended_category": null,
  "message": "Could not classify object into any category"
}
```

**Use Case:**
- Automatically suggest categories to users
- Pre-fill category fields in forms
- Validate object-category relationships
- **Note:** Final category selection is always user-determined; this is just a suggestion

**Supported Categories:**
- Foods: `fresh_ingredients`, `processed_foods`, `beverages_drinks`
- Animals: `vertebrates`, `invertebrates`, `human_raised_animals`
- Plants: `ornamental_plants`, `useful_plants`, `wild_natural_plants`

---

#### 3. Start Conversation

**POST /api/start**

Start a new learning session with an object.

**Request Body:**
```json
{
  "object_name": "banana",         // Required: Object to learn about
  "category": "fruit",             // Required: Category name for display
  "age": 6,                        // Optional: Child's age (3-8)
  "level2_category": "fresh_ingredients",  // Optional: Level 2 category
  "level3_category": "fruits"      // Optional: Level 3 category (display only)
}
```

**Response:**
```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "🍌 WOW! Bananas are fascinating! Why do you think bananas grow in bunches?",
  "object": "banana",
  "category": "fruit"
}
```

**Important:**
- Save the `session_id` for continuing the conversation
- `level1_category` is auto-detected from `level2_category`
- Age determines question complexity

---

#### 4. Continue Conversation

**POST /api/continue**

Continue an existing conversation with the child's response.

**Request Body:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",  // Required
  "child_response": "They grow together on trees"         // Required
}
```

**Response:**
```json
{
  "success": true,
  "response": "✅ YES! WOW! Bananas do grow together in bunches! That's called a 'hand' of bananas! 🍌 Why do you think they grow in bunches instead of alone?",
  "audio_output": "YES! WOW! Bananas do grow together in bunches! That's called a 'hand' of bananas! Why do you think they grow in bunches instead of alone?",
  "mastery_achieved": false,
  "correct_count": 1,
  "is_correct": true,
  "is_neutral": false
}
```

**Response Fields:**
- `response`: Full response with emojis (for display)
- `audio_output`: Clean text without emojis (for text-to-speech)
- `mastery_achieved`: True if child answered 4 questions correctly
- `correct_count`: Number of correct answers so far
- `is_correct`: Whether this answer was correct
- `is_neutral`: True for hints/reveals (no emoji prefix)

**Mastery Response:**
When `mastery_achieved: true`, the session is automatically deleted.

---

#### 5. Get Conversation History

**GET /api/history/:session_id**

Retrieve the full conversation history for a session.

**Example:**
```
GET /api/history/550e8400-e29b-41d4-a716-446655440000
```

**Response:**
```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "object": "banana",
  "category": "fruit",
  "history": [
    {
      "role": "system",
      "content": "You are a playful learning buddy..."
    },
    {
      "role": "user",
      "content": "The child wants to learn about: banana..."
    },
    {
      "role": "assistant",
      "content": "🍌 WOW! Bananas are fascinating!..."
    },
    {
      "role": "user",
      "content": "They grow together on trees"
    },
    {
      "role": "assistant",
      "content": "YES! WOW! Bananas do grow together..."
    }
  ]
}
```

---

#### 6. Reset Session

**POST /api/reset**

Delete a session to free up resources.

**Request Body:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Session reset successfully"
}
```

---

#### 7. List Sessions

**GET /api/sessions**

List all active sessions (for monitoring/debugging).

**Response:**
```json
{
  "success": true,
  "active_sessions": 3,
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "object": "banana",
      "category": "fruit"
    },
    {
      "session_id": "660e8400-e29b-41d4-a716-446655440001",
      "object": "dog",
      "category": "mammal"
    }
  ]
}
```

---

## Error Handling

### Error Response Format

```json
{
  "success": false,
  "error": "Error message describing what went wrong"
}
```

### Common Error Codes

- **400 Bad Request:** Missing required parameters or invalid input
- **404 Not Found:** Session not found or expired
- **500 Internal Server Error:** Server-side error (check logs)

### Example Errors

**Missing Parameters:**
```json
{
  "success": false,
  "error": "Both object_name and category are required"
}
```

**Invalid Session:**
```json
{
  "success": false,
  "error": "Invalid or expired session_id"
}
```

---

## Advanced Features

### Age-Appropriate Questioning

The system automatically adjusts question complexity based on age:

**Age 3-4:** Simple "what" questions
```
"What color is a banana?"
"What shape is it?"
```

**Age 5-6:** "What" and "how" questions
```
"How does a banana grow?"
"What happens when you peel it?"
```

**Age 7-8:** "What", "how", and "why" questions
```
"Why do bananas turn brown?"
"Why do they grow in bunches?"
```

### Category-Based Prompting

Categories influence the types of questions asked:

**fresh_ingredients:**
- Focus on farm/garden origins
- Natural smells and textures
- Healthy nutrients

**vertebrates:**
- Emphasize backbone and skeleton
- Movement capabilities
- Warm/cold blooded

**ornamental_plants:**
- Focus on beauty (flowers, colors)
- Growing in pots/gardens
- Making people happy

### Mastery System

**How it works:**
1. System tracks correct answers
2. Threshold: 4 correct answers
3. When threshold reached:
   - `mastery_achieved: true` in response
   - Celebration message displayed
   - Session automatically deleted
4. User can start new session

**Progress Tracking:**
- Each `/api/continue` response includes `correct_count`
- Web interface shows progress bar
- Visual feedback for correct/incorrect answers

---

## Development Guide

### Project Structure

```
Gemini/
├── app.py                    # Flask server + API + web interface
├── child_learning_assistant.py  # Core AI logic
├── prompts.py                # Hardcoded prompts
├── database.py               # Session storage
├── age_prompts.json          # Age-based prompts
├── category_prompts.json     # Category-based prompts
├── static/
│   ├── index.html            # Web interface
│   └── app.js                # JavaScript frontend
└── sessions.db               # SQLite database (auto-created)
```

### Running in Production

**For production deployment:**

1. **Disable debug mode:**
   ```python
   app.run(debug=False, host='0.0.0.0', port=5001)
   ```

2. **Use a production server:**
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5001 app:app
   ```

3. **Add authentication** (if needed)

4. **Set up HTTPS** (if needed)

5. **Configure CORS** for specific domains

### Customization

**Add new categories:**
Edit `category_prompts.json`:
```json
{
  "level2_categories": {
    "your_new_category": {
      "prompt": "Your custom prompt...",
      "parent": "level1_category"
    }
  }
}
```

**Modify prompts:**
Edit `prompts.py` to change:
- System personality
- Question styles
- Hint strategies
- Celebration messages

**Change mastery threshold:**
In `child_learning_assistant.py`:
```python
self.mastery_threshold = 4  # Change to desired number
```

---

## Technical Details & Recent Improvements

### State Machine Architecture

The system uses an intelligent state machine for conversation flow:

**States:**
- `INITIAL_QUESTION`: First question asked
- `AWAITING_ANSWER`: Waiting for child's response
- `GIVING_HINT_1`: First hint (easier question)
- `GIVING_HINT_2`: Second hint (even easier)
- `RECONNECTING`: Bridge hint answer back to original question
- `REVEALING_ANSWER`: Reveal answer after 3 "I don't know"
- `CELEBRATING`: Positive reinforcement, then next question
- `MASTERY_ACHIEVED`: 4 correct answers reached

**Key Features:**
- **Cascading Transitions:** States automatically cascade (e.g., `CELEBRATING` → `AWAITING_ANSWER` → `GIVING_HINT_1` if child says "I don't know")
- **Question Tracking:** Saves original question before hints for reconnection
- **Session Persistence:** All state is saved to database across requests

### Database Schema

**Sessions Table Fields:**
- `id`: Unique session identifier
- `current_object`: Object being learned
- `current_category`: Category name
- `conversation_history`: Full message history (JSON)
- `state`: Current state machine state
- `stuck_count`: Number of "I don't know" responses
- `question_count`: Questions asked so far
- `correct_count`: Correct answers (for mastery tracking)
- `current_main_question`: Current question being asked
- `expected_answer`: Expected answer for current question
- `question_before_hint`: Original question (before hint)
- `answer_before_hint`: Expected answer for original question
- `last_modified`: Timestamp

**Why These Fields Matter:**
- `current_main_question` & `expected_answer`: Enable hint generation
- `question_before_hint` & `answer_before_hint`: Enable hint reconnection
- All fields persist across requests for seamless multi-turn conversations

### Response Token Handling

**Gemini models use internal "reasoning tokens"** before generating visible output. To prevent truncation:

- **Standard responses:** `max_tokens=2000`
- **Hints:** `max_tokens=2000` (was 1000, caused truncation)
- **Reveals:** `max_tokens=2000`
- **Reconnections:** `max_tokens=2000`
- **Classification:** `max_tokens=200` (simple task)

This ensures complete responses without mid-sentence cutoffs.

### Recent Bug Fixes (December 2025)

**1. Hint Reconnection System**
- **Problem:** After answering a hint question, system would ask a NEW question instead of returning to original
- **Fix:** Added `RECONNECTING` state that bridges hint answer back to original question
- **Result:** Pedagogically sound - children now complete the original learning objective

**2. Session Persistence**
- **Problem:** `current_main_question` and `expected_answer` not saved to database
- **Fix:** Added fields to database schema + save/load logic
- **Result:** Hints work correctly across web requests

**3. State Cascading**
- **Problem:** From `CELEBRATING` state, saying "I don't know" triggered JSON parsing errors
- **Fix:** Moved `CELEBRATING` and `RECONNECTING` to cascade properly
- **Result:** Smooth transitions from any state to hints

**4. Response Truncation**
- **Problem:** Hints cut off mid-sentence due to max_tokens limit
- **Fix:** Increased `max_tokens` from 1000 to 2000
- **Result:** Complete, coherent responses

**5. None Handling**
- **Problem:** TypeError when `current_main_question` was None (safe string slicing)
- **Fix:** Added null checks and fallback values
- **Result:** Robust error handling

---

## Troubleshooting

### Server won't start

**Error:** `Address already in use`

**Solution:** Port 5001 is already taken
```bash
# Find process using port 5001
netstat -ano | findstr :5001

# Kill the process or change port in app.py
app.run(debug=True, host='0.0.0.0', port=5002)
```

### Web interface not loading

**Check:**
1. Server is running (`python app.py`)
2. Accessing correct URL (`http://localhost:5001`)
3. `static/` folder exists with `index.html` and `app.js`

### API returns 500 error

**Check:**
1. Server logs for error messages
2. `config.json` has valid API key
3. Database is writable (`sessions.db`)

### Sessions not persisting

**Check:**
1. `sessions.db` file exists and is writable
2. No database errors in server logs
3. Session ID is being stored and passed correctly

---

## Support

For issues or questions:
1. Check server logs for error messages
2. Verify all required files exist
3. Ensure API key is configured in `config.json`
4. Review this documentation

## Summary

✅ **What we provide:**
- Beautiful web interface for interactive learning
- REST API for custom integrations
- **AI-powered object classification** (automatic category suggestions)
- Age-appropriate questioning (3-8 years)
- Category-based prompting
- **Intelligent hint system with reconnection** (pedagogically sound)
- Session management with full state persistence
- Progress tracking and mastery system

✅ **What you can do:**
- Use the web interface directly with auto-classification
- Build custom applications using the API
- Integrate with mobile apps
- Create educational platforms
- Monitor and manage sessions
- Customize prompts and categories

✅ **What we need:**
- Gemini API key in `config.json`
- Python 3.7+ with required packages
- Port 5001 available (or customize)

✅ **Recent improvements:**
- Hint reconnection system (Dec 2025)
- Session persistence for question tracking
- State cascading fixes
- Response truncation fixes
- Automatic object classification

That's it! You're ready to use the Child Learning Assistant! 🎉
