# Category Prompts Guide

This guide explains how to fill in the `category_prompts.json` file with prompts for different object categories.

## File Structure

The `category_prompts.json` file has two main sections:

### 1. Level 1 Categories (Most Abstract)
These are the broadest categories. Examples: `animals`, `plants`, `objects`, `phenomena`.

### 2. Level 2 Categories (Medium Abstract)
These are more specific subcategories within level 1. Examples:
- Under `animals`: `spinal_animals`, `non_spinal_animals`
- Under `plants`: `natural_plants`, `cultivated_plants`

## How to Fill In Prompts

### Format
For each category, write a prompt that guides the LLM to ask appropriate questions for that category. The prompt should be placed in the `"prompt"` field.

### Example Structure

```json
{
  "level1_categories": {
    "animals": {
      "prompt": "When discussing animals, focus on behaviors, habitats, diets, and survival adaptations. Ask about how they move, communicate, and interact with their environment."
    },
    "plants": {
      "prompt": "When discussing plants, focus on growth processes, parts (roots, stems, leaves), reproduction, and their role in ecosystems. Ask about photosynthesis, seasons, and environmental needs."
    }
  },
  "level2_categories": {
    "spinal_animals": {
      "prompt": "For vertebrate animals, emphasize skeletal structure, movement capabilities, and complex behaviors. Discuss how having a backbone enables certain activities.",
      "parent": "animals"
    },
    "non_spinal_animals": {
      "prompt": "For invertebrate animals, focus on diverse body structures, unique adaptations like exoskeletons or shells, and survival strategies without backbones.",
      "parent": "animals"
    },
    "natural_plants": {
      "prompt": "For wild plants, emphasize natural growth cycles, seed dispersal, and ecological roles. Discuss adaptation to natural environments without human intervention.",
      "parent": "plants"
    },
    "cultivated_plants": {
      "prompt": "For cultivated plants, focus on how humans help them grow, farming practices, and the relationship between plants and people. Discuss domestication and agricultural purposes.",
      "parent": "plants"
    }
  }
}
```

## Prompt Writing Tips

1. **Be Specific**: Each prompt should guide the LLM toward category-appropriate questions
2. **Focus on Key Concepts**: Highlight the most important aspects of that category
3. **Use Action Words**: "Focus on...", "Emphasize...", "Ask about...", "Discuss..."
4. **Avoid Being Too Prescriptive**: Give guidance but allow creativity
5. **Consider the Audience**: Remember these are for young children (3-8 years old)

## How Prompts Are Combined

When a session starts, the system combines prompts in this order:

1. **Base System Prompt** (from database)
2. **Age-Specific Prompt** (from `age_prompts.json`)
3. **Category Prompts** (from `category_prompts.json`):
   - Level 1 category prompt
   - Level 2 category prompt

All these prompts work together to guide the LLM's questioning strategy.

## Example Usage Flow

If a user starts a session with:
- **Object**: "butterfly"
- **Age**: 5
- **Level 1 Category**: "animals"
- **Level 2 Category**: "non_spinal_animals"

The system will combine:
1. Base system prompt (teaching personality, JSON structure requirements)
2. Age 5-6 prompt (focus on "whats" and "hows")
3. Animals prompt (behaviors, habitats, etc.)
4. Non-spinal animals prompt (body structures, adaptations)

The LLM will then ask questions appropriate for a 5-year-old about a butterfly, focusing on what it is, how it moves/grows, and its invertebrate nature.

## Current Categories in Database

### Level 1:
- `animals`
- `plants`

### Level 2:
- `spinal_animals` (parent: animals)
- `non_spinal_animals` (parent: animals)
- `natural_plants` (parent: plants)
- `cultivated_plants` (parent: plants)

You can add more categories by following the same structure!
