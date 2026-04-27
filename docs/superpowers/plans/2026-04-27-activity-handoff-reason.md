# Activity Handoff Reason — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LLM-driven `[ACTIVITY_READY]` handoff auditable by requiring the model to emit a `REASON:` line that explains why it decided the child is ready, and surface that reason in debug output.

**Architecture:** The prompt instructs the LLM to append `REASON: <explanation>` on the line after `[ACTIVITY_READY]`. The SSE stream parser strips both the marker and the reason from child-facing text while extracting the reason into `activity_marker_reason` in the debug payload. No backend heuristic changes — purely additive observability.

**Tech Stack:** Python 3.11, Flask SSE streaming, regex (`re` module)

---

## Files

| File | Action | Responsibility |
|---|---|---|
| `Gemini/paixueji/paixueji_prompts.py` | Modify | Update `ATTRIBUTE_SOFT_GUIDE` TRANSITION SIGNAL to request a `REASON:` line |
| `Gemini/paixueji/paixueji_app.py` | Modify | Import `re`; update `_displayable_followup` to strip reason; extract reason after stream; pass to debug builder |
| `Gemini/paixueji/attribute_activity.py` | Modify | Add `activity_marker_reason` parameter to `build_attribute_debug` |
| `Gemini/paixueji/tests/test_attribute_discovery_pipeline.py` | Modify | Add tests for `activity_marker_reason` presence in debug |
| `Gemini/paixueji/tests/test_attribute_activity_pipeline.py` | Modify | Add test for `activity_marker_reason` field |

---

### Task 1: Prompt — Add REASON line to TRANSITION SIGNAL

**Files:**
- Modify: `Gemini/paixueji/paixueji_prompts.py:466-476`
- Test: `Gemini/paixueji/tests/test_attribute_discovery_pipeline.py:115-120`

- [ ] **Step 1: Modify the prompt**

Replace the TRANSITION SIGNAL paragraph in `ATTRIBUTE_SOFT_GUIDE` (around line 466):

```python
TRANSITION SIGNAL: When you choose technique C and include an
activity-preview question, your output should be exactly:
1. one child-facing question
2. then on a new line: [ACTIVITY_READY]
3. then on a new line: REASON: <1-sentence explanation of why the
   child is ready — e.g. "Child explored color through comparison and
   preference, showing readiness to find colored objects">
Both the marker and the REASON line are invisible to the child — the
system uses them to know the conversation reached a natural transition
point and to understand why. Do NOT add [ACTIVITY_READY] unless you
genuinely chose technique C and your question invites the child to DO
something related to {activity_target}. Adding it prematurely breaks
the experience.
```

- [ ] **Step 2: Update prompt invariant test**

In `test_attribute_discovery_pipeline.py`, add after `test_soft_guide_defines_marker_and_llm_decides_timing`:

```python
def test_soft_guide_requests_reason_line():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "reason:" in guide_lower
    assert "invisible to the child" in guide_lower
```

- [ ] **Step 3: Run prompt tests**

Run: `pytest Gemini/paixueji/tests/test_attribute_discovery_pipeline.py -v`
Expected: PASS (3 tests)

- [ ] **Step 4: Commit**

```bash
git add Gemini/paixueji/paixueji_prompts.py Gemini/paixueji/tests/test_attribute_discovery_pipeline.py
git commit -m "feat(prompt): add REASON line to ACTIVITY_READY marker instructions"
```

---

### Task 2: Debug Builder — Add `activity_marker_reason` field

**Files:**
- Modify: `Gemini/paixueji/attribute_activity.py:184-202`
- Test: `Gemini/paixueji/tests/test_attribute_discovery_pipeline.py:84-110`

- [ ] **Step 1: Add parameter to `build_attribute_debug`**

In `Gemini/paixueji/attribute_activity.py`, modify the function signature and return dict:

```python
def build_attribute_debug(
    *,
    decision: str,
    profile: AttributeProfile | None,
    state: DiscoverySessionState | None,
    reason: str | None = None,
    activity_marker_detected: bool = False,
    activity_marker_reason: str | None = None,
    response_text: str | None = None,
    intent_type: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "activity_marker_detected": activity_marker_detected,
        "activity_marker_reason": activity_marker_reason,
        "response_text": response_text,
        "intent_type": intent_type,
    }
```

- [ ] **Step 2: Add test for reason field**

In `test_attribute_discovery_pipeline.py`, modify `test_build_attribute_debug_includes_marker_flag` to also assert the reason field:

```python
def test_build_attribute_debug_includes_marker_flag():
    state = _make_state()
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="marker detected in follow-up",
        activity_marker_detected=True,
        activity_marker_reason="Child explored color through comparison and preference",
        response_text="Can you spot anything else around you that's bright red?",
        intent_type="correct_answer",
    )

    assert debug["decision"] == "attribute_activity"
    assert debug["activity_marker_detected"] is True
    assert debug["activity_marker_reason"] == "Child explored color through comparison and preference"
    assert debug["intent_type"] == "correct_answer"
    assert "touch_result" not in debug
    assert "readiness" not in debug
```

Also add a default test:

```python
def test_build_attribute_debug_defaults_reason_to_none():
    state = _make_state()
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
    )
    assert debug["activity_marker_reason"] is None
```

- [ ] **Step 3: Run tests**

Run: `pytest Gemini/paixueji/tests/test_attribute_discovery_pipeline.py -v`
Expected: PASS (all tests)

- [ ] **Step 4: Commit**

```bash
git add Gemini/paixueji/attribute_activity.py Gemini/paixueji/tests/test_attribute_discovery_pipeline.py
git commit -m "feat(debug): add activity_marker_reason to build_attribute_debug"
```

---

### Task 3: Stream Parser — Extract and strip `REASON:` line

**Files:**
- Modify: `Gemini/paixueji/paixueji_app.py:1319-1375`
- Test: `Gemini/paixueji/tests/test_attribute_activity_pipeline.py`

- [ ] **Step 1: Add `re` import**

At the top of `Gemini/paixueji/paixueji_app.py`, add `re` to the imports (around line 7):

```python
import json
import uuid
import asyncio
import threading
import os
import yaml
import re
```

- [ ] **Step 2: Update marker detection and extraction logic**

In the attribute activity streaming block (around line 1319), replace the marker handling code:

```python
                        activity_marker = "[ACTIVITY_READY]"
                        activity_marker_detected = False
                        activity_marker_reason = None
                        raw_followup_so_far = ""
                        full_followup = ""

                        _REASON_RE = re.compile(r"REASON:\s*(.+?)(?:\n|$)")

                        def _displayable_followup(raw_followup: str) -> str:
                            # Strip the activity marker
                            marker_free_followup = raw_followup.replace(activity_marker, "")
                            if activity_marker in raw_followup:
                                # Also strip the REASON line if present
                                marker_free_followup = _REASON_RE.sub("", marker_free_followup)
                                # Clean up any trailing newlines left after stripping
                                marker_free_followup = marker_free_followup.rstrip("\n")
                                return marker_free_followup

                            max_buffered_prefix = min(len(raw_followup), len(activity_marker) - 1)
                            for suffix_len in range(max_buffered_prefix, 0, -1):
                                if raw_followup.endswith(activity_marker[:suffix_len]):
                                    return marker_free_followup[:-suffix_len]
                            return marker_free_followup

                        async for _text_chunk, token_usage, full_so_far in followup_generator:
                            raw_followup_so_far = full_so_far
                            if activity_marker in raw_followup_so_far:
                                activity_marker_detected = True
                            displayable_followup = _displayable_followup(raw_followup_so_far)
                            visible_chunk = displayable_followup[len(full_followup):]
                            full_followup = displayable_followup
                            if visible_chunk == "":
                                continue
                            # ... rest of the yield block unchanged ...
```

- [ ] **Step 3: Extract reason after stream completes**

After the `async for` loop (after line 1360), add reason extraction:

```python
                        full_followup = _displayable_followup(raw_followup_so_far)

                        # Extract reason from raw text after marker is fully present
                        if activity_marker_detected:
                            reason_match = _REASON_RE.search(raw_followup_so_far)
                            if reason_match:
                                activity_marker_reason = reason_match.group(1).strip()

                        if activity_marker_detected:
                            assistant.attribute_state.activity_ready = True
                            assistant.attribute_activity_ready = True
```

- [ ] **Step 4: Pass reason to debug builder**

Update the `build_attribute_debug` call (around line 1367) to include the new field:

```python
                        attribute_debug = build_attribute_debug(
                            decision="attribute_activity",
                            profile=assistant.attribute_profile,
                            state=assistant.attribute_state,
                            reason=attribute_reason,
                            activity_marker_detected=activity_marker_detected,
                            activity_marker_reason=activity_marker_reason,
                            response_text=combined_response,
                            intent_type=intent_type_lower,
                        )
```

- [ ] **Step 5: Add unit test for reason extraction**

In `Gemini/paixueji/tests/test_attribute_activity_pipeline.py`, add:

```python
def test_build_attribute_debug_with_marker_reason():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=6)

    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="marker detected in follow-up",
        activity_marker_detected=True,
        activity_marker_reason="Child explored color through comparison and preference",
        intent_type="correct_answer",
    )

    assert debug["activity_marker_detected"] is True
    assert debug["activity_marker_reason"] == "Child explored color through comparison and preference"
    assert debug["intent_type"] == "correct_answer"
```

- [ ] **Step 6: Run tests**

Run: `pytest Gemini/paixueji/tests/test_attribute_activity_pipeline.py Gemini/paixueji/tests/test_attribute_discovery_pipeline.py -v`
Expected: PASS

Run: `pytest Gemini/paixueji/tests/test_all_endpoints.py::test_attribute_continue_returns_correct_shape -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add Gemini/paixueji/paixueji_app.py Gemini/paixueji/tests/test_attribute_activity_pipeline.py
git commit -m "feat(stream): extract and surface activity_marker_reason from LLM output"
```

---

## Self-Review

**1. Spec coverage:**
- [x] Prompt asks LLM to emit `REASON:` line — Task 1
- [x] Reason is invisible to child — Task 3 (`_displayable_followup` strips it)
- [x] Reason appears in debug output — Task 2 (`build_attribute_debug` field) + Task 3 (extraction)
- [x] Backward compatibility (no reason = `None`) — Task 2 default

**2. Placeholder scan:**
- No TBD/TODO/fill-in-details found.
- All code blocks contain complete, runnable code.
- Exact file paths and line ranges provided.

**3. Type consistency:**
- `activity_marker_reason: str | None` used consistently across `build_attribute_debug` signature, return dict, and caller in `paixueji_app.py`.
- `_REASON_RE` compiled once before the streaming loop, referenced in both `_displayable_followup` and post-loop extraction.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-27-activity-handoff-reason.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review

**Which approach?**
