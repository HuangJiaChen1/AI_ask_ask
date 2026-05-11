# IRL Verification Report
**Generated:** 2026-05-11T14:18:37.368379
**Model:** Gemini via Vertex AI (live calls)
**Method:** Each section shows the actual model output when the corresponding feature is triggered with a realistic input.
---
## Task 1: Attribute Selection — Primary + Fallback
**What was implemented:** select_attribute_profile uses Gemini to pick one primary and one fallback attribute from supported candidates.
**Test scenario:** Object: orange cat | Age: 5 | Domain: animals
**Prompt excerpt:**
```
...
```
### Model Output:
```
{
  "attribute_id": "appearance.body_color",
  "fallback_attribute_id": "appearance.covering",
  "confidence": "high",
  "reason": "For a 5-year-old, the most immediate and defining characteristic of an 'orange cat' is its color, with its fur covering being a natural secondary observation."
}
```
### Verification:
- [x] Returns valid JSON with attribute_id
- [x] Returns fallback_attribute_id different from primary
- [x] Contains confidence field
- [x] Contains reason field

---
## Task 2: Attribute Intro — No Quiz, Natural Salience
**What was implemented:** ask_attribute_intro_stream uses ATTRIBUTE_INTRO_PROMPT to make the attribute naturally noticeable without forced redirects.
**Test scenario:** Object: orange cat | Attribute: shape | Age: 5
**Prompt excerpt:**
```
...
```
### Model Output:
```
Oh, look at that! It’s an orange cat, and it’s curled up into such a perfect little circle. What do you notice about the way its body is shaped while it’s resting there?
```
### Verification:
- [x] Does NOT ask 'What shape is it?'
- [x] Does NOT say 'Let's talk about its shape'
- [x] Does NOT say 'Let's look at its shape'
- [x] Contains engagement hook (question mark)
- [x] Mentions the object (cat)

---
## Task 3: Follow-up Question — Stays on Primary Topic
**What was implemented:** ask_followup_question_stream with ATTRIBUTE_MULTI_TOPIC_GUIDE injected as attribute_soft_guide. Primary=shape, fallback=size.
**Test scenario:** Child said 'It's round like a ball!' about a cat. Assistant just responded celebrating the roundness.
**Prompt excerpt:**
```
...
```
### Model Output:
```
If that cat started to roll across the floor, do you think it would go fast or slow?

[ACTIVITY_READY]
REASON: The child described the cat as "round like a ball," so asking about it rolling explores that shape further.
```
### Verification:
- [x] Single question only (one question mark)
- [x] Does NOT contain [SWITCH_TO]
- [x] Does NOT say 'What else can you tell me'
- [x] Does NOT use 'Did you know'
- [x] Question is about shape or related visual detail

---
## Task 4: Follow-up Question — Child Shifted to Fallback Topic
**What was implemented:** ask_followup_question_stream with multi-topic guide where child clearly expressed interest in the fallback topic (size).
**Test scenario:** Child said 'It's round like a ball! And it's SO BIG! Bigger than my dog!' Assistant responded celebrating roundness.
**Prompt excerpt:**
```
...
```
### Model Output:
```
If that cat started to roll across the floor, do you think it would move fast or slow?

[ACTIVITY_READY]
REASON: The child described the cat as "round like a ball," so asking about it rolling explores that shape further.
```
### Verification:
- [x] Single question only (contains question mark)
- [x] Does NOT say 'What else can you tell me'
- [x] Does NOT use 'Did you know'
- [ ] Acknowledges child's interest in size OR asks about size

---
## Task 5: Attribute Activation Response — WOW Fact Aligns with Attribute
**What was implemented:** generate_attribute_activation_response_stream uses intent prompt + attribute_response_hint to keep the wow fact aligned with the current attribute.
**Test scenario:** CORRECT_ANSWER intent. Child said 'It's round!' about a cat. Attribute = shape.
**Prompt excerpt:**
```
...
```
### Model Output:
```
You're right, that cat is shaped like a big, soft ball! Cats curl up into that tight circle to keep their tummies warm and safe while they nap.
```
### Verification:
- [x] Celebrates child's answer (not hollow praise)
- [x] Does NOT use 'Did you know'
- [x] Does NOT ask a question (response only)
- [x] WOW fact relates to shape (not color or size)

---
## Task 6: Simulated SWITCH_TO — Model Given Full Multi-Topic Guide
**What was implemented:** ATTRIBUTE_MULTI_TOPIC_GUIDE prompt template tested in isolation to verify it can produce [SWITCH_TO] markers when the model sees fallback topics.
**Test scenario:** Model sees full multi-topic guide with primary=shape, fallback=size. Child clearly shifted to size.
**Prompt excerpt:**
```
...
```
### Model Output:
```
That is a great observation! It is quite a giant cat, isn't it? If you look at the cat's big body compared to its pointy ears, do you think the cat is shaped more like a circle or more like a long, stretchy rectangle?

[SWITCH_TO:appearance.body_size]

REASON: The child explicitly compared the cat's size to their dog, showing a strong interest in the scale of the animal.
```
### Verification:
- [x] Contains [SWITCH_TO] marker
- [x] Contains REASON line
- [x] Acknowledges size in child-facing text
- [x] Does NOT invite touch
- [x] Does NOT invite smell

---
# Summary of Findings
## ✅ What Works Well
- Attribute Selection — Primary + Fallback: all checks passed
- Attribute Intro — No Quiz, Natural Salience: all checks passed
- Follow-up Question — Stays on Primary Topic: all checks passed
- Attribute Activation Response — WOW Fact Aligns with Attribute: all checks passed
- Simulated SWITCH_TO — Model Given Full Multi-Topic Guide: all checks passed

## ⚠️ Issues Discovered
- **Follow-up Question — Child Shifted to Fallback Topic**
  - Failed checks: Acknowledges child's interest in size OR asks about size
  - Impact: See report for model output and specific failures

---

# Manual Audit

## Task 1: Attribute Selection — Primary + Fallback
**Automated result:** 4/4 passed
**Audit result:** PASS
**Severity:** —
**Dimension:** —
**Issue:** None. JSON is valid and well-structured. Primary (`appearance.body_color`) and fallback (`appearance.covering`) are both from the supported list and differ from each other. Reasoning is age-appropriate.

## Task 2: Attribute Intro — No Quiz, Natural Salience
**Automated result:** 5/5 passed
**Audit result:** PASS
**Severity:** —
**Dimension:** —
**Issue:** None. Output follows the BEAT structure: "Oh, look at that!" (emotional opening) → "It's an orange cat" (object confirmation) → "curled up into such a perfect little circle" (salience highlight for shape) → "What do you notice about the way its body is shaped while it's resting there?" (engagement hook). No forced redirects, no quiz questions. Age-appropriate vocabulary.

## Task 3: Follow-up Question — Stays on Primary Topic
**Automated result:** 5/5 passed
**Audit result:** WARN
**Severity:** major
**Dimension:** Prompt Spirit Compliance
**Issue:** The model emitted `[ACTIVITY_READY]` after only ONE shallow exchange about shape. The child said "It's round like a ball!" — a single-word observation. The prompt explicitly lists as an ANTI-PATTERN: "Adding [ACTIVITY_READY] after just one shallow exchange — premature handoff." The question itself is fine (imagination-based, shape-related), but the readiness marker is premature.
**Why checker missed it:** The automated checks only look for the presence/absence of `[SWITCH_TO]` and banned phrases. They do not evaluate whether `[ACTIVITY_READY]` is appropriate for the depth of conversation.
**Recommendation:** Add a check that `[ACTIVITY_READY]` should NOT appear in outputs where the conversation history has fewer than 3 child turns about the primary attribute.

## Task 4: Follow-up Question — Child Shifted to Fallback Topic
**Automated result:** 3/4 passed
**Audit result:** FAIL
**Severity:** major
**Dimension:** Prompt Spirit Compliance
**Issue:** The child clearly shifted interest to size ("And it's SO BIG! Bigger than my dog!" — emphasized, comparative, detailed). The model completely ignored this shift and produced a question nearly identical to Task 3: "If that cat started to roll across the floor, do you think it would move fast or slow?" It did not acknowledge size, did not switch topics, and did not ask a size-related question. The multi-topic guide says "BUT if the child clearly shows more interest in a fallback topic, you may switch." The model failed to act on this instruction. Additionally, `[ACTIVITY_READY]` was emitted prematurely, same as Task 3.
**Why checker missed it:** The checker only verifies that the output does not contain banned phrases and contains a question mark. It does not evaluate whether the question addresses the child's actual input.
**Recommendation:** The multi-topic guide is only injected into the follow-up question generator, not the response generator. But even in the question generator, the model is not reliably adapting to the child's interest. Consider:
1. Strengthening the prompt language around "clearly shifted interest" with concrete examples.
2. Adding a post-hoc filter that detects when the child's input mentions the fallback topic prominently and routes accordingly.

## Task 5: Attribute Activation Response — WOW Fact Aligns with Attribute
**Automated result:** 4/4 passed
**Audit result:** PASS
**Severity:** —
**Dimension:** —
**Issue:** None. The response celebrates "It's round!" with "You're right, that cat is shaped like a big, soft ball!" — a warm paraphrase, not a verbatim echo. The WOW fact "Cats curl up into that tight circle to keep their tummies warm and safe while they nap" directly relates to shape (curling into a circle). No questions. No "Did you know". Age-appropriate.

## Task 6: Simulated SWITCH_TO — Model Given Full Multi-Topic Guide
**Automated result:** 5/5 passed
**Audit result:** PASS
**Severity:** —
**Dimension:** —
**Issue:** None. When the model was explicitly given the full multi-topic guide (including fallback topics and SWITCH_TO rules), it correctly:
1. Acknowledged the child's size observation ("It is quite a giant cat, isn't it?")
2. Asked a frame-weaving question that bridges shape and size ("do you think the cat is shaped more like a circle or more like a long, stretchy rectangle?")
3. Emitted `[SWITCH_TO:appearance.body_size]` at the end
4. Provided a REASON with a direct child quote
This proves the **prompt template works** when the model sees it. The production gap is that this guide is not injected into the response generator (only the follow-up question generator sees it).

## Audit Summary
- **Total tasks audited:** 6
- **Passed:** 4
- **Warnings:** 1
- **Failed:** 1 (critical: 0, major: 2, minor: 0)

### Critical Issues Requiring Immediate Fix
- None.

### Major Issues
1. **Premature `[ACTIVITY_READY]` in Tasks 3 and 4** — The model declares activity readiness after only one shallow child exchange. This violates the anti-pattern in the multi-topic guide. The quote validation mechanism may catch this if the REASON doesn't contain a genuine quote about depth, but the model's REASON in Task 3 ("The child described the cat as 'round like a ball'") does contain a quote — so it would pass validation despite being shallow. This is a safety valve gap.
2. **Model ignores child's interest shift in Task 4** — When the child clearly expressed interest in the fallback topic (size), the model stayed on the primary topic (shape). The multi-topic guide's switching rule was not followed. This undermines the core value proposition of dynamic topic switching.

### Minor Issues / Notes
- Tasks 3 and 4 produced nearly identical outputs despite different child inputs, suggesting the model is not strongly conditioned by the specific content of the child's message when generating follow-up questions.

### Recommendations
1. **Strengthen premature-handoff detection** — Add a minimum-turn-count guard (e.g., at least 3 turns about the attribute) before accepting `[ACTIVITY_READY]`, independent of quote validation.
2. **Improve topic-switch sensitivity** — The multi-topic guide tells the model it MAY switch, but the model is conservative. Consider making the switch instruction stronger ("MUST switch" vs "may switch") or adding explicit child-input analysis in the prompt.
3. **Inject multi-topic guide into response generator** — The production architecture only passes the guide to `ask_followup_question_stream`. The `generate_attribute_activation_response_stream` does not see fallback topics, so `[SWITCH_TO]` markers are unlikely to appear in production responses. Either inject the guide into the response generator or move switch detection to the follow-up question stream.
