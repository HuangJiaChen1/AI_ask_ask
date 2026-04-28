# Category Activity Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a category-based activity lane that runs in parallel to the existing attribute lane, with matching backend streaming, frontend toggles/debug state, and HF report diagnostics.

**Architecture:** Mirror the existing attribute pipeline with a new `category_activity.py` backend module, category-specific intro/continue generators, additive stream fields, and isolated assistant state. Reuse shared readiness semantics, `infer_domain()`, and the existing chat-phase-complete UI/reporting paths while preventing cross-contamination between attribute and category lanes.

**Tech Stack:** Flask, Pydantic, async Gemini stream generators, vanilla JS frontend, pytest

---

## Chunk 1: Backend Category Lane Core

### Task 1: Add category pipeline domain models and policy helpers

**Files:**
- Create: `category_activity.py`
- Modify: `tests/test_category_activity_pipeline.py`
- Reference: `attribute_activity.py`, `stream/exploration_loader.py`, `exploration_categories.yaml`

- [ ] **Step 1: Write the failing tests**

Add tests for:
- `build_category_profile()` using a valid known domain and an unknown domain fallback
- `start_category_session()` bootstrapping the session state
- `classify_category_reply()` covering `uncertainty`, `constraint_avoidance`, `activity_command`, `curiosity`, `category_drift`, and `aligned`
- `evaluate_category_activity_readiness()` enforcing the 2-turn threshold
- `build_category_debug()` serializing profile/state/reply/readiness

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/test_category_activity_pipeline.py -q`
Expected: FAIL because `category_activity.py` and the new helpers do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Implement:
- `CATEGORY_ACTIVITY_TEMPLATES` with all 14 `ALL_DOMAINS` entries plus generic fallback behavior
- `CategoryProfile`, `CategorySessionState`, `CategoryReplyDecision`, `CategoryReadinessDecision`
- `build_category_profile()`, `start_category_session()`, `classify_category_reply()`, `evaluate_category_activity_readiness()`, `build_category_debug()`

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `pytest tests/test_category_activity_pipeline.py -q`
Expected: PASS

### Task 2: Add category prompts and stream generators

**Files:**
- Modify: `paixueji_prompts.py`, `stream/question_generators.py`, `stream/response_generators.py`, `stream/__init__.py`
- Modify: `tests/test_category_activity_api.py`

- [ ] **Step 1: Write the failing tests**

Add API-facing tests that assert:
- `/api/start` category lane uses `response_type="category_intro"`
- streamed prompt text comes from category intro/continue prompt templates

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/test_category_activity_api.py -q`
Expected: FAIL because the category prompt keys and generator functions are missing.

- [ ] **Step 3: Write the minimal implementation**

Add:
- `CATEGORY_INTRO_PROMPT`
- `CATEGORY_CONTINUE_PROMPT`
- `ask_category_intro_stream(...)`
- `generate_category_activation_response_stream(...)`
- matching exports in `stream/__init__.py`

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `pytest tests/test_category_activity_api.py -q`
Expected: PASS

## Chunk 2: Assistant, API, and Report Integration

### Task 3: Wire category lane state into assistant and stream schema

**Files:**
- Modify: `paixueji_assistant.py`, `schema.py`
- Modify: `tests/test_category_activity_api.py`, `tests/test_frontend_view_state.py`

- [ ] **Step 1: Write the failing tests**

Add expectations for:
- additive `StreamChunk` fields: `category_pipeline_enabled`, `category_lane_active`, `category_debug`
- assistant category lane lifecycle helpers and `activity_target` payload shape with `activity_source="category"`

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/test_category_activity_api.py tests/test_frontend_view_state.py -q`
Expected: FAIL because the schema and assistant state do not expose category fields yet.

- [ ] **Step 3: Write the minimal implementation**

Add category lane fields and helpers to `PaixuejiAssistant`, and additive category fields to `StreamChunk`.

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `pytest tests/test_category_activity_api.py tests/test_frontend_view_state.py -q`
Expected: PASS

### Task 4: Add `/api/start` and `/api/continue` category branching

**Files:**
- Modify: `paixueji_app.py`
- Modify: `tests/test_category_activity_api.py`, `tests/test_all_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- `/api/start` accepts `category_pipeline_enabled`, classifies with `infer_domain()`, starts the category lane, and streams category intro chunks
- `/api/continue` keeps category state isolated, classifies replies, updates readiness, and streams `category_chat` / `category_activity`
- attribute sessions still behave unchanged when category is off

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/test_category_activity_api.py tests/test_all_endpoints.py -q`
Expected: FAIL because the category lane is not routed through the API yet.

- [ ] **Step 3: Write the minimal implementation**

Implement:
- request parsing for `category_pipeline_enabled`
- category lane setup in `/api/start`
- category intro branch in `stream_introduction()`
- category reply classification/readiness branch in `/api/continue`
- `_assistant_stream_fields()` selection of `activity_ready` and `activity_target` from the active lane

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `pytest tests/test_category_activity_api.py tests/test_all_endpoints.py -q`
Expected: PASS

### Task 5: Extend HF report rendering and parsing for category diagnostics

**Files:**
- Modify: `paixueji_app.py`
- Modify: `tests/test_hf_report_viewer.py`

- [ ] **Step 1: Write the failing tests**

Add report tests for:
- turn summaries rendering category fields
- raw diagnostics appendix rendering `#### Raw Category Debug`
- `_parse_hf_report()` parsing category summary and raw appendix data while preserving backward compatibility

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/test_hf_report_viewer.py -q`
Expected: FAIL because category report fields are not rendered or parsed.

- [ ] **Step 3: Write the minimal implementation**

Add category summary/render/parse helpers and pass category debug data through report generation and parsing flows.

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `pytest tests/test_hf_report_viewer.py -q`
Expected: PASS

## Chunk 3: Frontend Toggle, Debug Panel, and Report Viewer

### Task 6: Add category toggle and live debug state in the frontend

**Files:**
- Modify: `static/index.html`, `static/app.js`
- Modify: `tests/test_frontend_view_state.py`

- [ ] **Step 1: Write the failing tests**

Add expectations for:
- category checkbox markup
- mutually exclusive toggle behavior with attribute checkbox
- category chunk state tracked in JS
- debug panel exposing category pipeline/lane/id/label/activity target/reply type/decision

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/test_frontend_view_state.py -q`
Expected: FAIL because the category toggle and debug state do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Add category checkbox UI, JS state variables, change listeners for radio-group behavior, chunk handling, debug rendering, and activity-ready handling that works for both attribute and category sources.

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `pytest tests/test_frontend_view_state.py -q`
Expected: PASS

### Task 7: Show category diagnostics in the report viewer

**Files:**
- Modify: `static/reports.js`
- Modify: `tests/test_hf_report_viewer.py`

- [ ] **Step 1: Write the failing tests**

Add expectations that the report viewer renders category summary/debug content when present.

- [ ] **Step 2: Run the targeted tests to verify RED**

Run: `pytest tests/test_hf_report_viewer.py -q`
Expected: FAIL because the viewer only formats bridge and attribute diagnostics.

- [ ] **Step 3: Write the minimal implementation**

Add category summary/debug formatter helpers and surface them in the popup/detail rendering alongside existing attribute data.

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run: `pytest tests/test_hf_report_viewer.py -q`
Expected: PASS

## Final Verification

- [ ] **Step 1: Run focused category-related verification**

Run:
- `pytest tests/test_category_activity_pipeline.py tests/test_category_activity_api.py tests/test_frontend_view_state.py tests/test_hf_report_viewer.py tests/test_all_endpoints.py -q`

Expected: PASS

- [ ] **Step 2: Run the broader regression suite covering touched areas**

Run:
- `pytest tests/test_attribute_activity_pipeline.py tests/test_attribute_activity_api.py tests/test_all_endpoints.py tests/test_frontend_view_state.py tests/test_hf_report_viewer.py -q`

Expected: PASS
