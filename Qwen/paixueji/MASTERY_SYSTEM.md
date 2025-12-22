# Mastery System Documentation

## Overview

The mastery system rewards children after they correctly answer a configurable number of questions (default: 4). It tracks correctness automatically using LLM evaluation.

## How It Works

### 1. Correctness Evaluation

The model now outputs a JSON structure that includes an `is_correct` field:

```json
{
  "reaction": "WOW! That's right!",
  "hint_or_info": "Yes, apples do grow on trees!",
  "next_question": "What colors can apples be?",
  "should_give_answer": false,
  "is_correct": true
}
```

**When is_correct is set to true:**
- Child's answer is correct or mostly correct (even if not perfect)
- Example: "On trees" → correct for "Where do apples grow?"

**When is_correct is set to false:**
- Child is stuck/confused
- Child's answer is wrong
- Giving hints or revealing answers
- Example: "I don't know" → not correct

### 2. Mastery Threshold

- Default: **4 correct answers**
- Configurable via `assistant.mastery_threshold`
- Tracked per session in `assistant.correct_count`

### 3. Mastery Message

When the threshold is reached, the assistant automatically responds with:

```
🎉 WOW! You have now mastered the {object_name}!
Congratulations! You answered 4 questions correctly!
You're amazing! 🎉
```

**Note:** This is a temporary message. The `mastery_achieved` flag allows for future customization (e.g., visual rewards, sound effects, achievements, etc.)

## API Response Structure

### /api/continue Endpoint

Returns:
```json
{
  "success": true,
  "response": "WOW! You got it right! What color are apples?",
  "mastery_achieved": false,
  "correct_count": 2
}
```

**Fields:**
- `response`: The assistant's message
- `mastery_achieved`: Boolean indicating if mastery threshold was reached on this turn
- `correct_count`: Total number of correct answers so far

### When Mastery is Achieved

```json
{
  "success": true,
  "response": "🎉 WOW! You have now mastered the Apple! Congratulations! You answered 4 questions correctly! You're amazing! 🎉",
  "mastery_achieved": true,
  "correct_count": 4
}
```

## State Management

### New State: MASTERY_ACHIEVED

Added to `ConversationState` enum:
```python
class ConversationState(Enum):
    INITIAL_QUESTION = "initial"
    AWAITING_ANSWER = "awaiting"
    GIVING_HINT_1 = "hint1"
    GIVING_HINT_2 = "hint2"
    REVEALING_ANSWER = "reveal"
    CELEBRATING = "celebrating"
    MASTERY_ACHIEVED = "mastery"  # New!
```

Once a session reaches mastery, it transitions to this state.

## Database Schema

New column added to `sessions` table:

```sql
correct_count INTEGER DEFAULT 0
```

This persists across server restarts, so children can resume their progress.

## Configuration

### Changing Mastery Threshold

In your code:
```python
assistant = ChildLearningAssistant()
assistant.mastery_threshold = 5  # Require 5 correct answers
```

Or modify the default in `child_learning_assistant.py`:
```python
self.mastery_threshold = 4  # Change this value
```

## Frontend Integration Example

### JavaScript (React/Vue/etc.)

```javascript
async function sendChildResponse(sessionId, response) {
  const result = await fetch('/api/continue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      child_response: response
    })
  });

  const data = await result.json();

  // Display assistant's response
  displayMessage(data.response);

  // Show progress
  updateProgressBar(data.correct_count, 4);

  // Check for mastery
  if (data.mastery_achieved) {
    showConfetti();
    playSuccessSound();
    showAchievementBadge(sessionData.object);
    // Future: trigger custom reward UI here!
  }
}
```

### Progress Indicator

Display progress toward mastery:
```javascript
function updateProgressBar(correctCount, threshold) {
  const percentage = (correctCount / threshold) * 100;
  document.getElementById('progress-bar').style.width = `${percentage}%`;
  document.getElementById('progress-text').textContent =
    `${correctCount} / ${threshold} correct answers`;
}
```

## Testing

### Manual Testing with demo.py

```bash
python demo.py
```

Try answering questions correctly to see mastery in action:
1. Object: "Apple"
2. Category: "Fruit"
3. Answer questions correctly (e.g., "red", "on trees", "round", "sweet")
4. After 4 correct answers, you'll see the mastery message!

### Testing via API

```bash
# Start the server
python app.py

# In another terminal
curl -X POST http://localhost:5001/api/start \
  -H "Content-Type: application/json" \
  -d '{"object_name": "Dog", "category": "Animal"}'

# Continue answering correctly and watch correct_count increment
curl -X POST http://localhost:5001/api/continue \
  -H "Content-Type: application/json" \
  -d '{"session_id": "YOUR_SESSION_ID", "child_response": "Brown"}'
```

## Future Enhancements

The `mastery_achieved` flag enables future customization:

### Ideas for Custom Rewards
- **Visual Rewards**: Confetti animation, badges, stars
- **Sound Effects**: Success jingles, applause
- **Achievements**: "Apple Master", "Nature Expert"
- **Unlockables**: New objects, themes, avatars
- **Progress Tracking**: Mastery history, leaderboards
- **Certificates**: Printable achievement certificates
- **Share**: Share progress with parents/teachers

### Example: Custom Mastery Response

Instead of the default message, you can customize it:

```python
# In child_learning_assistant.py:continue_conversation()
if mastery_achieved:
    # Custom message with animation trigger
    response = {
        "type": "mastery",
        "object": self.current_object,
        "correct_count": self.correct_count,
        "message": f"You have now mastered the {self.current_object}!",
        "badge": "apple_master.png",
        "animation": "confetti"
    }
```

## Correctness Tracking Logic

The system tracks correctness at the state machine level:

```python
# In continue_conversation()
response, is_correct = self._get_model_response_with_validation()

# Increment counter only when correct
if is_correct:
    self.correct_count += 1

# Check threshold
if self.correct_count >= self.mastery_threshold:
    mastery_achieved = True
```

**Important Notes:**
- Hints don't count as correct (is_correct = false)
- Revealed answers don't count as correct
- Only actual child answers are evaluated for correctness
- Stuck responses ("I don't know") are not counted as correct

## Resetting Mastery

Mastery resets when:
1. Starting a new object: `assistant.start_new_object()`
2. Manual reset: `assistant.reset()`
3. Starting a new session via `/api/start`

## Error Handling

If `is_correct` is missing from model response:
- Defaults to `false`
- No correctness is recorded
- Session continues normally

## Performance Impact

- **Minimal**: Correctness evaluation happens during normal response generation
- **No extra API calls**: Uses existing structured JSON output
- **Database**: One additional INTEGER column per session
