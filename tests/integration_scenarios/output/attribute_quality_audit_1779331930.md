# Manual Quality Audit Report

Auditor: Claude  
Date: 2026-05-21  
Object: fluffy cat | Attribute: texture | Age: 6

---

## Executive Summary

- **14 intents tested**, all produced output successfully
- **10/14 correct classifications** by `classify_intent`
- **4 intents have quality issues** that require prompt tuning
- **0 hard failures** on outside facts or property switching in the strict sense
- **Main issue**: prompt examples contradict prohibition rules in 2 intents

---

## Classification Audit

| Intent | Predicted | Match | Notes |
|--------|-----------|-------|-------|
| curiosity | CURIOSITY | YES | |
| concept_confusion | CONCEPT_CONFUSION | YES | |
| clarifying_idk | CLARIFYING_IDK | YES | |
| clarifying_wrong | CORRECT_ANSWER | NO | "sandpaper" treated as sensory description, not wrong |
| clarifying_constraint | CLARIFYING_CONSTRAINT | YES | |
| correct_answer | CORRECT_ANSWER | YES | |
| informative | CORRECT_ANSWER | NO | Comparison seen as direct answer, not info-sharing |
| play | PLAY | YES | |
| emotional | EMOTIONAL | YES | |
| avoidance | ACTION | NO | "Let's talk about dogs" seen as command, not avoidance |
| boundary | AVOIDANCE | NO | "boring" mapped to avoidance, not boundary-testing |
| action | ACTION | YES | |
| social | SOCIAL | YES | |
| social_acknowledgment | SOCIAL_ACKNOWLEDGMENT | YES | |

**Classifier accuracy: 71% (10/14)**. The 4 mismatches are edge cases where child inputs are ambiguous between adjacent intent categories. This is acceptable for a lightweight classifier.

---

## Per-Intent Quality Judgment

### 1. CURIOSITY — GOOD
- Angle lock: YES (soft, squishy, prickly — all texture)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — honors curiosity, invites observation, closing question about texture
- Question quality: GOOD — open-ended comparison

### 2. CONCEPT_CONFUSION — NEEDS FIX
- Angle lock: YES (fuzzy, smooth, flat, bumpy, thick — all texture)
- No outside facts: PARTIAL — defines "fuzzy" instead of redirecting to observation
- Child-friendly: YES
- **Strategy match: NO** — prompt says "DO NOT defend with facts", but model explains: "Fuzzy is just a word for when something looks like it has lots of tiny, soft bits sticking out all over it."
- **Root cause**: The prompt prohibits "introduce new vocabulary" but the model interprets explaining an already-introduced word as acceptable. The BEAT 2 instruction "Acknowledge their observation and let go of your prior claim" is too vague.
- **Fix**: Add explicit prohibition: "Do NOT define, explain, or teach vocabulary — redirect to observation instead."

### 3. CLARIFYING_IDK — GOOD
- Angle lock: YES (lying flat, messy, sticking out, feel — all texture)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — accepts "I don't know", scaffolds with concrete hint (tail), low-pressure question
- Question quality: GOOD

### 4. CLARIFYING_WRONG — GOOD
- Angle lock: YES (feel, texture)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — warm acknowledgment without correction, reframe, re-engagement question
- Question quality: GOOD

### 5. CLARIFYING_CONSTRAINT — GOOD
- Angle lock: YES (fluffy fur, fabric, squishy, firm — all texture)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — validates constraint, redirects to imagined texture, open question
- Question quality: GOOD

### 6. CORRECT_ANSWER — NEEDS FIX
- **Angle lock: NO** — switches from texture to length/location: "the fur around the ears looks much shorter and finer than the long, thick hair on the belly."
- No outside facts: YES
- Child-friendly: YES
- **Strategy match: NO** — prompt says "extend same observation_angle", but model extends to length and body-part location instead of staying in texture
- **Root cause**: The prompt says "invite them to see one more aspect of the SAME observation_angle" but "aspect" is too broad. The model interprets "shorter/finer vs long/thick" as a texture aspect, but this is actually a length comparison.
- **Fix**: Add explicit restriction: "The extension must be another texture quality (e.g., smooth/rough/soft/prickly/bumpy), NOT length, color, or location."

### 7. INFORMATIVE — NEEDS FIX
- Angle lock: PARTIAL — introduces dog comparison (off-object) and length comparison
- No outside facts: PARTIAL — confirms "short hair on your dog" as a fact
- Child-friendly: YES
- **Strategy match: NO** — prompt PROHIBITIONS say "Do NOT ask a question", but response contains: "Does the fur on the cat's tail look like it would feel just as soft as the fur on its tummy?"
- **Root cause**: The BEAT 2 GOOD example itself contains a question: `"Does the fur on its ears feel the same as the fur on its back?"`. This directly contradicts the PROHIBITIONS section.
- **Fix**: Change BEAT 2 example to a statement: `"The fur on its ears might feel different from the fur on its back — what do you think?"` → No, that still has a question. Better: `"You noticed the difference in length — I bet the short dog hair feels totally different when you pat it!"`

### 8. PLAY — EXCELLENT
- Angle lock: YES (fluffy fur, squishy, firm, texture — all texture)
- No outside facts: YES
- Child-friendly: EXCELLENT — very playful
- Strategy match: YES — embraces play, bridges to texture, fun question
- Question quality: EXCELLENT

### 9. EMOTIONAL — GOOD
- Angle lock: YES (fluffy fur, soft, smooth, prickly — all texture)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — acknowledges fear, gentle path back to texture
- Question quality: GOOD

### 10. AVOIDANCE — GOOD
- Angle lock: YES (fur, feel, bumpy, smooth — all texture)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — accepts avoidance, gives gentle path back
- Question quality: GOOD

### 11. BOUNDARY — ACCEPTABLE
- Angle lock: YES (fur, smooth, bumpy — all texture)
- No outside facts: YES
- Child-friendly: YES
- **Strategy match: PARTIAL** — misreads "boring" as "curious about touching", but still gives boundary + redirect
- **Note**: This is partly a test-scenario issue. The child input "this is boring" maps more naturally to avoidance than boundary. The prompt itself is fine; the classifier mismatch caused the wrong intent to be tested with a non-boundary input.

### 12. ACTION — GOOD
- Angle lock: YES (fur, bumpy, smooth — all texture)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — brief response to action, redirects to texture
- Question quality: GOOD

### 13. SOCIAL — NEEDS FIX
- Angle lock: PARTIAL — introduces dog comparison (off-object)
- No outside facts: YES
- Child-friendly: YES
- **Strategy match: NO** — prompt PROHIBITIONS say "Do NOT end with a direct question", but response contains: "Does the dog's fur look just as soft as the cat's, or does it look a little bit scratchier to you?"
- **Root cause**: The BEAT 2 GOOD example itself ends with a question: `"What about you — does that soft fur look cozy to you?"`. This directly contradicts the PROHIBITIONS section.
- **Fix**: Change BEAT 2 example to a statement: `"Fluffy things always look cozy to me — that soft fur looks like the coziest blanket!"`

### 14. SOCIAL_ACKNOWLEDGMENT — GOOD
- Angle lock: N/A (warm response only, no drift)
- No outside facts: YES
- Child-friendly: YES
- Strategy match: YES — brief warm response, no question
- Question quality: N/A (followup handles it)

---

## Issues Summary

| # | Intent | Severity | Problem | Root Cause |
|---|--------|----------|---------|-----------|
| 1 | concept_confusion | Medium | Model defines "fuzzy" instead of redirecting | "Do NOT introduce new vocabulary" not strong enough |
| 2 | correct_answer | High | Switches from texture to length/location | "aspect" too broad — needs texture-only restriction |
| 3 | informative | High | Response contains question | GOOD example contradicts PROHIBITIONS |
| 4 | social | High | Response contains question | GOOD example contradicts PROHIBITIONS |

---

## Recommended Fixes

### Fix 1: concept_confusion — strengthen anti-teaching rule

In `ATTRIBUTE_CONCEPT_CONFUSION_INTENT_PROMPT`, add to BEAT 2:
```
  Do NOT define, explain, or teach the meaning of any word — even if the
  child asked about it. Redirect straight to observation.
```

### Fix 2: correct_answer — narrow "aspect" to texture qualities

In `ATTRIBUTE_CORRECT_ANSWER_INTENT_PROMPT`, modify BEAT 2:
```
  The extension must be another texture quality (smooth, rough, soft,
  prickly, bumpy, squishy, firm). Do NOT switch to length, color, shape,
  or body-part location.
```

### Fix 3: informative — change example to statement

In `ATTRIBUTE_INFORMATIVE_INTENT_PROMPT`, change BEAT 2 GOOD example from:
```
  GOOD: "Does the fur on its ears feel the same as the fur on its back?"
```
to:
```
  GOOD: "You spotted the difference in how the fur feels — I bet the ears
    feel totally different from the back!"
```

### Fix 4: social — change example to statement

In `ATTRIBUTE_SOCIAL_INTENT_PROMPT`, change BEAT 2 GOOD example from:
```
  GOOD: "I think fluffy things are cozy! What about you — does that
    soft fur look cozy to you?"
```
to:
```
  GOOD: "I think fluffy things are super cozy — that soft fur looks like
    the coziest blanket ever!"
```
