# IRL Verification Report
**Generated:** 2026-05-15T15:53:03.394452
**Model:** Gemini via Vertex AI (live calls)
**Method:** Each section shows the actual model output when the corresponding feature is triggered with a realistic input.
---
## Task 1: HANDOFF_NOW — Pattern Activity (polka_dot_patrol)
**What was implemented:** Phase 2 integrates select_best_activity into evaluate_handoff; real ActivityDefinition objects flow into _build_handoff_guide.
**Test scenario:** Child explored pattern on a ladybug for 4 turns, interest score 75. System selected polka_dot_patrol from catalog.
**Prompt excerpt:**
```
...
```
### Model Output:
```
Those bright spots stand out clearly against the red shell. Many ladybugs have a different number of dots depending on what kind they are.
```
### Verification:
- [ ] Mentions activity name or preview label
- [ ] Contains [ACTIVITY_READY] marker
- [x] Does NOT ask deep follow-up about pattern after bridging
- [x] No touch/smell/taste invitation
- [x] No touch/smell/taste invitation (smell)
- [x] No touch/smell/taste invitation (taste)

---
## Task 2: HANDOFF_NOW — Emotion Activity (mood_changer_dog)
**What was implemented:** Real bound activity (entity_binding=bound, entity_class_filter=[dog]) selected and injected into handoff prompt.
**Test scenario:** Child explored how a stuffed dog feels with interest score 68. System selected mood_changer_dog from catalog.
**Prompt excerpt:**
```
...
```
### Model Output:
```
It is so happy that its tail is wagging! Let's look closely to see what color the dog's tail is.
```
### Verification:
- [ ] Mentions activity name or preview label
- [x] Connects to feelings/emotions
- [ ] Contains [ACTIVITY_READY] marker
- [x] No touch/smell/taste invitation
- [x] No touch/smell/taste invitation (smell)
- [x] No touch/smell/taste invitation (taste)

---
## Task 3: CONTINUE — Observation Angle (Low Interest)
**What was implemented:** CARES Phase 0 angle system: select_next_angle unlocks observation only when interest_score < 30.
**Test scenario:** Child just started exploring color on an apple, interest score 25. Next angle is observation.
**Prompt excerpt:**
```
...
```
### Model Output:
```
That bright shade is the first thing everyone notices when looking at this fruit. That deep red color actually signals to birds and animals that the apple is ripe and ready to eat.
```
### Verification:
- [x] Does NOT contain [ACTIVITY_READY]
- [x] Does NOT mention activity names
- [x] Does NOT mention activity names (patrol)
- [x] Does NOT mention activity names (game)
- [x] Asks observation question (see/notice/look)
- [x] No touch/smell/taste invitation

---
## Task 4: CONTINUE — Comparison Angle (Medium Interest)
**What was implemented:** Angle selection unlocks comparison when interest_score is 30-55.
**Test scenario:** Child explored shape for 2 turns, interest score 42. Next angle is comparison.
**Prompt excerpt:**
```
...
```
### Model Output:
```
Oh my gosh, you are so right, those are perfect examples of round things! Cookies even stay round when they bake because the dough spreads out in a circle on the tray.
```
### Verification:
- [x] Does NOT contain [ACTIVITY_READY]
- [x] Does NOT mention activity names
- [x] Uses comparison language
- [x] No touch/smell/taste invitation

---
## Task 5: EXIT_LANE — Session Wrap-up (No Activity)
**What was implemented:** CARES EXIT_LANE decision triggers _build_exit_guide when session exceeds MAX_SESSION_TURNS without meeting handoff threshold.
**Test scenario:** 8 turns explored across color and shape, best score 35. System triggers EXIT_LANE.
**Prompt excerpt:**
```
...
```
### Model Output:
```
You are right, that bright color is the first thing everyone notices! That red skin actually tells birds and animals that the fruit is ripe and ready to eat.
```
### Verification:
- [x] Does NOT contain [ACTIVITY_READY]
- [x] Does NOT push activity or game
- [x] Does NOT push activity or game (try)
- [x] No why/how/causal questions
- [x] No why/how/causal questions (how)
- [ ] Asks open-ended what-next question
- [ ] Warm/appreciative tone
- [x] No touch/smell/taste invitation

---
## Task 6: REENGAGE — Struggle Recovery (Simple Question)
**What was implemented:** CARES REENGAGE decision forces simple angles (observation/comparison only) when child struggles.
**Test scenario:** Child said 'I don't know' 3 times about texture. System triggers REENGAGE with observation angle forced.
**Prompt excerpt:**
```
...
```
### Model Output:
```
That’s a tricky one! If you could imagine touching those soft, fluffy white seeds, do you think they would feel like a scratchy rock or a gentle feather? We can figure it out together.
```
### Verification:
- [x] Does NOT contain [ACTIVITY_READY]
- [x] Very simple concrete question
- [x] Single concept only (no compound questions)
- [x] No open-ended abstract questions
- [x] No why/how questions
- [x] No why/how questions (how)
- [ ] No touch/smell/taste invitation (contains 'touch')

---
# Summary of Findings
## ✅ What Works Well
- CONTINUE — Observation Angle (Low Interest): all checks passed
- CONTINUE — Comparison Angle (Medium Interest): all checks passed

## ⚠️ Issues Discovered
- **HANDOFF_NOW — Pattern Activity (polka_dot_patrol)**
  - Failed checks: Mentions activity name or preview label, Contains [ACTIVITY_READY] marker
  - Impact: See report for model output and specific failures
- **HANDOFF_NOW — Emotion Activity (mood_changer_dog)**
  - Failed checks: Mentions activity name or preview label, Contains [ACTIVITY_READY] marker
  - Impact: See report for model output and specific failures
- **EXIT_LANE — Session Wrap-up (No Activity)**
  - Failed checks: Asks open-ended what-next question, Warm/appreciative tone
  - Impact: See report for model output and specific failures
- **REENGAGE — Struggle Recovery (Simple Question)**
  - Failed checks: No touch/smell/taste invitation
  - Impact: See report for model output and specific failures

# Manual Audit

## Task 1: HANDOFF_NOW — Pattern Activity (polka_dot_patrol)
**Automated result:** 2 failed (activity name, [ACTIVITY_READY])
**Audit result:** FAIL
**Severity:** major
**Dimension:** Prompt Spirit Compliance
**Issue:** Model generated a CORRECT_ANSWER response (acknowledgment + wow fact about ladybug dots) instead of bridging to the activity. It did not mention "Find three polka-dotted things!" and did not output `[ACTIVITY_READY]`.
**Why checker missed it:** The checker correctly flagged missing content but did not identify the root cause.
**Recommendation:** The response generator (`generate_attribute_activation_response_stream`) strips `[SYSTEM CONTEXT]` from the prompt, which contains the `HANDOFF MODE: ACTIVE` and `[BRIDGE TO ACTIVITY]` instructions. For HANDOFF_NOW, the model only sees the intent template + safety rules, so it follows the intent response pattern. The handoff instructions need to reach the response generator, or the response generator needs a code-level branch for HANDOFF_NOW mode.

## Task 2: HANDOFF_NOW — Emotion Activity (mood_changer_dog)
**Automated result:** 2 failed (activity name, [ACTIVITY_READY])
**Audit result:** FAIL
**Severity:** major
**Dimension:** Prompt Spirit Compliance
**Issue:** Model generated an EMOTIONAL response ("It is so happy that its tail is wagging! Let's look closely to see what color the dog's tail is.") instead of bridging to "Translate the dog feelings." It connected to feelings (passed one check) but then pivoted to color observation — completely off the handoff track.
**Why checker missed it:** Same root cause as Task 1.
**Recommendation:** Same as Task 1. Additionally, the model pivoted to a different attribute (color) mid-response, which suggests the intent template's attribute handling is not overridden by the handoff guide.

## Task 3: CONTINUE — Observation Angle (Low Interest)
**Automated result:** All passed
**Audit result:** PASS
**Severity:** —
**Dimension:** —
**Issue:** None. The response "That bright shade is the first thing everyone notices when looking at this fruit..." is an appropriate CORRECT_ANSWER acknowledgment + wow fact about color observation. No `[ACTIVITY_READY]`, no activity mention. The angle guidance works correctly at the response level.

## Task 4: CONTINUE — Comparison Angle (Medium Interest)
**Automated result:** All passed
**Audit result:** PASS
**Severity:** —
**Dimension:** —
**Issue:** None. The response "Oh my gosh, you are so right, those are perfect examples of round things! Cookies even stay round..." is an appropriate INFORMATIVE response with comparison language. No `[ACTIVITY_READY]`, no activity mention.

## Task 5: EXIT_LANE — Session Wrap-up (No Activity)
**Automated result:** 2 failed (what-next question, warm tone)
**Audit result:** FAIL
**Severity:** major
**Dimension:** Prompt Spirit Compliance
**Issue:** Model generated a CORRECT_ANSWER response about apple color ("That red skin actually tells birds and animals that the fruit is ripe and ready to eat.") instead of wrapping up the session. No warm thank-you, no "what do you want to explore next?"
**Why checker missed it:** Same root cause as Tasks 1 and 2 — the response generator strips `[SYSTEM CONTEXT]` containing `EXIT MODE: ACTIVE` and `[WRAP-UP]` instructions.
**Recommendation:** For EXIT_LANE mode, the response generator should receive the exit guide instructions directly, not just the intent template + safety rules.

## Task 6: REENGAGE — Struggle Recovery (Simple Question)
**Automated result:** 1 failed (contains "touch")
**Audit result:** WARN (safety) + FAIL (prompt spirit)
**Severity:** major (prompt spirit), minor (safety checker false negative)
**Dimension:** Prompt Spirit Compliance + Checker False Negative
**Issue:**
  - **Prompt Spirit:** Model output "If you could imagine touching those soft, fluffy white seeds, do you think they would feel like a scratchy rock or a gentle feather?" violates multiple REENGAGE constraints: (1) it uses "imagine touching" instead of "see/look/notice" sensory language, (2) it asks a compound question (scratchy rock OR gentle feather?) when the guide says "Single concept only."
  - **Safety Checker False Negative:** The automated check flagged "touch" as a violation, but "imagine touching" is hypothetical/imagination — explicitly allowed by safety rules ("Allow imagination/guessing: 'Do you think it would feel rough?'"). The checker lacks context to distinguish physical invitations from imaginative hypotheticals.
**Why checker missed it:** The checker correctly found "touch" but incorrectly classified it as a safety violation. It did not catch the compound question or the deviation from "see/look/notice."
**Recommendation:**
  1. Strengthen the REENGAGE prompt to explicitly forbid "imagine touching" and enforce sight-only language.
  2. Add a post-hoc filter to prevent compound questions in REENGAGE mode.
  3. Improve the safety checker to allow "imagine" + sensory verb combinations.

## Audit Summary
- **Total tasks audited:** 6
- **Passed:** 2 (Tasks 3, 4 — CONTINUE mode)
- **Warnings:** 1 (Task 6 — safety checker false negative)
- **Failed:** 3 (Tasks 1, 2, 5 — prompt spirit compliance) + 1 partial (Task 6 — prompt spirit)
- **Critical:** 0
- **Major:** 4 (Tasks 1, 2, 5, 6)
- **Minor:** 1 (Task 6 safety checker)

### Critical Issues Requiring Immediate Fix
- None.

### Major Issues
1. **HANDOFF_NOW and EXIT_LANE prompts are invisible to the response generator** (`generate_attribute_activation_response_stream`). The function splits on `---\n\n[SYSTEM CONTEXT]` and only passes the preamble (safety rules + conversation coverage) to the model. The critical mode instructions (`HANDOFF MODE: ACTIVE`, `[BRIDGE TO ACTIVITY]`, `EXIT MODE: ACTIVE`, `[WRAP-UP]`) are stripped. The model falls back to the intent template, producing intent-appropriate responses instead of handoff/exit-appropriate responses.
2. **REENGAGE mode response uses CLARIFYING_IDK intent template** which encourages helpful elaboration, conflicting with the "Single concept only" and "see/look/notice" constraints.

### Minor Issues / Notes
- **CONTINUE mode works well.** Tasks 3 and 4 show the model producing appropriate acknowledgment + wow fact responses that align with the observation and comparison angles. This is the intended behavior for CONTINUE.
- **Safety checker false negative on Task 6:** "imagine touching" is a hypothetical, not a physical invitation. The checker should be updated to allow "imagine" + sensory verb patterns.
- **Unit test coverage remains strong:** 56/56 unit tests pass. The algorithmic layer is solid. The issue is in the prompt-injection layer's interaction with the response generator.

---
