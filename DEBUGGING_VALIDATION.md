# Debugging Validation Issues

## Why Validation Might Fail

### 1. **Regex Patterns Too Narrow**
The model can phrase direct answers without trigger words:
- ❌ Catches: "here's a secret: X"
- ✅ Misses: "They drink water from tree roots" (direct fact, no trigger)

**Solution**: Use LLM-based semantic detection instead of pure regex.

### 2. **LLM Classification Not Running**
Possible causes:
- API timeout
- Exception in classification call
- Falling back to weak regex patterns

**Solution**: Check console output for `[Warning]` messages.

### 3. **Database Prompts Are Old**
The default prompts in `database.py` might not have strict instructions.

**Solution**: Update prompts via `/api/update_prompt` or modify `database.py:42-114`.

### 4. **Validation Passing When It Shouldn't**
The LLM classifier might wrongly classify a direct answer as a hint.

**Solution**: Review classification prompt or add more pattern checks.

### 5. **Max Retries Exhausted**
If validation fails 3 times, the system accepts the last response anyway.

**Solution**: Check if you see 3 validation failures in console.

## Diagnostic Steps

### Step 1: Run Diagnostic Script

```bash
python diagnose_validation.py
```

This will show you:
- Raw JSON from the model
- What validation caught
- How many retries happened
- Final accepted response

### Step 2: Check Console Output

Look for these indicators:

**Good Signs:**
```
[Raw JSON from LLM]:
  should_give_answer: False
  hint_or_info: Think about where birds sit...

[Validation PASSED] State: hint1
```

**Problem Signs:**
```
[Raw JSON from LLM]:
  hint_or_info: They drink water from tree roots

[Direct answer detected by pattern]: they\s+drink
[VALIDATION FAILED - Attempt 1/3]
Reason: You gave a direct answer instead of a hint
```

**Worst Case:**
```
[VALIDATION FAILED - Attempt 1/3]
[VALIDATION FAILED - Attempt 2/3]
[VALIDATION FAILED - Attempt 3/3]
# Still outputs the bad response after 3 failures
```

### Step 3: Identify Root Cause

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| No `[Direct answer detected]` messages | LLM classifier not working | Check API connectivity |
| Shows `[Warning] LLM answer detection failed` | API timeout or error | Check error details |
| `[Direct answer detected]` but validation passes | Topic jump detection failing | Check `_is_jumping_to_new_topic()` |
| No `[VALIDATION FAILED]` at all | Validation not running | Check state machine transitions |
| 3 failed attempts, bad response shown | Model persistently violating rules | Strengthen prompts or increase retries |

## Enhanced Validation (Already Implemented)

### 1. **LLM-Based Answer Detection**
```python
# Instead of regex patterns, use semantic understanding
classification_prompt = """
Text: "{text}"
Is this:
A) A genuine HINT
B) A DIRECT ANSWER/EXPLANATION
"""
```

### 2. **Increased Retries**
Changed from 2 to 3 retries (max_retries=3).

### 3. **Better Debug Output**
Shows:
- Raw JSON from model
- Validation pass/fail with details
- Detected patterns
- Retry attempts

### 4. **Stricter Fallback Patterns**
```python
fallback_patterns = [
    r"they\s+(?:are|drink|eat|grow|live|come)",
    r"it'?s\s+(?:like|because|made of)",
    r"(?:apples|it|they)\s+(?:have|contain|are full of)",
]
```

### 5. **Topic Jump Detection**
Uses LLM to compare previous question vs next question:
```
Previous: "Why does it make a crunchy sound?"
Next: "Do apples float in water?"
LLM: "B - COMPLETELY NEW question" → REJECTED
```

## Testing Validation

### Test Case 1: Direct Answer in Hint
```bash
python diagnose_validation.py
```

Expected: See `[Direct answer detected by LLM]` and retry.

### Test Case 2: Topic Jumping
Child stuck on "Why crunchy?"
Model tries to ask about floating.

Expected: See `"You're asking about a NEW topic"` and retry.

### Test Case 3: Meta-Instructions
Model outputs `*(Wait for child's answer)*`

Expected: Filtered out by `_filter_meta_instructions()`.

## Performance Impact

Each validation adds:
- **1-2 extra LLM calls** per response (answer detection + topic jump detection)
- **~200-500ms latency** per call
- **Minimal cost** (max_tokens=10 for classification)

If too slow, you can:
1. Disable LLM classification (use only regex)
2. Cache classification results
3. Use faster model for classification

## Configuration

### Increase Retries
In `child_learning_assistant.py`:
```python
def _get_model_response_with_validation(self, max_retries=5):  # Increase to 5
```

### Disable Debug Output
Comment out print statements in `_get_model_response_with_validation()`.

### Use Faster Classification Model
In `config.json`:
```json
{
  "classification_model": "qwen-turbo",  // Faster, cheaper
  "model_name": "qwen-plus"              // Main model
}
```

## Common Issues & Solutions

### Issue: "They drink water from tree roots" passes validation

**Diagnosis**: LLM classifier thinks it's a hint.

**Solution**: Add explicit examples to classification prompt or add regex pattern:
```python
r"they\s+drink\s+\w+\s+from"
```

### Issue: Validation always fails, exhausts retries

**Diagnosis**: Instructions too strict or model can't follow JSON format.

**Solution**:
1. Check if JSON parsing works: look for `[Warning] Failed to parse JSON`
2. Simplify state instructions
3. Increase temperature slightly

### Issue: Meta-instructions still showing

**Diagnosis**: Pattern not catching the format.

**Solution**: Add pattern to `_filter_meta_instructions()`:
```python
r'your_pattern_here'
```

## Next Steps for Production

1. **Log validation failures** to database for analysis
2. **A/B test** different strictness levels
3. **Monitor retry rates** - if >30%, instructions need improvement
4. **Collect examples** of failures to improve patterns
5. **Consider fine-tuning** model on good hint examples
