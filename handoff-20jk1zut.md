# Handoff: Orange Cat Diagnostic — Two-Agent Split

## Context

User ran `/diagnose` on a Human Feedback Critique Report for session `d188e779-2e36-4716-98a8-ecb2048574e9` (orange cat, age 6). The conversation identified 4 bugs in the activity-driven attribute pipeline. The user wants to split work between two agents:

- **Agent A (Fix Agent):** Apply confirmed fixes for bugs 1-3 (entity_name search, parameterized eligibility, hardcoded prompt).
- **Agent B (Design Agent):** Continue discussing the follow-up question drifting fix (bug 4) with the user.

---

## Diagnostic Summary

Full diagnosis with code traces and test verification is in `tests/test_diagnose_orange_cat.py` (6 passing regression tests). The failing conversation trace is preserved in the user's message history (`/diagnose` invocation with the full Human Feedback Critique Report).

### Bug 1: `entity_class` search should be `entity_name` search [CONFIRMED FIX]

**Location:** `activities/__init__.py:342-347` (`_is_eligible`)

**Current broken code:**
```python
if activity.entity_binding == "bound":
    if activity.entity_class_filter:
        entity_classes = set(entity_info.get("entity_class", [])) if entity_info else set()
        filters = set(activity.entity_class_filter)
        if not (entity_classes & filters):
            return False
```

**Root cause:** `mappings_dev20_0318/animals/cats.yaml` has no `entity_class` field. `_find_entity("cat")` returns a dict without `entity_class`, so `entity_classes = set()` and `dream_whisperer_cat` (filter=[cat]) is rejected.

**User-confirmed fix direction:** Change to match on `entity_name` instead of `entity_class`.

**Suggested implementation:** For bound activities, compare `activity.entity` (e.g. `"cat"`) against `entity_info.get("entity_name")` (case-insensitive) instead of using `entity_class_filter` intersection.

---

### Bug 2: Parameterized eligibility check is broken [READY TO FIX]

**Location:** `activities/__init__.py:348-351` (`_is_eligible`)

**Current broken code:**
```python
elif activity.entity_binding == "parameterized":
    # V1 simplified: parameterized needs extracted properties to be useful
    if extracted_properties is not None and not extracted_properties:
        return False
```

**Root cause:** When `extracted_properties=None` (the default in `get_eligible_activities_for_object`), the condition `extracted_properties is not None` is False, so the check is skipped. All parameterized activities enter the eligible pool even with no properties extracted.

**Fix:** Change to `if extracted_properties is None or not extracted_properties:`.

---

### Bug 3: Hardcoded dandelion prompt [READY TO FIX]

**Location:** `activities/catalog/fluffy_expedition_dandelion/tag_block.yaml:55`

**Current:**
```yaml
preview_prompt: "This dandelion is fluffy. Let's find more soft or fuzzy things nearby."
```

**Root cause:** This prompt becomes `activity_target` in `attribute_activity.py:174` and is used for ALL objects, including "orange cat".

**Fix options:**
- Option A: Make it entity-agnostic: `"This looks fluffy. Let's find more soft or fuzzy things nearby."`
- Option B: Add runtime placeholder substitution (e.g. `{runtime_entity}`) in `attribute_activity.py`

---

### Bug 4: Follow-up questions drift away from activity goal [NEEDS DESIGN DISCUSSION]

**This is the area Agent B should discuss with the user.**

#### Root Cause Chain

1. **Dimension Derivation Error** (`paixueji_app.py:1795`):
   ```python
   dimension = assistant.attribute_state.profile.attribute_id.split(".")[0]
   ```
   For `activity.fluffy_expedition_dandelion`, `dimension = "activity"` — a synthetic namespace prefix, not a real dimension.

2. **Wrong Angle Pool** (`stream/exploration_angles.py:116`):
   ```python
   pool_key = "physical" if dimension in PHYSICAL_DIMENSIONS else "engagement"
   ```
   `"activity"` is not in `PHYSICAL_DIMENSIONS`, so it falls through to `engagement` pool (emotional, memory, imagination, social).

3. **Activity Target Dropped** (`paixueji_app.py:195-232`):
   `_build_continue_guide` receives `activity_target` but never includes it in the prompt. The LLM never sees the goal ("find three soft/fuzzy things").

4. **Focus Topic is a Label** (`paixueji_app.py:2028`):
   ```python
   focus_topic = f"the '{attribute_label}' attribute"
   ```
   This produces `"the 'Find three fluffy friends' attribute"` — the LLM is told to stay on a label, not a concrete goal.

#### Transcript Evidence

| Turn | Angle | Question | Why It's Wrong |
|------|-------|----------|---------------|
| 1 | emotional | "Does looking at that soft, orange fur make you feel calm or excited?" | Activity is texture/observation, not emotion |
| 2 | memory | "Does seeing this cat remind you of any other animals?" | No push toward "find fluffy things" |
| 3 | imagination | "If you could give that cat a special name..." | Complete diversion |

The LLM had zero context that the conversation goal was a **collection quest** (`mechanic: collect`, `game_style: quest_collector`).

#### Open Design Questions for Agent B

- Should `dimension` be derived from the activity's `observation_angle` (`texture` → `appearance` → physical pool) instead of the `attribute_id` prefix?
- Should `_build_continue_guide` inject `activity_target`, `observation_angle`, and `mechanic` into the prompt so the LLM knows it is guiding a collection quest?
- Should `focus_topic` describe the activity goal ("finding soft/fuzzy things nearby") rather than the activity label?
- Should angle selection be constrained to angles compatible with the activity's `observation_angle` and `bridge_prerequisites`?
- How should the prompt change when `mechanic: imagine` (dream_whisperer_cat) vs `mechanic: collect` (fluffy_expedition_dandelion)?

---

## Artifacts

| Artifact | Path | Purpose |
|----------|------|---------|
| Regression tests | `tests/test_diagnose_orange_cat.py` | 6 tests that reproduce all 4 bugs |
| Activity catalog (fluffy) | `activities/catalog/fluffy_expedition_dandelion/tag_block.yaml` | Contains hardcoded dandelion prompt |
| Activity catalog (dream) | `activities/catalog/dream_whisperer_cat/tag_block.yaml` | Bound activity rejected due to missing entity_class |
| Entity mapping | `mappings_dev20_0318/animals/cats.yaml` | Missing `entity_class` field |
| Eligibility logic | `activities/__init__.py:324-356` | Both broken checks are here |
| Continue guide builder | `paixueji_app.py:195-232` | Drops activity_target |
| Angle selection | `stream/exploration_angles.py:99-164` | Falls through to engagement pool |
| Follow-up generator | `stream/question_generators.py:185-287` | Assembles final prompt |
| Base follow-up prompt | `paixueji_prompts.py:168-260` | Uses focus_topic |
| Soft guide template | `paixueji_prompts.py:456-546` | ATTRIBUTE_SOFT_GUIDE with activity_target placeholder |

---

## Suggested Skills for Next Session

- **Agent A (Fix):** No special skill needed — straight implementation. Consider `superpowers:test-driven-development` for TDD discipline.
- **Agent B (Design):** `superpowers:brainstorming` before proposing the drifting fix, since it involves architectural decisions about how activities communicate their goals to the prompt layer.
