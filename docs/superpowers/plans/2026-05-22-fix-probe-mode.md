# Fix PROBE Mode: Separate Response and Verification Question Generation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove pushy PROBE directive injection from the response generator, move verification context to the follow-up generator only, and let PROBE mode use the follow-up question generator for gentle verification questions.

**Architecture:** PROBE mode currently forces the response generator to both celebrate the child's input AND ask a verification question in a single LLM call. This contradicts the two-step design (response generator → follow-up generator) and produces pushy language. The fix treats PROBE like CONTINUE for the response part, but uses a dedicated verification guide in the follow-up generator.

**Tech Stack:** Python, Flask, Gemini API, pytest

---

### File Structure

| File | Responsibility |
|------|-------------|
| `stream/verification_guided_conversation.py` | New `build_probe_verification_context` function — gentle verification guide for PROBE follow-ups |
| `paixueji_app.py` | Remove PROBE directive injection, remove verification context from response generator path, add PROBE to follow-up condition, add PROBE-specific verification guide |
| `tests/test_diagnose_orange_cat.py` | Strengthen `test_probe_mode_generates_followup_question`, add `test_build_probe_verification_context` |

---

### Task 1: Add `build_probe_verification_context` to VGC module

**Files:**
- Modify: `stream/verification_guided_conversation.py:152` (after `check_probe_needed`)

- [ ] **Step 1: Write the function**

```python
def build_probe_verification_context(pending_items: list[VerificationItem]) -> str:
    """Build a gentle, direct verification guide for PROBE mode follow-ups.

    Unlike `build_verification_context` which tells the LLM to guide naturally
    and NOT ask directly, this function instructs the LLM to ask the pending
    verification question directly but gently.
    """
    lines = ["[VERIFICATION -- ask gently and directly]"]
    for item in pending_items:
        q = getattr(item, "question", "")
        if q:
            lines.append(f"- {q}")
    lines.append(
        "\nAsk ONE of these questions in a warm, natural way. "
        "Do NOT command. Do NOT demand. Sound like a curious friend."
    )
    return "\n".join(lines)
```

- [ ] **Step 2: Verify no syntax errors**

Run: `python -c "from stream.verification_guided_conversation import build_probe_verification_context; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add stream/verification_guided_conversation.py
git commit -m "feat: add build_probe_verification_context for gentle PROBE follow-ups"
```

---

### Task 2: Import `build_probe_verification_context` in `paixueji_app.py`

**Files:**
- Modify: `paixueji_app.py:290-295`

- [ ] **Step 1: Add import**

Change:
```python
from stream.verification_guided_conversation import (
    build_verification_context,
    classify_verification,
    check_probe_needed,
    VerificationItem,
)
```

To:
```python
from stream.verification_guided_conversation import (
    build_verification_context,
    build_probe_verification_context,
    classify_verification,
    check_probe_needed,
    VerificationItem,
)
```

- [ ] **Step 2: Commit**

```bash
git add paixueji_app.py
git commit -m "chore: import build_probe_verification_context"
```

---

### Task 3: Delete PROBE directive injection

**Files:**
- Modify: `paixueji_app.py:1831-1835`

- [ ] **Step 1: Remove the directive block**

Delete these 5 lines:
```python
                            # PROBE mode: append a directive to ask more directly
                            soft_guide = (
                                f"{soft_guide}\n\n[DIRECTIVE] The child seems close to being ready for an activity, "
                                "but we need to confirm one thing first. Ask a clear, direct question to verify the pending property."
                            )
```

After deletion, the `elif decision == HandoffDecision.PROBE:` branch ends at the `_build_continue_guide(...)` call, identical to the `else:` (CONTINUE) branch above it.

- [ ] **Step 2: Commit**

```bash
git add paixueji_app.py
git commit -m "fix: remove pushy PROBE directive injection from response generator"
```

---

### Task 4: Move verification context out of response generator path

**Files:**
- Modify: `paixueji_app.py:1860-1867`

- [ ] **Step 1: Delete the verification context injection block**

Delete these 8 lines:
```python
                        # VGC: Inject pending verification context into prompt
                        pending_for_prompt = [
                            v for v in assistant.attribute_state.verification_queue
                            if v.status == "pending"
                        ]
                        if pending_for_prompt:
                            verification_ctx = build_verification_context(pending_for_prompt)
                            soft_guide = f"{soft_guide}\n\n{verification_ctx}"
```

This removes verification context from ALL response generator paths (CONTINUE, CONTINUE_SWITCH, PROBE). The response generator now receives only the base guide with no verification hints.

- [ ] **Step 2: Commit**

```bash
git add paixueji_app.py
git commit -m "fix: remove verification context from response generator path"
```

---

### Task 5: Add PROBE to follow-up generation condition

**Files:**
- Modify: `paixueji_app.py:1958-1960`

- [ ] **Step 1: Add PROBE to the condition**

Change:
```python
                        if (
                            needs_followup
                            and decision in (HandoffDecision.CONTINUE, HandoffDecision.CONTINUE_SWITCH)
                        ):
```

To:
```python
                        if (
                            needs_followup
                            and decision in (HandoffDecision.CONTINUE, HandoffDecision.CONTINUE_SWITCH, HandoffDecision.PROBE)
                        ):
```

- [ ] **Step 2: Commit**

```bash
git add paixueji_app.py
git commit -m "fix: allow PROBE mode to use follow-up question generator"
```

---

### Task 6: Add PROBE-specific verification guide in follow-up path

**Files:**
- Modify: `paixueji_app.py:1966-1969` (inside the follow-up block, before `followup_generator = ...`)

- [ ] **Step 1: Replace the followup_soft_guide construction**

Current code:
```python
                            followup_soft_guide = (
                                soft_guide.split("---\n\n[SYSTEM CONTEXT]")[0].strip()
                                if soft_guide else soft_guide
                            )
```

Replace with:
```python
                            pending_for_prompt = [
                                v for v in assistant.attribute_state.verification_queue
                                if v.status == "pending"
                            ]

                            if decision == HandoffDecision.PROBE and pending_for_prompt:
                                followup_soft_guide = build_probe_verification_context(pending_for_prompt)
                            else:
                                followup_soft_guide = (
                                    soft_guide.split("---\n\n[SYSTEM CONTEXT]")[0].strip()
                                    if soft_guide else soft_guide
                                )
                                if pending_for_prompt:
                                    verification_ctx = build_verification_context(pending_for_prompt)
                                    followup_soft_guide = f"{followup_soft_guide}\n\n{verification_ctx}"
```

**Logic:**
- For PROBE mode with pending items: use the new gentle-direct verification context (replaces the continue guide entirely)
- For CONTINUE/CONTINUE_SWITCH: keep existing behavior — strip system context and append standard verification context if pending

- [ ] **Step 2: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: use gentle verification guide for PROBE follow-up questions"
```

---

### Task 7: Update regression tests

**Files:**
- Modify: `tests/test_diagnose_orange_cat.py:345-367`

- [ ] **Step 1: Strengthen `test_probe_mode_generates_followup_question`**

The existing test checks that PROBE is in the followup condition. After the fix, strengthen it to verify the followup path actually produces verification-related text:

Replace the existing `test_probe_mode_generates_followup_question` with:

```python
def test_probe_mode_generates_followup_question():
    """
    PROBE mode should be included in the follow-up question generation condition
    so the response generator doesn't have to violate its own 'Do NOT ask
    a question' rule.
    """
    import pathlib

    source_path = pathlib.Path(__file__).parent.parent / "paixueji_app.py"
    source = source_path.read_text(encoding="utf-8")

    # Find the followup decision condition block
    followup_condition_match = re.search(
        r'if\s*\(\s*needs_followup[\s\S]*?decision in\s*\(([^)]+)\)',
        source,
    )
    assert followup_condition_match is not None, (
        "Could not find followup condition block"
    )
    decisions_str = followup_condition_match.group(1)
    assert "PROBE" in decisions_str or "probe" in decisions_str.lower(), (
        "PROBE decision must be included in followup generation"
    )

    # Verify PROBE uses build_probe_verification_context in the followup path
    assert "build_probe_verification_context" in source, (
        "PROBE followup must use build_probe_verification_context"
    )
```

- [ ] **Step 2: Add `test_build_probe_verification_context`**

Add this new test after `test_probe_mode_generates_followup_question`:

```python
def test_build_probe_verification_context():
    """Unit test for build_probe_verification_context."""
    from stream.verification_guided_conversation import (
        build_probe_verification_context,
        VerificationItem,
    )

    items = [
        VerificationItem(
            property="has_fluffy_fur",
            question="Does it have fluffy fur?",
            for_activity_id="fluffy_expedition_dandelion",
        ),
    ]
    result = build_probe_verification_context(items)
    assert "Does it have fluffy fur?" in result
    assert "ask gently and directly" in result.lower()
    assert "Do NOT command" in result
    assert "Do NOT demand" in result
```

- [ ] **Step 3: Run the orange cat tests**

Run: `pytest tests/test_diagnose_orange_cat.py -v`
Expected: All tests pass, especially:
- `test_probe_directive_does_not_use_pushy_language` (PASS — directive removed)
- `test_probe_mode_generates_followup_question` (PASS — PROBE in condition, new function used)
- `test_build_probe_verification_context` (PASS — new function works)

- [ ] **Step 4: Commit**

```bash
git add tests/test_diagnose_orange_cat.py
git commit -m "test: strengthen PROBE followup tests and add build_probe_verification_context unit test"
```

---

### Task 8: Run full test suite

- [ ] **Step 1: Run attribute pipeline tests**

Run: `pytest tests/test_attribute_activity_api.py -v`
Expected: All pass

- [ ] **Step 2: Run CARES handoff tests**

Run: `pytest tests/test_cares_handoff.py -v`
Expected: All pass

- [ ] **Step 3: Run all orange cat regression tests**

Run: `pytest tests/test_diagnose_orange_cat.py -v`
Expected: All pass

- [ ] **Step 4: Final commit (if any fixes needed)**

If any tests failed, fix and commit. If all passed, no additional commit needed.

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Remove pushy PROBE directive injection → Task 3
- [x] Move verification context out of response generator → Task 4
- [x] Add PROBE to follow-up condition → Task 5
- [x] Add PROBE-specific gentle verification guide → Task 1 + Task 6
- [x] Strengthen regression tests → Task 7

**2. Placeholder scan:** No TBD, TODO, or "implement later" found.

**3. Type consistency:**
- `build_probe_verification_context` takes `list[VerificationItem]` → matches `build_verification_context`
- Import added to same block as existing VGC imports
- `HandoffDecision.PROBE` already exists in `stream/cares_handoff.py`

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-fix-probe-mode.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
