# Testing Scenarios for Age and Category Prompting

This document outlines different test scenarios to verify the exception handling and fallback mechanisms.

## Scenario 1: Full Information (All Prompts Used)
**Input:**
- Object: "butterfly"
- Category: "insect"
- Age: 5
- Level 1: "animals" (exists in database)
- Level 2: "non_spinal_animals" (exists in database)

**Expected Behavior:**
- Uses base prompt + age prompt (5-6 group) + both category prompts
- Output: `[INFO] Using age-appropriate prompting for age: 5`
- Output: `[INFO] Using category prompts: Level 1: animals, Level 2: non_spinal_animals`
- LLM asks "what" and "how" questions about animals and invertebrates

## Scenario 2: Age Only (No Categories)
**Input:**
- Object: "car"
- Category: "vehicle"
- Age: 7
- Level 1: (press Enter to skip)
- Level 2: (press Enter to skip)

**Expected Behavior:**
- Uses base prompt + age prompt (7-8 group) only
- Output: `[INFO] Using age-appropriate prompting for age: 7`
- Output: `[INFO] No categories specified. Using base prompts without category-specific guidance.`
- LLM asks "what", "how", and "why" questions

## Scenario 3: Categories Not in Database (Fallback)
**Input:**
- Object: "computer"
- Category: "technology"
- Age: 6
- Level 1: "technology" (NOT in database)
- Level 2: "electronic_devices" (NOT in database)

**Expected Behavior:**
- Uses base prompt + age prompt only (categories are skipped)
- Output: `[INFO] Using age-appropriate prompting for age: 6`
- Output: `[WARNING] Categories not found in database: Level 1: technology, Level 2: electronic_devices`
- Output: `[INFO] Continuing with available prompts. Add these categories to category_prompts.json if needed.`
- LLM still works, using age-appropriate questions without category guidance

## Scenario 4: Mixed (One Category Found, One Not)
**Input:**
- Object: "rose"
- Category: "flower"
- Age: 4
- Level 1: "plants" (exists in database)
- Level 2: "flowers" (NOT in database)

**Expected Behavior:**
- Uses base prompt + age prompt + level 1 category prompt
- Output: `[INFO] Using age-appropriate prompting for age: 4`
- Output: `[INFO] Using category prompts: Level 1: plants`
- Output: `[WARNING] Categories not found in database: Level 2: flowers`
- Output: `[INFO] Continuing with available prompts. Add these categories to category_prompts.json if needed.`
- LLM asks "what" questions about plants

## Scenario 5: No Age or Categories (Pure Base Prompt)
**Input:**
- Object: "ball"
- Category: "toy"
- Age: (press Enter to skip)
- Level 1: (press Enter to skip)
- Level 2: (press Enter to skip)

**Expected Behavior:**
- Uses only base prompt from database
- Output: `[INFO] No age specified. Using base prompts without age-specific guidance.`
- Output: `[INFO] No categories specified. Using base prompts without category-specific guidance.`
- LLM asks questions based purely on base system prompt

## Scenario 6: Empty Category Database File
**Setup:** Empty all prompts from `category_prompts.json` (but keep structure)

**Input:**
- Object: "dog"
- Category: "animal"
- Age: 5
- Level 1: "animals"
- Level 2: "spinal_animals"

**Expected Behavior:**
- Uses base prompt + age prompt only
- Output: `[INFO] Using age-appropriate prompting for age: 5`
- Output: `[WARNING] Categories not found in database: Level 1: animals, Level 2: spinal_animals`
- System continues gracefully without crashing

## How to Test

1. **Before testing:** Make sure `category_prompts.json` is filled with some prompts (or leave empty to test fallback)

2. **Run demo:**
   ```bash
   python demo.py
   ```

3. **Try each scenario above** and verify the output messages match expected behavior

4. **Observe LLM responses:**
   - With age 4: Should ask simpler "what" questions
   - With age 7-8: Should ask more complex "why" questions
   - With category prompts: Should incorporate category-specific themes
   - Without category prompts: Should still work normally

## Key Points

✅ **System never crashes** when categories are missing
✅ **Age prompts always work** regardless of category status
✅ **Clear feedback** about which prompts are being used
✅ **Graceful degradation** - system works with any combination of inputs
✅ **User-friendly warnings** guide users to add missing categories
