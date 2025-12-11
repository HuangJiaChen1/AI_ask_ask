# Gemini Token Budget - Final Configuration

## The Issue with Gemini 2.5 Pro

Gemini 2.5 Pro uses **extended reasoning** where it internally thinks through problems before generating output. This reasoning consumes a large portion of the token budget.

### Typical Token Usage Pattern:
```json
"usage": {
  "completion_tokens": 1000,
  "reasoning_tokens": 900,    // 90% used for internal thinking
  "audio_tokens": 0
}
```

Out of 1000 completion tokens:
- **900 tokens** = Internal reasoning (invisible to us)
- **100 tokens** = Actual visible output

---

## Evolution of Token Budgets

### Initial Attempt (FAILED):
```python
_is_child_stuck(): max_tokens=10
_generate_hint(): max_tokens=150
_generate_reveal(): max_tokens=150
```
**Result:** Empty responses, truncated mid-sentence

### Second Attempt (PARTIAL):
```python
_is_child_stuck(): max_tokens=100
_generate_hint(): max_tokens=500
_generate_reveal(): max_tokens=500
```
**Result:** Still truncated, not enough for full responses

### Final Configuration (WORKING):
```python
# Classification
_is_child_stuck(): max_tokens=200

# Hint generation
_generate_hint_only(): max_tokens=1000

# Answer reveal
_generate_reveal_answer(): max_tokens=1000

# JSON mode (needs most)
_get_initial_question(): max_tokens=2000
_get_structured_response(): max_tokens=2000

# Default
config.json: max_tokens=2000
```

---

## Complete Token Budget Table

| Function | max_tokens | Purpose | Reason for Size |
|----------|-----------|---------|-----------------|
| **config.json (default)** | 2000 | Base for all calls | Ensures generous budget |
| **_get_initial_question()** | 2000 | Generate first question (JSON) | JSON + reasoning + full response |
| **_get_structured_response()** | 2000 | Process child's answer (JSON) | JSON + reasoning + reaction + next Q |
| **_generate_hint_only()** | 1000 | Create hint question | Creative thinking + full hint sentence |
| **_generate_reveal_answer()** | 1000 | Reveal answer + new question | Answer explanation + transition |
| **_is_child_stuck()** | 200 | A/B classification | Simple output but needs reasoning space |

---

## Token Usage Examples

### Stuck Detection (200 tokens):
```
Prompt: "Is child stuck or attempting? Response: 'I don't know'"
Usage:
  reasoning_tokens: 180
  output: "A" (just 1 character!)
Total: 181 tokens
```
**Lesson:** Even 1-character output needs 200 tokens due to reasoning.

### Hint Generation (1000 tokens):
```
Prompt: "Create an easier question with same answer 'yellow'"
Usage:
  reasoning_tokens: 850
  output: "That's okay! Let me help you think... What color is the big, bright sun?"
Total: ~900 tokens
```
**Lesson:** Creative tasks use most tokens for thinking, output is small.

### JSON Response (2000 tokens):
```
Prompt: "Respond with JSON containing reaction, next_question, is_correct..."
Usage:
  reasoning_tokens: 1800
  output: {JSON object with multiple fields}
Total: ~1900 tokens
```
**Lesson:** Structured output needs maximum budget.

---

## Warning Signs of Insufficient Tokens

### Symptom 1: Empty Content
```json
"content": "",
"finish_reason": "MAX_TOKENS"
```
**Diagnosis:** All tokens used for reasoning, none left for output

### Symptom 2: Truncated Mid-Sentence
```
"What color is the big, bright"
```
**Diagnosis:** Ran out of tokens before completing thought

### Symptom 3: Incomplete JSON
```json
{"reaction": "Great!", "next_question": "What
```
**Diagnosis:** Token limit hit while generating JSON

---

## Detection & Monitoring

We now log truncation warnings:
```python
[WARNING] Response was truncated due to MAX_TOKENS limit!
[WARNING] Token usage: {'reasoning_tokens': 998, 'completion_tokens': 1000}
[WARNING] Response may be truncated (doesn't end with punctuation): '...big, bright'
```

These warnings help identify when to increase max_tokens further.

---

## Rules of Thumb for Gemini 2.5 Pro

1. **For simple classification (A/B):** Use 200+ tokens
   - Even though output is 1 character, reasoning uses 180+

2. **For short creative text:** Use 1000+ tokens
   - Hints, explanations, short responses

3. **For structured JSON:** Use 2000+ tokens
   - Multiple fields + reasoning = high usage

4. **Safety factor:** Multiply expected output by 20x
   - Want 50 tokens output? Set max_tokens=1000
   - Want 100 tokens output? Set max_tokens=2000

5. **When in doubt:** Go higher
   - Extra tokens don't cost more if unused
   - Too few tokens = broken responses

---

## Testing & Verification

After setting these values, test:

1. **"I don't know" 3 times** - Check hints aren't cut off
2. **Wrong answer** - Check correction isn't cut off
3. **Correct answer** - Check celebration + next question complete
4. **Long conversations** - Check no accumulation issues

Monitor logs for:
- `[WARNING] Response was truncated`
- `[WARNING] Response may be truncated`
- `[ERROR] Empty content`

If you see these, increase max_tokens for that function.

---

## Cost Considerations

**Q:** Won't 2000 tokens cost more?

**A:** No! You only pay for tokens actually used. Setting max_tokens=2000 doesn't mean you'll use 2000 every time. It means "allow up to 2000 if needed."

Example:
```
max_tokens=2000 set
actual usage: 900 tokens (450 reasoning + 450 output)
You pay for: 900 tokens (not 2000)
```

**Lesson:** It's better to set high limits and pay for actual usage than set low limits and get broken responses.

---

## Summary

**The Golden Rule for Gemini 2.5 Pro:**

> Set `max_tokens` at least **20x your expected output length** to account for reasoning tokens.

**Current Configuration (Final):**
- Classification: 200 tokens
- Short responses: 1000 tokens
- JSON responses: 2000 tokens
- Default: 2000 tokens

This ensures all responses are complete and not truncated.
