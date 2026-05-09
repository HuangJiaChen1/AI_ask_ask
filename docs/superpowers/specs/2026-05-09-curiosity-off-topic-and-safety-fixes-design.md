# Design: Curiosity Off-Topic Handling + Safety Fixes

**Date:** 2026-05-09
**Context:** IRL Verification Report 2026-05-08-v3 found 13 issues across 29 tasks. This spec addresses all identified flaws.
**Approach:** Answer+Bridge for off-topic curiosity; inject safety rules into all intent response prompts; targeted prompt tweaks for remaining issues.

---

## 1. CURIOSITY Intent — Off-Topic Handling

### 1.1 Problem
When a child exploring a lion asks "Why is the sky blue?", the model answered "Lions grow so big because..." — completely ignoring the child's question and delivering a non-sequitur lion fact. The prompt says "Stay on the child's exact question; do not drift sideways," but the model prioritizes `{object_name}` over `{child_answer}`.

### 1.2 Design: Answer + Bridge

The model already receives both `{child_answer}` and `{object_name}`, so it can self-detect off-topic questions. We restructure the CURIOSITY prompt with an explicit branch:

```
OFF-TOPIC CHECK — before writing any response:
  Ask yourself: "Is the child's question directly about {object_name}?"

  IF YES → follow normal 3-beat structure:
    BEAT 1: Direct answer about {object_name}
    BEAT 2: WOW detail amplifying that answer
    BEAT 3: Playful question growing from the WOW detail

  IF NO → follow BRIDGE structure:
    BEAT 1 — ANSWER THE EXACT QUESTION:
      Give a truthful, specific answer to what they asked. 1 sentence.

    BEAT 2 — BRIDGE TO {object_name}:
      Find ONE genuine, concrete connection between your answer and {object_name}.
      Use sensory comparisons, shared environments, or behaviors.
      GOOD: "...and lions breathe that same air when they roar across the plains!"
      GOOD: "...just like how a lion's golden fur looks brightest when the sun hits it!"
      BAD: "...and lions are blue too!" (false)
      BAD: "...which is interesting, just like lions are interesting." (lazy pivot)

    BEAT 3 — QUESTION ABOUT {object_name}:
      One playful question rooted firmly back in {object_name}.
```

### 1.3 Edge Case: Weak or Impossible Bridge

If no genuine connection exists after one attempt, fall back to a gentle pivot:

```
"That's a cool fact about the sky! Want to know something surprising about lions?"
```

### 1.4 State Tracking (Lightweight)

Even with bridging, 3+ consecutive off-topic questions signal the child may be done with the current object. Track `consecutive_off_topic_curiosity` in the state container:
- Increment when curiosity question is off-topic (determined by model, not hardcoded)
- Reset on any on-topic response or non-curiosity intent
- At threshold 2, the system offers a topic switch on the next curiosity turn

### 1.5 Files Modified

- `paixueji_prompts.py` — `CURIOSITY_INTENT_PROMPT` (restructured with OFF-TOPIC CHECK and BRIDGE structure)
- `state.py` — Add `consecutive_off_topic_curiosity` field (optional for this phase)

---

## 2. Safety Rules Injection into All Intent Response Prompts

### 2.1 Problem

`SENSORY_SAFETY_RULES` is defined in `paixueji_prompts.py` and injected into follow-up **question** prompts, but is **absent from all 18 `*_INTENT_PROMPT` templates**. The attribute pipeline reuses intent prompts via `generate_attribute_activation_response_stream`, so response generation has zero safety guardrails.

This caused 6 touch-invitation violations:
- Task 16 (Social, ordinary): "feel how soft its fur is" + uses banned word "pet"
- Task 21 (Clarifying IDK, attribute): "Imagine if you touched"
- Task 22 (Clarifying Wrong, attribute): "Go ahead and give it a gentle touch!"
- Task 25 (Play, attribute): "try to pet the spikes"
- Task 26 (Emotional, attribute): "touch it very gently with just one finger"
- Task 28 (Concept Confusion, attribute): "if you touch the flat parts"

### 2.2 Design

Add `{sensory_safety_rules}` placeholder to every intent prompt, placed before the PROHIBITIONS section. This ensures safety constraints are visible at response-generation time.

**Prompts to modify (all in `paixueji_prompts.py`):**
1. `CURIOSITY_INTENT_PROMPT`
2. `CLARIFYING_IDK_INTENT_PROMPT`
3. `CLARIFYING_OPEN_ENDED_IDK_INTENT_PROMPT`
4. `GIVE_ANSWER_IDK_INTENT_PROMPT`
5. `GIVE_ANSWER_OPEN_ENDED_IDK_INTENT_PROMPT`
6. `CLARIFYING_WRONG_INTENT_PROMPT`
7. `CLARIFYING_CONSTRAINT_INTENT_PROMPT`
8. `CORRECT_ANSWER_INTENT_PROMPT`
9. `INFORMATIVE_INTENT_PROMPT`
10. `PLAY_INTENT_PROMPT`
11. `EMOTIONAL_INTENT_PROMPT`
12. `AVOIDANCE_INTENT_PROMPT`
13. `BOUNDARY_INTENT_PROMPT`
14. `ACTION_INTENT_PROMPT`
15. `SOCIAL_INTENT_PROMPT`
16. `SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT`
17. `CONCEPT_CONFUSION_INTENT_PROMPT`
18. `CLASSIFICATION_FALLBACK_PROMPT`

### 2.3 Runtime Injection

Modify two generator functions in `stream/response_generators.py`:

- `generate_intent_response_stream` — pass `sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES` to template `.format()`
- `generate_attribute_activation_response_stream` — pass `sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES` to template `.format()`

### 2.4 Files Modified

- `paixueji_prompts.py` — Add `{sensory_safety_rules}` placeholder to all 18 intent prompts
- `stream/response_generators.py` — Pass safety rules in both response generators

---

## 3. Action Subtype C — Prevent Question-Asking

### 3.1 Problem

TYPE C prompt says "Accept warmly and offer one option," but the model appends a curiosity-style question: "No worries — let's make it more fun! **How do you think** an apple grows..."

### 3.2 Design

In `ACTION_INTENT_PROMPT` TYPE C section:
- Add explicit prohibition: "Do NOT ask a question. Offer a single concrete option as a statement."
- Update example from "No worries — let's make it more fun!" to "No worries — let's look at the apple's skin instead."

### 3.3 Files Modified

- `paixueji_prompts.py` — `ACTION_INTENT_PROMPT` TYPE C section

---

## 4. Action Subtype D — Topic Switch Vocabulary

### 4.1 Problem

Model produced "much furrier and wiggier" — awkward invented word.

### 4.2 Design

Add to `TOPIC_SWITCH_RESPONSE_PROMPT`: "Use natural, simple comparisons. Avoid invented words like 'wiggier'."

### 4.3 Files Modified

- `paixueji_prompts.py` — `TOPIC_SWITCH_RESPONSE_PROMPT`

---

## 5. Emotional Mild — Remove Ambiguous Physical Approach

### 5.1 Problem

"Want to look even more closely and find the most colorful spot?" could be interpreted as inviting physical approach to a real puppy.

### 5.2 Design

In `EMOTIONAL_INTENT_PROMPT` BEAT 2 for positive emotions, change:
- FROM: "Want to look even more closely and find the most colorful spot?"
- TO: "Want to use your eyes like a detective and find the most colorful spot?"

### 5.3 Files Modified

- `paixueji_prompts.py` — `EMOTIONAL_INTENT_PROMPT`

---

## 6. Boundary — Mandatory Safety Reason

### 6.1 Problem

Boundary response validated curiosity and offered alternative but omitted the brief safety reason.

### 6.2 Design

In `BOUNDARY_INTENT_PROMPT`, make the safety reason a mandatory step:

```
STRUCTURE:
1. VALIDATE CURIOSITY: "I totally get why you'd want to..."
2. BRIEF SAFETY REASON (required): Explain why the boundary exists in one simple sentence.
   "Some mushrooms could make our tummies feel really sick."
3. EXCITING ALTERNATIVE: "Instead, do you want to..."
```

### 6.3 Files Modified

- `paixueji_prompts.py` — `BOUNDARY_INTENT_PROMPT`

---

## 7. Verification Plan

After implementing all fixes:

1. Run `python scripts/irl_verify.py --config scripts/irl_verify_all_intents.json` to regenerate the verification report
2. Manually audit all model outputs for:
   - No touch/smell/taste invitations in any response
   - Curiosity responses answer the exact question asked (with bridge back to object if off-topic)
   - Action Subtype C offers a statement, not a question
   - Boundary responses always include a safety reason
   - Topic switch uses natural vocabulary
   - Emotional mild uses sight-only language

---

## Summary of Files to Modify

| File | Changes |
|------|---------|
| `paixueji_prompts.py` | Restructure `CURIOSITY_INTENT_PROMPT`; add `{sensory_safety_rules}` to all 18 intent prompts; fix `ACTION_INTENT_PROMPT` TYPE C; update `TOPIC_SWITCH_RESPONSE_PROMPT`; fix `EMOTIONAL_INTENT_PROMPT`; fix `BOUNDARY_INTENT_PROMPT` |
| `stream/response_generators.py` | Pass `sensory_safety_rules` in `generate_intent_response_stream` and `generate_attribute_activation_response_stream` |
