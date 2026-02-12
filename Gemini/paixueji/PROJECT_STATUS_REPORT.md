# Paixueji Project Status Report

**Last Updated:** January 7, 2026
**Project State:** Stable - Production-Ready with Known Limitations
**Repository:** `C:\Users\123\Documents\GitHub\AI_ask_ask\Gemini\paixueji\`

---

## Executive Summary

**Paixueji** (鎷嶅绾?- "Take learning levels") is an interactive educational AI assistant designed for young children (ages 3-8) that teaches about objects through guided questioning and conversation. Instead of telling children facts, the AI asks carefully crafted questions to encourage observation, critical thinking, and deeper understanding of objects around them.

**Current Status:**
- 鉁?Core functionality is complete and operational
- 鉁?Dual-parallel architecture implemented
- 鉁?Real-time streaming and debug infrastructure in place
- 鈿狅笍 Several production-critical gaps (session persistence, test coverage)
- 鈿狅笍 Technical debt items identified for future work

**Last Activity:** Multiple test sessions on January 7, 2026, validating focus mode transitions and conversation flow.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Completed Work](#completed-work)
3. [Pending Work & Known Issues](#pending-work--known-issues)
4. [Architecture Reference](#architecture-reference)
5. [Quick Start Guide](#quick-start-guide)
6. [Next Steps Recommendations](#next-steps-recommendations)
7. [Critical Files Reference](#critical-files-reference)

---

## Project Overview

### Purpose & Core Functionality

Paixueji enables object-based learning through:
- **Guided Questioning**: AI asks engaging questions about specific objects (e.g., "What color is an apple?")
- **Age-Appropriate Adaptation**: Different question complexity for three age groups (3-4, 5-6, 7-8 years)
- **Focus Strategies**:
  - **Depth mode**: Deep dive into properties of one object
  - **Width mode**: Explore related objects (same color/shape/category)
  - **System-managed mode**: Automatic switching based on performance
- **Real-time Streaming**: Live SSE (Server-Sent Events) for immediate feedback
- **Intelligent Validation**: AI evaluates answers for correctness and engagement
- **Topic Switching**: Seamless transitions between different objects

### Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.x, Flask web framework |
| **AI Engine** | Google Gemini 2.5 Flash Lite (Vertex AI) |
| **Async** | asyncio with event loop management |
| **Frontend** | HTML5/CSS3, vanilla JavaScript |
| **Streaming** | Server-Sent Events (SSE) |
| **Data Models** | Pydantic for validation |
| **Logging** | Loguru (30-day retention, daily rotation) |
| **Storage** | In-memory sessions (JSON config files) |

### Key Features

- **Dual-Parallel Response Architecture**: Generates feedback + follow-up question in sequence
- **Conversation Flow Tree**: Debug infrastructure for incident analysis
- **Session Save/Restore**: Export/import conversation state as JSON
- **Manual Topic Switch Override**: AI detects new objects but offers user confirmation
- **System-Managed Focus**: Automatic depth鈫抴idth transitions based on performance
- **Debug Panel**: Real-time session metadata and flow tree visualization
- **Age-Based Question Types**:
  - 3-4 years: WHAT questions only
  - 5-6 years: WHAT + HOW questions
  - 7-8 years: WHAT + HOW + WHY questions

---

## Completed Work

### Major Features Implemented

#### 1. Dual-Parallel Response Architecture 鉁?- **Location:** `paixueji_stream.py`
- **Description:** Responses split into two parts:
  - Part 1: Feedback/explanation (validates answer correctness)
  - Part 2: Follow-up question (continues learning)
- **Impact:** Enables natural conversation flow with validation + progression
- **Recent Commits:**
  - `e6306dc` - Merged dual-parallel branch
  - `5d530e6` - "final ver before handling"

#### 2. Conversation Flow Tree Debugging System 鉁?- **Location:** `conversation_tree.py` (249 lines)
- **Features:**
  - Tree-based conversation tracking
  - Node types: introduction, followup, explanation, gentle_correction
  - Validation + decision separation
  - Export to text report or JSON
  - Mermaid diagram generation
- **Use Case:** Incident debugging and conversation analysis
- **Status:** Fully operational, integrated into main flow

#### 3. Real-Time SSE Streaming 鉁?- **Locations:** `app.py`, `paixueji_stream.py`, `static/app.js`
- **Implementation:**
  - Async generators for streaming responses
  - Queue-based async-to-sync bridge (`async_gen_to_sync`)
  - SSE event parsing on frontend
  - Chunk-by-chunk text rendering
- **Performance:** 3-15 second response times (logged)
- **Edge Cases Handled:** Timeout detection, error fallbacks

#### 4. System-Managed & Manual Focus Modes 鉁?- **Location:** `static/app.js` (focus mode control panel)
- **Modes:**
  - **System-managed**: Auto depth鈫抴idth transitions after 3-4 questions
  - **Manual**: User selects depth/width_shape/width_color/width_category
  - **Mid-chat switching**: Dropdown to change focus during conversation
- **Logic:** Tracks depth_questions_count, depth_target, width_categories_tried
- **Status:** Both modes operational and tested

#### 5. Session Save/Restore Functionality (Removed)
- **Status:** Deprecated and removed from UI and API as part of codebase cleanup.

#### 6. AI-Powered Answer Validation & Routing 鉁?- **Location:** `paixueji_stream.py` (`decide_topic_switch_with_validation`)
- **Routes to 5 Response Types:**
  1. **Positive feedback** (correct answer)
  2. **Explanation** (child unsure or says "I don't know")
  3. **Gentle correction** (factually wrong answer)
  4. **Topic switch** (child names new object)
  5. **Explicit switch** (manual object selection)
- **Validation Fields:** `is_engaged`, `is_factually_correct`, `correctness_reasoning`
- **Status:** Fully operational with streaming integration

#### 7. Manual Topic Switch with Detection Override 鉁?- **Location:** `static/app.js` (manual topic switch panel)
- **Flow:**
  1. AI detects child mentioned new object
  2. Shows detected object + reasoning
  3. User confirms or cancels switch
  4. If confirmed, triggers explicit switch flow
- **UI:** Inline panel with object name, reasoning, and action buttons
- **Status:** Implemented and tested

#### 8. Age-Appropriate Question Generation 鉁?- **Location:** `age_prompts.json`, `paixueji_stream.py`
- **Age Groups:**
  - **3-4 years**: Simple WHAT questions, concrete concepts
  - **5-6 years**: WHAT + HOW questions, cause-and-effect
  - **7-8 years**: WHAT + HOW + WHY questions, critical thinking
- **Integration:** Age guidance appended to system messages
- **Status:** Fully operational

#### 9. Debug Panel & Flow Tree Visualization 鉁?- **Location:** `static/index.html`, `static/app.js`
- **Features:**
  - Fixed-position debug panel (right side)
  - Real-time display: Session ID, object, tone, focus mode, correct answers
  - Flow tree modal with Mermaid diagram
  - Export conversation state button
- **Endpoints:** `/api/debug/flow-tree/<session_id>`, `/api/debug/logs/<session_id>`
- **Status:** Fully functional

#### 10. Comprehensive Operational Documentation 鉁?- **Location:** `docs/action-flow-graph/`, `OPERATIONAL_ARCHITECTURE.md`
- **Contents:**
  - Action taxonomy (56 actions categorized)
  - State models (frontend, session, streaming)
  - Phase 1-3 transition tables
  - Master flow Mermaid diagram
  - Completeness checklist (51 production scenarios)
- **Status:** Phases 1-3 complete, Phases 4-9 marked as TODO

### Recent Development Activity

**Commits (Last 7 days):**
- `e6306dc` (Jan 7) - Merge dual-parallel branch into main
- `5d530e6` (Jan 7) - "final ver before handling" (Qwen config cleanup)
- Earlier: "operational architecture", "object switching logic", "manual/system focus mode"

**Modified Files:**
- `static/app.js` - Enhanced to 1,410 lines (SSE, focus control, state save/restore)
- `static/index.html` - Added debug panel, focus controls, restore UI
- Python cache files - Active development and testing

**Test Sessions (Jan 7):**
- Multiple sessions testing banana object
- Focus mode: depth with pirate tone
- Validation pipeline working correctly
- Response times: 3-15 seconds (one slow LLM call logged)

### Code Optimizations

- **Shallow Copy**: Replaced deep copy with shallow copy for message lists (10-100x faster)
- **Pydantic Serialization**: Using `model_dump_json()` directly for efficiency
- **Age Guidance**: Appending age-specific prompts to system messages
- **Error Handling**: 76 try/except blocks with safe fallback responses

---

## Pending Work & Known Issues

### Critical (Production-Blocking)

#### 1. No Session Persistence 鈿狅笍
- **Issue:** Sessions stored in-memory Python dict (`sessions = {}` in `app.py:23`)
- **Impact:** All sessions lost on server restart
- **Location:** `app.py:23` (NOTE comment acknowledges this)
- **Recommendation:** Implement Redis or database storage for production
- **Affected Scenarios:** Completeness checklist #20-22 (session edge cases)

#### 2. Zero Test Coverage 鈿狅笍
- **Issue:** No test files exist in codebase
- **Impact:** No automated verification of:
  - Validation logic (`decide_topic_switch_with_validation`)
  - Stream chunk generation
  - Session management
  - Category classification
  - SSE parsing
  - Focus mode transitions
- **Recommendation:** Create pytest suite covering critical paths
- **Priority:** High (before production deployment)

#### 3. Incomplete Error Handling 鈿狅笍
- **Issue:** 76 try/except blocks use generic `except Exception` with fallback messages
- **Impact:** No granular error recovery for specific failure modes
- **Examples:**
  - API failures default to "Tell me about {object}!" (introduction)
  - Validation failures default to "Great job!" (feedback)
- **Silent Handlers:** 14 instances of bare `pass` in exception handlers
- **Recommendation:** Add error type classification, retry logic, circuit breaker

### Documentation Gaps

#### 4. Phase 4-9 Transition Tables Incomplete 鈿狅笍
- **Location:** `docs/action-flow-graph/README.md:63-73`
- **Missing Files:**
  - `phase4-dual-parallel.md` (TODO)
  - `phase5-response-streaming.md` (TODO)
  - `phase6-question-streaming.md` (TODO)
  - `phase7-frontend-rendering.md` (TODO)
  - `phase8-system-managed-focus.md` (TODO)
  - `phase9-error-handling.md` (TODO)
- **Workaround:** Use master flow diagram + completeness checklist
- **Priority:** Medium (helpful for new developers)

#### 5. Missing Deployment Documentation 鈿狅笍
- **Issue:** No deployment guide or production setup instructions
- **Missing:**
  - Environment-specific configs (.dev, .prod, .test)
  - CI/CD pipeline documentation
  - Scaling considerations
  - Monitoring setup
- **Priority:** Medium (before production deployment)

### Technical Debt

#### 6. Unbounded Conversation History 鈿狅笍
- **Issue:** No truncation/pagination for long conversations
- **Impact:** Memory growth in extended sessions (1000+ messages)
- **Location:** Documented in `docs/action-flow-graph/README.md:325`
- **Affected Scenario:** Completeness checklist #46
- **Recommendation:** Implement sliding window or database pagination

#### 7. Large Module Sizes 鈿狅笍
- **Issue:** Single responsibility principle violated
- **Files:**
  - `paixueji_stream.py`: 2,877 lines (validation + streaming + response + question generation + focus management)
  - `app.py`: 1,326 lines (routes + SSE + session + debugging)
- **Impact:** Harder to maintain, test, and onboard new developers
- **Recommendation:** Refactor into smaller modules by responsibility

#### 8. Silent Exception Handlers 鈿狅笍
- **Issue:** 14 instances of bare `pass` statements in exception handlers
- **Locations:** `app.py:233, 388`; `paixueji_stream.py:240, 342, 436, 528, 615, 706, 801, 898, 1383, 1519, 1653, 2001`
- **Impact:** Errors suppressed with no logging or recovery
- **Recommendation:** Add logging statements or specific error handling

#### 9. No Dependency Version Pinning 鈿狅笍
- **Issue:** `requirements.txt` has no version constraints
- **Dependencies:**
  ```
  flask
  flask-cors
  google-genai
  requests
  pydantic
  loguru
  ```
- **Impact:** Breaking changes in dependencies can cause failures
- **Recommendation:** Pin to specific versions (e.g., `flask==3.0.0`)

#### 10. No Environment-Specific Configuration 鈿狅笍
- **Issue:** `config.json` has hardcoded credentials
- **Missing:** Dev/staging/prod environment separation
- **Location:** `config.json` (54 bytes, minimal)
- **Recommendation:** Use environment variables + config templates

### Performance & Monitoring

#### 11. Performance Metrics Not Actively Used 鈿狅笍
- **Issue:** `SLOW_LLM_CALL_THRESHOLD = 5.0` defined but not reported to users
- **Location:** `paixueji_stream.py:32`
- **Missing:** Performance dashboard, metrics aggregation
- **Recommendation:** Add monitoring with alerts for slow responses

#### 12. Event Loop Resource Management 鈿狅笍
- **Issue:** Event loops created per request, relies on garbage collection
- **Location:** `app.py` (event loop creation in routes)
- **Missing:** Explicit cleanup in finally blocks
- **Impact:** Potential resource leaks under high load
- **Recommendation:** Add explicit `loop.close()` in cleanup

---

## Architecture Reference

### System Architecture

```
User Browser
    鈫?Flask Server (:5001)
    鈫?POST /api/start or /api/continue
Session Management (in-memory dict)
    鈫?Create/retrieve PaixuejiAssistant
Async Stream Engine (paixueji_stream.py)
    鈫?Async generators
Google Gemini API (Vertex AI)
    鈫?Streaming responses
SSE Event Loop Bridge (async_gen_to_sync)
    鈫?Queue-based bridge
Flask Response Stream
    鈫?Server-Sent Events
Browser JavaScript (SSE listener)
    鈫?Real-time chunk rendering
Chat UI (messages, progress, thinking time)
```

### API Endpoints (11 Total)

| Method | Endpoint | Type | Purpose |
|--------|----------|------|---------|
| GET | `/` | HTML | Serve index.html |
| GET | `/api/health` | JSON | Health check, session count |
| POST | `/api/start` | SSE | Create session, start conversation |
| POST | `/api/continue` | SSE | Submit answer, continue conversation |
| POST | `/api/reset` | JSON | End session, cleanup |
| POST | `/api/classify` | JSON | Classify object into categories |
| POST | `/api/force-switch` | JSON | Force topic switch |
| POST | `/api/select-object` | JSON | Select object from suggestions |
| GET | `/api/debug/flow-tree/<id>` | JSON | Get conversation flow tree |
| GET | `/api/debug/logs/<id>` | JSON | Get session logs |
| GET | `/api/sessions` | JSON | List all active sessions |

### Key Components

| Component | File | Lines | Responsibility |
|-----------|------|-------|----------------|
| Flask Server | `app.py` | 1,326 | API endpoints, session management, SSE streaming |
| Stream Engine | `paixueji_stream.py` | 2,877 | Async streaming, LLM calls, validation, response generation |
| Gemini Client | `paixueji_assistant.py` | 343 | Lightweight wrapper, state tracking, config loading |
| Flow Tree | `conversation_tree.py` | 249 | Debug tree for conversation tracing |
| Prompts | `paixueji_prompts.py` | 183 | System prompts, templates, focus guidance |
| Schema | `schema.py` | 163 | Pydantic models for request/response validation |
| Frontend | `static/app.js` | 1,410 | SSE handling, UI rendering, state management |
| UI Layout | `static/index.html` | - | Web interface, forms, chat area, debug panel |

### Data Flow: Start Conversation

```
User fills form (age, object, categories, tone, focus_mode)
    鈫?POST /api/start
    鈫?Create PaixuejiAssistant instance
    鈫?Initialize conversation history with system prompt
    鈫?Call ask_introduction_question_stream()
    鈫?LLM generates first question (streamed)
    鈫?SSE chunks 鈫?browser 鈫?render gradually
```

### Data Flow: Continue Conversation

```
User types answer
    鈫?POST /api/continue
    鈫?Validate answer (correctness + engagement)
    鈫?Route to response type:
   - Correct 鈫?Positive feedback
   - Unsure 鈫?Explanation
   - Wrong 鈫?Gentle correction
   - New object 鈫?Topic switch
    鈫?Generate Part 1: Feedback (streamed)
    鈫?Generate Part 2: Follow-up question (streamed)
    鈫?Update session state
    鈫?SSE chunks 鈫?browser 鈫?render
```

---

## Quick Start Guide

### Prerequisites

- Python 3.x installed
- Google Cloud account with Vertex AI enabled
- `GOOGLE_APPLICATION_CREDENTIALS` environment variable set

### Installation

```bash
# Clone repository (if not already)
cd C:\Users\123\Documents\GitHub\AI_ask_ask\Gemini\paixueji\

# Install dependencies
pip install -r requirements.txt
```

### Configuration

1. **Google Cloud Setup:**
   - Set environment variable: `GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json`
   - Update `config.json` with your project ID and location

2. **Config Files:**
   - `config.json` - Gemini model, project ID, location
   - `age_prompts.json` - Age-specific guidance (3-4, 5-6, 7-8 years)
   - `object_prompts.json` - Object categories (foods, animals, plants)

### Running the Application

```bash
# Start Flask server
python app.py

# Server starts on http://localhost:5001
# Open browser to http://localhost:5001
```

### Using the Application

1. **Fill out form:**
   - Select child's age (3-4, 5-6, or 7-8 years)
   - Enter object name (e.g., "apple", "banana", "dog")
   - Choose tone (friendly, encouraging, playful, pirate)
   - Select focus mode (system-managed or manual)

2. **Start conversation:**
   - Click "Start" to begin
   - AI asks first question about the object

3. **Answer questions:**
   - Type answers in input box
   - Press Enter or click "Send"
   - AI validates and asks follow-up questions

4. **Debug features:**
   - View session info in right-side debug panel
   - Click "Show Flow Tree" to see conversation diagram
   - Session save/restore UI removed from the web interface

### Key Files to Know

- **Main entry point:** `app.py`
- **Streaming logic:** `paixueji_stream.py`
- **Frontend:** `static/app.js`, `static/index.html`
- **Configuration:** `config.json`, `age_prompts.json`, `object_prompts.json`
- **Logs:** `logs/paixueji_YYYY-MM-DD.log` (daily rotation)

---

## Next Steps Recommendations

### Priority 1: Critical (Production-Blocking)

#### 1. Implement Session Persistence
- **Task:** Replace in-memory dict with Redis or PostgreSQL
- **Files to modify:** `app.py:23` (sessions dict)
- **Requirements:**
  - Serialize PaixuejiAssistant state to JSON
  - Add session expiration (e.g., 24 hours)
  - Implement cleanup job for expired sessions
- **Estimated complexity:** Medium
- **Dependencies:** Redis client or SQLAlchemy

#### 2. Create Test Suite
- **Task:** Add pytest with coverage for critical paths
- **Test coverage needed:**
  - Validation logic (`decide_topic_switch_with_validation`)
  - Stream chunk generation and parsing
  - Session creation/cleanup
  - API endpoints (mocked Gemini responses)
  - Focus mode transitions
- **Files to create:** `tests/`, `pytest.ini`, `conftest.py`
- **Target coverage:** 70%+ on core modules
- **Estimated complexity:** High

#### 3. Improve Error Handling
- **Task:** Add granular error handling with retry logic
- **Changes:**
  - Replace `except Exception` with specific error types
  - Add logging to all exception handlers
  - Implement circuit breaker for API failures
  - Add retry with exponential backoff
- **Files to modify:** `paixueji_stream.py`, `app.py`
- **Estimated complexity:** Medium

### Priority 2: High (Before Next Release)

#### 4. Complete Phase 4-9 Documentation
- **Task:** Write missing transition table documentation
- **Files to create:**
  - `docs/action-flow-graph/03-transition-tables/phase4-dual-parallel.md`
  - `docs/action-flow-graph/03-transition-tables/phase5-response-streaming.md`
  - `docs/action-flow-graph/03-transition-tables/phase6-question-streaming.md`
  - `docs/action-flow-graph/03-transition-tables/phase7-frontend-rendering.md`
  - `docs/action-flow-graph/03-transition-tables/phase8-system-managed-focus.md`
  - `docs/action-flow-graph/03-transition-tables/phase9-error-handling.md`
- **Estimated complexity:** Medium

#### 5. Implement Conversation History Truncation
- **Task:** Add sliding window or pagination for long conversations
- **Approaches:**
  - Keep last N messages (e.g., 50)
  - Or use token-based limit (e.g., 10k tokens)
  - Or move old messages to database
- **Files to modify:** `paixueji_assistant.py`, `app.py`
- **Estimated complexity:** Low

#### 6. Add Environment-Specific Configuration
- **Task:** Separate dev/staging/prod configs
- **Changes:**
  - Use environment variables for secrets
  - Create config templates for each environment
  - Add config validation at startup
- **Files to modify:** `config.json` 鈫?`config.template.json`, add `.env` support
- **Estimated complexity:** Low

### Priority 3: Medium (Quality Improvements)

#### 7. Refactor Large Modules
- **Task:** Break down `paixueji_stream.py` into smaller modules
- **Suggested structure:**
  - `streaming/validation.py` - Answer validation logic
  - `streaming/response_generators.py` - 5 response types
  - `streaming/question_generators.py` - Follow-up question logic
  - `streaming/focus_manager.py` - Focus mode transitions
  - `streaming/gemini_client.py` - API integration
- **Files to modify:** `paixueji_stream.py` (split into 5 modules)
- **Estimated complexity:** High

#### 8. Add Performance Monitoring
- **Task:** Implement metrics collection and alerting
- **Metrics to track:**
  - Response times (p50, p95, p99)
  - API failure rates
  - Active session count
  - Focus mode transition patterns
- **Tools:** Prometheus + Grafana or similar
- **Estimated complexity:** Medium

#### 9. Remove Silent Exception Handlers
- **Task:** Add logging to all 14 bare `pass` statements
- **Files to modify:** `app.py`, `paixueji_stream.py`
- **Changes:** Replace `pass` with `logger.error()` or specific handling
- **Estimated complexity:** Low

### Priority 4: Low (Nice to Have)

#### 10. Pin Dependency Versions
- **Task:** Update `requirements.txt` with specific versions
- **Command:** `pip freeze > requirements.txt`
- **Estimated complexity:** Trivial

#### 11. Add Pre-commit Hooks
- **Task:** Setup code quality checks
- **Hooks:** Black (formatting), flake8 (linting), mypy (type checking)
- **Files to create:** `.pre-commit-config.yaml`
- **Estimated complexity:** Low

#### 12. Create Deployment Documentation
- **Task:** Write deployment guide
- **Contents:**
  - Production setup checklist
  - Environment variable reference
  - Scaling considerations
  - Backup and recovery procedures
- **Files to create:** `DEPLOYMENT.md`
- **Estimated complexity:** Low

---

## Critical Files Reference

### Core Python Modules

| File | Lines | Purpose | Key Functions |
|------|-------|---------|---------------|
| `app.py` | 1,326 | Flask server, API endpoints, session management | `/api/start`, `/api/continue`, `async_gen_to_sync` |
| `paixueji_stream.py` | 2,877 | Async streaming, LLM integration, validation | `ask_introduction_question_stream`, `decide_topic_switch_with_validation` |
| `paixueji_assistant.py` | 343 | Gemini client wrapper, state tracking | `PaixuejiAssistant.__init__`, `classify_object` |
| `conversation_tree.py` | 249 | Debug flow tree | `ConversationFlowTree.add_node`, `generate_text_report` |
| `paixueji_prompts.py` | 183 | System prompts, templates | `get_focus_prompt`, response templates |
| `schema.py` | 163 | Pydantic models | `StreamChunk`, `CallAskAskRequest` |

### Frontend Files

| File | Lines | Purpose | Key Functions |
|------|-------|---------|---------------|
| `static/app.js` | 1,410 | SSE handling, UI rendering, state management | `startConversation`, `continueConversation` |
| `static/index.html` | - | Web interface, forms, debug panel | Form layout, chat area, focus controls |
| `static/style.css` | - | Styling and responsive design | Layout, animations, debug panel positioning |

### Configuration Files

| File | Size | Purpose | Format |
|------|------|---------|--------|
| `config.json` | 54 bytes | Google Cloud project, model config | JSON |
| `age_prompts.json` | - | Age-specific guidance (3-4, 5-6, 7-8) | JSON |
| `object_prompts.json` | - | Object categories with guidance | JSON |
| `requirements.txt` | - | Python dependencies | Text (package list) |

### Documentation

| File/Directory | Purpose |
|----------------|---------|
| `docs/action-flow-graph/` | Detailed operational documentation |
| `docs/action-flow-graph/01-action-taxonomy.md` | 56 actions categorized by type |
| `docs/action-flow-graph/02-state-models.md` | Frontend, session, streaming state models |
| `docs/action-flow-graph/03-transition-tables/` | Phase-by-phase state transitions (1-3 complete) |
| `docs/action-flow-graph/04-master-flow.mmd` | Single Mermaid diagram of all flows |
| `docs/action-flow-graph/05-completeness-checklist.md` | 51 production scenarios for debugging |
| `OPERATIONAL_ARCHITECTURE.md` | System topology, data flows, audit findings |

### Logs

| File | Format | Retention |
|------|--------|-----------|
| `logs/paixueji_YYYY-MM-DD.log` | Text (Loguru) | 30 days |

---

## Contact & Resources

**Repository Path:**
```
C:\Users\123\Documents\GitHub\AI_ask_ask\Gemini\paixueji\
```

**Git Status (as of Jan 7, 2026):**
- Branch: `main`
- Recent merge: `dual-parallel` 鈫?`main`
- Modified files: `__pycache__/*`, `static/app.js`, `static/index.html`
- Untracked: `logs/paixueji_2026-01-07.log`

**Key Resources:**
- Operational Architecture: `OPERATIONAL_ARCHITECTURE.md`
- Action Flow Graphs: `docs/action-flow-graph/README.md`
- Completeness Checklist: `docs/action-flow-graph/05-completeness-checklist.md`

---

## Conclusion

Paixueji is a well-architected educational AI assistant with comprehensive documentation and working core features. The dual-parallel architecture, conversation flow tree, and real-time streaming are all operational and tested.

The main gaps for production readiness are:
1. **Session persistence** (currently in-memory only)
2. **Test coverage** (no automated tests exist)
3. **Error handling refinement** (generic fallbacks need granularity)

With these critical items addressed, the system would be production-ready for deployment. The existing documentation provides a solid foundation for future developers to understand and extend the codebase.

**Total Codebase:** ~6,600 lines of production code + extensive documentation

---

**End of Status Report**


