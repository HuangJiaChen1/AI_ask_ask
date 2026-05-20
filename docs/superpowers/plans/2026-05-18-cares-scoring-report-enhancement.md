# CARES Scoring Fix + Report Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix handoff timing so on-track children handoff in 2-3 turns (by adding a participation streak bonus to CARES interest scoring), and enrich the Human Feedback Critique Report with CARES interest score breakdowns and handoff decisions.

**Architecture:** Add a `streak_bonus` to `compute_attribute_interest_score()` that rewards sustained engagement (0-15 pts based on `turns_explored`). Extract a reusable `compute_attribute_interest_score_breakdown()` helper for report rendering. Surface CARES data in three report locations: a summary section, per-turn summaries, and raw diagnostics.

**Tech Stack:** Python, Flask, pytest. Existing modules: `stream/cares_handoff.py`, `paixueji_app.py`, `tests/test_attribute_activity_pipeline.py`.

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `stream/cares_handoff.py` | CARES interest scoring logic | Add `streak_bonus` + `compute_attribute_interest_score_breakdown()` |
| `paixueji_app.py` | HTTP layer + report generation | Enrich report with CARES data (4 locations) |
| `tests/test_attribute_activity_pipeline.py` | Existing validation tests | Add test for streak bonus; remove obsolete `insufficient_turns` test |

---

## Task 1: Add Participation Streak Bonus to CARES Scoring

**Files:**
- Modify: `stream/cares_handoff.py:55-91`
- Test: `tests/test_attribute_activity_pipeline.py`

### Step 1: Write the failing test

```python
def test_compute_attribute_interest_score_with_streak_bonus():
    """Streak bonus rewards sustained engagement: +5 per turn, max 15."""
    from stream.cares_handoff import AttributeInterestRecord, compute_attribute_interest_score

    # 2 turns, all positive → base=50, streak=10 → total=60
    r2 = AttributeInterestRecord(
        attribute_id="appearance.covering",
        turns_explored=2,
        intent_history=["CORRECT_ANSWER", "CORRECT_ANSWER"],
    )
    assert compute_attribute_interest_score(r2) == 60.0

    # 3 turns, all positive → base=50, streak=15 → total=65
    r3 = AttributeInterestRecord(
        attribute_id="appearance.covering",
        turns_explored=3,
        intent_history=["CORRECT_ANSWER", "CORRECT_ANSWER", "CORRECT_ANSWER"],
    )
    assert compute_attribute_interest_score(r3) == 65.0

    # 1 turn positive → base=50, streak=5 → total=55
    r1 = AttributeInterestRecord(
        attribute_id="appearance.covering",
        turns_explored=1,
        intent_history=["CORRECT_ANSWER"],
    )
    assert compute_attribute_interest_score(r1) == 55.0

    # 5 turns, 3 positive, 2 struggle → base=30, streak=15, penalty=16 → total=29
    r_mixed = AttributeInterestRecord(
        attribute_id="appearance.covering",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER", "CLARIFYING_IDK", "CORRECT_ANSWER",
                        "CLARIFYING_WRONG", "CORRECT_ANSWER"],
        struggle_count=2,
    )
    assert compute_attribute_interest_score(r_mixed) == 29.0
```

Run: `pytest tests/test_attribute_activity_pipeline.py::test_compute_attribute_interest_score_with_streak_bonus -v`
Expected: **FAIL** — function returns 50.0 for 2-turn case, not 60.0

### Step 2: Add `compute_attribute_interest_score_breakdown` and refactor

In `stream/cares_handoff.py`, replace the existing `compute_attribute_interest_score` (lines 55-91) with:

```python
def compute_attribute_interest_score_breakdown(record: AttributeInterestRecord) -> dict[str, float]:
    """Return component breakdown of the interest score."""
    if record.turns_explored == 0:
        return {"base": 0.0, "initiation": 0.0, "depth": 0.0, "streak": 0.0, "penalty": 0.0, "total": 0.0}

    positive_intents = {
        "CORRECT_ANSWER", "INFORMATIVE", "CURIOSITY", "PLAY", "EMOTIONAL",
    }
    positive = sum(1 for it in record.intent_history if it in positive_intents)
    base = (positive / record.turns_explored) * 50

    initiation = min(record.child_initiated_count * 8 + record.child_returned_count * 15, 30)

    depth = min(record.elaboration_turns * 4 + record.question_count * 6 + record.emotional_count * 5, 25)

    streak = min(record.turns_explored * 5, 15)

    penalty = min(record.struggle_count * 8 + record.avoidance_count * 12, 35)

    total = max(0.0, base + initiation + depth + streak - penalty)
    return {
        "base": base,
        "initiation": initiation,
        "depth": depth,
        "streak": streak,
        "penalty": penalty,
        "total": total,
    }


def compute_attribute_interest_score(record: AttributeInterestRecord) -> float:
    """Compute interest score for a single attribute (0-100)."""
    return compute_attribute_interest_score_breakdown(record)["total"]
```

Run: `pytest tests/test_attribute_activity_pipeline.py::test_compute_attribute_interest_score_with_streak_bonus -v`
Expected: **PASS**

### Step 3: Verify existing tests still pass

Run: `pytest tests/test_attribute_activity_pipeline.py -v`
Expected: All tests pass (the obsolete `test_validate_activity_ready_insufficient_turns` was already removed in a prior commit).

### Step 4: Commit

```bash
git add stream/cares_handoff.py tests/test_attribute_activity_pipeline.py
git commit -m "feat: add participation streak bonus to CARES interest scoring

- Streak bonus: +5 per turn explored, max 15
- Extract compute_attribute_interest_score_breakdown() for report rendering
- 2-turn all-positive conversation now scores 60, triggering HANDOFF_NOW"
```

---

## Task 2: Enrich Human Feedback Critique Report with CARES Data

**Files:**
- Modify: `paixueji_app.py` (multiple locations)

### Step 2.1: Add `attribute_interest_records` parameter to report builder

**Location:** `paixueji_app.py:4185`

Change the function signature from:
```python
async def build_human_feedback_report(object_name, age, session_id, transcript,
                                 all_exchanges, exchange_critiques,
                                 global_conclusion, key_concept=None,
                                 introduction=None, introduction_critique=None,
                                 session_resolution_debug=None):
```

To:
```python
async def build_human_feedback_report(object_name, age, session_id, transcript,
                                 all_exchanges, exchange_critiques,
                                 global_conclusion, key_concept=None,
                                 introduction=None, introduction_critique=None,
                                 session_resolution_debug=None,
                                 attribute_interest_records=None):
```

### Step 2.2: Pass `attribute_interest_records` from the endpoint

**Location:** `paixueji_app.py:3980-3992`

Change:
```python
        report_md = build_human_feedback_report(
            object_name=assistant.object_name,
            age=assistant.age,
            session_id=session_id,
            transcript=transcript,
            all_exchanges=all_exchanges,
            exchange_critiques=exchange_critiques,
            global_conclusion=global_conclusion,
            key_concept=assistant.key_concept,
            introduction=introduction,
            introduction_critique=introduction_critique,
            session_resolution_debug=assistant.session_resolution_debug,
        )
```

To:
```python
        report_md = build_human_feedback_report(
            object_name=assistant.object_name,
            age=assistant.age,
            session_id=session_id,
            transcript=transcript,
            all_exchanges=all_exchanges,
            exchange_critiques=exchange_critiques,
            global_conclusion=global_conclusion,
            key_concept=assistant.key_concept,
            introduction=introduction,
            introduction_critique=introduction_critique,
            session_resolution_debug=assistant.session_resolution_debug,
            attribute_interest_records=assistant.attribute_interest_records,
        )
```

### Step 2.3: Add helper to render CARES Interest Summary

**Location:** Insert new function before `_render_turn_summary` in `paixueji_app.py` (around line 4600, before the existing `_render_turn_summary` at line 4605).

```python
def _render_cares_interest_summary(attribute_interest_records):
    """Render a markdown table of CARES interest scores and breakdowns."""
    if not attribute_interest_records:
        return ""

    from stream.cares_handoff import compute_attribute_interest_score_breakdown

    lines = ["## CARES Interest Analysis\n\n"]
    lines.append(
        "| Attribute | Turns | Score | Base | Initiation | Depth | Streak | Penalty |\n"
    )
    lines.append(
        "|-----------|-------|-------|------|------------|-------|--------|---------|\n"
    )

    best_attr = None
    best_score = -1.0
    for attr_id, record in attribute_interest_records.items():
        bd = compute_attribute_interest_score_breakdown(record)
        lines.append(
            f"| `{attr_id}` | {record.turns_explored} | {bd['total']:.1f} | "
            f"{bd['base']:.1f} | {bd['initiation']:.1f} | {bd['depth']:.1f} | "
            f"{bd['streak']:.1f} | {bd['penalty']:.1f} |\n"
        )
        if bd["total"] > best_score:
            best_score = bd["total"]
            best_attr = attr_id

    lines.append("\n")
    if best_attr:
        lines.append(f"**Best attribute:** `{best_attr}` (score: {best_score:.1f})\n")
    lines.append("**Handoff threshold:** 60\n")
    if best_score >= 60:
        lines.append(f"**Would handoff:** Yes — score >= threshold\n")
    else:
        lines.append(f"**Would handoff:** No — score < threshold\n")
    lines.append("\n---\n\n")
    return "".join(lines)
```

### Step 2.4: Insert CARES summary into report body

**Location:** `paixueji_app.py:4379` (right after `report += "---\n\n"` that closes the Conversation Transcript section).

Change:
```python
    report += "---\n\n"

    critiqued_exchanges = []
```

To:
```python
    report += "---\n\n"

    # CARES Interest Analysis section
    report += _render_cares_interest_summary(attribute_interest_records)

    critiqued_exchanges = []
```

### Step 2.5: Surface CARES decision + scores in Turn Summary

**Location:** `paixueji_app.py:4658-4661` (inside `_render_turn_summary`, after the existing attribute/category debug blocks, before the `diagnostics_ref` line).

Add before `if diagnostics_ref:`:
```python
    if attribute_debug:
        cares_decision = attribute_debug.get("cares_handoff_decision")
        cares_reason = attribute_debug.get("cares_handoff_reason")
        interest_current = attribute_debug.get("interest_score_current")
        interest_best = attribute_debug.get("interest_score_best")
        if cares_decision:
            lines.append(f"- CARES Decision: `{cares_decision}`\n")
        if cares_reason:
            lines.append(f"- CARES Reason: `{cares_reason}`\n")
        if interest_current is not None:
            lines.append(f"- Interest Score (current): `{interest_current:.1f}`\n")
        if interest_best is not None:
            lines.append(f"- Interest Score (best): `{interest_best:.1f}`\n")
```

The `_render_turn_summary` function should now look like (showing the full modified tail):

```python
def _render_turn_summary(
    bridge_debug,
    attribute_debug,
    category_debug,
    response_type,
    diagnostics_ref=None,
):
    if not bridge_debug and not attribute_debug and not category_debug:
        return ""
    lines = ["#### Turn Summary\n\n"]
    # ... existing bridge_debug block unchanged ...
    if attribute_debug:
        attribute_summary = _derive_report_attribute_summary(attribute_debug)
        for label, key in [
            ("Attribute Pipeline", "attribute_pipeline"),
            ("Attribute Lane", "attribute_lane"),
            ("Attribute ID", "attribute_id"),
            ("Attribute Label", "attribute_label"),
            ("Activity Target", "activity_target"),
            ("Attribute Branch", "attribute_branch"),
            ("Attribute Reply Type", "attribute_reply_type"),
            ("Attribute Decision", "attribute_decision"),
        ]:
            value = attribute_summary.get(key)
            if value is not None:
                lines.append(f"- {label}: `{value}`\n")
        # NEW: CARES fields
        cares_decision = attribute_debug.get("cares_handoff_decision")
        cares_reason = attribute_debug.get("cares_handoff_reason")
        interest_current = attribute_debug.get("interest_score_current")
        interest_best = attribute_debug.get("interest_score_best")
        if cares_decision:
            lines.append(f"- CARES Decision: `{cares_decision}`\n")
        if cares_reason:
            lines.append(f"- CARES Reason: `{cares_reason}`\n")
        if interest_current is not None:
            lines.append(f"- Interest Score (current): `{interest_current:.1f}`\n")
        if interest_best is not None:
            lines.append(f"- Interest Score (best): `{interest_best:.1f}`\n")
    # ... existing category_debug block unchanged ...
    if diagnostics_ref:
        lines.append(f"- Diagnostics Ref: `{diagnostics_ref}`\n")
    lines.append("\n")
    return "".join(lines)
```

### Step 2.6: Add CARES Interest Record to raw diagnostics

**Location:** `paixueji_app.py:4797-4801` (inside `_render_raw_diagnostics_entry`, after the existing attribute/category summary lines, before the `_render_raw_bridge_debug` call).

Add after the category_summary block and before `lines.append("\n")`:

```python
    # NEW: CARES Interest Record subsection
    if attribute_debug and attribute_interest_records:
        from stream.cares_handoff import compute_attribute_interest_score_breakdown
        attr_id = attribute_debug.get("attribute_id") or attribute_debug.get("state", {}).get("profile", {}).get("attribute_id")
        if attr_id and attr_id in attribute_interest_records:
            record = attribute_interest_records[attr_id]
            bd = compute_attribute_interest_score_breakdown(record)
            lines.append("\n#### CARES Interest Record\n\n")
            lines.append(f"- attribute_id: `{record.attribute_id}`\n")
            lines.append(f"- turns_explored: `{record.turns_explored}`\n")
            lines.append(f"- intent_history: `{record.intent_history}`\n")
            lines.append(f"- child_initiated_count: `{record.child_initiated_count}`\n")
            lines.append(f"- child_returned_count: `{record.child_returned_count}`\n")
            lines.append(f"- elaboration_turns: `{record.elaboration_turns}`\n")
            lines.append(f"- question_count: `{record.question_count}`\n")
            lines.append(f"- emotional_count: `{record.emotional_count}`\n")
            lines.append(f"- struggle_count: `{record.struggle_count}`\n")
            lines.append(f"- avoidance_count: `{record.avoidance_count}`\n")
            lines.append(f"- explored_angle_ids: `{record.explored_angle_ids}`\n")
            lines.append(f"- score_breakdown: base={bd['base']:.1f} initiation={bd['initiation']:.1f} "
                        f"depth={bd['depth']:.1f} streak={bd['streak']:.1f} penalty={bd['penalty']:.1f} "
                        f"total={bd['total']:.1f}\n")
```

**Important:** `_render_raw_diagnostics_entry` does not currently receive `attribute_interest_records`. You must add it as a parameter. Change the function signature at line 4752 from:

```python
def _render_raw_diagnostics_entry(
    exchange_index,
    source_label,
    response_type,
    bridge_debug,
    attribute_debug=None,
    category_debug=None,
):
```

To:
```python
def _render_raw_diagnostics_entry(
    exchange_index,
    source_label,
    response_type,
    bridge_debug,
    attribute_debug=None,
    category_debug=None,
    attribute_interest_records=None,
):
```

Then update the two call sites:

**Call site 1:** Inside `register_diagnostics` in `build_human_feedback_report` (around line 4404). Find:
```python
            report += _render_raw_diagnostics_entry(
                exchange_index,
                entry["source_label"],
                entry["response_type"],
                entry.get("bridge_debug"),
                entry.get("attribute_debug"),
                entry.get("category_debug"),
            )
```

Change to:
```python
            report += _render_raw_diagnostics_entry(
                exchange_index,
                entry["source_label"],
                entry["response_type"],
                entry.get("bridge_debug"),
                entry.get("attribute_debug"),
                entry.get("category_debug"),
                attribute_interest_records=attribute_interest_records,
            )
```

### Step 2.7: Run all tests

Run: `pytest tests/test_attribute_activity_pipeline.py -v`
Expected: All tests pass.

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass (or only pre-existing failures).

### Step 2.8: Commit

```bash
git add paixueji_app.py
git commit -m "feat: enrich HF report with CARES interest score breakdown and handoff decisions

- Add compute_attribute_interest_score_breakdown() helper in cares_handoff.py
- CARES Interest Analysis table in report header (score per attribute)
- Per-turn CARES Decision + Interest Score in Turn Summary
- Full AttributeInterestRecord dump in Raw Diagnostics"
```

---

## Self-Review

**1. Spec coverage check:**

| Requirement | Task | Status |
|-------------|------|--------|
| On-track child hands off in 2-3 turns | Task 1: streak_bonus adds +10 at 2 turns, +15 at 3 turns | Covered |
| Report shows interest score breakdown | Task 2.3: `_render_cares_interest_summary` table | Covered |
| Report shows handoff decision per turn | Task 2.5: `cares_handoff_decision` in Turn Summary | Covered |
| Report shows full interest record in diagnostics | Task 2.6: `CARES Interest Record` subsection | Covered |
| No placeholders | All code is complete | Verified |

**2. Placeholder scan:**
- No "TBD", "TODO", "implement later" found.
- No vague directives like "add appropriate error handling".
- Every step shows exact code or exact commands.

**3. Type consistency check:**
- `compute_attribute_interest_score_breakdown` returns `dict[str, float]` with keys `"base"`, `"initiation"`, `"depth"`, `"streak"`, `"penalty"`, `"total"`.
- Report rendering uses these exact keys consistently across Tasks 2.3, 2.5, 2.6.
- `_render_raw_diagnostics_entry` parameter name `attribute_interest_records` matches the parameter name passed at the call site.

**Gap found & fixed:**
- `_render_raw_diagnostics_entry` initially did not receive `attribute_interest_records`. Added as parameter and wired through the call site in `register_diagnostics`.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-18-cares-scoring-report-enhancement.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
