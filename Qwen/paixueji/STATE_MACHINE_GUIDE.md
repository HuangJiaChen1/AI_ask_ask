# State Machine Implementation Guide

## What Changed

The assistant now uses a **4-layer enforcement system** to prevent giving direct answers when it should give hints:

### 1. LLM-Based Stuck Detection
Instead of hardcoding phrases like "I don't know", the system uses the LLM itself to classify if the child is stuck or attempting to answer. This handles variations like:
- "what?" → Stuck
- "dunno" → Stuck
- "huh?" → Stuck
- "Nope" → Stuck
- "help!" → Stuck
- "red" → Attempting to answer
- "maybe it's blue?" → Attempting to answer

**Accuracy:** 100% on test cases (see `test_stuck_detection.py`)

**Fallback:** If the LLM classification fails, it falls back to keyword matching.

### 2. State Machine
Tracks conversation state and enforces behavioral rules programmatically:

**States:**
- `INITIAL_QUESTION` - Starting the conversation
- `AWAITING_ANSWER` - Waiting for child's response
- `GIVING_HINT_1` - First "I don't know" → give subtle hints
- `GIVING_HINT_2` - Second "I don't know" → give stronger hints
- `REVEALING_ANSWER` - Third+ "I don't know" → now can reveal answer
- `CELEBRATING` - Child got it right → celebrate and move to next question

**Key Feature:** The system counts how many times the child is stuck and automatically transitions through hint levels before revealing the answer.

**Important:** When giving hints (GIVING_HINT_1 or GIVING_HINT_2), the "next_question" field should contain a **guiding question** to help them discover the answer to the CURRENT question, NOT a new topic question. Only after revealing the answer or celebrating a correct answer does the system move to a new question.

### 3. Structured JSON Output
The model must respond in JSON format:
```json
{
  "reaction": "WOW! That's interesting!",
  "hint_or_info": "Hmm, think about where you see them in the sky...",
  "next_question": "What do you see after it rains?",
  "should_give_answer": false
}
```

Each state gets specific instructions. For example:
- **GIVING_HINT_1**: "Give hints about the CURRENT question. 'next_question' should be a GUIDING question, NOT a new topic!"
- **GIVING_HINT_2**: "Give stronger hints. 'next_question' should be an EASIER guiding question about the SAME topic."
- **REVEALING_ANSWER**: "NOW you can set should_give_answer to TRUE and ask a NEW question."

### 4. Validation Loop
Before accepting a response, the system:
1. Checks if `should_give_answer` matches the current state
2. Scans for direct answer patterns like:
   - "it is X!"
   - "the answer is"
   - "(psst, it's X)"
   - "actually, X"
3. If validation fails → adds correction message + retries (up to 2 times)

## How to Use

### Running the Demo
```bash
python demo.py
```

Try this test sequence:
1. Object: "Rainbow"
2. Category: "Nature"
3. Response: "I don't know" (should get HINT 1)
4. Response: "I don't know" (should get HINT 2)
5. Response: "I don't know" (should get ANSWER revealed)

### Running the API
```bash
python app.py
```

The API works the same as before - state is automatically managed and persisted.

## Debugging

The system prints validation failures to console:
```
[Validation failed, attempt 1]: In state hint1, should_give_answer MUST be false
[Validation failed, attempt 2]: You gave a direct answer instead of a hint
```

## Database Changes

Three new columns added to `sessions` table:
- `state` - Current conversation state (e.g., "hint1", "awaiting")
- `stuck_count` - Number of "I don't know" responses
- `question_count` - Questions asked so far

**Auto-migration** runs on startup, so existing databases are updated automatically.

## Why This Is More Powerful Than Prompts

**Before:**
- ❌ Model ignores "don't give answers" in system prompt
- ❌ No way to enforce rules
- ❌ Inconsistent behavior

**After:**
- ✅ State machine enforces hint progression (1st hint → 2nd hint → reveal)
- ✅ Validation catches and rejects direct answers
- ✅ Structured output separates hints from answers explicitly
- ✅ Automatic retry with stronger corrections
- ✅ Consistent, predictable behavior

## Architecture Diagram

```
Child Response
    ↓
LLM Classification (stuck vs attempting to answer)
    ↓
State Machine (update stuck_count, transition state)
    ↓
Get Structured Response (JSON with state-specific instruction)
    ↓
Validate Response (check should_give_answer + scan for patterns)
    ↓
Valid? → Build text → Return to user
Invalid? → Add correction → Retry (max 2 attempts)
```

## Performance Impact

- **Latency:** ~20-30% increase due to stuck detection classification + JSON parsing + validation
- **API Calls:** 1 extra call per child response (for stuck detection) + main response call + optional retry calls
- **Cost:** Small increase due to stuck detection call (uses same model but with max_tokens=10, so very cheap)

## Configuration

No configuration needed! The system uses:
- Prompts from database (via `/api/update_prompt` or default)
- Same config.json for API credentials
- Automatic state persistence in sessions.db

## Testing

```bash
# Test state machine and database migration
python test_state_machine.py

# Test LLM-based stuck detection (100% accuracy)
python test_stuck_detection.py

# Test full conversation flow
python demo.py
```

## Common Issues

**Issue:** "Production prompts not found in database"
**Solution:** Run `python app.py` once to initialize default prompts, or use the API endpoint `/api/update_prompt`.

**Issue:** Model still gives direct answers
**Solution:** Check console for validation failures. The patterns in `_contains_direct_answer()` can be extended to catch more cases.

**Issue:** Responses feel too robotic
**Solution:** The structured JSON is converted back to natural text. If it feels unnatural, adjust the state instructions in `_get_state_instruction()`.
