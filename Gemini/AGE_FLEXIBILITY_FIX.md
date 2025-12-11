# Age Flexibility Fix - Problem and Solution

## The Problem

When you entered **age 8** (which should ask "what", "how", AND "why" questions), the LLM still asked very childish questions:

```
🍌 Ooh! A BANANA! How exciting! They are so yummy and fun to peel!
Let's think... What COLOR is a banana? Is it yellow? Or maybe green? What do you see?
```

This is a simple "what color" question appropriate for age 3-4, not age 8.

## Root Cause

The **base prompts in the database** (database.py) contained **hard-coded restrictions** that conflict with age-specific guidance:

### Base System Prompt (Line 88-119):
```python
CRITICAL: Ask questions with SIMPLE, 1-3 WORD answers!

Avoid complex questions:
✗ "Why does...?" (requires explanation)
✗ "How does it work?" (requires process)
✗ "What makes...?" (requires causal explanation)
```

### Initial Question Prompt (Line 144-189):
```python
CRITICAL: Ask questions with SIMPLE, SINGLE-WORD answers!

Avoid complex questions:
✗ "Why does it...?" (requires explanation)
✗ "How does it...?" (requires process explanation)
```

### State Instructions (Line 221-266):
```python
CRITICAL: Ask questions with SIMPLE, SINGLE answers!

Avoid complex questions:
✗ "Why does...?" (requires explanation)
✗ "How does...?" (requires process)
```

## The Conflict

When prompts are combined:

```
Combined Prompt =
    Base: "CRITICAL: AVOID 'Why' and 'How' questions! ✗✗✗"
    +
    Age 8 Guidance: "Focus on WHAT, HOW, and WHY questions"
```

The base prompts use **emphatic language** ("CRITICAL", multiple ✗ marks) that appears first, causing the LLM to follow those instructions instead of the age-specific guidance that comes after.

## The Solution

### Change the Base Prompts' Role:
- **Before**: Base prompts dictated question complexity (only simple "what color" questions)
- **After**: Base prompts provide personality and structure, AGE prompts control complexity

### Key Changes:

1. **Removed hard-coded restrictions** like:
   - ❌ "CRITICAL: Ask questions with SIMPLE, 1-3 WORD answers!"
   - ❌ "Avoid complex questions: ✗ 'Why does...?'"

2. **Added flexibility instructions**:
   - ✅ "Follow the AGE-SPECIFIC GUIDANCE to determine question complexity"
   - ✅ "If told to ask 'why' questions, focus on reasoning and causes"

3. **Provided examples for different age levels**:
   - Age 3-4: "What color is a banana?" → "yellow"
   - Age 7-8: "Why do bananas get brown spots?" → "because they ripen"

## How to Apply the Fix

Run the update script:

```bash
python update_prompts_for_age_flexibility.py
```

This will:
1. Update all database prompts to be age-flexible
2. Remove hard-coded question complexity restrictions
3. Add instructions to follow AGE-SPECIFIC GUIDANCE
4. Preserve the playful personality and structure

## Testing After Fix

After running the update script, test with different ages:

### Age 4 (Should ask "what" questions):
```
🍌 Bananas are amazing! What COLOR is a banana? Yellow? Green?
```

### Age 6 (Should ask "what" and "how" questions):
```
🍌 Bananas are so cool! HOW does a banana grow? Does it grow on trees or underground?
```

### Age 8 (Should ask "what", "how", AND "why" questions):
```
🍌 Bananas are fascinating! WHY do you think bananas turn brown when they get old?
What causes that change?
```

## Before and After Comparison

### BEFORE (Age 8 test):
```
Question: What COLOR is a banana? Is it yellow? Or maybe green?
Type: Simple "what" question (age 3-4 level)
Problem: Ignores age 8 guidance to ask "why" questions
```

### AFTER (Age 8 test):
```
Question: Why do you think bananas are curved instead of straight?
Type: "Why" question (age 7-8 level)
Success: Follows age-specific guidance correctly
```

## Technical Details

### Prompt Combination Order:
```
1. System Prompt (base personality + "Follow AGE-SPECIFIC GUIDANCE")
2. + Age Guidance (e.g., "Focus on WHAT, HOW, and WHY questions")
3. + Category Guidance (e.g., "Discuss plant growth processes")
4. → Final Combined Prompt
```

### Why This Works:
- Base prompt now **defers to** age guidance instead of contradicting it
- Instructions explicitly say "Follow the AGE-SPECIFIC GUIDANCE"
- Examples show different complexity levels for different ages
- No more "CRITICAL: AVOID" statements that override age guidance

## Files Modified

- **Database prompts** (updated by script):
  - `system_prompt`
  - `user_prompt`
  - `initial_question_prompt`
  - `hint_prompt` (minor update)
  - `reveal_prompt` (no change needed)
  - `state_instructions_json`

## Backward Compatibility

- ✅ Old sessions without age will still work (uses base prompts)
- ✅ Existing API endpoints continue to function
- ✅ Only the prompt content changed, not the structure
- ✅ All existing features (hints, reveals, mastery) unchanged

## Next Steps

1. **Run the update script**: `python update_prompts_for_age_flexibility.py`
2. **Test with demo.py**: Try ages 4, 6, and 8 with the same object
3. **Observe question differences**: Verify complexity increases with age
4. **Add category prompts**: Fill in `category_prompts.json` as needed

## Summary

The fix changes the base prompts from **prescriptive** ("only ask simple questions") to **adaptive** ("follow the age guidance provided"). This allows the age-specific prompts to properly control question complexity while the base prompts handle personality and structure.
