# Gemini 2.5 Reasoning Tokens Issue

## The Problem

Gemini 2.5 Pro uses an **extended reasoning** feature where it internally "thinks" before generating output. This reasoning uses up tokens from the `max_tokens` budget, often leaving very little room for actual content.

### Example from API Response:
```json
"usage": {
  "completion_tokens": 418,
  "reasoning_tokens": 416,  // 99.5% used for reasoning!
  "audio_tokens": 0
}
```

Out of 418 completion tokens:
- **416 tokens** = Internal reasoning (invisible to user)
- **~2 tokens** = Actual content (what we see)

### Symptoms:
1. **Truncated responses** - Only 115 characters returned when we needed full JSON
2. **Empty content errors** - "API returned empty content" when max_tokens too low
3. **JSON parsing failures** - Incomplete JSON that can't be parsed

## The Solution

### Before (Original):
```python
# config.json
"max_tokens": 1000  # Not enough!

# API calls
max_tokens=10   # Way too small for stuck detection
max_tokens=150  # Too small for hints/reveals
```

### After (Fixed):
```python
# config.json
"max_tokens": 2000  # Doubled default

# API calls - specific overrides
_get_initial_question(): max_tokens=2000      # JSON mode needs more
_get_structured_response(): max_tokens=2000   # JSON mode needs more
_generate_hint_only(): max_tokens=500         # Non-JSON but still needs room
_generate_reveal_answer(): max_tokens=500     # Non-JSON but still needs room
_is_child_stuck(): max_tokens=100            # Classification needs room
```

## Why This Works

Gemini 2.5 Pro allocates tokens like this:
```
Total max_tokens = Reasoning tokens + Output tokens
```

If you set `max_tokens=100`:
- Gemini might use 98 tokens for reasoning
- Only 2 tokens left for actual output = truncated response

If you set `max_tokens=2000`:
- Gemini might use 1800 tokens for reasoning
- 200 tokens left for output = full JSON response

## Key Takeaway

**For Gemini 2.5 Pro with reasoning:**
- Set `max_tokens` **10x higher** than the expected output length
- JSON mode needs even more (2000+ tokens)
- Short responses (A/B classification) still need 100+ tokens
- Monitor the `reasoning_tokens` field in API responses

## Files Modified

1. **config.json**: Increased default from 1000 → 2000
2. **child_learning_assistant.py**:
   - `_get_initial_question()`: Added max_tokens=2000
   - `_get_structured_response()`: Added max_tokens=2000
   - `_generate_hint_only()`: Increased 150 → 500
   - `_generate_reveal_answer()`: Increased 150 → 500
   - `_is_child_stuck()`: Increased 10 → 100

## Verification

Run the basic API test to see reasoning token usage:
```bash
cd Gemini
python test_api_basic.py
```

Look for:
```json
"completion_tokens": 418,
"reasoning_tokens": 416
```

This shows how many tokens Gemini uses for internal reasoning vs actual output.
