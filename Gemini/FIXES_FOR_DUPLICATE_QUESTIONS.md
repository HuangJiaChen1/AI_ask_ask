# Fixes for Duplicate Questions and Redundant Category Input

## Issues Fixed

### Issue 1: Redundant Category Input
**Problem:** Demo was asking for both:
1. "Enter object category: fruit"
2. Level 1/2/3 categories later

This was confusing and redundant.

**Solution:**
- Removed the separate "category" input
- Now only asks for Level 1, 2, 3 categories
- Derives the `category` parameter from the most specific level provided:
  - Uses level3 if provided
  - Otherwise uses level2
  - Otherwise uses level1
  - Falls back to "object" if none provided

### Issue 2: LLM Asking Same Question Twice
**Problem:** LLM was rephrasing the same question multiple times:
```
"WHY do you think it has that peel? 🤔 What is the purpose of the banana's peel?"
```

This confuses children and makes answer validation difficult.

**Solution:** Updated all prompts to explicitly forbid asking the same question twice.

## Changes Made

### File: `demo.py`

**Before:**
```python
category = input("Enter object category: ").strip()
# ... later ...
level1_category = input("Level 1 category: ").strip()
level2_category = input("Level 2 category: ").strip()
```

**After:**
```python
# Removed separate category input
level1_category = input("Level 1 category: ").strip()
level2_category = input("Level 2 category (or Enter to skip): ").strip()
level3_category = input("Level 3 category (or Enter to skip): ").strip()

# Derive category from most specific level
category = level3_category or level2_category or level1_category or "object"
```

### File: `prompts.py`

**Added to SYSTEM_PROMPT:**
```python
CRITICAL RULE:
- Ask your question ONLY ONCE per response
- DO NOT rephrase or repeat the same question in different words
- Example WRONG: "Why does it grow? What makes it grow?" ✗
- Example CORRECT: "Why do you think it grows?" ✓
```

**Added to USER_PROMPT:**
```python
CRITICAL: Ask your question ONLY ONCE. Do not rephrase or repeat the same question in different words.
```

**Added to INITIAL_QUESTION_PROMPT:**
```python
CRITICAL RULES for full_response:
✗ DO NOT ask the same question twice in different ways
✗ DO NOT rephrase the question multiple times
✓ DO ask the question ONCE clearly at the end
✓ DO use a single, clear question - not two versions of the same question

IMPORTANT: Ask your main_question ONLY ONCE in the full_response.
DO NOT rephrase it or ask it again in different words.

Example of WRONG (asking twice):
"Why do you think it has that peel? 🤔 What is the purpose of the banana's peel?" ✗

Example of CORRECT (asking once):
"Let's think about that bright yellow peel... why do you think bananas have a peel?" ✓
```

**Added to STATE_INSTRUCTIONS_JSON:**
```python
CRITICAL: In your next_question, ask the question ONLY ONCE.
DO NOT rephrase or repeat the question in different words.
Example WRONG: "Why does it turn brown? What causes the browning?" ✗
Example CORRECT: "Why do you think it turns brown?" ✓
```

## New Input Flow

### Before:
```
Enter object name: banana
Enter object category: fruit          ← Redundant
Enter child's age: 8
Level 1 category: plants              ← Already provided "fruit" above
Level 2 category: cultivated_plants
```

### After:
```
Enter object name: banana
Enter child's age: 8
Level 1 category: plants
Level 2 category: cultivated_plants
Level 3 category: fruits

Category: fruits (derived from level 3)
```

## Testing

After these changes, test with:

```bash
python demo.py
```

**Test Case:**
- Object: banana
- Age: 8
- Level 1: plants
- Level 2: (skip)
- Level 3: (skip)

**Expected Output:**
- Category should be derived as "plants"
- LLM should ask ONE clear "why" question
- NO duplicate/rephrased questions

**Example Good Output:**
```
🍌 WOW! Bananas are fascinating! Why do you think they grow in bunches?
```

**Example Bad Output (Should NOT happen anymore):**
```
🍌 WOW! Why do they grow in bunches? What makes them grow together? ✗
```

## Benefits

1. ✅ **Cleaner Input Flow** - No redundant category question
2. ✅ **Flexible Categorization** - Can provide level 1, 2, or 3 as needed
3. ✅ **One Clear Question** - Child knows exactly what to answer
4. ✅ **Easier Validation** - Single question = single expected answer
5. ✅ **Better UX** - Less confusing for both child and parent

## Summary

- **Removed redundant category input** - use level categories instead
- **Added strict rules against duplicate questions** - ask once, clearly
- **Category derived automatically** - from most specific level provided
- **All prompts updated** - system, user, initial, and state instructions
