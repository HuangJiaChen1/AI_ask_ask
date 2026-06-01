# Filter Weak Activities from Selection Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In manual activity selection mode, only display `ready` and `verifiable` activities in the frontend selection panel; filter out `weak` activities on both backend (payload construction) and frontend (rendering).

**Architecture:** Add a category filter in the backend SSE payload builder (`paixueji_app.py`) and a defensive filter in the frontend renderer (`static/app.js`). When the filtered list is empty, hide the panel and show a fallback message.

**Tech Stack:** Python (Flask), JavaScript (vanilla), pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|--------------|
| `paixueji_app.py` | Modify line 1158-1169 | Filter `weak` activities when building `eligible_payload` |
| `static/app.js` | Modify line 1152-1171 | Defensive filter + empty-list handling in `renderActivitySelectionPanel` |
| `tests/test_api_flow.py` | Modify | Add integration test for manual selection payload filtering |

---

## Task 1: Backend — Write Failing Integration Test

**Files:**
- Modify: `tests/test_api_flow.py`

- [ ] **Step 1: Add test that asserts weak activities are filtered from SSE payload**

Append this test to `tests/test_api_flow.py`:

```python
def test_manual_activity_selection_filters_weak_activities(client):
    """When manual_activity_selection is enabled, weak activities are not sent in the payload."""
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    # Mock the discovery result so we have mixed categories
    mock_result = MagicMock()
    mock_result.primary_activity_id = "color_hunt"
    mock_result.primary_category = "ready"
    mock_result.secondary_activity_ids = ["shape_seeker"]
    mock_result.verification_queue = []
    mock_result.assessment = "Mixed"
    mock_result.proceed = True
    mock_result.all_activity_categories = {
        "color_hunt": "ready",
        "shape_seeker": "verifiable",
        "time_traveler": "weak",
    }

    with patch("paixueji_app.discover_talkable_activities", return_value=(mock_result, {})):
        payload = {
            "age": 6,
            "object_name": "cat",
            "manual_activity_selection": True,
        }
        response = client.post("/api/start", json=payload)
        assert response.status_code == 200

        events = parse_sse(response.data)
        selection_events = [
            e for e in events
            if e["event"] == "chunk"
            and e["data"]
            and e["data"].get("response_type") == "activity_selection"
        ]
        assert len(selection_events) == 1

        eligible = selection_events[0]["data"]["eligible_activities"]
        categories = {a["category"] for a in eligible}
        assert "weak" not in categories, f"weak should be filtered, got categories: {categories}"
        assert len(eligible) == 2  # ready + verifiable only
        ids = {a["activity_id"] for a in eligible}
        assert ids == {"color_hunt", "shape_seeker"}
```

- [ ] **Step 2: Run the test to confirm it fails**

Run:
```bash
cd C:/Users/123/Documents/GitHub/AI_ask_ask
pytest tests/test_api_flow.py::test_manual_activity_selection_filters_weak_activities -v
```

Expected: **FAIL** — the test will fail because `time_traveler` (category `weak`) is currently included in the payload.

---

## Task 2: Backend — Implement Filtering

**Files:**
- Modify: `paixueji_app.py:1158-1169`

- [ ] **Step 3: Add category filter to eligible_payload list comprehension**

Replace lines 1158-1169 in `paixueji_app.py`:

```python
                    if assistant.pending_activity_selection:
                        eligible_payload = [
                            {
                                "activity_id": a.activity_id,
                                "name": a.name,
                                "observation_angle": a.observation_angle,
                                "focal_attribute": a.focal_attribute,
                                "preview_prompt": a.preview_prompt or a.description,
                                "description": a.description,
                                "category": cat,
                            }
                            for a in assistant.pending_eligible_activities
                            if (cat := assistant.pending_activity_categories.get(a.activity_id, "weak")) in ("ready", "verifiable")
                        ]
```

- [ ] **Step 4: Run the test to confirm it passes**

Run:
```bash
pytest tests/test_api_flow.py::test_manual_activity_selection_filters_weak_activities -v
```

Expected: **PASS**

- [ ] **Step 5: Run the full test suite to ensure no regressions**

Run:
```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add paixueji_app.py tests/test_api_flow.py
git commit -m "feat: filter weak activities from manual selection payload

Only ready/verifiable activities are sent to frontend.
Weak activities are excluded on both backend and frontend.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Frontend — Implement Defensive Filter + Empty List Handling

**Files:**
- Modify: `static/app.js:1152-1171`

> **Note:** The project has no JavaScript test framework (no jest/vitest/playwright config found). This task relies on manual browser verification.

- [ ] **Step 7: Replace renderActivitySelectionPanel with filtered version**

Replace lines 1152-1171 in `static/app.js`:

```javascript
/**
 * Render the manual activity selection panel with category labels
 * @param {Array} activities - List of eligible activities from backend
 */
function renderActivitySelectionPanel(activities) {
    const container = document.getElementById('activityCards');
    if (!container) return;
    container.innerHTML = '';

    // Defensive filter: only show ready/verifiable activities
    const displayable = (activities || []).filter(
        act => act.category === 'ready' || act.category === 'verifiable'
    );

    // Empty list fallback
    if (displayable.length === 0) {
        window.paixuejiUi.setActivitySelectionVisible(false);
        appendMessage('bot', '当前没有合适的活动，换个话题试试吧。');
        awaitingActivitySelection = false;
        return;
    }

    displayable.forEach(act => {
        const card = document.createElement('div');
        card.className = 'activity-card';
        const categoryClass = `category-${act.category || 'weak'}`;
        card.innerHTML = `
            <div class="activity-card-header">
                <h4>${escapeHtml(act.name || act.activity_id)}</h4>
                <span class="activity-category ${categoryClass}">${act.category || 'weak'}</span>
            </div>
            <p class="activity-meta">${escapeHtml(act.observation_angle || '')} · ${escapeHtml(act.focal_attribute || '')}</p>
            <p class="activity-preview">${escapeHtml(act.preview_prompt || act.description || '')}</p>
        `;
        card.onclick = () => selectActivity(act.activity_id);
        container.appendChild(card);
    });
}
```

- [ ] **Step 8: Commit**

```bash
git add static/app.js
git commit -m "feat: frontend filters weak activities and handles empty list

Defensive filter in renderActivitySelectionPanel.
Shows fallback message when no displayable activities remain.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: End-to-End Verification

- [ ] **Step 9: Start the Flask server**

```bash
cd C:/Users/123/Documents/GitHub/AI_ask_ask
python paixueji_app.py
```

- [ ] **Step 10: Open browser and test manual activity selection**

Open `http://localhost:5000` (or the configured port).

1. Start a conversation with an object that triggers mixed activity categories (e.g., "cat").
2. Ensure `manual_activity_selection` is enabled in the request (check frontend network tab or backend logs).
3. Verify the activity selection panel:
   - **Should see:** Activities with `ready` (green) and `verifiable` (yellow) badges.
   - **Should NOT see:** Activities with `weak` (gray) badge.
4. Click a `ready` activity — confirm the attribute intro starts normally.
5. Repeat with a `verifiable` activity — confirm it also works.

- [ ] **Step 11: Test empty-list fallback**

To test the empty-list case, temporarily hardcode all categories to `"weak"` in the backend (or use an object where LLM classifies everything as weak), then:
1. Start a conversation.
2. Verify the activity selection panel does NOT appear.
3. Verify a bot message appears: "当前没有合适的活动，换个话题试试吧。"

Restore the backend code after testing.

---

## Self-Review Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | Spec coverage: Backend filtering ✓ | Task 2 |
| 2 | Spec coverage: Frontend filtering ✓ | Task 3 |
| 3 | Spec coverage: Empty list handling ✓ | Task 3 |
| 4 | Placeholder scan: No TBD/TODO/fill in details | Clean |
| 5 | Type consistency: `eligible_payload` fields match before/after | Verified |
| 6 | `select-activity` endpoint unaffected: It reads from `pending_eligible_activities` (full list), not `eligible_payload` (filtered) | Verified |

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-filter-weak-activities.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
