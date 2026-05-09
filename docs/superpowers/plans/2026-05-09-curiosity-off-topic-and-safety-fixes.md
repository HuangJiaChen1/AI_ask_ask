# Curiosity Off-Topic + Safety Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 verification issues from IRL report 2026-05-08-v3: inject safety rules into all response prompts, redesign CURIOSITY intent for off-topic questions, and fix 4 smaller prompt issues.

**Architecture:** All changes are prompt-level or parameter-passing in response generators. No new infrastructure. Two generator functions in `stream/response_generators.py` need a new `sensory_safety_rules` parameter passed to prompt formatting. All intent prompt templates in `paixueji_prompts.py` need `{sensory_safety_rules}` placeholder added.

**Tech Stack:** Python 3, LangGraph, Google GenAI (Gemini), Flask

---

## File Structure

| File | Responsibility | Change Type |
|------|---------------|-------------|
| `paixueji_prompts.py` | All prompt templates | Modify: add `{sensory_safety_rules}` to 18 intent prompts; restructure CURIOSITY; tweak ACTION, TOPIC_SWITCH, EMOTIONAL, BOUNDARY |
| `stream/response_generators.py` | Response stream generators | Modify: pass `sensory_safety_rules` in `generate_intent_response_stream` and `generate_attribute_activation_response_stream` |
| `tests/` | Existing test suite | Run: verify no regressions |
| `scripts/irl_verify.py` | IRL verification runner | Run: verify fixes produce correct model outputs |

---

### Task 1: Add `{sensory_safety_rules}` Placeholder to All Intent Prompts

**Files:**
- Modify: `paixueji_prompts.py`

Add `{sensory_safety_rules}` to the 18 intent prompt templates. Place it right before the `PROHIBITIONS` section in each prompt (or before `YOUR MISSION` if no PROHIBITIONS exist). This follows the pattern already used in `EXPLANATION_RESPONSE_PROMPT` (line 79).

**Prompts to modify:**

1. `CURIOSITY_INTENT_PROMPT` (~line 1110, before PROHIBITIONS)
2. `CLARIFYING_IDK_INTENT_PROMPT` (before PROHIBITIONS)
3. `CLARIFYING_OPEN_ENDED_IDK_INTENT_PROMPT` (before PROHIBITIONS)
4. `GIVE_ANSWER_IDK_INTENT_PROMPT` (before PROHIBITIONS)
5. `GIVE_ANSWER_OPEN_ENDED_IDK_INTENT_PROMPT` (before PROHIBITIONS)
6. `CLARIFYING_WRONG_INTENT_PROMPT` (before PROHIBITIONS)
7. `CLARIFYING_CONSTRAINT_INTENT_PROMPT` (before PROHIBITIONS)
8. `CORRECT_ANSWER_INTENT_PROMPT` (before PROHIBITIONS)
9. `INFORMATIVE_INTENT_PROMPT` (before PROHIBITIONS)
10. `PLAY_INTENT_PROMPT` (before PROHIBITIONS)
11. `EMOTIONAL_INTENT_PROMPT` (before PROHIBITIONS)
12. `AVOIDANCE_INTENT_PROMPT` (before PROHIBITIONS)
13. `BOUNDARY_INTENT_PROMPT` (before PROHIBITIONS)
14. `ACTION_INTENT_PROMPT` (before PROHIBITIONS)
15. `SOCIAL_INTENT_PROMPT` (before PROHIBITIONS)
16. `SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT` (before PROHIBITIONS)
17. `CONCEPT_CONFUSION_INTENT_PROMPT` (before PROHIBITIONS)
18. `CLASSIFICATION_FALLBACK_PROMPT` (before PROHIBITIONS)

For each prompt, search for the `PROHIBITIONS:` line and insert `{sensory_safety_rules}\n\n` right before it.

Example change for `CURIOSITY_INTENT_PROMPT`:

```python
# OLD (around line 1110):
  One short question — fun, imaginative, no wrong answer.

PROHIBITIONS:
- Do NOT say "That's a great question!" or "Great question!"

# NEW:
  One short question — fun, imaginative, no wrong answer.

{sensory_safety_rules}

PROHIBITIONS:
- Do NOT say "That's a great question!" or "Great question!"
```

- [ ] **Step 1: Add placeholder to CURIOSITY through CLASSIFICATION_FALLBACK prompts**

Use `grep -n "PROHIBITIONS:" paixueji_prompts.py` to find all locations, then insert `{sensory_safety_rules}\n\n` before each one.

- [ ] **Step 2: Verify all 18 prompts have the placeholder**

Run:
```bash
grep -c "sensory_safety_rules" paixueji_prompts.py
```
Expected: at least 19 (1 definition + 18 prompts; previously there were ~5 usages in question prompts)

- [ ] **Step 3: Commit**

```bash
git add paixueji_prompts.py
git commit -m "fix: add {sensory_safety_rules} placeholder to all 18 intent prompts"
```

---

### Task 2: Pass `sensory_safety_rules` in `generate_intent_response_stream`

**Files:**
- Modify: `stream/response_generators.py:76-84`

- [ ] **Step 1: Add safety rules to format call**

In `generate_intent_response_stream`, find the `prompt_template.format(...)` call and add `sensory_safety_rules`:

```python
# OLD (lines 76-84):
        prompt = prompt_template.format(
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt=age_prompt,
            last_model_response=last_model_response,
            knowledge_context=knowledge_context,
            character_profile=character_profile,
        )

# NEW:
        prompt = prompt_template.format(
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt=age_prompt,
            last_model_response=last_model_response,
            knowledge_context=knowledge_context,
            character_profile=character_profile,
            sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
        )
```

- [ ] **Step 2: Run existing tests to check for regressions**

```bash
pytest tests/ -v --tb=short
```
Expected: All tests pass (no failures related to prompt formatting KeyError)

- [ ] **Step 3: Commit**

```bash
git add stream/response_generators.py
git commit -m "fix: inject SENSORY_SAFETY_RULES into generate_intent_response_stream"
```

---

### Task 3: Pass `sensory_safety_rules` in `generate_attribute_activation_response_stream`

**Files:**
- Modify: `stream/response_generators.py:262-269`

- [ ] **Step 1: Add safety rules to format call**

In `generate_attribute_activation_response_stream`, find the `intent_template.format(...)` call and add `sensory_safety_rules`:

```python
# OLD (lines 262-269):
    try:
        intent_prompt = intent_template.format(
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt=age_prompt,
            last_model_response=last_model_response,
            knowledge_context=knowledge_context,
        )

# NEW:
    try:
        intent_prompt = intent_template.format(
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt=age_prompt,
            last_model_response=last_model_response,
            knowledge_context=knowledge_context,
            sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
        )
```

- [ ] **Step 2: Run existing tests**

```bash
pytest tests/ -v --tb=short
```
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add stream/response_generators.py
git commit -m "fix: inject SENSORY_SAFETY_RULES into attribute activation response stream"
```

---

### Task 4: Redesign CURIOSITY_INTENT_PROMPT with Off-Topic Handling

**Files:**
- Modify: `paixueji_prompts.py:1055-1117`

- [ ] **Step 1: Replace the CURIOSITY_INTENT_PROMPT**

Find `CURIOSITY_INTENT_PROMPT = """\` at line 1055. Replace the entire prompt (through the closing `"""` at line 1117) with:

```python
CURIOSITY_INTENT_PROMPT = """\
CONTEXT:
- Child (age {age}) asked: "{child_answer}"
- You're exploring: {object_name}
- Your last response: "{last_model_response}"

AGE GUIDANCE:
{age_prompt}

GROUNDING (prefer these facts over memory for BEAT 2 — use your best judgment if none fit):
{knowledge_context}

{sensory_safety_rules}

VOICE CONTRACT:
- Sound like an older-kid buddy, not a teacher
- Use plain words and short sentences
- Be specific without sounding literary

YOUR MISSION:
A child asked a genuine question — reward it with a delightful, truthful, specific answer.
Do NOT start with "That's a great question!" — lead with the answer immediately.

OFF-TOPIC CHECK — before writing any response:
  Ask yourself: "Is the child's question directly about {object_name}?"

  IF YES → follow the ON-TOPIC structure below.

  IF NO (the question is about something else) → follow the BRIDGE structure:
    BEAT 1 — ANSWER THE EXACT QUESTION: Give a truthful, specific answer to what they asked. 1 sentence.
    BEAT 2 — BRIDGE TO {object_name}: Find ONE genuine, concrete connection between your answer
      and {object_name}. Use sensory comparisons, shared environments, or behaviors.
      GOOD: "...and lions breathe that same air when they roar across the plains!"
      GOOD: "...just like how a lion's golden fur looks brightest when the sun hits it!"
      BAD: "...and lions are blue too!" (false connection)
      BAD: "...which is interesting, just like lions are interesting." (lazy pivot)
      If no genuine connection exists after one attempt, skip BEAT 2 and use the fallback pivot.
    BEAT 3 — QUESTION ABOUT {object_name}: One playful question rooted firmly back in {object_name}.
      "Want to know something surprising about lions?"
      "Speaking of lions, do you think a lion's mane looks lighter or darker in bright sun?"

SPECIAL CASE — REPHRASE REQUEST:
If the child is asking what you meant, says they do not understand, or asks you to say it again:
- Rephrase the last idea in simpler words
- Stay on the same point instead of adding a new angle
- Ask one small concrete question at the end
- Do not pivot to a new WOW fact
- No wow pivot, no fancy metaphor, no new topic

ON-TOPIC STRUCTURE (2-3 sentences, 3 beats):

BEAT 1 — DIRECT ANSWER: Give the specific answer to what they asked. Use concrete, sensory words.
  Ages 3-5: "Frogs are green so they can hide in the grass — it's like a magic trick!"
  Ages 6-8: "Frogs are green because of special pigment cells that work like built-in camouflage!"

ANCHOR CHECK — before writing BEAT 2, identify:
  What specific question did the child ask? → Your WOW detail MUST amplify the answer to *that question*.
  BAD: Child asks "why does it roar?" → WOW detail about mane color (unrelated topic)
  GOOD: Child asks "why does it roar?" → WOW detail about how lions' roars travel 5 miles / coordinate hunts

BEAT 2 — ONE WOW DETAIL: Add ONE surprising, specific fact that amplifies the answer. Use numbers, comparisons, or sensory images.
  GOOD: "And some frogs can even change their shade of green depending on the light!"
  BAD: "And frogs are really interesting animals." (too vague)

BEAT 3 — CLOSING QUESTION: End with ONE fun, imaginative question that grows from the WOW detail
  in Beat 2. The education is already done in Beats 1 and 2 — Beat 3 should be playful, not
  another teaching moment.
  GOOD: "Can you imagine being able to change colour like that — what colour would you turn?"
  GOOD: "If you had that superpower, how would you use it?"
  GOOD: "Want to try making that sound yourself?"
  BAD: "Do you know any other animals that can do this?" (knowledge-testing)
  BAD: "Did you know...?" (banned phrasing — do not use)
  One short question — fun, imaginative, no wrong answer.

PROHIBITIONS:
- Do NOT say "That's a great question!" or "Great question!"
- Do NOT give vague answers ("It's part of nature" is not an answer)
- Do NOT make up facts — rely on the child's question, the object, and any grounded facts already shared
- Do NOT make Beat 3 knowledge-testing — that is another teaching moment, not play
- Do NOT answer a different question than the one the child asked, even if it is about {object_name}

Respond naturally (NOT JSON). 2-3 sentences max.
"""
```

- [ ] **Step 2: Verify the prompt renders without KeyError**

Run a quick Python check:
```bash
python -c "
import paixueji_prompts
prompts = paixueji_prompts.get_prompts()
template = prompts['curiosity_intent_prompt']
result = template.format(
    child_answer='Why is the sky blue?',
    object_name='lion',
    age=5,
    age_prompt='Use simple words.',
    last_model_response='What do you think?',
    knowledge_context='Lions are big cats.',
    sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES
)
print('OK — prompt renders successfully')
print('Has OFF-TOPIC CHECK:', 'OFF-TOPIC CHECK' in result)
print('Has BRIDGE structure:', 'BRIDGE TO' in result)
"
```
Expected: All prints show True/OK

- [ ] **Step 3: Commit**

```bash
git add paixueji_prompts.py
git commit -m "feat: redesign CURIOSITY prompt with off-topic detection and bridge structure"
```

---

### Task 5: Fix ACTION_INTENT_PROMPT TYPE C

**Files:**
- Modify: `paixueji_prompts.py:1739-1742`

- [ ] **Step 1: Update TYPE C instructions**

Find the TYPE C block in `ACTION_INTENT_PROMPT` and replace:

```python
# OLD:
TYPE C — VAGUE OR META REQUEST ("I'm bored", "This is too hard", "Can we change?"):
  Accept warmly and offer one option.
  "Of course — we can find something even cooler to explore!"
  "No worries — let's make it more fun!"

# NEW:
TYPE C — VAGUE OR META REQUEST ("I'm bored", "This is too hard", "Can we change?"):
  Accept warmly and offer one option as a statement. Do NOT ask a question.
  "No worries — let's look at the apple's skin instead."
  "Of course — we can find something even cooler to explore!"
```

- [ ] **Step 2: Commit**

```bash
git add paixueji_prompts.py
git commit -m "fix: strengthen ACTION TYPE C to prohibit questions and offer concrete option"
```

---

### Task 6: Fix TOPIC_SWITCH_RESPONSE_PROMPT, EMOTIONAL_INTENT_PROMPT, BOUNDARY_INTENT_PROMPT

**Files:**
- Modify: `paixueji_prompts.py`

- [ ] **Step 1: Add vocabulary guardrail to TOPIC_SWITCH_RESPONSE_PROMPT**

Find `TOPIC_SWITCH_RESPONSE_PROMPT` (~line 120). Replace:

```python
# OLD:
5. Respond naturally (NOT JSON)
"""

# NEW:
5. Use natural, simple comparisons. Avoid invented words like "wiggier".
6. Respond naturally (NOT JSON)
"""
```

- [ ] **Step 2: Fix EMOTIONAL_INTENT_PROMPT positive emotion example**

Find the positive emotion BEAT 2 example in `EMOTIONAL_INTENT_PROMPT` (~line 1615). Replace:

```python
# OLD:
    - Excited: "Want to look even more closely and find the most colorful spot?"

# NEW:
    - Excited: "Want to use your eyes like a detective and find the most colorful spot?"
```

- [ ] **Step 3: Strengthen BOUNDARY_INTENT_PROMPT safety reason requirement**

Find BEAT 2 in `BOUNDARY_INTENT_PROMPT` (~line 1691). Replace the heading:

```python
# OLD:
BEAT 2 — BRIEF SAFETY REASON (one sentence only, age-scaled):

# NEW:
BEAT 2 — BRIEF SAFETY REASON (required — one sentence only, age-scaled):
```

Also add after the age examples and before PROHIBITIONS:

```python
# Find this line (~line 1698):
  Keep it to ONE sentence — do not lecture.

# Replace with:
  Keep it to ONE sentence — do not lecture.
  You MUST include this step. Do not skip the safety reason.
```

- [ ] **Step 4: Commit all three prompt tweaks**

```bash
git add paixueji_prompts.py
git commit -m "fix: topic switch vocab guardrail, emotional sight-only language, boundary mandatory safety reason"
```

---

### Task 7: Run Full Test Suite

**Files:**
- Test: `tests/`

- [ ] **Step 1: Run pytest**

```bash
pytest tests/ -v --tb=short
```
Expected: All tests pass. No KeyError failures from prompt formatting.

- [ ] **Step 2: If any test fails, fix before proceeding**

Common issue: Tests that mock prompt templates may need `sensory_safety_rules` added to their mock format strings. Search for test files that construct prompt templates:

```bash
grep -r "intent_prompt" tests/ --include="*.py"
```

If any test manually constructs a prompt template string without `{sensory_safety_rules}`, add the placeholder.

---

### Task 8: Run IRL Verification

**Files:**
- Run: `scripts/irl_verify.py`
- Config: `scripts/irl_verify_all_intents.json`

- [ ] **Step 1: Run the verification script**

```bash
python scripts/irl_verify.py --config scripts/irl_verify_all_intents.json
```

This makes live LLM calls. It will take several minutes.

- [ ] **Step 2: Review the generated report**

Check the output file (typically `docs/verification/all-intents-verification-*.md`). Verify:

- **Task 1 (Curiosity):** Model answers the exact question asked. If off-topic, includes a bridge back to the object.
- **Tasks 16, 21, 22, 25, 26, 28:** No touch/smell/taste/physical interaction invitations in any response.
- **Task 14 (Action Subtype C):** Response is a statement offering one option, no question mark.
- **Task 15 (Action Subtype D):** Transition uses natural vocabulary, no invented words.
- **Task 8 (Emotional Mild):** Uses sight-only language, no physical approach ambiguity.
- **Task 11 (Boundary):** Includes a brief safety reason.

- [ ] **Step 3: If verification reveals new issues, iterate**

Address any new failures by adjusting the relevant prompt and re-running verification for that specific task.

---

## Self-Review Checklist

**1. Spec coverage:**
- [ ] Safety rules injection into all 18 intent prompts → Task 1
- [ ] Pass safety rules in `generate_intent_response_stream` → Task 2
- [ ] Pass safety rules in `generate_attribute_activation_response_stream` → Task 3
- [ ] CURIOSITY off-topic handling with Answer+Bridge → Task 4
- [ ] Action Subtype C fix → Task 5
- [ ] Topic Switch vocabulary guardrail → Task 6, Step 1
- [ ] Emotional Mild sight-only language → Task 6, Step 2
- [ ] Boundary mandatory safety reason → Task 6, Step 3
- [ ] Verification → Task 8

**2. Placeholder scan:**
- [ ] No TBDs, TODOs, or "implement later"
- [ ] All code blocks contain complete code
- [ ] All commands have expected outputs specified

**3. Type consistency:**
- [ ] `sensory_safety_rules` parameter name consistent across both generator functions and all 18 prompts
- [ ] `paixueji_prompts.SENSORY_SAFETY_RULES` referenced correctly (module-level constant)
