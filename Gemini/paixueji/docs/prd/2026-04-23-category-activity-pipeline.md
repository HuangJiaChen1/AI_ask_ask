# PRD: Category → Activity Pipeline

> Created: 2026-04-23
> Status: Draft

## Overview
<!-- prd-scoping -->

A new "Category → Activity" pipeline that recommends activities based on the **category** (domain) an object belongs to, rather than the specific attribute of that object. When a child names "cat", the attribute pipeline focuses on a specific attribute (e.g., fur feel), while the category pipeline recognizes "cat" belongs to the **animals** category and can recommend category-level activities (e.g., "animal recognition flashcards"). The pipeline runs as a **parallel lane** to the existing attribute→activity pipeline, triggered by an explicit "Category" toggle in the frontend. It follows the same engagement-tracking pattern: infer category, guide chat toward category-level engagement, count turns, and trigger activity when 2 engaged turns are reached.

## Goals
<!-- prd-scoping -->

1. **Category classification**: Given an object name, classify it into one of the 14 existing domains (animals, food, vehicles, etc.) using the existing `infer_domain()` function.
2. **Category activity target generation**: Produce a category-level `activity_target` string (e.g., "discovering different animals and what makes them special") that represents the category-wide exploration goal.
3. **Category engagement tracking**: Track child engagement across turns with category-level questions, using the same threshold (2 engaged turns) as the attribute pipeline.
4. **Category reply classification**: Classify child replies in the context of category-level conversation (aligned, drift, curiosity, etc.) to determine counted vs. uncounted turns.
5. **Category readiness evaluation**: Determine when the child is ready for a category-level activity, mirroring the attribute pipeline's readiness policy.
6. **Parallel lane operation**: Coexist with the attribute pipeline as a selectable lane — the frontend "Category" toggle selects which lane is active for a given session.
7. **Frontend "Category" toggle**: Add a "Category" button/toggle to the frontend UI that allows selecting the category lane, mirroring the existing attribute lane toggle.

## Out of Scope
<!-- prd-scoping -->

1. **Activity library implementation**: The actual activity matching algorithm (which specific activity to launch given a category) is out of scope — that will be implemented in a future project. This PRD only covers the chatting pipeline up to the point where an activity target is produced.
2. **Replacing the attribute pipeline**: The category pipeline is additive, not a replacement.
3. **New category taxonomy**: We reuse the existing 14 domains from `exploration_categories.yaml`. No new taxonomy is created.
4. **IB PYP theme integration**: Themes from `themes.json` are not part of this pipeline. Category = domain (14 items), not theme (6 items).
5. **Multi-category objects**: An object maps to exactly one category. Objects that could belong to multiple categories (e.g., "horse" → animals vs. vehicles) will be resolved to a single category by `infer_domain()`.
6. **Category switching mid-session**: Once a category is selected for a session, it does not change.

## Success Criteria
<!-- prd-scoping -->

1. Given an object name + "Category" lane selection, the pipeline classifies the object into one of the 14 domains and produces a category-level `activity_target` string.
2. The category pipeline tracks engagement with the same threshold as the attribute pipeline (2 counted turns → activity ready).
3. The category pipeline correctly classifies child replies (aligned, curiosity, drift, uncertainty, constraint avoidance, activity command) in the category context.
4. The attribute pipeline continues to work identically when the category lane is not selected.
5. Session state correctly reflects which lane (attribute or category) is active, with no cross-contamination.
6. The `/api/start` and `/api/continue` endpoints support the category lane with the same SSE streaming contract as the attribute lane.
7. A "Category" toggle is visible and functional in the frontend UI: selecting it activates the category lane, deselecting it returns to the attribute lane (or no lane). The toggle displays the inferred category name once classification completes.
8. All existing tests pass; new tests cover the category pipeline with the same mock strategy (offline, no real Gemini calls).

## Interaction Points
<!-- prd-detailing -->

### IP-1: Session start — frontend toggle

**Source:** Goal 7  
The user selects the "Category" checkbox on the start form before pressing "Start Learning!". The frontend reads this toggle and includes `category_pipeline_enabled: true` in the `/api/start` POST body, alongside the existing `attribute_pipeline_enabled` flag. Only one of the two can be active per session; if both are sent as `true`, the backend rejects or defaults to category lane (to be decided at constraint phase).

### IP-2: `/api/start` — category classification

**Source:** Goals 1, 2  
On receiving `category_pipeline_enabled: true`, the server calls `infer_domain(object_name, client, config)` to classify the object into one of the 14 domains. If classification succeeds, a `CategoryProfile` is built containing `category_id` (e.g., `"animals"`), `category_label` (e.g., `"Animals"`), and `activity_target` (e.g., `"discovering different animals and what makes them special"`). The session's `category_lane_active` is set to `True`. The first SSE chunk carries `category_pipeline_enabled`, `category_lane_active`, and `category_debug` fields, mirroring the attribute pipeline's intro chunk contract.

### IP-3: `/api/start` — category intro generation

**Source:** Goals 2, 3  
With `category_lane_active`, the `/api/start` stream runs a category intro generator (analogous to `ask_attribute_intro_stream`) that produces the first assistant message. The intro is framed around the inferred category rather than a specific attribute. The `response_type` on the chunk is `"category_intro"`.

### IP-4: `/api/continue` — child reply classification

**Source:** Goals 4, 5  
On each `/api/continue` call while `category_lane_active`, the server calls `classify_category_reply(state, child_input)` to determine the reply type and whether the turn counts. The classification logic mirrors the attribute pipeline's reply classifier but uses category-level context (e.g., drift detection checks whether the child is talking about a different category vs. a different feature of the same category).

### IP-5: `/api/continue` — readiness evaluation and activity trigger

**Source:** Goals 3, 5  
After reply classification, `evaluate_category_activity_readiness(state, reply)` checks whether the 2-turn threshold has been met. When `activity_ready` becomes `True`, the stream returns a `response_type="category_activity"` chunk with `chat_phase_complete=True`, and the frontend shows the chat-phase-complete modal — the same behavior as the attribute pipeline.

### IP-6: Frontend debug panel — live session state

**Source:** Goal 7, SC 7  
A "Category" `<label>/<input type="checkbox">` element is added to `index.html` adjacent to the existing "Attributes" toggle. The toggle is mutually exclusive with "Attributes" (selecting one deselects the other via JS). After session start, the debug panel displays: `category_pipeline_enabled` (on/off), `category_lane_active` (active/inactive), `category_id`, `category_label`, `activity_target`, `category_reply_type`, `category_decision`, `turn_count`, `activity_ready` — mirroring the depth of the existing attribute debug rows.

### IP-7: Report viewer — per-turn category debug

**Source:** SC 7 (extended per feedback)  
After a session ends, the HF critique report includes category debug data at two levels:

1. **Turn Summary block** (inline in the report markdown): each model turn's `#### Turn Summary` sub-block lists category fields (`Category Lane`, `Category ID`, `Category Label`, `Activity Target`, `Category Reply Type`, `Category Decision`) alongside bridge/attribute fields when the category lane was active.
2. **Raw Diagnostics Appendix** (`#### Raw Category Debug`): each exchange entry includes a full structured dump of `CategoryProfile`, `CategorySessionState`, `CategoryReplyDecision`, and `CategoryReadinessDecision` — sufficient to reconstruct exact pipeline state at any turn without the live server.

---

## Behavior Decision Trees
<!-- prd-detailing -->

### Tree 1: `/api/start` — category lane activation

```
category_pipeline_enabled = true?
├── YES → call infer_domain(object_name)
│   ├── domain found (one of 14) → build CategoryProfile → start_category_session()
│   │   → stream category_intro (response_type="category_intro")
│   └── domain not found (None) → CategoryProfile with domain=None, activity_target=generic fallback
│       → stream category_intro with generic framing
│       → category_lane_active = True (degraded mode, no domain-specific target)
└── NO → proceed with existing logic (attribute lane or ordinary chat)
```

**Deviation probe:**
- What if `infer_domain` raises an exception? → treat as domain not found; log error; continue with fallback.
- What if both `attribute_pipeline_enabled` and `category_pipeline_enabled` are `true`? → backend activates category lane only; attribute lane is ignored; a warning is logged.

### Tree 2: `/api/continue` — category reply classification

```
category_lane_active = true?
├── YES → classify_category_reply(state, child_input)
│   ├── uncertainty ("don't know", "not sure") → counted=False, state_action="scaffold_category"
│   ├── constraint avoidance ("stop", "don't want") → counted=False, state_action="low_pressure_repair"
│   ├── activity command ("play", "game", "let's") → counted=False, state_action="acknowledge_keep_category"
│   ├── curiosity (question mark / "why"/"how"/"what") → counted=True, state_action="answer_and_reconnect"
│   ├── category drift (child talks about a completely different domain) → counted=True, state_action="accept_comparison_keep_category"
│   └── aligned (child engages with category topic) → counted=True, state_action="continue_category_lane"
│
│   → evaluate_category_activity_readiness(state, reply)
│       ├── already ready → state_action="invite_category_activity"
│       ├── counted AND turn_count >= 2 → activity_ready=True, state_action="invite_category_activity"
│       └── not ready → state_action = reply.state_action
│
│   → stream response (response_type="category_activity" if ready, else "category_chat")
└── NO → proceed with existing logic
```

**Deviation probe:**
- What if `category_lane_active` but `category_state` is `None` (race condition)? → fall through to existing ordinary-chat logic; log warning.
- What if the child's reply is empty or whitespace? → treat as aligned (default branch); do not count unless non-empty.

### Tree 3: Frontend toggle mutual exclusion (enforced radio-group behaviour)

```
User checks "Category" checkbox
├── "Attributes" is currently checked → uncheck "Attributes" immediately (before form submit)
└── "Attributes" is unchecked → no change

User checks "Attributes" checkbox
├── "Category" is currently checked → uncheck "Category" immediately (before form submit)
└── "Category" is unchecked → no change

User unchecks either checkbox → both unchecked (no lane active) — allowed
Result: both checked simultaneously is structurally impossible
```

---

## Implementation Approach
<!-- prd-detailing -->

The implementation follows the attribute pipeline's structure exactly, adding parallel category equivalents. No existing files are deleted or restructured.

### New file: `category_activity.py`

Mirrors `attribute_activity.py`. Contains:
- `CategoryProfile` dataclass: `category_id`, `category_label`, `activity_target`, `domain`
- `CategorySessionState` dataclass: `object_name`, `category_id`, `profile`, `age`, `turn_count`, `activity_ready`, `last_question`
- `CategoryReplyDecision` dataclass: `reply_type`, `category_id`, `counted_turn`, `activity_ready`, `state_action`, `reason`
- `CategoryReadinessDecision` dataclass: mirrors `AttributeReadinessDecision`
- `build_category_profile(domain, object_name) -> CategoryProfile`: builds profile from a known domain; uses a `CATEGORY_ACTIVITY_TEMPLATES` dict (14 entries, one per domain)
- `start_category_session(...)` → `CategorySessionState`
- `classify_category_reply(state, child_reply)` → `CategoryReplyDecision`
- `evaluate_category_activity_readiness(state, reply)` → `CategoryReadinessDecision`
- `build_category_debug(...)` → debug dict

### New data: `CATEGORY_ACTIVITY_TEMPLATES` dict (in `category_activity.py`)

14 entries mapping each domain to a category-level activity target string, e.g.:
- `"animals"` → `"discovering different animals and what makes them special"`
- `"food"` → `"exploring different foods and how we eat them"`
- `"vehicles"` → `"learning about vehicles and how they help us travel"`
- (fallback for `None` domain) → `"exploring different kinds of things in our world"`

### New stream generators: `stream/category_generators.py`

Two async generators mirroring the attribute equivalents:
- `ask_category_intro_stream(...)`: generates the first message framing the category exploration
- `generate_category_activation_response_stream(...)`: generates turn responses during the category chat phase, using `state_action` to vary the response style

### Changes to `paixueji_assistant.py`

Add category-lane state fields parallel to existing attribute fields:
```python
self.category_pipeline_enabled = False
self.category_lane_active = False
self.category_state = None
self.category_profile = None
self.last_category_debug = None
self.category_activity_ready = False
```
Add methods: `start_category_lane(state, profile)`, `clear_category_lane()`, `set_last_category_debug(d)`, `category_activity_target() -> dict | None`

### Changes to `schema.py` (`StreamChunk`)

Add fields mirroring the attribute fields:
```python
category_pipeline_enabled: bool = False
category_lane_active: bool = False
category_debug: dict | None = None
```
`activity_ready` and `activity_target` are already present and reused (the category pipeline sets `activity_source="category"` in the target dict).

### Changes to `paixueji_app.py`

1. **`/api/start`**: Read `category_pipeline_enabled` from request body. If `True`, call `infer_domain()`, build `CategoryProfile`, call `start_category_session()`, call `assistant.start_category_lane()`. In the `stream_introduction()` generator, add a branch for `assistant.category_lane_active` that calls `ask_category_intro_stream`.
2. **`/api/continue`**: In the continue generator, add a branch for `assistant.category_lane_active` that calls `classify_category_reply` + `evaluate_category_activity_readiness`, then streams via `generate_category_activation_response_stream`.
3. **`_assistant_stream_fields()`**: Add `category_pipeline_enabled`, `category_lane_active`, `category_debug`, updating `activity_ready` and `activity_target` to reflect whichever lane is active.
4. **`_derive_report_category_summary(category_debug)`**: New helper mirroring `_derive_report_attribute_summary`. Extracts: `category_pipeline`, `category_lane`, `category_id`, `category_label`, `activity_target`, `category_reply_type`, `category_decision` from the category debug dict.
5. **`_render_raw_category_debug(category_debug)`**: New helper mirroring `_render_raw_attribute_debug`. Renders a `#### Raw Category Debug` block containing: `decision`, `reason`, `response_text` (flat), plus sub-groups `Category Profile`, `Category State`, `Category Reply`, `Category Readiness` — each rendered as a `##### ...` block with key-value lines.
6. **`_render_turn_summary()`**: Extend the existing function to also render category summary fields (`Category Pipeline`, `Category Lane`, `Category ID`, `Category Label`, `Activity Target`, `Category Reply Type`, `Category Decision`) from `category_debug` when present, appended after the existing attribute block.
7. **`_render_raw_diagnostics_entry()`**: Pass `category_debug` as a new parameter; append `_render_raw_category_debug(category_debug)` after the existing `_render_raw_attribute_debug` block.
8. **`parse_summary_block()`**: Add parsing for all 7 new category summary fields (`category_pipeline`, `category_lane`, `category_id`, `category_label`, `activity_target` (already exists, shared), `category_reply_type`, `category_decision`).
9. **`parse_turn_diagnostics()`**: Add the 7 category fields to the returned dict in all three return branches.
10. **`parse_raw_diagnostics_appendix()`**: Add the 7 category fields to the per-exchange entry dict and the regex-based extraction loop; add `#### Raw Category Debug` parsing analogous to `#### Raw Attribute Debug`.
11. **`_parse_hf_report()` transcript assembly**: Carry the 7 category fields from `parse_turn_diagnostics` into each turn dict; merge from appendix entries in the same pattern as attribute fields.

### Changes to `index.html`

Add a "Category" checkbox `<label>` immediately after the existing "Attributes" label:
```html
<label class="category-toggle" for="categoryPipelineEnabled">
    <input type="checkbox" id="categoryPipelineEnabled">
    <span>Category</span>
</label>
```

### Changes to `app.js`

1. Add `currentCategoryPipelineEnabled`, `currentCategoryLaneActive`, `currentCategoryActivityTarget`, `currentCategoryDebug` state variables.
2. In `startConversation()`: read `categoryPipelineEnabled` from the new checkbox; add `category_pipeline_enabled` to the POST body; zero out all `currentCategory*` variables on reset.
3. Add mutual-exclusion enforcement: the two checkboxes behave like a radio group. Checking "Category" immediately unchecks "Attributes" and vice versa via `change` event listeners. Both checkboxes unchecked is valid (no lane active). Both checked simultaneously must be impossible — the listener on each checkbox unchecks the other before the form can be submitted.
4. In the chunk handler: read `category_pipeline_enabled`, `category_lane_active`, `category_debug` from incoming chunks; update state variables.
5. In `updateDebugPanel()`: display `category_pipeline_enabled` (on/off), `category_lane_active` (active/inactive), `category_id`, `category_label`, `activity_target`, `category_reply_type`, `category_decision`, `turn_count`, `activity_ready` — mirroring the existing attribute debug rows.
6. In the report viewer (`reports.js` or inline report rendering): for each model turn that has category fields set, render a "Category Lane" section in the turn detail view showing the same 7 fields, alongside (not replacing) any existing attribute or bridge debug display.

## Hard Constraints
<!-- prd-constraints -->

1. **Attribute pipeline must be unaffected.** A session with `category_pipeline_enabled=true` must not alter the behaviour of a session with `attribute_pipeline_enabled=true` or neither flag set. The two lanes must be fully isolated — no shared mutable state, no fallback from one lane to the other mid-session.

2. **Mutual exclusion is enforced in the frontend — both flags true must never reach the backend.** The "Attributes" and "Category" checkboxes behave as a radio group: checking one unchecks the other immediately. The backend may therefore assume that at most one of `attribute_pipeline_enabled` / `category_pipeline_enabled` is `true` in any `/api/start` request. No backend disambiguation logic is needed or permitted for this case.

3. **`infer_domain()` must be the only classification path.** The category pipeline must not introduce a second LLM call to classify domain. It reuses `infer_domain()` exclusively — both its DB-lookup and Gemini-fallback layers.

4. **No new taxonomy introduced.** The 14 domains from `exploration_categories.yaml` are the only valid `category_id` values. Any domain value not in `ALL_DOMAINS` must be treated as `None` and handled via the generic fallback.

5. **`StreamChunk` schema changes are additive only.** New fields (`category_pipeline_enabled`, `category_lane_active`, `category_debug`) must have defaults so all existing callers that do not pass them continue to work without modification.

6. **Report format must remain backward-compatible.** Existing reports that do not contain `#### Raw Category Debug` or category fields in Turn Summary must parse without error. All new parsing logic must be guarded by `if` checks and regex `re.search` (not positional) so old report formats are not broken.

7. **Engagement threshold is fixed at 2 counted turns**, matching `ATTRIBUTE_ACTIVITY_READY_TURN_THRESHOLD`. This value must not be made configurable in this feature; any change to the threshold applies to both pipelines or neither.

## Soft Constraints
<!-- prd-constraints -->

1. **Category intro prompt style should match the attribute intro.** The category intro should feel like a natural extension of the existing chat style — same age-appropriate language, same tone, similar length — rather than introducing a visibly different register.

2. **`CATEGORY_ACTIVITY_TEMPLATES` strings should be general enough to survive future activity library design.** The strings are free-text descriptions of exploration goals, not prescriptive activity names. If the activity library later defines specific activity titles, the template strings may be updated, but their format should not be assumed to match activity IDs.

3. **Debug panel category fields should appear in the same visual location as attribute fields.** Category lane rows should be grouped near the existing attribute lane rows, not scattered across unrelated sections, to reduce cognitive load when comparing lanes.

4. **`category_debug` dict fields should mirror attribute debug field names where semantics align.** For example, `reply_type`, `counted_turn`, `state_action`, `reason`, `turn_count`, `activity_ready` should use identical key names in both debug dicts. This allows generic report-rendering helpers to be shared or templated rather than duplicated.

## Assumptions
<!-- prd-constraints -->

1. **`infer_domain()` LLM fallback covers any object the child might name.** If the Gemini fallback fails for an unusual object (e.g., a proper noun, a made-up word), `infer_domain()` returns `None`. The category pipeline handles `None` via a generic `activity_target` fallback and proceeds — it does not block session start.  
   *Violated if:* `infer_domain()` raises unhandled exceptions for certain inputs. Mitigation: wrap the call in a `try/except` in `/api/start`, same as `select_attribute_profile`.

2. **The frontend toggle model (one checkbox per lane) is sufficient for v1.** Users are assumed to be developers/testers, not end-user children. A more polished lane-selection UI is deferred.  
   *Violated if:* A non-developer user needs to use the frontend. Mitigation: none needed for this scope.

3. **Report markdown format is stable during this feature's development.** The report rendering and parsing code (`_render_turn_summary`, `parse_summary_block`, etc.) will not be significantly refactored in parallel with this feature.  
   *Violated if:* Another branch changes report format simultaneously. Mitigation: verify report parsing tests pass on both the existing and new report formats after integration.

4. **`stream/category_generators.py` can share the same Gemini client and config pattern as `stream/response_generators.py`.** No new auth or model configuration is needed for the category generators.

## Expectations
<!-- prd-constraints -->

1. **The category pipeline produces coherent, age-appropriate chat.** Given an inferred category (e.g., `animals`), the intro and follow-up responses should sound naturally connected to exploring that category with a child of the given age — not generic filler.

2. **Reply classification is accurate enough for engagement counting.** The `classify_category_reply` function does not need to be perfect, but misclassifying aligned replies as non-counted should be rare enough that the 2-turn threshold is reachable in a normal conversation. Edge-case misclassifications are acceptable and can be improved iteratively.

3. **Report debug fields are complete enough to diagnose any pipeline failure without the live server.** Given only the saved report file, a developer must be able to determine: which category was inferred, what the activity target was, how each child reply was classified, whether the threshold was reached, and what the final readiness decision was.

4. **No regression in existing test suite.** All `pytest` tests pass with the new code in place. New category tests follow the same offline mock strategy (no live Gemini calls) used by `tests/conftest.py`.

## Test Strategy
<!-- prd-ops-planning -->

All tests run offline using the existing `conftest.py` mock strategy — no live Gemini calls. Tests are organised into two new files mirroring the attribute pipeline.

### New file: `tests/test_category_activity_pipeline.py`

Unit tests for `category_activity.py` in isolation — no Flask, no network.

| Test | What it verifies |
|---|---|
| `test_build_category_profile_known_domain` | Given a domain in `ALL_DOMAINS`, `build_category_profile()` returns a `CategoryProfile` with matching `category_id`, non-empty `activity_target`, correct `category_label` |
| `test_build_category_profile_none_domain_uses_fallback` | `domain=None` returns a profile with the generic fallback `activity_target` instead of raising |
| `test_classify_category_reply_all_cases` | Parametrised over all 6 reply branches (uncertainty, constraint avoidance, activity command, curiosity, category drift, aligned) — checks `reply_type`, `counted_turn`, `state_action` |
| `test_category_readiness_requires_two_counted_turns` | First counted turn → `activity_ready=False`; second counted turn → `activity_ready=True`, `chat_phase_complete=True`, `state_action="invite_category_activity"` |
| `test_activity_command_does_not_count_or_trigger_readiness` | `"Let's play"` → `counted_turn=False`, readiness stays `False` |
| `test_already_ready_state_stays_ready` | Once `state.activity_ready=True`, `evaluate_category_activity_readiness` always returns `activity_ready=True` regardless of reply |
| `test_build_category_debug_includes_profile_state_reason` | `build_category_debug()` dict contains `profile`, `state`, `reply`, `readiness`, `reason`, `response_text` keys |
| `test_start_category_session_initial_state` | `turn_count=0`, `activity_ready=False`, correct `object_name`, correct `profile` |

### New file: `tests/test_category_activity_api.py`

Integration tests through the Flask test client using `client` and `mock_gemini_client` fixtures from `conftest.py`.

| Test | What it verifies |
|---|---|
| `test_category_pipeline_start_uses_category_intro` | POST `/api/start` with `category_pipeline_enabled=True` → final chunk has `response_type="category_intro"`, `category_pipeline_enabled=True`, `category_lane_active=True`, non-null `category_debug` with valid `profile.category_id` |
| `test_category_pipeline_off_does_not_activate_lane` | `category_pipeline_enabled=False` → `category_lane_active=False`, `category_debug=None`, `response_type="introduction"` |
| `test_category_pipeline_attribute_pipeline_off_when_category_on` | `category_pipeline_enabled=True` → `attribute_pipeline_enabled=False`, `attribute_lane_active=False` in the final chunk |
| `test_category_pipeline_infer_domain_none_uses_fallback` | Patch `infer_domain` to return `None` → lane still activates, `category_debug.profile.category_id=None`, `activity_target` contains the generic fallback string |
| `test_category_continue_classifies_reply_and_tracks_turns` | Two-turn session: first `/api/continue` → `activity_ready=False`, `category_debug.readiness.engaged_turn_count=1`; second → `activity_ready=True`, `chat_phase_complete=True`, `activity_target.activity_source="category"` |
| `test_category_continue_constraint_avoidance_does_not_count` | `"I can't do that"` → `reply_type="constraint_avoidance"`, `counted_turn=False`, `activity_ready=False` after turn |
| `test_category_pipeline_does_not_interfere_with_bridge_pipeline` | Start with `category_pipeline_enabled=False` on an anchorable object → `bridge_phase` progresses normally, no category fields contaminate the session |

### Non-automatable checks (manual)

| Check | How to verify |
|---|---|
| Toggle mutual exclusion in browser | Check "Category" → "Attributes" unchecks automatically and vice versa; both cannot be simultaneously checked |
| Debug panel fields populated | After `/api/start` with category lane, all 9 debug fields appear in the panel (`category_pipeline_enabled`, `category_lane_active`, `category_id`, `category_label`, `activity_target`, `category_reply_type`, `category_decision`, `turn_count`, `activity_ready`) |
| Report contains category debug blocks | After a complete category-lane session, open the saved report — confirm `#### Turn Summary` lists Category Lane fields and appendix contains `#### Raw Category Debug` with 4 sub-sections |
| Old report loads without error | Open a report saved before this feature — confirm no parsing errors and no empty/broken category columns in the turn viewer |

## Monitoring
<!-- prd-ops-planning -->

This is a locally-run development tool with no production infrastructure. Monitoring uses two complementary channels: the frontend debug panel (real-time, per-session) and server logs (persistent, post-session).

### Frontend debug panel (real-time)

The debug panel is the primary monitoring surface during active development and testing. The following category lane fields are visible live as chunks arrive:

| Field | What it tells you |
|---|---|
| `category_pipeline_enabled` (on/off) | Whether the category lane was requested for this session |
| `category_lane_active` (active/inactive) | Whether classification succeeded and the lane is running |
| `category_id` | Which of the 14 domains was inferred (or blank if `None`) |
| `category_label` | Human-readable domain name |
| `activity_target` | The category-level activity goal string |
| `category_reply_type` | How the most recent child reply was classified |
| `category_decision` | The last pipeline decision (e.g., `category_lane_started`, `category_activity`) |
| `turn_count` | Number of engaged turns counted so far |
| `activity_ready` | Whether the 2-turn threshold has been reached |

A blank `category_id` with `category_lane_active=active` indicates the `None`-domain fallback path was taken — useful for spotting objects that `infer_domain` could not classify.

### Server logs (persistent)

Log lines emitted via `loguru` for post-session diagnosis and CI output:

| Signal | Level | Log line |
|---|---|---|
| `infer_domain()` returned `None` | INFO | `[CATEGORY] domain inference returned None for {object_name}, using fallback` |
| Category lane activated successfully | INFO | `[CATEGORY] lane started — object={object_name}, domain={domain}, activity_target={activity_target}` |
| Activity readiness reached | INFO | `[CATEGORY] activity_ready=True after {turn_count} engaged turns` |
| Exception during `infer_domain` | ERROR | `[CATEGORY] domain inference exception: {exc}` |

No new metrics infrastructure, dashboards, or alerting thresholds are required for this feature.

## Rollback Plan
<!-- prd-ops-planning -->

The category pipeline is purely additive. Rollback is low-risk.

**To disable the feature without reverting code:**
- Remove the "Category" checkbox from `index.html`. With no UI trigger, `category_pipeline_enabled` is never sent as `true`, so the backend category branch is never entered.

**To fully revert:**
1. Delete `category_activity.py` and `stream/category_generators.py`.
2. Revert changes to `paixueji_assistant.py`, `schema.py`, `paixueji_app.py`, `index.html`, `app.js`.
3. Delete `tests/test_category_activity_pipeline.py` and `tests/test_category_activity_api.py`.
4. Run `pytest` to confirm the existing test suite is clean.

**Impact scope:** Sessions in flight at rollback time are lost (in-memory sessions reset on server restart — existing known behaviour per `OPERATIONAL_ARCHITECTURE.md`). No persistent data is written by the category pipeline; no database migrations are involved. Report files already saved before rollback are unaffected — old report parsing is backward-compatible.

**Irreversible operations:** None. The category pipeline writes no new files, no new databases, and no new persisted state outside the in-memory `sessions` dict.

## Performance Expectations
<!-- prd-ops-planning -->

| Operation | Expected cost | Basis |
|---|---|---|
| `infer_domain()` on a known object (DB lookup) | ~0 ms extra | Pure dict lookup; same path used by attribute pipeline today |
| `infer_domain()` on an unknown object (Gemini fallback) | Same latency as the existing attribute pipeline's `infer_domain` call | Already paid by the attribute pipeline; not a new cost |
| `build_category_profile()` | <1 ms | Pure in-process dict lookup, no I/O |
| `classify_category_reply()` | <1 ms | Pure string operations, no I/O |
| `evaluate_category_activity_readiness()` | <1 ms | Pure integer comparison, no I/O |
| `ask_category_intro_stream()` / `generate_category_activation_response_stream()` | Same latency as the corresponding attribute generators | Same Gemini model, same token budget |

The category pipeline adds at most one LLM call per session start (`infer_domain` Gemini fallback), which is already present in the attribute pipeline. For objects in the DB, there is zero additional latency. No new streaming budget or per-turn overhead is introduced.

---
## Changelog
| Date | Author | Change |
|------|--------|--------|
| 2026-04-23 | | Initial draft |
