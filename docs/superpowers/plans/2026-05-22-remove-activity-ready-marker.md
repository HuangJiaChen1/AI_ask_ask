# Remove [ACTIVITY_READY] Marker and Unify Handoff Decision

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the `[ACTIVITY_READY]` marker and its validation logic, move the minimum-turns gate into `evaluate_handoff`, and make `activity_ready` solely controlled by the CARES handoff decision.

**Architecture:** The attribute pipeline currently has two disconnected "ready" systems — CARES interest scoring (`evaluate_handoff`) and LLM-marker validation (`_validate_activity_ready`). This plan collapses them into one: `evaluate_handoff` becomes the single authority. When it returns `HANDOFF_NOW`, `activity_ready` is set directly. The `[ACTIVITY_READY]` marker and all validation code are removed entirely.

**Tech Stack:** Python, Flask, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `stream/cares_handoff.py` | CARES handoff decision logic. Adding a minimum-turns gate to `evaluate_handoff`. |
| `paixueji_app.py` | Flask SSE endpoint. Removing `_validate_activity_ready`, `_strip_activity_markers`, `MIN_ACTIVITY_READY_TURNS`, and all `[ACTIVITY_READY]` references from prompt builders and response generation. |
| `tests/test_cares_handoff.py` | Unit tests for CARES handoff logic. Adding a regression test for insufficient turns. |

---

## Context for the Implementer

The bug: after 1 turn with a `CORRECT_ANSWER` intent, CARES interest score is 65 (≥ 50 threshold), so `evaluate_handoff` returns `HANDOFF_NOW`. The system forces the LLM to bridge to an activity. But `_validate_activity_ready` rejects the response because `turn_count=1 < MIN_ACTIVITY_READY_TURNS=3`. The child hears "let's play" but `activity_ready` stays `False`.

Root cause: two independent "ready" systems with different criteria and timing.

---

### Task 1: Add Minimum-Turns Gate to `evaluate_handoff`

**Files:**
- Modify: `stream/cares_handoff.py`
- Test: `tests/test_cares_handoff.py`

- [ ] **Step 1: Write the failing test**

Add at the end of `tests/test_cares_handoff.py`:

```python
from stream.cares_handoff import MIN_INTEREST_FOR_HANDOFF


def test_evaluate_handoff_insufficient_turns_blocks_handoff():
    """1 turn with high score should NOT trigger HANDOFF_NOW.

    Regression for: child says 'its orange' after 1 turn; score=65 but
    evaluate_handoff incorrectly returned HANDOFF_NOW because it did not
    check turns_explored. The _build_handoff_guide then forced a jarring
    activity switch before the conversation had enough depth.
    """
    rec = AttributeInterestRecord(
        attribute_id="appearance.texture",
        turns_explored=1,
        intent_history=["CORRECT_ANSWER"],
        is_current=True,
    )
    # Score: base=(1/1)*60=60, streak=min(1*5,20)=5 -> 65 >= 50
    assert compute_attribute_interest_score(rec) == 65.0

    mock_activity = SimpleNamespace(
        activity_id="fluffy_expedition_dandelion",
        name="Find three fluffy friends",
        observation_angle="texture",
    )
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.texture": rec},
        turn_count=1,
        age=6,
        primary_activity=mock_activity,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.CONTINUE
    assert "insufficient_turns" in reason
    assert meta["current_turns"] == 1
    assert meta["best_score"] == 65.0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_cares_handoff.py::test_evaluate_handoff_insufficient_turns_blocks_handoff -v
```

Expected: FAIL — `AssertionError: assert <HandoffDecision.HANDOFF_NOW: 'handoff_now'> == <HandoffDecision.CONTINUE: 'continue'>`

- [ ] **Step 3: Add the MIN_TURNS_FOR_HANDOFF constant and gate**

In `stream/cares_handoff.py`, add after line 16 (`MAX_SESSION_TURNS = 8`):

```python
MIN_TURNS_FOR_HANDOFF = 3
```

Then in `evaluate_handoff`, inside the `HANDOFF_NOW` branch (after the `best_score >= MIN_INTEREST_FOR_HANDOFF` check and before the verification-queue sub-checks), add:

```python
    # Gate: minimum turns before handoff
    current_record = records.get(current_attr)
    if current_record and current_record.turns_explored < MIN_TURNS_FOR_HANDOFF:
        return HandoffDecision.CONTINUE, f"insufficient_turns:{current_record.turns_explored}", {
            "current_attribute": current_attr,
            "current_turns": current_record.turns_explored,
            "min_turns": MIN_TURNS_FOR_HANDOFF,
            "best_score": best_score,
        }
```

The resulting block should look like:

```python
    # 3. Interest threshold met and primary activity available -> HANDOFF_NOW
    logger.info(
        "[gate_1_interest] score=%.0f, threshold=%d, pass=%s",
        best_score, MIN_INTEREST_FOR_HANDOFF, best_score >= MIN_INTEREST_FOR_HANDOFF,
    )
    if best_score >= MIN_INTEREST_FOR_HANDOFF and primary_activity is not None:
        logger.info(
            "[gate_3_primary_activity] activity_id=%s, readiness_score=%.0f",
            primary_activity.activity_id, best_score,
        )

        # Gate: minimum turns before handoff
        current_record = records.get(current_attr)
        if current_record and current_record.turns_explored < MIN_TURNS_FOR_HANDOFF:
            return HandoffDecision.CONTINUE, f"insufficient_turns:{current_record.turns_explored}", {
                "current_attribute": current_attr,
                "current_turns": current_record.turns_explored,
                "min_turns": MIN_TURNS_FOR_HANDOFF,
                "best_score": best_score,
            }

        # Gate 3b: Verification status check
        verification_queue = getattr(
            ...
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_cares_handoff.py::test_evaluate_handoff_insufficient_turns_blocks_handoff -v
```

Expected: PASS

- [ ] **Step 5: Run all CARES handoff tests**

```bash
pytest tests/test_cares_handoff.py -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add stream/cares_handoff.py tests/test_cares_handoff.py
git commit -m "fix: add minimum-turns gate to evaluate_handoff

Prevents HANDOFF_NOW from firing before the conversation has
reached sufficient depth (3 turns). The old _validate_activity_ready
checked this *after* the LLM had already generated a handoff
message, which was too late.

Regression test: test_evaluate_handoff_insufficient_turns_blocks_handoff"
```

---

### Task 2: Delete `_validate_activity_ready` and `_strip_activity_markers`

**Files:**
- Modify: `paixueji_app.py`

These two functions exist only to handle the `[ACTIVITY_READY]` marker. Since the marker is being removed, the functions are dead code.

- [ ] **Step 1: Delete `_strip_activity_markers`**

Delete lines 55–63 of `paixueji_app.py`:

```python
_REASON_RE = re.compile(r"REASON:.*", re.IGNORECASE)


def _strip_activity_markers(text: str) -> str:
    """Remove [ACTIVITY_READY] and any REASON: line from LLM output.

    This is a defensive post-processing step applied to all child-facing text
    that comes from generators instructed with ATTRIBUTE_MULTI_TOPIC_GUIDE.
    """
    cleaned = text.replace("[ACTIVITY_READY]", "")
    cleaned = _REASON_RE.sub("", cleaned)
    return cleaned.rstrip("\n")
```

Also delete the module-level `_REASON_RE` constant (line ~53) since it was only used by `_strip_activity_markers`.

- [ ] **Step 2: Delete `_validate_activity_ready`**

Delete lines 66–117 of `paixueji_app.py` (the entire function, including docstring).

- [ ] **Step 3: Verify no remaining references**

```bash
grep -n "_validate_activity_ready\|_strip_activity_markers\|_REASON_RE" paixueji_app.py
```

Expected: No output (or only references in comments if any remain — remove those too).

- [ ] **Step 4: Commit**

```bash
git add paixueji_app.py
git commit -m "refactor: remove _validate_activity_ready and _strip_activity_markers

These functions existed solely to validate/remove the [ACTIVITY_READY]
marker. The marker itself is being removed; handoff readiness is now
determined entirely by evaluate_handoff before any LLM call."
```

---

### Task 3: Delete `MIN_ACTIVITY_READY_TURNS` and Remove Marker from Prompt Builders

**Files:**
- Modify: `paixueji_app.py`

- [ ] **Step 1: Delete the `MIN_ACTIVITY_READY_TURNS` constant**

Delete line 322 of `paixueji_app.py`:

```python
# Minimum turns before [ACTIVITY_READY] marker is accepted in attribute activity pipeline.
MIN_ACTIVITY_READY_TURNS = 3
```

- [ ] **Step 2: Remove `[ACTIVITY_READY]` from `_build_continue_guide`**

In `paixueji_app.py`, line 167 of `_build_continue_guide`, change:

```python
Continue exploring the current attribute. Do NOT output [ACTIVITY_READY].
```

to:

```python
Continue exploring the current attribute.
```

- [ ] **Step 3: Remove `[ACTIVITY_READY]` from `_build_handoff_guide`**

In `paixueji_app.py`, inside `_build_handoff_guide` (around lines 208–220), remove:

```python
4. End with [ACTIVITY_READY] on its own line

Example of a good bridge:
"You really seem to love colors! Want to try the Color Matching Game? [ACTIVITY_READY]"

ANTI-PATTERNS -- NEVER produce these:
...
- Ending with anything other than [ACTIVITY_READY]
```

The `Your next message MUST:` block should end after item 3.

The remaining ANTI-PATTERNS list should be:

```python
ANTI-PATTERNS -- NEVER produce these:
- Asking a deep question about the attribute AFTER mentioning the activity
- Forgetting to say the activity name
- Re-phrasing a question from an already-used angle
```

- [ ] **Step 4: Remove `[ACTIVITY_READY]` from `_build_exit_guide`**

In `paixueji_app.py`, inside `_build_exit_guide` (around line 268), remove:

```python
- Outputting [ACTIVITY_READY]
```

- [ ] **Step 5: Commit**

```bash
git add paixueji_app.py
git commit -m "refactor: remove MIN_ACTIVITY_READY_TURNS and all [ACTIVITY_READY] prompts

The constant and all prompt references to [ACTIVITY_READY] are dead
code now that handoff readiness is determined by evaluate_handoff."
```

---

### Task 4: Simplify Response Generation Logic

**Files:**
- Modify: `paixueji_app.py`

The response-generation block (around lines 1967–1996) currently detects and validates `[ACTIVITY_READY]` in the LLM output. Replace this with direct `activity_ready` assignment when `decision == HandoffDecision.HANDOFF_NOW`.

- [ ] **Step 1: Replace the response validation block**

Find this block (around lines 1982–1996):

```python
                        # Fix 2: Detect [ACTIVITY_READY] in response text BEFORE stripping.
                        # This is the only detection path for intents without follow-up
                        # (curiosity, play, emotional) and takes precedence over follow-up
                        # detection to avoid double-handling.
                        raw_response = full_response
                        response_ready_valid, response_rejected_reason, response_reason_text = (
                            _validate_activity_ready(raw_response, assistant, child_input)
                        )
                        if response_ready_valid:
                            assistant.attribute_state.activity_ready = True
                            assistant.attribute_activity_ready = True

                        # Safety net: strip any leaked [ACTIVITY_READY] / REASON:
                        # from response text before the child sees it.
                        full_response = _strip_activity_markers(full_response)
```

Replace with:

```python
                        # Handoff decision is authoritative. If we reached HANDOFF_NOW,
                        # all readiness checks (interest score, turns, verification queue)
                        # have already passed in evaluate_handoff.
                        if decision == HandoffDecision.HANDOFF_NOW:
                            assistant.attribute_state.activity_ready = True
                            assistant.attribute_activity_ready = True
                            response_ready_valid = True
                            response_rejected_reason = None
                            response_reason_text = None
                        else:
                            response_ready_valid = False
                            response_rejected_reason = None
                            response_reason_text = None
```

- [ ] **Step 2: Simplify the followup generation block**

Find the followup block (around lines 2035–2147). The key changes:

1. Remove `activity_marker_detected`, `activity_marker_reason`, `activity_marker_rejected_reason` tracking.
2. Simplify `_displayable_followup` — it no longer needs to strip markers.
3. Remove the `[ACTIVITY_READY]` validation inside followup.

Replace lines 2035–2147 with:

```python
                        full_followup = ""

                        # Only generate follow-up for CONTINUE modes.
                        # HANDOFF_NOW, EXIT_LANE, and REENGAGE guides instruct the LLM
                        # to produce a complete message in one shot; running the follow-up
                        # generator with the same guide produces a second competing bridge
                        # that gets concatenated with the response, causing duplication.
                        if (
                            needs_followup
                            and decision in (HandoffDecision.CONTINUE, HandoffDecision.CONTINUE_SWITCH)
                        ):
                            messages_with_response = messages + [
                                {"role": "user", "content": child_input},
                                {"role": "assistant", "content": full_response},
                            ]
                            followup_soft_guide = (
                                soft_guide.split("---\n\n[SYSTEM CONTEXT]")[0].strip()
                                if soft_guide else soft_guide
                            )
                            followup_generator = ask_followup_question_stream(
                                messages=messages_with_response,
                                object_name=object_name_attr,
                                age_prompt=age_prompt,
                                age=assistant.age or 6,
                                config=assistant.config,
                                client=assistant.client,
                                attribute_soft_guide=followup_soft_guide,
                                response_text="",
                                focus_topic=f"the {observation_angle} of the {object_name_attr}",
                            )

                            # Collect the full followup without yielding to the client.
                            async for _text_chunk, token_usage, full_so_far in followup_generator:
                                pass

                            full_followup = full_so_far if full_so_far else ""

                            if full_followup:
                                sequence_number += 1
                                yield sse_event("chunk", StreamChunk(
                                    response=full_followup,
                                    session_finished=False,
                                    duration=0.0,
                                    token_usage=None,
                                    finish=False,
                                    sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="attribute_activity",
                                    correct_answer_count=assistant.correct_answer_count,
                                    intent_type=intent_type_lower,
                                    **_assistant_stream_fields(assistant),
                                ))
```

**Note:** The old code had `_displayable_followup` which stripped markers. Since markers are gone, we just use `full_so_far` directly. The `yield` that was inside the `if followup_ready_valid` / `else` branches is now unconditional — if `full_followup` is non-empty, we yield it.

- [ ] **Step 3: Update `build_attribute_debug` call**

Find the `build_attribute_debug` call (around lines 2159–2170) and hardcode the marker fields to their default "not detected" values:

```python
                        attribute_debug = build_attribute_debug(
                            decision="attribute_activity",
                            profile=assistant.attribute_profile,
                            state=assistant.attribute_state,
                            reason=attribute_reason,
                            activity_marker_detected=False,
                            activity_marker_reason=None,
                            activity_marker_rejected_reason=None,
                            response_text=combined_response,
                            intent_type=intent_type_lower,
                            reply_type="discovery",
                        )
```

- [ ] **Step 4: Commit**

```bash
git add paixueji_app.py
git commit -m "refactor: simplify response generation — remove ACTIVITY_READY detection

The response and followup generators no longer detect or validate
[ACTIVITY_READY] markers. Handoff readiness is now determined
exclusively by evaluate_handoff before any LLM call."
```

---

### Task 5: Clean Up `_assistant_stream_fields`

**Files:**
- Modify: `paixueji_app.py`

The `activity_ready_rejected_reason` field in SSE debug output is now always `None`. Keep the field in the payload for backward compatibility with the frontend, but stop reading it from state.

- [ ] **Step 1: Stop reading `last_activity_ready_rejected_reason` from state**

In `_assistant_stream_fields` (around line 506–516), change:

```python
    activity_ready_rejected_reason = None
    if getattr(assistant, "attribute_state", None):
        state = assistant.attribute_state
        switch_state = {
            "attribute_switched_to": getattr(state, "switched_to", None),
            "attribute_switch_reason": getattr(state, "switch_reason", None),
            "attribute_fallback_count": len(getattr(state, "fallback_profiles", ())),
            "attribute_turn_count": getattr(state, "turn_count", 0),
        }
        fallback_labels = [fb.label for fb in getattr(state, "fallback_profiles", ())] or None
        activity_ready_rejected_reason = getattr(state, "last_activity_ready_rejected_reason", None)
```

to:

```python
    if getattr(assistant, "attribute_state", None):
        state = assistant.attribute_state
        switch_state = {
            "attribute_switched_to": getattr(state, "switched_to", None),
            "attribute_switch_reason": getattr(state, "switch_reason", None),
            "attribute_fallback_count": len(getattr(state, "fallback_profiles", ())),
            "attribute_turn_count": getattr(state, "turn_count", 0),
        }
        fallback_labels = [fb.label for fb in getattr(state, "fallback_profiles", ())] or None
```

- [ ] **Step 2: Hardcode the rejected_reason to None in the return dict**

In the return dict (around line 546), change:

```python
        "attribute_activity_ready_rejected_reason": activity_ready_rejected_reason,
```

to:

```python
        "attribute_activity_ready_rejected_reason": None,
```

(Keeping the key for frontend backward compatibility, but the value is always `None` now.)

- [ ] **Step 3: Commit**

```bash
git add paixueji_app.py
git commit -m "refactor: hardcode activity_ready_rejected_reason to None

The rejected reason was produced by _validate_activity_ready, which
has been removed. The field is kept in the SSE payload for frontend
backward compatibility but is always None."
```

---

### Task 6: Run Full Test Suite

- [ ] **Step 1: Run CARES handoff tests**

```bash
pytest tests/test_cares_handoff.py -v
```

Expected: All pass.

- [ ] **Step 2: Run attribute activity API tests**

```bash
pytest tests/test_attribute_activity_api.py -v
```

Expected: All pass. (If any test asserts on `activity_marker_detected`, `activity_ready_rejected_reason`, or `[ACTIVITY_READY]` in response text, update those assertions.)

- [ ] **Step 3: Run attribute activity pipeline tests**

```bash
pytest tests/test_attribute_activity_pipeline.py -v
```

Expected: All pass.

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v --tb=short
```

Expected: All pass. If any failures relate to `[ACTIVITY_READY]`, update or remove those test cases.

- [ ] **Step 5: Final commit**

```bash
git commit -m "test: verify full suite passes after ACTIVITY_READY removal"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ `evaluate_handoff` checks `turns_explored >= 3` before returning `HANDOFF_NOW` — Task 1
- ✅ `_validate_activity_ready` deleted — Task 2
- ✅ `_strip_activity_markers` deleted — Task 2
- ✅ `MIN_ACTIVITY_READY_TURNS` deleted — Task 3
- ✅ All `[ACTIVITY_READY]` references removed from prompt builders — Task 3
- ✅ Response generation simplified — Task 4
- ✅ Followup generation simplified — Task 4
- ✅ `activity_ready` set directly by `evaluate_handoff` decision — Task 4
- ✅ Debug output cleaned up — Task 5
- ✅ Regression test added — Task 1

**2. Placeholder scan:**
- No "TBD", "TODO", or "implement later" found.
- No "Add appropriate error handling" or "handle edge cases" found.
- All code blocks contain complete, runnable code.

**3. Type consistency:**
- `MIN_TURNS_FOR_HANDOFF` is used consistently as an int.
- `HandoffDecision` enum values match across all tasks.
- `build_attribute_debug` parameter names match the call site.
