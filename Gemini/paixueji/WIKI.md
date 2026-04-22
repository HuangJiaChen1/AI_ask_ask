# Paixueji Repo Wiki

An interactive learning companion for young children (ages 3-8) that asks questions about objects and guides understanding through conversation. Powered by Gemini (Vertex AI) with a LangGraph workflow, real-time SSE streaming, and a post-hoc critique pipeline.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Quick Start](#2-quick-start)
3. [Architecture: Two Systems, One Codebase](#3-architecture-two-systems-one-codebase)
4. [Directory Map](#4-directory-map)
5. [Core Modules](#5-core-modules)
   - [paixueji_app.py — Flask API & SSE Bridge](#51-paixueji_apppy--flask-api--sse-bridge)
   - [graph.py — LangGraph Workflow](#52-graphpy--langgraph-workflow)
   - [stream/ — Shared Generators](#53-stream--shared-generators)
   - [schema.py — StreamChunk & Debug Models](#54-schemapy--streamchunk--debug-models)
   - [paixueji_assistant.py — Session State](#55-paixueji_assistantpy--session-state)
   - [paixueji_prompts.py — All Prompt Templates](#56-paixueji_promptspy--all-prompt-templates)
6. [Bridge & Anchor System](#6-bridge--anchor-system)
7. [Attribute & Activity Pipeline](#7-attribute--activity-pipeline)
8. [Object Resolution](#8-object-resolution)
9. [Fun Facts (Grounded)](#9-fun-facts-grounded)
10. [Intent Classification (9+4 Node Architecture)](#10-intent-classification-94-node-architecture)
11. [API Reference](#11-api-reference)
12. [Configuration](#12-configuration)
13. [Runtime-Overridable Behaviour](#13-runtime-overridable-behaviour)
14. [Knowledge Base & Dimension Coverage](#14-knowledge-base--dimension-coverage)
15. [Session Model](#15-session-model)
16. [Critique System (Post-Hoc)](#16-critique-system-post-hoc)
17. [Tracing & Observability](#17-tracing--observability)
18. [Testing](#18-testing)
19. [Known Constraints](#19-known-constraints)
20. [Critical Consistency Rule](#20-critical-consistency-rule)

---

## 1. Project Overview

Paixueji ("ask-ask" in Chinese) is a conversational AI that helps young children explore objects through guided questioning. The system:

- Classifies child utterances into 13+ communicative intents
- Generates age-appropriate responses and follow-up questions
- Bridges surface topics to deeper anchor topics (e.g., "cat" -> "mammals")
- Activates attribute exploration lanes (physical/engagement dimensions)
- Serves grounded fun facts via Google Search Grounding
- Runs a post-hoc critique pipeline to evaluate conversation quality

Tech stack: Python 3, Flask, LangGraph, Google Gemini (Vertex AI), Pydantic, PyYAML, Loguru.

---

## 2. Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up authentication
export GOOGLE_APPLICATION_CREDENTIALS="path/to/credentials.json"

# Run the app
python paixueji_app.py
# → http://localhost:5001

# Run tests (offline, Gemini is mocked)
pytest

# Run a single test file
pytest tests/test_api_flow.py

# Run a single test function
pytest tests/test_api_flow.py::test_function_name
```

---

## 3. Architecture: Two Systems, One Codebase

The repo contains two distinct runtime systems that share a common core:

### Chat System (real-time)
```
Browser → POST /api/start or /api/continue
  → Flask (paixueji_app.py)
  → async_gen_to_sync() bridge
  → LangGraph workflow (graph.py)
  → stream/ generators
  → Gemini API (Vertex AI)
  → SSE chunks → browser
```

### Critique System (post-hoc, offline)
```
POST /api/manual-critique
  → Background thread (paixueji_app.py)
  → tests/quality/pipeline.py
  → stream/ generators + paixueji_prompts.py
  → Gemini API
  → Report saved to reports/
```

**Both systems use the same `stream/` functions, `schema.py` types, and prompt strings.** A change in any shared component must be verified against both systems.

---

## 4. Directory Map

```
paixueji/
├── paixueji_app.py            # Flask server, SSE bridge, all API endpoints
├── graph.py                   # LangGraph StateGraph, 21+ nodes, routing
├── paixueji_assistant.py      # PaixuejiAssistant session state wrapper
├── paixueji_prompts.py        # All prompt templates (system, intent, intro, etc.)
├── schema.py                  # StreamChunk, TokenUsage, debug info models
├── object_resolver.py         # LLM-based object name → anchor resolution
├── attribute_activity.py      # Attribute pipeline: classify, profile, session
├── bridge_activation_policy.py # Bridge phases, activation turn counting
├── bridge_context.py          # BridgeContext builder, relation normalization
├── bridge_debug.py            # Debug info builders for bridge transitions
├── bridge_profile.py          # BridgeProfile inference (LLM-based)
├── pre_anchor_policy.py       # Pre-anchor reply classification
├── kb_context.py              # KB context formatters (chat + intro)
├── graph_lookup.py            # YAML concept lookup, IB PYP theme classification
├── theme_classifier.py        # Theme classification helpers
├── trace_assembler.py         # TraceObject assembly for critique pipeline
├── trace_schema.py            # Trace schema dataclasses
├── model_json.py              # JSON extraction from LLM output (with recovery)
├── resolution_debug.py        # Resolution debug formatting
├── prompt_optimizer.py        # Prompt optimization pipeline
├── config.json                # Model names, GCP project, temperature
├── age_prompts.json           # Age-band language guidance (3-4, 5-6, 7-8)
├── object_prompts.json        # 3-level category taxonomy
├── themes.json                # IB PYP theme definitions
├── concepts.json              # Concept definitions
├── hook_types.json            # Question hook type taxonomy
├── exploration_categories.yaml # 14-domain sub-attribute hierarchy
├── prompt_overrides.json      # Runtime prompt overrides (no restart)
├── router_overrides.json      # Runtime routing overrides (no restart)
├── stream/                    # Shared streaming core (see below)
├── mappings_dev20_0318/       # YAML entity dimension data (age-tiered)
├── tests/                     # Test suite (see Testing section)
├── static/                    # Frontend assets
├── logs/                      # Runtime logs (loguru, 30-day retention)
├── traces/                    # Per-session trace JSON files
├── reports/                   # Critique reports output
├── docs/                      # Architecture diagrams, plans
└── optimizations/             # Prompt optimization data
```

---

## 5. Core Modules

### 5.1 paixueji_app.py — Flask API & SSE Bridge

The monolithic entry point (~4000 lines). Responsibilities:

- **Flask server** with CORS, serving static files at `/`
- **In-memory session store** (`sessions` dict, keyed by session_id)
- **SSE streaming** via `Response(generate_sse(), mimetype='text/event-stream')`
- **Async bridge**: `async_gen_to_sync()` bridges Flask (sync) to LangGraph (async)
- **Global Gemini client** initialized at startup for connection reuse
- **20 API endpoints** (see API Reference)
- **Background threads** for critique pipeline
- **Rate-limit handling** with user-friendly SSE error payloads

Key constants:
- `MAX_BRIDGE_ATTEMPTS = 2`
- `MAX_PRE_ANCHOR_SUPPORT_TURNS = 2`
- `MAX_BRIDGE_ACTIVATION_TURNS = 4`
- `GUIDE_MODE_THRESHOLD = 2` (correct answers to complete chat mode)

### 5.2 graph.py — LangGraph Workflow

Defines `PaixuejiState` TypedDict (~30 fields) and a `StateGraph` with 21+ async nodes.

**Node catalog:**

| Node | Line | Purpose |
|:---|:---:|:---|
| `node_analyze_input` | 523 | Classify child utterance into intent |
| `node_generate_fun_fact` | 565 | Produce grounded fun fact |
| `node_generate_intro` | 592 | Stream introduction question |
| `node_curiosity` | 791 | Child asks why/what/how |
| `node_concept_confusion` | 824 | Concept confusion handler |
| `node_clarifying_idk` | 857 | Child says "I don't know" |
| `node_fallback_freeform` | 894 | Classification failed fallback |
| `node_give_answer_idk` | 925 | Child deeply confused — reveal answer |
| `node_clarifying_wrong` | 1009 | Child gives incorrect answer |
| `node_clarifying_constraint` | 1042 | Child gives partial answer |
| `node_correct_answer` | 1075 | Child answers correctly |
| `node_informative` | 1151 | Child shares knowledge |
| `node_play` | 1206 | Child being silly/imaginative |
| `node_emotional` | 1239 | Child expresses feeling |
| `node_avoidance` | 1272 | Child refuses/exits |
| `node_boundary` | 1326 | Child asks risky action |
| `node_action` | 1359 | Child issues command |
| `node_social` | 1413 | Child asks about AI |
| `node_social_acknowledgment` | 1468 | Social acknowledgment |
| `node_finalize` | 1523 | Build final StreamChunk, accumulate text |
| `node_classify_theme` | 1608 | IB PYP theme classification |

**Tracing**: All nodes decorated with `@trace_node`, which captures execution time and state diffs into `nodes_executed`.

**Primary chat-mode path:**
```
analyze_input → route_logic → [intent_node] → generate_question → finalize
```

**Completion path:**
```
correct_answer threshold → classify_theme → correct_answer → finalize
```

### 5.3 stream/ — Shared Generators

All public functions re-exported via `stream/__init__.py`. Both Chat and Critique systems depend on these.

| File | Functions | Purpose |
|:---|:---|:---|
| `response_generators.py` | `generate_intent_response_stream`, `generate_classification_fallback_stream`, `generate_bridge_activation_response_stream`, `generate_bridge_retry_response_stream`, `generate_bridge_support_response_stream`, `generate_attribute_activation_response_stream`, `generate_topic_switch_response_stream` | 7 async generators for streaming LLM responses |
| `question_generators.py` | `ask_introduction_question_stream`, `ask_followup_question_stream`, `ask_attribute_intro_stream` | 3 async generators for question-only streams |
| `validation.py` | `classify_intent`, `classify_pre_anchor_semantic_reply`, `classify_bridge_follow`, `classify_dimension`, `map_response_to_kb_item` | Intent classification & KB mapping |
| `fun_fact.py` | `generate_fun_fact`, `get_cached_fun_fact`, `cache_fun_fact` | Two-step grounded fact generation (grounding → structuring) + cache pool |
| `utils.py` | `clean_messages_for_api`, `prepare_messages_for_streaming`, `convert_messages_to_gemini_format`, `extract_previous_response`, `select_hook_type` | Message preparation, format conversion, hook selection |
| `exploration_loader.py` | `get_candidate_sub_attributes`, `infer_domain`, `sub_attribute_to_label`, `dimension_to_activity_target` | 14-domain YAML loader for attribute pipeline |
| `db_loader.py` | `load_physical_dimensions`, `load_engagement_dimensions` | Age-tiered dimension maps from YAML entity files |
| `errors.py` | `RateLimitError`, `raise_if_rate_limited`, `build_sse_error_payload` | Rate-limit detection and SSE error formatting |

### 5.4 schema.py — StreamChunk & Debug Models

Pydantic models defining the unified chunk format:

- **`StreamChunk`**: The core streaming unit. ~60 fields including:
  - `response`, `session_finished`, `duration`, `token_usage`, `finish`, `sequence_number`
  - Intent fields: `intent_type`, `classification_status`
  - Fun fact fields: `fun_fact`, `fun_fact_hook`, `fun_fact_question`, `real_facts`
  - Theme fields: `ibpyp_theme`, `ibpyp_theme_name`, `key_concept`
  - Bridge/anchor fields: `bridge_phase`, `anchor_status`, `anchor_object_name`, etc.
  - Attribute pipeline fields: `attribute_pipeline_enabled`, `attribute_lane_active`, `activity_ready`
  - Debug fields: `nodes_executed`, `bridge_debug`, `resolution_debug`

- **`TokenUsage`**: `input_tokens`, `output_tokens`, `total_tokens`
- **`BridgeDebugInfo`**: ~25 fields tracking bridge transitions
- **`ActivationTransitionDebugInfo`**: Before/after state for activation transitions
- **`ResolutionDebugInfo`**: Object resolution debug trace

### 5.5 paixueji_assistant.py — Session State

`PaixuejiAssistant` holds all per-session mutable state:

- Gemini client + configuration
- Conversation history and `ConversationState` enum
- Object names: `object_name`, `surface_object_name`, `visible_object_name`, `anchor_object_name`
- Bridge state: `bridge_phase`, `bridge_attempt_count`, `bridge_profile`, `learning_anchor_active`
- Activation state: `activation_turn_count`, `activation_handoff_ready`, `activation_last_question_*`
- Attribute pipeline: `attribute_pipeline_enabled`, `attribute_lane_active`, `attribute_state`, `attribute_profile`
- IB PYP theme: `ibpyp_theme`, `ibpyp_theme_name`, `key_concept`
- Dimension coverage: `physical_dimensions`, `engagement_dimensions`, `dimensions_covered`
- Struggle tracking: `consecutive_struggle_count`, `correct_answer_count`

Key methods:
- `apply_resolution()` — Apply an `ObjectResolutionResult` to session state
- `activate_anchor_topic()` — Promote anchor to active learning topic
- `begin_bridge_activation()` / `commit_bridge_activation()` — Manage bridge activation lifecycle
- `start_attribute_lane()` / `clear_attribute_lane()` — Manage attribute pipeline
- `load_dimension_data()` / `load_object_context_from_yaml()` — Load YAML-sourced context

### 5.6 paixueji_prompts.py — All Prompt Templates

~2000-line module containing all LLM prompt templates:

- `SYSTEM_PROMPT` — Core system instructions (voice contract, age guidance)
- `USER_INTENT_PROMPT` — Intent classification prompt
- `{intent}_INTENT_PROMPT` — Per-intent response templates (curiosity, clarifying_idk, etc.)
- `INTRODUCTION_QUESTION_PROMPT` — Opening question generation
- `FOLLOWUP_QUESTION_PROMPT` — Follow-up question generation
- `OBJECT_RESOLUTION_PROMPT` — Object name → anchor resolution
- `BRIDGE_PROFILE_PROMPT` — Bridge profile inference
- `FUN_FACT_GROUNDING_PROMPT` / `FUN_FACT_JSON_PROMPT` — Two-step fun fact generation
- Runtime-overridable: `INPUT_ANALYZER_RULES`, `THEME_NAVIGATOR_RULES`

---

## 6. Bridge & Anchor System

The bridge system connects a **surface object** (what the child mentioned) to a deeper **anchor object** (a supported entity with rich knowledge-base coverage).

### Bridge Phases

| Phase | Constant | Meaning |
|:---|:---|:---|
| None | `BRIDGE_PHASE_NONE` | No bridge active |
| Pre-anchor | `BRIDGE_PHASE_PRE_ANCHOR` | Anchor identified but not yet activated |
| Activation | `BRIDGE_PHASE_ACTIVATION` | Bridge transition in progress |
| Anchor general | `BRIDGE_PHASE_ANCHOR_GENERAL` | Anchor is the active learning topic |

### Key Files

| File | Role |
|:---|:---|
| `bridge_activation_policy.py` | Phase constants, activation turn counting, answer heuristics, KB question matching |
| `bridge_context.py` | `BridgeContext` dataclass, `build_bridge_context()`, relation normalization |
| `bridge_profile.py` | `BridgeProfile` dataclass, `infer_bridge_profile()` (LLM-based) |
| `bridge_debug.py` | Debug info builders for bridge transitions, continuity anchors |
| `pre_anchor_policy.py` | `classify_pre_anchor_reply()` — decides whether child followed the bridge |

### Flow

1. Child mentions surface object → `object_resolver.py` identifies anchor
2. `bridge_profile.py` infers relation, angles, steering rules
3. Pre-anchor: `pre_anchor_policy.py` classifies child's reply to bridge prompts
4. Activation: `bridge_activation_policy.py` tracks turns, validates questions/answers
5. Commit: anchor becomes the active topic, dimension data loaded

---

## 7. Attribute & Activity Pipeline

The attribute pipeline allows the system to drill into specific physical/engagement dimensions of an object and eventually propose a hands-on activity.

### Key Concepts

- **SubAttributeCandidate**: A specific dimension+attribute pair from `exploration_categories.yaml`
- **AttributeProfile**: Selected attribute with label, activity target, branch, examples
- **AttributeSessionState**: Tracks turn count, activity readiness, question history

### Key Files

| File | Role |
|:---|:---|
| `attribute_activity.py` | `AttributeProfile`, `AttributeSessionState`, `classify_attribute_reply()`, `select_attribute_profile()`, `start_attribute_session()` |
| `stream/exploration_loader.py` | 14-domain YAML loader, `get_candidate_sub_attributes()`, `infer_domain()`, `dimension_to_activity_target()` |
| `exploration_categories.yaml` | 14 domains × 3 tiers of sub-attribute definitions |

### 14 Domains

animals, food, vehicles, plants, people_roles, buildings_places, clothing_accessories, daily_objects, natural_phenomena, arts_music, signs_symbols, nature_landscapes, human_body, imagination

---

## 8. Object Resolution

When a child names an object, the system resolves it against the knowledge base to find:

- **Surface object name**: What the child said (normalized)
- **Visible object name**: What to display
- **Anchor object name**: Deeper supported entity (if any)
- **Anchor status**: `exact_supported`, `partial_supported`, `anchored_high`, `unresolved`
- **Bridge profile**: How to bridge surface → anchor

### Key Files

| File | Role |
|:---|:---|
| `object_resolver.py` | `resolve_object_input()` — LLM + lookup-based resolution |
| `model_json.py` | `extract_json_object()` — Robust JSON extraction with recovery |
| `resolution_debug.py` | Debug formatting for resolution trace |
| `graph_lookup.py` | YAML concept lookup, theme classification, anchor formatting |

---

## 9. Fun Facts (Grounded)

Two-step pipeline (grounding + JSON cannot be combined in one Gemini call):

1. **Grounded Research**: Gemini + Google Search → raw facts text
2. **JSON Structuring**: Gemini + JSON mode → structured fun facts + real facts
3. **Cache pool**: Store 3-5 fun facts, randomly pick one per conversation

`stream/fun_fact.py` manages the cache (`_fun_fact_cache`) keyed by lowercase object name.

---

## 10. Intent Classification (9+4 Node Architecture)

The system classifies child utterances into 13+ communicative intents:

### Primary Intents (9)

| Intent | Node | Behavior |
|:---|:---|:---|
| CURIOSITY | `node_curiosity` | Expand gently + suggest action |
| CLARIFYING_IDK | `node_clarifying_idk` | Affirm + give partial answer |
| CLARIFYING_WRONG | `node_clarifying_wrong` | Affirm effort + gently correct |
| CLARIFYING_CONSTRAINT | `node_clarifying_constraint` | Add constraint/refine |
| CORRECT_ANSWER | `node_correct_answer` | Celebrate + deepen |
| INFORMATIVE | `node_informative` | Give space + social reaction |
| PLAY | `node_play` | Play along + gamify |
| EMOTIONAL | `node_emotional` | Empathize first + redirect |
| AVOIDANCE | `node_avoidance` | Acknowledge + re-hook or topic switch |

### Extended Intents (+4)

| Intent | Node | Behavior |
|:---|:---|:---|
| BOUNDARY | `node_boundary` | Empathize + deny danger + safe alternative |
| ACTION | `node_action` | Execute or redirect |
| SOCIAL | `node_social` | Warm direct answer |
| SOCIAL_ACKNOWLEDGMENT | `node_social_acknowledgment` | Brief acknowledgment |

### Special Nodes

| Node | Trigger |
|:---|:---|
| `node_concept_confusion` | Concept confusion detected |
| `node_give_answer_idk` | 2+ consecutive struggles (IDK/wrong) |
| `node_fallback_freeform` | Classification failure |
| `node_classify_theme` | Correct answer threshold reached |

---

## 11. API Reference

| Method | Endpoint | Purpose |
|:---|:---|:---|
| GET | `/` | Serve frontend |
| GET | `/api/health` | Health check, session count |
| GET | `/api/objects` | List supported objects |
| POST | `/api/start` | Start a new session (SSE stream) |
| POST | `/api/continue` | Continue an existing session (SSE stream) |
| POST | `/api/reset` | Reset/clear a session |
| GET | `/api/sessions` | List active sessions |
| POST | `/api/lookup-concepts` | Look up available concepts for an object |
| POST | `/api/force-switch` | Force a topic switch |
| GET | `/api/exchanges/<session_id>` | Get exchange history for a session |
| POST | `/api/manual-critique` | Trigger post-hoc critique on a session |
| POST | `/api/optimize-prompt` | Start prompt optimization |
| POST | `/api/optimize-prompt/<id>/approve` | Approve optimization |
| POST | `/api/optimize-prompt/<id>/refine` | Refine optimization |
| POST | `/api/optimize-prompt/<id>/reject` | Reject optimization |
| GET | `/api/reports/hf` | List human-feedback reports |
| GET | `/api/reports/hf/<date>/<filename>` | View a report |
| GET | `/api/reports/hf/<date>/<filename>/raw` | View raw report data |
| POST | `/api/handoff` | Handoff endpoint |
| GET | `/tmp/handoff/<filename>` | Serve handoff file |

---

## 12. Configuration

### config.json

| Key | Default | Purpose |
|:---|:---|:---|
| `project` | `elaborate-baton-480304-r8` | GCP project ID |
| `location` | `global` | GCP location |
| `model_name` | `gemini-3.1-flash-lite-preview` | Primary model |
| `grounding_model` | `gemini-3.1-flash-lite-preview` | Model for search grounding |
| `high_reasoning_model` | `gemini-3-pro-preview` | Model for complex reasoning |
| `temperature` | 0.3 | LLM temperature |
| `max_tokens` | 1000 | Max output tokens |
| `wonderlens_url` | `https://...` | Wonderlens service URL |

### age_prompts.json

Three age bands with language guidance:
- **3-4 years**: Simplest vocabulary, shortest sentences
- **5-6 years**: Moderate complexity
- **7-8 years**: More complex explanations allowed

### hook_types.json

Question hook taxonomy (8 types):
- Open-ended: 想象导向, 情绪投射, 角色代入, 选择偏好, 创意改造, 意图好奇
- Concrete: 细节发现, 经验、生活链接

---

## 13. Runtime-Overridable Behaviour

The app reads these JSON files on every request — no restart required:

| File | Overrides |
|:---|:---|
| `prompt_overrides.json` | `INPUT_ANALYZER_RULES`, `THEME_NAVIGATOR_RULES` in `paixueji_prompts.py` |
| `router_overrides.json` | Data-driven routing decisions |

This enables self-evolution: prompts and routing can be tuned in production without redeployment.

---

## 14. Knowledge Base & Dimension Coverage

### Physical Dimensions (6)

`appearance`, `senses`, `function`, `structure`, `context`, `change`

### Engagement Dimensions (5)

`emotions`, `relationship`, `reasoning`, `imagination`, `narrative`

### Data Source

`mappings_dev20_0318/` — YAML entity files with age-tiered dimension data:

- Each entity has physical + engagement dimensions
- Three age tiers: `tier_0` (3-4), `tier_1` (5-6), `tier_2` (7-8)
- Loaded by `stream/db_loader.py` with LRU caching
- Dimension coverage tracked per-session: `dimensions_covered`, `active_dimension`

### IB PYP Themes

Six transdisciplinary themes from the IB Primary Years Programme:

| ID | Name |
|:---|:---|
| `how_world_works` | How the World Works |
| `sharing_planet` | Sharing the Planet |
| `who_we_are` | Who We Are |
| `how_we_express` | How We Express Ourselves |
| `how_we_organize` | How We Organize Ourselves |
| `where_place_time` | Where We Are in Place and Time |

Classification via `graph_lookup.py` → `classify_object_yaml()` with fallback to conversation-based analysis.

---

## 15. Session Model

- Sessions stored **in-memory** in the `sessions` dict (`paixueji_app.py`)
- All session data is lost on server restart
- Each session holds a `PaixuejiAssistant` instance with full mutable state
- Session lifecycle: `start` → `continue` (repeated) → `reset` or timeout
- Flask bridges to async LangGraph via `async_gen_to_sync()`

---

## 16. Critique System (Post-Hoc)

The critique pipeline evaluates completed conversations offline:

1. **Trigger**: `POST /api/manual-critique` with session_id
2. **Assembly**: `trace_assembler.py` builds a `TraceObject` from conversation history + node traces
3. **Pipeline**: `tests/quality/pipeline.py` runs the critique
4. **Report**: Saved to `reports/` as JSON

### Trace Schema (`trace_schema.py`)

- `TraceObject` — Complete trace of a conversation
- `NodeTrace` — Per-node execution trace
- `HumanCritique` — Human feedback data
- `ExchangeContext` — Per-exchange context
- `CulpritIdentification` — Issue identification with confidence
- `effective_culprits()` — Filter culprits by confidence threshold

### Node Glossary (`trace_assembler.py`)

Contains a human-readable glossary mapping each graph node to its role and prompt key, used in critique reports for explainability.

---

## 17. Tracing & Observability

### Loguru Logging

`stream/utils.py` configures loguru with:
- File rotation at midnight
- 30-day retention
- DEBUG level
- Backtrace + diagnose enabled
- Log path: `logs/paixueji_{date}.log`

### Node Execution Tracing

Every graph node is wrapped by `@trace_node` (graph.py:244), which captures:
- Node name
- Execution time in milliseconds
- State changes (before vs after diff on `KEY_STATE_FIELDS`)
- Full `state_before` snapshot

Trace entries accumulate in `state["nodes_executed"]` and are emitted in the final `StreamChunk`.

### Router Tracing

`@trace_router` decorator captures routing decisions, stored on the assistant object and merged into `nodes_executed` by `node_finalize`.

### Slow Call Detection

`SLOW_LLM_CALL_THRESHOLD = 5.0` seconds — calls exceeding this threshold are logged as warnings.

---

## 18. Testing

### Test Infrastructure

- `tests/conftest.py` — Mocks the Gemini client; all tests run **offline**
- 35+ test files covering all major subsystems

### Test Categories

| Category | Files |
|:---|:---|
| API endpoints | `test_all_endpoints.py`, `test_api_flow.py` |
| Guide flow | `test_guide_flow.py` |
| Object resolution | `test_object_resolver.py`, `test_unknown_object_flow.py` |
| Bridge system | `test_bridge_activation_*.py`, `test_bridge_context.py`, `test_bridge_debug.py`, `test_bridge_follow.py`, `test_bridge_profile.py` |
| Attribute pipeline | `test_attribute_activity_api.py`, `test_attribute_activity_pipeline.py` |
| Intent classification | `test_intent_fixes.py`, `test_debug_intent_descriptions.py` |
| Correct answer | `test_correct_answer_tracking.py`, `test_frontend_correct_answer_threshold.py` |
| Pre-anchor | `test_pre_anchor_policy.py` |
| Exploration | `test_exploration_loader.py`, `test_yaml_classifier.py` |
| Fun facts | `test_open_ended_idk.py` |
| Frontend | `test_frontend_view_state.py`, `test_object_name_card.py` |
| Critique | `test_hf_report_viewer.py`, `test_split_critique_buttons.py` |
| Integration | `integration_runner.py`, `integration_scenarios/` |
| Quality | `tests/quality/` (critique pipeline tests) |

### Running Tests

```bash
# All tests (offline, mocked Gemini)
pytest

# Single file
pytest tests/test_api_flow.py

# Single function
pytest tests/test_api_flow.py::test_function_name
```

---

## 19. Known Constraints

- **In-memory sessions**: All session data lost on restart. No persistence layer.
- **Orphan threads**: Background critique threads may outlive their sessions.
- **Session leaks**: No automatic session cleanup/expiry mechanism.
- **Monolithic app**: `paixueji_app.py` is ~4000 lines; endpoint handlers mix routing logic with business logic.
- **No auth**: API endpoints have no authentication.
- **Single-process**: No horizontal scaling; one Flask process serves all sessions.
- **Cold-start latency**: First Gemini call after startup has higher latency (mitigated by global client init).

---

## 20. Critical Consistency Rule

**A change in any shared component must be verified against BOTH systems before committing.**

| Shared component | Chat | Critique |
|:---|:---:|:---:|
| `stream/` module (all files) | Yes | Yes |
| `paixueji_prompts.py` | Yes | Yes |
| `schema.py` (`StreamChunk`) | Yes | Yes |
| `stream/utils.py` | Yes | Yes |
| `paixueji_assistant.py` session state | Yes | Yes |

Changing a generator signature, a `StreamChunk` field, a prompt template, or a utility function in `stream/` can silently break the critique pipeline even if the live chat still works. Always test both paths.
