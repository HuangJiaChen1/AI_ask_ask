# Final Fixes for Incorrect Answer & "I don't know" Handling

## Issues Found

### Issue 1: Stuck Detection Still Running Out of Tokens
**Symptom:**
```
"completion_tokens": 98,
"reasoning_tokens": 98,
"finish_reason": "MAX_TOKENS"
"content": ""  ← Empty!
```

**Root Cause:** Even with `max_tokens=100`, Gemini used ALL tokens for reasoning, leaving 0 for output.

**Fix:** Increased to `max_tokens=200` for stuck detection
```python
_is_child_stuck(): max_tokens=200  # Was 100, originally 10
```

---

### Issue 2: JSON Parsing Error - "Extra data: line 8 column 1 (char 303)"
**Symptom:**
```
, I need to create a JSON response.
The user's answer is "square"...
{
  "reaction": "...",
  "next_question": "..."
}
[more text here]  ← Extra data after JSON!
```

**Root Cause:** Gemini included reasoning text BEFORE and AFTER the JSON, despite instructions.

**Fix 1 - Improved JSON Extraction:**
- Old: Used regex `\{.*\}` (greedy match from first { to last })
- New: **Balanced brace matching** - finds first { and its matching }
- Validates extracted JSON before returning
- Falls back to greedy match if balanced extraction fails

```python
def extract_json_from_response(text):
    # 1. Try markdown code blocks
    # 2. Try balanced brace matching ← NEW
    # 3. Try greedy match (fallback)
    # 4. Validate all extractions
```

**Fix 2 - Stronger JSON Instructions:**
Changed from:
```
"IMPORTANT: You MUST respond with ONLY valid JSON..."
```

To:
```
CRITICAL INSTRUCTIONS:
1. Respond with ONLY valid JSON
2. NO text before the JSON
3. NO text after the JSON
4. NO markdown code blocks (no ```)
5. NO explanations or reasoning
6. Start directly with { and end directly with }
7. Your ENTIRE response must be parseable JSON

Example of CORRECT response:
{"key": "value"}

Example of WRONG response:
Here's the JSON: {"key": "value"}
```

---

## Complete Token Budget Summary

### After All Fixes:

| Function | max_tokens | Purpose |
|----------|-----------|---------|
| `config.json` (default) | 2000 | Base for all calls |
| `_get_initial_question()` | 2000 | JSON mode + reasoning |
| `_get_structured_response()` | 2000 | JSON mode + reasoning |
| `_generate_hint_only()` | 500 | Non-JSON but needs reasoning space |
| `_generate_reveal_answer()` | 500 | Non-JSON but needs reasoning space |
| `_is_child_stuck()` | 200 | Classification + reasoning |

### Token Usage Pattern:
For Gemini 2.5 Pro with reasoning:
```
max_tokens = 200
├── reasoning_tokens: ~190 (95%)
└── actual_output: ~10 (5%)
```

**Lesson:** Set `max_tokens` at least **20x the expected output length** for Gemini 2.5 Pro.

---

## Debug Logging Added

Now tracks entire conversation flow:
```python
[DEBUG] State BEFORE update: celebrating, stuck_count: 0
[DEBUG] API Response keys: dict_keys([...])
[DEBUG] LLM classification result: 'B' for input: 'square'
[DEBUG] is_stuck detection: False for response: 'square'
[DEBUG] Child attempting answer, resetting stuck_count to 0
[DEBUG] State AFTER update: awaiting, stuck_count: 0
[DEBUG] Calling _get_model_response_with_validation()
[DEBUG extract_json] Found balanced JSON: {...}
```

---

## Testing

Run the demo:
```bash
cd Gemini
python demo.py
```

Test cases:
1. **Correct answer** ("yellow" for banana color)
   - Should show ✅ emoji
   - Should celebrate

2. **Wrong answer** ("square" for banana shape)
   - Should show ❌ emoji
   - Should gently correct and ask next question

3. **"I don't know"** (first time)
   - Should detect stuck
   - Should give Hint 1

4. **"I don't know"** (second time)
   - Should give stronger Hint 2

5. **"I don't know"** (third time)
   - Should reveal answer and move on

---

## Files Modified

1. **child_learning_assistant.py**:
   - `extract_json_from_response()`: Added balanced brace matching + validation
   - `_call_gemini_api()`: Much stronger JSON instructions with examples
   - `_is_child_stuck()`: Increased max_tokens to 200
   - `continue_conversation()`: Added comprehensive debug logging
   - `_update_state()`: Added state transition debugging

2. **All previous fixes** remain in place:
   - Initial question: max_tokens=2000
   - Structured response: max_tokens=2000
   - Hints/reveals: max_tokens=500
   - Default config: max_tokens=2000

---

## Expected Behavior Now

### Correct Answer Flow:
```
User: "yellow"
→ LLM classifies as "B" (attempting)
→ is_stuck = False
→ State: AWAITING → CELEBRATING
→ ✅ "YES! WOW! That's right!"
→ Asks next question
```

### Wrong Answer Flow:
```
User: "square"
→ LLM classifies as "B" (attempting)
→ is_stuck = False
→ State: AWAITING → CELEBRATING
→ ❌ "Not quite! A banana is curvy, not square!"
→ Asks next question
```

### "I Don't Know" Flow:
```
User: "I don't know"
→ LLM classifies as "A" (stuck)
→ is_stuck = True, stuck_count = 1
→ State: AWAITING → GIVING_HINT_1
→ "That's okay! Think about fire trucks..."
```

---

## Key Improvements

1. **Robust JSON extraction** - handles text before/after JSON
2. **Sufficient token budget** - 200 tokens for classification, 2000 for JSON
3. **Clear instructions** - numbered list with examples for Gemini
4. **Comprehensive logging** - debug every step of the flow
5. **Validated extraction** - test that extracted JSON is parseable

All issues should now be resolved!
