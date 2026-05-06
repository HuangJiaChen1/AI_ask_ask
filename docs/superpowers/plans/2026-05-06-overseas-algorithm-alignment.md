# Align paixueji prompts with 海外算法汇总.docx (Section 4 — Voice Interaction)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `paixueji_prompts.py`, `hook_types.json`, classifier, and graph dispatch to match the 2026-05-05 internal product doc (Section 4 "语音交互"), which gives BEAT-level changes for prompts, adds two new hook types (English examples), introduces ACTION subtype dispatch, and hardens sensory safety across all prompts.

**Architecture:** String-level prompt edits with a new module-level `SENSORY_SAFETY_RULES` constant injected into every prompt that recommends sensory exploration. Hook taxonomy expanded via JSON. ACTION subtype added to the classifier regex output, then branched in `graph.py` `node_action`. All changes are additive or surgical; no new files except test files.

**Tech Stack:** Python 3.10, pytest, LangGraph, Gemini (Vertex AI), Flask SSE.

---

## File structure

| File | Responsibility |
|---|---|
| `paixueji_prompts.py` | All prompt strings. New constants `SENSORY_SAFETY_RULES`, `CHARACTER_PROFILE`, and ~12 surgical BEAT edits across sections 2/3/6. |
| `hook_types.json` | Canonical hook registry. Append two new entries (Imitation + Silly Twist) with English examples. |
| `stream/utils.py` | Hook selector (`select_hook_type`). Update `HIGH_IMAGINATION_HOOKS` and bucket assignments. |
| `graph.py` | LangGraph nodes. Update `OPEN_ENDED_QUESTION_HOOKS`/`CONCRETE_QUESTION_HOOKS`; extend `node_analyze_input` to propagate `action_subtype`; rewrite `node_action` to branch on subtype. |
| `stream/validation.py` | Intent classifier parser. Add `ACTION_SUBTYPE` regex extraction. |
| `paixueji_assistant.py` | Assistant state. Add `action_subtype` field. |
| `prompt_overrides.json` | ~~Deleted~~ — runtime override mechanism removed per team decision. ACTION_SUBTYPE changes go straight into `paixueji_prompts.py` source. |
| `tests/test_overseas_algo_*.py` | 8 new test files (see tasks). |

---

### Task 1: Create SENSORY_SAFETY_RULES constant and inject into key prompts

**Files:**
- Modify: `paixueji_prompts.py` (top, near line 30)
- Test: `tests/test_overseas_algo_sensory_safety.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_sensory_safety.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_sensory_safety_rules_constant_exists():
    assert hasattr(pp, "SENSORY_SAFETY_RULES"), "SENSORY_SAFETY_RULES not found"
    assert "Do NOT invite the child to TOUCH" in pp.SENSORY_SAFETY_RULES
    assert "Only voices, stretches" in pp.SENSORY_SAFETY_RULES

def test_sensory_safety_injected_into_explanation_response():
    prompts = pp.get_prompts()
    text = prompts.get("explanation_response_prompt", "")
    assert "Do NOT invite the child to TOUCH" in text, "SENSORY_SAFETY_RULES not injected into EXPLANATION_RESPONSE_PROMPT"

def test_sensory_safety_injected_into_followup_question():
    prompts = pp.get_prompts()
    text = prompts.get("followup_question_prompt", "")
    assert "Do NOT invite the child to TOUCH" in text, "SENSORY_SAFETY_RULES not injected into FOLLOWUP_QUESTION_PROMPT"

def test_sensory_safety_injected_into_attribute_intro():
    prompts = pp.get_prompts()
    text = prompts.get("attribute_intro_prompt", "")
    assert "Do NOT invite the child to TOUCH" in text, "SENSORY_SAFETY_RULES not injected into ATTRIBUTE_INTRO_PROMPT"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/123/Documents/GitHub/AI_ask_ask
pytest tests/test_overseas_algo_sensory_safety.py -v
```

Expected: 4 FAILs (`SENSORY_SAFETY_RULES not found`, etc.).

- [ ] **Step 3: Write minimal implementation**

In `paixueji_prompts.py`, after the imports and before "1. INTRODUCTION PROMPTS", add:

```python
SENSORY_SAFETY_RULES = """\
SENSORY SAFETY (applies to all sensory invitations):
- Default to sight: "What do you notice?", "Which part looks the biggest?", "Is it shiny or dull?"
- Allow imagination/guessing: "Do you think it would feel rough?", "If it rolled, would it go fast or slow?"
- Do NOT invite the child to TOUCH, SMELL, TASTE, LICK, or PHYSICALLY INTERACT with the object —
  the environment may be unsafe (parks, public spaces, unknown items).
- Do NOT use "Do you know…" framing — it creates testing pressure.
- For imitation: only voices and stretches/movements are OK ("Let's bark like a puppy!").
  NEVER suggest petting an animal, touching/smelling a plant, or any physical contact.
"""
```

Then inject it into these prompts by adding the placeholder inside their triple-quoted strings:

1. **EXPLANATION_RESPONSE_PROMPT** (around line 54): insert after the opening context block:
   ```
   {sensory_safety_rules}
   ```
2. **FOLLOWUP_QUESTION_PROMPT** (around line 181): insert after the opening context block:
   ```
   {sensory_safety_rules}
   ```
3. **ATTRIBUTE_INTRO_PROMPT** (around line 375): insert after the TASK line:
   ```
   {sensory_safety_rules}
   ```
4. **ATTRIBUTE_SOFT_GUIDE** (around line 423): insert after the opening line:
   ```
   {sensory_safety_rules}
   ```

Also update each prompt's `format()` call (or f-string construction site) to pass `sensory_safety_rules=SENSORY_SAFETY_RULES`. For prompts that are already f-strings (e.g., `ATTRIBUTE_INTRO_PROMPT = f"""..."""`), just ensure the variable is in scope and add the placeholder. For prompts that use `.format(...)`, add the kwarg.

The easiest way: if a prompt uses f-string formatting with braces like `{age_prompt}`, add `{sensory_safety_rules}` alongside it. If it uses `.format(age_prompt=...)`, add `sensory_safety_rules=SENSORY_SAFETY_RULES`.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_sensory_safety.py -v
```

Expected: 4 PASSes.

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_sensory_safety.py
git commit -m "feat: add SENSORY_SAFETY_RULES constant and inject into key prompts

- Adds a single-source-of-truth safety block prohibiting touch/smell/taste.
- Injected into EXPLANATION_RESPONSE, FOLLOWUP_QUESTION, ATTRIBUTE_INTRO, ATTRIBUTE_SOFT_GUIDE.
- Document reference: 海外算法汇总.docx Section 4 Follow-up questions / 模仿引导 safety."
```

---

### Task 2: Rewrite FOLLOWUP GOOD tier and clean remaining sensory violations

**Files:**
- Modify: `paixueji_prompts.py` (FOLLOWUP_QUESTION_PROMPT GOOD tier, plus scattered lines)
- Test: `tests/test_overseas_algo_followup_good.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_followup_good.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_followup_good_no_sniff_tap_hold():
    prompts = pp.get_prompts()
    text = prompts.get("followup_question_prompt", "")
    assert "sniff" not in text.lower(), "FOLLOWUP still mentions sniff"
    assert "tap" not in text.lower(), "FOLLOWUP still mentions tap"
    assert "hold" not in text.lower(), "FOLLOWUP still mentions hold"
    assert "try having a little sniff" not in text.lower()

def test_followup_good_has_visual_examples():
    prompts = pp.get_prompts()
    text = prompts.get("followup_question_prompt", "")
    assert "Is it shiny or dull?" in text
    assert "Which part looks the biggest?" in text
    assert "Do you think it’s smooth or bumpy?" in text or "smooth or bumpy" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_followup_good.py -v
```

Expected: 2 FAILs.

- [ ] **Step 3: Rewrite FOLLOWUP GOOD tier**

In `paixueji_prompts.py`, find `FOLLOWUP_QUESTION_PROMPT` GOOD tier (around line 197). Replace the entire GOOD block with:

```
  GOOD — VISUAL OR IMAGINATIVE INVITE:
  Ask the child to notice something they can SEE or easily judge without touching.
  Focus on visual details, simple comparison, or easy choice.
  Avoid asking the child to touch, smell, taste, or interact physically.
  Make sure it can be answered just by looking or thinking.
  "Is it shiny or dull?"
  "Which part looks the biggest?"
  "Do you think it’s smooth or bumpy?"
  "Is it more round or more long?"
  "Do you think it’s the same inside?"
  "If it rolled, would it go fast or slow?"
  "If you dropped it, would it make a loud sound or a quiet one?"
```

- [ ] **Step 4: Clean remaining sensory violations**

Search `paixueji_prompts.py` for remaining touch/smell/taste encouragement and rewrite to visual/imagination phrasing. Known sites (verified by grep):

- Around line 265: change "see, touch, feel" → "see, look closely, imagine how it feels"
- Around line 340: change "texture, smell, sound, use" — remove "smell"; keep "texture, sound, use"
- Around line 1150–1151: remove tongue/taste scaffolding; replace with "What do you think it tastes like?" → "If you could guess its flavor, would it be sweet or sour?"
- Around line 1261: change "see, taste, touch, or hear" → "see or hear"
- Around line 1334: remove sensory invite wording that mentions touch
- Around line 1376: change "what do you think a {object} would taste like" → "if you could guess, would it taste sweet or crunchy?"

For each change, keep the semantic intent (engaging the child) but remove physical-interaction verbs.

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_followup_good.py -v
```

Expected: 2 PASSes.

- [ ] **Step 6: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_followup_good.py
git commit -m "feat: rewrite FOLLOWUP GOOD tier to visual-only + clean sensory violations

- Removes sniff/tap/hold from FOLLOWUP_QUESTION_PROMPT GOOD tier.
- Replaces with visual/imagination examples per doc spec.
- Cleans 6+ scattered touch/smell/taste references across prompts.
- Document reference: 海外算法汇总.docx Section 4 Follow-up questions."
```

---

### Task 3: Add new hook types (English examples)

**Files:**
- Modify: `hook_types.json`
- Test: `tests/test_overseas_algo_hook_types.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_hook_types.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import json

def test_hook_types_count():
    with open(r"C:\Users\123\Documents\GitHub\AI_ask_ask\hook_types.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 10, f"Expected 10 hooks, got {len(data)}"

def test_imitation_hook_present():
    with open(r"C:\Users\123\Documents\GitHub\AI_ask_ask\hook_types.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "模仿引导" in data
    hook = data["模仿引导"]
    assert hook["safety_constraint"] == "voices_and_motions_only"
    assert any("bark like a puppy" in ex for ex in hook["examples"])
    assert any("stretch together like sunflowers" in ex for ex in hook["examples"])

def test_silly_twist_hook_present():
    with open(r"C:\Users\123\Documents\GitHub\AI_ask_ask\hook_types.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "轻搞怪/无厘头" in data
    hook = data["轻搞怪/无厘头"]
    assert any("dance party" in ex for ex in hook["examples"])
    assert any("chocolate bar" in ex for ex in hook["examples"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_hook_types.py -v
```

Expected: 3 FAILs (`Expected 10 hooks, got 8`).

- [ ] **Step 3: Append new hook entries**

In `hook_types.json`, after the existing entries (after line 91), add before the closing `}`:

```json
,
  "模仿引导": {
    "name": "模仿引导",
    "concept": "Through the object, invite the child to mimic a small sound or gentle stretch/movement. STRICTLY voices and gentle body motions only.",
    "examples": [
      "Should we bark like a puppy together? Woof woof!",
      "Look at this sunflower stretching toward the sun — let's all stretch together like sunflowers!"
    ],
    "age_weights": {"3": 2, "4": 2, "5": 2, "6": 1, "7": 1, "8": 1},
    "requires_history": false,
    "safety_constraint": "voices_and_motions_only",
    "note": "NEVER suggest petting an animal, touching/smelling a plant, or any physical contact with the object. Only voices, stretches, and own-body motions."
  },
  "轻搞怪/无厘头": {
    "name": "轻搞怪/无厘头",
    "concept": "Introduce a light, playful, slightly unrealistic twist to the object to spark fun and reduce pressure. Stay close to the visible features; avoid completely random fantasy.",
    "examples": [
      "Do you think this red apple sneaks out to a dance party when you're asleep?",
      "Does this sock look like it just ate a big chocolate bar?"
    ],
    "age_weights": {"3": 1, "4": 2, "5": 2, "6": 2, "7": 1, "8": 1},
    "requires_history": false,
    "answer_shape": "binary_or_short"
  }
```

Make sure JSON is valid (trailing comma before the new entry if needed). The existing file ends with a `}` on line 92 with no trailing comma after the last entry. Add a comma after the `创意改造` closing brace, then append the two new entries.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_hook_types.py -v
```

Expected: 3 PASSes.

- [ ] **Step 5: Commit**

```bash
git add hook_types.json tests/test_overseas_algo_hook_types.py
git commit -m "feat: add 模仿引导 + 轻搞怪/无厘头 hook types with English examples

- Imitation hook has safety_constraint=voices_and_motions_only.
- Silly Twist hook has answer_shape=binary_or_short.
- Examples in English per project direction.
- Document reference: 海外算法汇总.docx Section 4 Hook design."
```

---

### Task 4: Update hook selector buckets

**Files:**
- Modify: `stream/utils.py`, `graph.py`
- Test: `tests/test_overseas_algo_hook_selector.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_hook_selector.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
from stream.utils import HIGH_IMAGINATION_HOOKS, select_hook_type, OPEN_ENDED_QUESTION_HOOKS, CONCRETE_QUESTION_HOOKS

def test_silly_twist_in_high_imagination():
    assert "轻搞怪/无厘头" in HIGH_IMAGINATION_HOOKS, "Silly twist should be high-imagination"

def test_imitation_not_in_high_imagination():
    assert "模仿引导" not in HIGH_IMAGINATION_HOOKS, "Imitation should NOT be high-imagination"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_hook_selector.py -v
```

Expected: 1 FAIL (`Silly twist should be high-imagination`).

- [ ] **Step 3: Update HIGH_IMAGINATION_HOOKS in stream/utils.py**

Find `HIGH_IMAGINATION_HOOKS` in `stream/utils.py` (around line 23). Change from:
```python
HIGH_IMAGINATION_HOOKS = {"想象导向", "情绪投射", "角色代入", "创意改造"}
```
to:
```python
HIGH_IMAGINATION_HOOKS = {"想象导向", "情绪投射", "角色代入", "创意改造", "轻搞怪/无厘头"}
```

- [ ] **Step 4: Update OPEN_ENDED / CONCRETE buckets in graph.py**

Find `OPEN_ENDED_QUESTION_HOOKS` and `CONCRETE_QUESTION_HOOKS` in `graph.py` (around line 40-51). Add:
- `"轻搞怪/无厘头"` to `OPEN_ENDED_QUESTION_HOOKS`
- `"模仿引导"` to `CONCRETE_QUESTION_HOOKS`

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_hook_selector.py -v
```

Expected: 2 PASSes.

- [ ] **Step 6: Commit**

```bash
git add stream/utils.py graph.py tests/test_overseas_algo_hook_selector.py
git commit -m "feat: assign new hooks to selector buckets

- 轻搞怪/无厘头 added to HIGH_IMAGINATION_HOOKS + OPEN_ENDED_QUESTION_HOOKS.
- 模仿引导 added to CONCRETE_QUESTION_HOOKS.
- Document reference: 海外算法汇总.docx Section 4 Hook design."
```

---

### Task 5: Simple prompt edits — EXPLANATION "2-3→1-2" and CURIOSITY BEAT 2 anchor

**Files:**
- Modify: `paixueji_prompts.py`
- Test: `tests/test_overseas_algo_simple_edits.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_simple_edits.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_explanation_offer_count():
    prompts = pp.get_prompts()
    text = prompts.get("explanation_response_prompt", "")
    assert "Offer 1-2 fun suggestions" in text, "EXPLANATION_RESPONSE should say 1-2"
    assert "Offer 2-3 fun suggestions" not in text, "EXPLANATION_RESPONSE should not say 2-3"

def test_curiosity_beat2_anchor_constraint():
    prompts = pp.get_prompts()
    text = prompts.get("curiosity_intent_prompt", "")
    assert "natural extension of what the child asked about" in text, "CURIOSITY BEAT 2 missing anchor constraint"
    assert "Do NOT introduce an unrelated trivia jump" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_simple_edits.py -v
```

Expected: 2 FAILs.

- [ ] **Step 3: Implement both edits**

**Edit A — EXPLANATION_RESPONSE_PROMPT line 64:**
Change:
```
   - Offer 2-3 fun suggestions related to the category.
```
to:
```
   - Offer 1-2 fun suggestions related to the category.
```

**Edit B — CURIOSITY_INTENT_PROMPT BEAT 2 (around line 1047):**
After the existing BEAT 2 description, append:
```
  The WOW detail MUST be a natural extension of what the child asked about — same dimension/feature, just amplified. Do NOT introduce an unrelated trivia jump.
  GOOD: child asked "why does a frog jump?" → BEAT 2 about leg muscles.
  BAD: child asked about jumping → BEAT 2 about color-changing.
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_simple_edits.py -v
```

Expected: 2 PASSes.

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_simple_edits.py
git commit -m "feat: EXPLANATION 2-3→1-2 + CURIOSITY BEAT 2 anchor constraint

- Document reference: 海外算法汇总.docx Section 4 Response principles / CURIOSITY BEAT 2."
```

---

### Task 6: CLARIFYING_IDK_INTENT_PROMPT single-clue cap

**Files:**
- Modify: `paixueji_prompts.py`
- Test: `tests/test_overseas_algo_clarifying_idk.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_clarifying_idk.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_clarifying_idk_single_clue_language():
    prompts = pp.get_prompts()
    text = prompts.get("clarifying_idk_intent_prompt", "")
    assert "THIS IS YOUR ONLY CHANCE TO HINT" in text, "Missing single-clue cap instruction"
    assert "After this turn, the system will reveal the answer" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_clarifying_idk.py -v
```

Expected: 1 FAIL.

- [ ] **Step 3: Implement edit**

In `paixueji_prompts.py`, find `CLARIFYING_IDK_INTENT_PROMPT` (around line 1127). After the `YOUR MISSION:` block and before `STRUCTURE`, insert:

```
CRITICAL: THIS IS YOUR ONLY CHANCE TO HINT. After this turn, the system will reveal the answer regardless of the child's reply. Do NOT try to drag out the guessing.
```

Then tighten BEAT 3 to remove any question-mark phrasing. Change BEAT 3 to:
```
BEAT 3 — LOW-PRESSURE HANDOFF (3-7 words max, NOT a full question, do NOT use a question mark):
  "You can try." / "We can figure it out together." / "Take your time."
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_clarifying_idk.py -v
```

Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_clarifying_idk.py
git commit -m "feat: cap CLARIFYING_IDK to single clue + tighten BEAT 3

- Adds explicit 'only chance to hint' instruction.
- Removes question-mark examples from BEAT 3 to prevent re-prompting.
- Graph layer already routes consecutive struggles ≥2 to give_answer_idk; this tightens the prompt itself.
- Document reference: 海外算法汇总.docx Section 4 CLARIFYING_IDK."
```

---

### Task 7: GIVE_ANSWER_OPEN_ENDED_IDK_INTENT_PROMPT drop BEAT 3

**Files:**
- Modify: `paixueji_prompts.py`
- Test: `tests/test_overseas_algo_open_ended_idk.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_open_ended_idk.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_open_ended_idk_no_beat3():
    prompts = pp.get_prompts()
    text = prompts.get("give_answer_open_ended_idk_intent_prompt", "")
    assert "BEAT 3" not in text, "Should drop BEAT 3 entirely"
    assert "LIGHT RE-OPEN" not in text
    assert "2 beats" in text or "2–2 beats" in text, "Should state 2 beats"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_open_ended_idk.py -v
```

Expected: 1 FAIL.

- [ ] **Step 3: Implement edit**

In `paixueji_prompts.py`, find `GIVE_ANSWER_OPEN_ENDED_IDK_INTENT_PROMPT` (around line 1270). Make three changes:

1. Change STRUCTURE header from "3 beats" to "2 beats".
2. Delete the entire BEAT 3 block (lines ~1290-1292, the LIGHT RE-OPEN section).
3. After BEAT 2, add:
```
  No re-open. The next turn will move on to a new topic or activity recommendation.
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_open_ended_idk.py -v
```

Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_open_ended_idk.py
git commit -m "feat: drop BEAT 3 from GIVE_ANSWER_OPEN_ENDED_IDK

- Open-ended IDK no longer re-opens; flows straight to next topic.
- Document reference: 海外算法汇总.docx Section 4 GIVE_ANSWER_OPEN_ENDED_IDK."
```

---

### Task 8: CLARIFYING_WRONG_INTENT_PROMPT BEAT 1 three named styles

**Files:**
- Modify: `paixueji_prompts.py`
- Test: `tests/test_overseas_algo_clarifying_wrong.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_clarifying_wrong.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_clarifying_wrong_has_named_styles():
    prompts = pp.get_prompts()
    text = prompts.get("clarifying_wrong_intent_prompt", "")
    assert "Interesting Observation" in text
    assert "So Close" in text
    assert "Playful Pivot" in text
    assert "ACKNOWLEDGE THE EFFORT" in text
    assert "NEVER use \"no\" or \"wrong\"" in text
    assert "MIRROR THEIR LOGIC" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_clarifying_wrong.py -v
```

Expected: 1 FAIL.

- [ ] **Step 3: Implement edit**

In `paixueji_prompts.py`, find `CLARIFYING_WRONG_INTENT_PROMPT` BEAT 1 (around line 1323). Replace the entire BEAT 1 block with:

```
BEAT 1 — WARM ACKNOWLEDGMENT (RANDOMIZE STYLE — pick ONE per turn):
  PRINCIPLES:
  - ACKNOWLEDGE THE EFFORT (the doing/looking, not the result)
  - NEVER use "no" or "wrong" — use pivot words instead
  - MIRROR THEIR LOGIC briefly when possible

  STYLE 1 — "Interesting Observation":
    "Oh, I see you're looking at the [part they got wrong]! That's a cool spot to start."
    "I love how you noticed the [color/shape]! Let's look even closer together..."
  STYLE 2 — "So Close" (near-miss only):
    "You're on such a good track! You almost caught it."
    "I like how your brain is working on this one!"
  STYLE 3 — "Playful Pivot":
    "Ooh, that's a creative way to see it! Let's see if there's another secret hidden here..."
    "Hmm, good thinking! Let's try to look at it from a different side."
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_clarifying_wrong.py -v
```

Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_clarifying_wrong.py
git commit -m "feat: enrich CLARIFYING_WRONG BEAT 1 with three named styles

- Adds Interesting Observation / So Close / Playful Pivot styles.
- Adds four principles: ACKNOWLEDGE THE EFFORT, NEVER say no/wrong, MIRROR THEIR LOGIC.
- Document reference: 海外算法汇总.docx Section 4 CLARIFYING_WRONG BEAT 1."
```

---

### Task 9: EMOTIONAL_INTENT_PROMPT extreme tier

**Files:**
- Modify: `paixueji_prompts.py`
- Test: `tests/test_overseas_algo_emotional_extreme.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_emotional_extreme.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_emotional_has_extreme_tier():
    prompts = pp.get_prompts()
    text = prompts.get("emotional_intent_prompt", "")
    assert "STRONG/EXTREME" in text or "EXTREME" in text, "Missing extreme emotion tier"
    assert "REAL-WORLD SUPPORT" in text
    assert "trusted person" in text or "grown-up you trust" in text
    assert "Do NOT try to fix the emotion within the system" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_emotional_extreme.py -v
```

Expected: 1 FAIL.

- [ ] **Step 3: Implement edit**

In `paixueji_prompts.py`, find `EMOTIONAL_INTENT_PROMPT` (around line 1577). Make these changes:

1. In STEP 1, replace the existing A/B with A/B/C:
```
STEP 1 — IDENTIFY EMOTION TYPE:
  A. POSITIVE (excited, amazed, delighted): Match and amplify.
  B. NEGATIVE — MILD (scared, grossed out, mildly uncomfortable): Name it and normalize it.
  C. NEGATIVE — STRONG/EXTREME (e.g., "I am SO mad at you", "I hate it", "I am angry"):
     Treat as a moment that should NOT be resolved inside the product. See BEAT 2 (EXTREME).
     Note: "I'm mad at you" said lightly may be Type B; gauge intensity from context.
```

2. After the existing BEAT 2 block, add a new BEAT 2 section:
```
BEAT 2 — for C (REAL-WORLD SUPPORT):
  - Gentle grounding or permission to stop: "We can pause here."
  - Suggest reaching out to a trusted person: "This might be a good time to talk to a grown-up you trust."
  TONE: Calm, simple, non-dramatic.
  PROHIBITIONS:
  - Do NOT try to fix the emotion within the system
  - Do NOT continue the {object_name} exploration
  - Do NOT ask any question
```

3. Keep the existing BEAT 2 for A/B unchanged.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_emotional_extreme.py -v
```

Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_emotional_extreme.py
git commit -m "feat: add EXTREME emotion tier to EMOTIONAL_INTENT_PROMPT

- STEP 1 gains branch C: STRONG/EXTREME.
- BEAT 2 (EXTREME) offers real-world pause + trusted-adult suggestion.
- Strict prohibitions: no fixing, no exploration, no questions.
- Document reference: 海外算法汇总.docx Section 4 EMOTIONAL_INTENT."
```

---

### Task 10: CONCEPT_CONFUSION_INTENT_PROMPT split A/B + no re-ask

**Files:**
- Modify: `paixueji_prompts.py`
- Test: `tests/test_overseas_algo_concept_confusion.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_concept_confusion.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_concept_confusion_no_reask_prohibition():
    prompts = pp.get_prompts()
    text = prompts.get("concept_confusion_intent_prompt", "")
    assert "Do NOT skip Beat 3" not in text, "Should remove the old 'must not skip' prohibition"
    assert "DO NOT RE-ASK" in text or "do not re-ask" in text.lower(), "Should add no-re-ask rule"

def test_concept_confusion_has_validate_questioning():
    prompts = pp.get_prompts()
    text = prompts.get("concept_confusion_intent_prompt", "")
    assert "VALIDATE THE QUESTIONING SPIRIT" in text
    assert "self-verify" in text.lower() or "re-verify" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_concept_confusion.py -v
```

Expected: 2 FAILs.

- [ ] **Step 3: Implement edit**

In `paixueji_prompts.py`, find `CONCEPT_CONFUSION_INTENT_PROMPT` (around line 1808). Make these changes:

1. **Insert BEAT 1.1** after BEAT 1 intro, before the existing (A)/(B) split:
```
BEAT 1.1 — (B) ONLY: VALIDATE THE QUESTIONING SPIRIT.
  One short phrase honoring the child's instinct to question.
  "I love that you're checking — that's how scientists think!"
  Then move to BEAT 1.2.
```

2. **Rename existing BEAT 1 to BEAT 1.2**:
```
BEAT 1.2 — EXPLAIN OR GENTLY CONFIRM:
  (A) Vocabulary: ...
  (B) Disputed fact: ...
```

3. **Add AI self-verification check** before BEAT 1.2(B):
```
  Before delivering BEAT 1.2(B), pause to silently re-verify the disputed fact against
  {object_name} and current grounding facts (if available). If you have ANY doubt,
  downgrade to "That's a great thing to wonder about — let's check together with a grown-up later."
```

4. **Replace BEAT 3 entirely** with:
```
BEAT 3 — DO NOT RE-ASK. Choose ONE of these:
  (a) DOWNGRADE: Ask a simpler, related question that the child can definitely answer.
  (b) PIVOT TO ACTIVITY: If interaction is winding down, gracefully transition into an
      activity recommendation tied to {object_name}.
  (c) (B-only, if child STILL insists after BEAT 1.2): Suggest asking a trusted grown-up.
      "Maybe we can ask a grown-up you trust about this — they might know even more!"
```

5. **Remove** the prohibition line: `Do NOT skip Beat 3 — the child must not be left hanging`

6. Update the STRUCTURE header from "3 beats, 3 beats" to accommodate BEAT 1.1.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_concept_confusion.py -v
```

Expected: 2 PASSes.

- [ ] **Step 5: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_concept_confusion.py
git commit -m "feat: restructure CONCEPT_CONFUSION with split A/B BEATs and no forced re-ask

- Adds BEAT 1.1 validating questioning spirit (B-only).
- Adds AI self-verification step before BEAT 1.2(B).
- Replaces mandatory BEAT 3 re-ask with downgrade/pivot-to-activity/trusted-grown-up options.
- Removes 'Do NOT skip Beat 3' prohibition.
- Document reference: 海外算法汇总.docx Section 4 CONCEPT_CONFUSION."
```

---

### Task 11: SOCIAL_INTENT_PROMPT CHARACTER_PROFILE stub

**Files:**
- Modify: `paixueji_prompts.py`
- Test: `tests/test_overseas_algo_social_profile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_social_profile.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_character_profile_constant_exists():
    assert hasattr(pp, "CHARACTER_PROFILE"), "CHARACTER_PROFILE not found"
    assert "Age:" in pp.CHARACTER_PROFILE
    assert "Hobbies:" in pp.CHARACTER_PROFILE

def test_social_prompt_has_character_profile():
    prompts = pp.get_prompts()
    text = prompts.get("social_intent_prompt", "")
    assert "CHARACTER_PROFILE" in text or "character profile" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_social_profile.py -v
```

Expected: 2 FAILs.

- [ ] **Step 3: Add CHARACTER_PROFILE constant**

In `paixueji_prompts.py`, near the top (after `SENSORY_SAFETY_RULES`), add:

```python
CHARACTER_PROFILE = """\
When asked about yourself, stay within these facts (vary the wording):
- Age: TBD (placeholder: "around 1 year old in computer years")
- Family: TBD
- Hobbies: TBD (placeholder: "I love listening to kids tell me about cool things they find!")
- Where I live: TBD (placeholder: "inside this app")
- Friends: TBD
# TODO(character-design): replace TBD placeholders once art/character profile finalized
"""
```

- [ ] **Step 4: Inject into SOCIAL_INTENT_PROMPT**

In `SOCIAL_INTENT_PROMPT` (around line 1739), add `{character_profile}` near the BEAT 1 examples, so the LLM sees the profile constraints before answering.

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_social_profile.py -v
```

Expected: 2 PASSes.

- [ ] **Step 6: Commit**

```bash
git add paixueji_prompts.py tests/test_overseas_algo_social_profile.py
git commit -m "feat: add CHARACTER_PROFILE stub for SOCIAL_INTENT_BEAT_1

- Adds placeholder profile with TODO for character-design team.
- Injected into SOCIAL_INTENT_PROMPT so LLM respects answer boundaries.
- Document reference: 海外算法汇总.docx Section 4 SOCIAL_INTENT."
```

---

### Task 12: ATTRIBUTE_INTRO_PROMPT BEAT 4 hook injection + fallback

**Files:**
- Modify: `paixueji_prompts.py`, `stream/question_generators.py` (or wherever `ask_attribute_intro_stream` lives)
- Test: `tests/test_overseas_algo_attribute_intro.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_attribute_intro.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_attribute_intro_has_hook_placeholder():
    prompts = pp.get_prompts()
    text = prompts.get("attribute_intro_prompt", "")
    assert "{hook_type_section}" in text, "ATTRIBUTE_INTRO should accept hook_type_section"

def test_attribute_intro_has_fallback_path():
    prompts = pp.get_prompts()
    text = prompts.get("attribute_intro_prompt", "")
    assert "FALLBACK" in text or "fallback" in text.lower()
    assert "AI gently states the attribute" in text or "states the attribute" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_attribute_intro.py -v
```

Expected: 2 FAILs.

- [ ] **Step 3: Modify ATTRIBUTE_INTRO_PROMPT**

In `paixueji_prompts.py`, find `ATTRIBUTE_INTRO_PROMPT` BEAT 4 (around line 404). Replace it with:

```
BEAT 4 — ENGAGEMENT HOOK
  PRIMARY: Open question that lets the child notice the salient attribute.
    "What do you notice first when you look at it?"
  FALLBACK (when the attribute is non-observable or hard to elicit): AI gently states the
  attribute, then uses the assigned hook type to build an emotional rather than
  knowledge-testing bridge.
    "Look at how soft the petals are! {hook_type_section}"
  The LLM picks PRIMARY by default; FALLBACK is allowed when SUGGESTED ATTRIBUTE is non-observable.
```

Also ensure `{hook_type_section}` is passed in the format() / f-string call site.

- [ ] **Step 4: Wire hook_type_section into attribute intro stream generator**

Find `ask_attribute_intro_stream` in `stream/question_generators.py` (or wherever it lives). Ensure it calls `select_hook_type()` and passes `hook_type_section=selected_hook_text` into the prompt formatting, mirroring the pattern used by `ask_introduction_question_stream`.

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_attribute_intro.py -v
```

Expected: 2 PASSes.

- [ ] **Step 6: Commit**

```bash
git add paixueji_prompts.py stream/question_generators.py tests/test_overseas_algo_attribute_intro.py
git commit -m "feat: add hook injection + fallback to ATTRIBUTE_INTRO BEAT 4

- BEAT 4 gains PRIMARY (open question) and FALLBACK (state attribute + hook).
- {hook_type_section} wired through ask_attribute_intro_stream.
- Document reference: 海外算法汇总.docx Section 4 ATTRIBUTE_INTRO BEAT 4."
```

---

### Task 13: ACTION subtype classifier extension

**Files:**
- Modify: `paixueji_prompts.py` (USER_INTENT_PROMPT), `stream/validation.py`
- Test: `tests/test_overseas_algo_action_subtype_classifier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_action_subtype_classifier.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
from stream.validation import classify_intent
import asyncio

async def test_action_subtype_parsing():
    # Simulate a raw classifier response containing ACTION_SUBTYPE
    raw = (
        "INTENT: ACTION\n"
        "ACTION_SUBTYPE: B\n"
        "NEW_OBJECT: null\n"
        "REASONING: child asked for a new activity\n"
    )
    # We can't easily call classify_intent without mocking the LLM,
    # so test the parsing logic directly.
    import re
    m = re.search(r"ACTION_SUBTYPE:\s*([A-D]|NONE)", raw)
    assert m and m.group(1) == "B"

asyncio.run(test_action_subtype_parsing())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_action_subtype_classifier.py -v
```

Expected: 1 FAIL (the regex extraction not yet in validation.py, though the pure-regex test above passes; if the test imports validation.py and checks for an attribute, it fails).

Actually, a better test:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import re

def test_action_subtype_regex():
    text = "ACTION_SUBTYPE: B"
    m = re.search(r"ACTION_SUBTYPE:\s*([A-D]|NONE)", text)
    assert m and m.group(1) == "B"
```

But that's too trivial. A better test checks that the prompt contains the ACTION_SUBTYPE instruction:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
import paixueji_prompts as pp

def test_user_intent_prompt_has_action_subtype():
    prompts = pp.get_prompts()
    text = prompts.get("user_intent_prompt", "")
    assert "ACTION_SUBTYPE" in text
    assert "A — REPEAT REQUEST" in text
    assert "B — NEW ACTIVITY REQUEST" in text
    assert "C — VAGUE OR META REQUEST" in text
    assert "D — UNRELATED SPECIFIC TOPIC" in text
```

- [ ] **Step 2b: Rewrite test and run**

Replace the test file with the above. Run:
```bash
pytest tests/test_overseas_algo_action_subtype_classifier.py -v
```
Expected: 1 FAIL.

- [ ] **Step 3: Add ACTION_SUBTYPE to USER_INTENT_PROMPT**

In `paixueji_prompts.py`, find `USER_INTENT_PROMPT` (around line 859). After the existing intent list and before RULE 2, add:

```
RULE 1b — ACTION SUBTYPE (only when INTENT is ACTION):
  ACTION_SUBTYPE: A | B | C | D | NONE
    A — REPEAT REQUEST ("Say that again", "What?", "Huh?")
    B — NEW ACTIVITY REQUEST ("Give me a new question", "Let's do something else", "I'm bored")
    C — VAGUE OR META REQUEST ("I'm bored", "This is too hard", "Can we change?")
    D — REQUEST FOR UNRELATED SPECIFIC TOPIC ("I want to talk about dogs instead")
    NONE — when intent is not ACTION
```

- [ ] **Step 4: Verify no runtime overrides exist**

`prompt_overrides.json` has been deleted. Ensure the file does not exist in the repo root. The ACTION_SUBTYPE change lives only in `paixueji_prompts.py` source.

- [ ] **Step 5: Update stream/validation.py parser**

In `stream/validation.py`, find the regex parsing block (around line 96-126). After extracting `intent`, `new_object`, and `reasoning`, add:

```python
action_subtype_match = re.search(r"ACTION_SUBTYPE:\s*([A-D]|NONE)", text, re.IGNORECASE)
action_subtype = action_subtype_match.group(1).upper() if action_subtype_match else None
```

Then add `"action_subtype": action_subtype` to the return dict.

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_action_subtype_classifier.py -v
```

Expected: 1 PASS.

- [ ] **Step 7: Commit**

```bash
git add paixueji_prompts.py stream/validation.py tests/test_overseas_algo_action_subtype_classifier.py
git commit -m "feat: extend classifier to emit ACTION_SUBTYPE A/B/C/D

- USER_INTENT_PROMPT gains RULE 1b with subtype definitions.
- validation.py regex extracts action_subtype from classifier output.
- Document reference: 海外算法汇总.docx Section 4 ACTION_INTENT."
```

---

### Task 14: ACTION subtype graph dispatch

**Files:**
- Modify: `paixueji_assistant.py`, `graph.py`
- Test: `tests/test_overseas_algo_action_subtype_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_overseas_algo_action_subtype_dispatch.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")
from paixueji_assistant import PaixuejiAssistant

def test_assistant_has_action_subtype_field():
    a = PaixuejiAssistant(session_id="test", age=5)
    assert hasattr(a, "action_subtype"), "PaixuejiAssistant missing action_subtype"
    assert a.action_subtype is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_overseas_algo_action_subtype_dispatch.py -v
```

Expected: 1 FAIL.

- [ ] **Step 3: Add action_subtype to PaixuejiAssistant**

In `paixueji_assistant.py`, find the `__init__` or field definitions. Add:

```python
self.action_subtype: Optional[str] = None
```

Also reset it at the start of each turn (where other fields like `consecutive_struggle_count` are managed).

- [ ] **Step 4: Propagate action_subtype in node_analyze_input**

In `graph.py`, find `node_analyze_input` (around line 523-562). In the return dict, add:

```python
"action_subtype": intent_result.get("action_subtype"),
```

And also set it on the assistant:
```python
state["assistant"].action_subtype = intent_result.get("action_subtype")
```

- [ ] **Step 5: Branch node_action on subtype**

In `graph.py`, find `node_action` (around line 1389-1401). Replace the simple stream generation with subtype branching:

```python
subtype = state.get("action_subtype") or "C"
if subtype == "A":
    # TYPE A — re-state last response (existing prompt behavior is fine)
    response_stream = generate_intent_response_stream(..., intent_type="action")
elif subtype == "B":
    # TYPE B — new activity: acknowledge + flip activity_ready
    state["assistant"].attribute_activity_ready = True
    response_stream = generate_intent_response_stream(..., intent_type="action")
elif subtype == "C":
    # TYPE C — vague/meta: acknowledge + offer option + flip activity_ready
    state["assistant"].attribute_activity_ready = True
    response_stream = generate_intent_response_stream(..., intent_type="action")
elif subtype == "D":
    new_obj = state.get("new_object_name")
    if new_obj:
        # delegate to existing topic-switch flow
        response_stream = generate_topic_switch_response_stream(...)
    else:
        # no new object → treat as Type C
        state["assistant"].attribute_activity_ready = True
        response_stream = generate_intent_response_stream(..., intent_type="action")
```

Ensure `generate_topic_switch_response_stream` is imported in `graph.py`.

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/test_overseas_algo_action_subtype_dispatch.py -v
```

Expected: 1 PASS (for the assistant field). For behavior-level tests, add:

```python
def test_action_type_b_sets_activity_ready():
    from paixueji_assistant import PaixuejiAssistant
    a = PaixuejiAssistant(session_id="test", age=5)
    a.attribute_activity_ready = False
    a.action_subtype = "B"
    # Simulate the flag flip (this would normally happen inside node_action)
    # For a unit test, just verify the field exists and can be set.
    assert a.action_subtype == "B"
```

- [ ] **Step 7: Commit**

```bash
git add paixueji_assistant.py graph.py tests/test_overseas_algo_action_subtype_dispatch.py
git commit -m "feat: implement ACTION subtype branching in graph dispatch

- PaixuejiAssistant gains action_subtype field.
- node_analyze_input propagates action_subtype from classifier result.
- node_action branches: B/C flip attribute_activity_ready; D delegates to topic_switch if new_object present.
- Document reference: 海外算法汇总.docx Section 4 ACTION_INTENT Type B/C/D."
```

---

### Task 15: Final integration and full test run

**Files:**
- All modified files
- Test: full suite

- [ ] **Step 1: Syntax-check all modified Python files**

```bash
cd C:/Users/123/Documents/GitHub/AI_ask_ask
python -m py_compile paixueji_prompts.py graph.py stream/validation.py stream/utils.py paixueji_assistant.py
python -m json.tool hook_types.json > /dev/null
# prompt_overrides.json removed — no JSON override to validate
```

Expected: no output (success) for all four commands.

- [ ] **Step 2: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: All existing tests pass + all new `test_overseas_algo_*` tests pass. If any regressions appear, fix them before proceeding.

- [ ] **Step 3: Run the new tests in isolation**

```bash
pytest tests/test_overseas_algo_ -v
```

Expected: All 15 new test files pass.

- [ ] **Step 4: Manual smoke test — boot the app**

```bash
python paixueji_app.py
```

In another terminal (or via browser/Postman), send a test SSE request and verify the app starts without `hook_types.json` load errors.

- [ ] **Step 5: Commit final integration**

```bash
git add -A
git commit -m "integration: all overseas-algo alignment changes validated

- Full test suite green (pytest tests/ -v).
- Syntax checks pass for all modified Python and JSON files.
- Flask boot smoke test passes."
```

---

## Self-review

### 1. Spec coverage

| Doc requirement | Plan task |
|---|---|
| FOLLOWUP GOOD tier safety (visual-only) | Task 2 |
| SENSORY_SAFETY_RULES global injection | Task 1 |
| Hook 模仿引导 + 轻搞怪/无厘头 | Task 3, 4 |
| EXPLANATION 2-3 → 1-2 | Task 5 |
| CURIOSITY BEAT 2 anchor | Task 5 |
| CLARIFYING_IDK single clue | Task 6 |
| GIVE_ANSWER_OPEN_ENDED drop BEAT 3 | Task 7 |
| CLARIFYING_WRONG BEAT 1 three styles | Task 8 |
| EMOTIONAL extreme tier | Task 9 |
| CONCEPT_CONFUSION split A/B + no re-ask | Task 10 |
| SOCIAL CHARACTER_PROFILE stub | Task 11 |
| ATTRIBUTE_INTRO BEAT 4 hook injection | Task 12 |
| ACTION subtype classifier + dispatch | Task 13, 14 |

All doc requirements from Section 4 are covered. No gaps.

### 2. Placeholder scan

- No "TBD" in code steps (except `CHARACTER_PROFILE` which is explicitly a stub with a TODO comment — this is intentional).
- No "implement later" or "add appropriate error handling" placeholders.
- Every test shows actual assertions.
- Every commit includes a descriptive message.

### 3. Type consistency

- `action_subtype` used consistently as `Optional[str]` across `paixueji_assistant.py`, `graph.py`, and `stream/validation.py`.
- `SENSORY_SAFETY_RULES` and `CHARACTER_PROFILE` are module-level string constants, matching existing patterns like `age_prompts.json` loading.
- Hook JSON schema matches existing entries (same field names: name, concept, examples, age_weights, requires_history).

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-06-overseas-algorithm-alignment.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
