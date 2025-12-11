# Debug Guide - Understanding Server Logs

## Debug Messages Added

I've added comprehensive debug logging to help you understand what's happening with your web demo.

## What You'll See

### 1. Server Startup

When you run `python app.py`, you'll see:

```
============================================================
Child Learning Assistant - Flask Web Service (Gemini)
============================================================

📁 Static folder: C:\Users\123\PycharmProjects\AI_ask_ask\Gemini\static
   Exists: ✅ Yes
   Files: index.html, app.js

🌐 Web Interface:
  http://localhost:5001

📡 API Endpoints:
  ...

============================================================
🚀 Server starting on http://localhost:5001
   Open your browser and visit the URL above!
============================================================
```

**What to check:**
- ✅ Static folder exists
- ✅ Files `index.html` and `app.js` are listed

### 2. Page Load

When you open `http://localhost:5001` in your browser:

```
[DEBUG] Serving index.html from static folder
127.0.0.1 - - [10/Dec/2025 16:50:01] "GET / HTTP/1.1" 200 -
[DEBUG] Serving static file: app.js
127.0.0.1 - - [10/Dec/2025 16:50:01] "GET /static/app.js HTTP/1.1" 200 -
```

**What to check:**
- ✅ Status code `200` (not `404` or `304`)
- ✅ Both `index.html` and `app.js` load successfully

### 3. Starting a Session

When you click "Start Learning!" in the web interface:

```
[DEBUG] /api/start called with data: {
  'object_name': 'banana',
  'category': 'fruit',
  'age': 6,
  'level2_category': 'fresh_ingredients'
}
[INFO] Using age-appropriate prompting for age: 6
[INFO] Auto-detected Level 1 category 'foods' from Level 2 'fresh_ingredients'
[INFO] Using category prompts: Level 1: foods, Level 2: fresh_ingredients
[DEBUG] Requesting initial question for: banana
[DEBUG] API Response keys: dict_keys([...])
[DEBUG] Session created: 550e8400..., Object: banana, Age: 6, Level2: fresh_ingredients
127.0.0.1 - - [10/Dec/2025 16:51:23] "POST /api/start HTTP/1.1" 201 -
```

**What to check:**
- ✅ Request data shows all fields correctly
- ✅ Age prompting detected
- ✅ Category auto-detection working
- ✅ Session created successfully (status 201)

### 4. Continuing Conversation

When you send a response:

```
[DEBUG] /api/continue called with session: 550e8400...
[DEBUG] Child response: 'It grows on trees'
[DEBUG] State BEFORE update: awaiting, stuck_count: 0
[DEBUG] is_stuck detection: False for response: 'It grows on trees'
[DEBUG] Child attempting answer, resetting stuck_count to 0
[DEBUG] State AFTER update: celebrating, stuck_count: 0
[DEBUG] Response generated - Correct: True, Mastery: False, Count: 1
127.0.0.1 - - [10/Dec/2025 16:52:15] "POST /api/continue HTTP/1.1" 200 -
```

**What to check:**
- ✅ Session ID matches
- ✅ Child response captured
- ✅ State transitions (awaiting → celebrating)
- ✅ Correctness detected
- ✅ Count incremented

### 5. Mastery Achievement

When child answers 4 questions correctly:

```
[DEBUG] /api/continue called with session: 550e8400...
[DEBUG] Child response: 'To protect the banana'
[DEBUG] Response generated - Correct: True, Mastery: True, Count: 4
[DEBUG] Mastery achieved! Deleting session: 550e8400...
127.0.0.1 - - [10/Dec/2025 16:55:30] "POST /api/continue HTTP/1.1" 200 -
```

**What to check:**
- ✅ Correct count reaches 4
- ✅ Mastery flag set to True
- ✅ Session deleted

## Common Issues and Solutions

### Issue 1: "GET /app.js 404"

**What you see:**
```
127.0.0.1 - - [10/Dec/2025 16:50:01] "GET /app.js HTTP/1.1" 404 -
```

**Problem:** JavaScript file not found

**Solution:** Already fixed! The HTML now loads from `/static/app.js`

**After fix, you should see:**
```
[DEBUG] Serving static file: app.js
127.0.0.1 - - [10/Dec/2025 16:50:01] "GET /static/app.js HTTP/1.1" 200 -
```

---

### Issue 2: "Static folder not found"

**What you see:**
```
📁 Static folder: C:\...\static
   Exists: ❌ No
```

**Problem:** Static folder doesn't exist

**Solution:**
```bash
mkdir static
```

Then add `index.html` and `app.js` to the folder.

---

### Issue 3: Empty response from API

**What you see:**
```
[DEBUG] /api/start called with data: None
[ERROR] No JSON data received
```

**Problem:** Frontend not sending JSON data

**Solution:** Check browser console (F12) for JavaScript errors

---

### Issue 4: Session not found

**What you see:**
```
[DEBUG] /api/continue called with session: None...
```

**Problem:** Session ID not being passed from frontend

**Solution:** Check that `sessionId` variable is set in JavaScript

---

## How to Use Debug Logs

### 1. Verify Static Files Load

Look for:
```
[DEBUG] Serving index.html from static folder
[DEBUG] Serving static file: app.js
```

Both should show status `200`.

### 2. Track API Calls

For each action, you'll see:
- Request received: `[DEBUG] /api/... called with...`
- Processing: Age detection, category lookup
- Response sent: Status code (200, 201, 404, 500)

### 3. Monitor State Changes

Watch for:
- State transitions: `BEFORE → AFTER`
- Stuck detection: `is_stuck detection: True/False`
- Correct answers: `Correct: True, Count: N`

### 4. Check Errors

Look for:
- `[ERROR]` messages in red
- Status codes 400, 404, 500
- Python tracebacks (full error details)

## HTTP Status Codes

- **200 OK:** Request successful
- **201 Created:** Session created successfully
- **304 Not Modified:** Browser cached version used
- **400 Bad Request:** Missing or invalid parameters
- **404 Not Found:** Resource not found (file or session)
- **500 Internal Server Error:** Server-side error (check logs)

## Tips for Debugging

### Check Browser Console

1. Open browser (Chrome/Firefox/Edge)
2. Press **F12** to open Developer Tools
3. Go to **Console** tab
4. Look for JavaScript errors or API errors

### Check Network Tab

1. Open Developer Tools (F12)
2. Go to **Network** tab
3. Reload page
4. Check:
   - Files loaded: `index.html`, `app.js`
   - API calls: `/api/start`, `/api/continue`
   - Status codes and response data

### Follow the Flow

**Normal flow:**
```
1. Browser requests /
   [DEBUG] Serving index.html
   → Status 200

2. Browser requests /static/app.js
   [DEBUG] Serving static file: app.js
   → Status 200

3. User fills form and clicks "Start"
   [DEBUG] /api/start called with data: {...}
   [DEBUG] Session created: ...
   → Status 201

4. User sends response
   [DEBUG] /api/continue called with session: ...
   [DEBUG] Response generated - Correct: True...
   → Status 200

5. (Repeat step 4 until mastery)

6. Mastery achieved
   [DEBUG] Mastery achieved! Deleting session...
   → Status 200
```

## Example Debug Session

Here's what a complete successful session looks like:

```bash
# Server starts
============================================================
📁 Static folder: .../static
   Exists: ✅ Yes
   Files: index.html, app.js
🚀 Server starting on http://localhost:5001
============================================================

# User opens browser
[DEBUG] Serving index.html from static folder
[DEBUG] Serving static file: app.js

# User starts session
[DEBUG] /api/start called with data: {'object_name': 'banana', 'age': 6, ...}
[INFO] Using age-appropriate prompting for age: 6
[INFO] Auto-detected Level 1 category 'foods' from Level 2 'fresh_ingredients'
[DEBUG] Session created: a1b2c3d4..., Object: banana, Age: 6

# User answers question 1
[DEBUG] /api/continue called with session: a1b2c3d4...
[DEBUG] Child response: 'yellow'
[DEBUG] Response generated - Correct: True, Count: 1

# User answers question 2
[DEBUG] /api/continue called with session: a1b2c3d4...
[DEBUG] Child response: 'on trees'
[DEBUG] Response generated - Correct: True, Count: 2

# User answers question 3
[DEBUG] /api/continue called with session: a1b2c3d4...
[DEBUG] Child response: 'it grows from flowers'
[DEBUG] Response generated - Correct: True, Count: 3

# User answers question 4
[DEBUG] /api/continue called with session: a1b2c3d4...
[DEBUG] Child response: 'to protect it'
[DEBUG] Response generated - Correct: True, Mastery: True, Count: 4
[DEBUG] Mastery achieved! Deleting session: a1b2c3d4...

# Session complete!
```

## Summary

✅ **Added debug logging for:**
- Static file serving
- API requests (start, continue)
- Session creation and deletion
- Age and category detection
- Response generation
- Mastery achievement

✅ **Check these logs when:**
- Web page doesn't load → Check static file logs
- API doesn't work → Check API request logs
- Session lost → Check session ID logs
- Wrong questions → Check age/category detection logs

The debug messages will help you understand exactly what's happening at each step! 🐛🔍
