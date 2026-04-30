# OpenSpec Integration Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install OpenSpec, create behavioral specs for the Introduction and General Chat pipelines, and build the Session Driver (Layer 1 of the simulation test harness).

**Architecture:** OpenSpec provides the directory structure and artifact schema. The Session Driver wraps Flask's test client to consume SSE streams and extract structured turn results. Behavioral specs are markdown files describing pipeline behavior at the user-experience level.

**Tech Stack:** Node.js (OpenSpec CLI), Python 3.12, Flask test client, Pydantic (StreamChunk), Pytest

---

## File Structure

```
openspec/                          # Created by `openspec init`
  config.yaml
  specs/
    pipelines/
      introduction.md              # NEW: Behavioral spec for intro pipeline
      general_chat.md              # NEW: Behavioral spec for general chat pipeline
  changes/                         # Created by `openspec init`
  explorations/                    # Created by `openspec init`

tests/
  harness/                         # NEW: Test harness package
    __init__.py
    session_driver.py              # NEW: Layer 1 — SSE session driver
  e2e_scenarios/                   # NEW: E2E scenario files
    intro_basic.yaml               # NEW: First scenario
  test_harness_session_driver.py   # NEW: Tests for the harness itself
```

---

## Task 1: Install and Initialize OpenSpec

**Files:**
- Create: `openspec/config.yaml`, `openspec/specs/` (directory), `openspec/changes/` (directory)
- Test: Run `openspec status` to verify

- [ ] **Step 1: Verify Node.js version**

Run: `node --version`
Expected: `v20.19.0` or higher. If lower, upgrade Node.js first.

- [ ] **Step 2: Install OpenSpec CLI globally**

Run: `npm install -g @fission-ai/openspec`
Expected: Installs without errors.

- [ ] **Step 3: Initialize OpenSpec in this project**

Run: `openspec init`
When prompted for tool selection, choose `claude` (Claude Code).
When prompted for profile, choose `core` (default quick path).

Expected: Creates `openspec/config.yaml`, `openspec/specs/`, `openspec/changes/`, `.claude/skills/openspec-*`.

- [ ] **Step 4: Verify the directory structure**

Run: `ls -la openspec/ && echo "---" && cat openspec/config.yaml`
Expected: Shows `config.yaml`, `specs/`, `changes/`, `explorations/` directories.

- [ ] **Step 5: Remove auto-generated .claude skills (we use superpowers instead)**

Run: `rm -rf .claude/skills/openspec-*`
Expected: `.claude/skills/` no longer contains OpenSpec-generated skills.

- [ ] **Step 6: Commit**

```bash
git add openspec/ .claude/skills/
git commit -m "chore: initialize OpenSpec project structure

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Create Behavioral Spec for Introduction Pipeline

**Files:**
- Create: `openspec/specs/pipelines/introduction.md`

- [ ] **Step 1: Create the pipelines directory**

Run: `mkdir -p openspec/specs/pipelines`

- [ ] **Step 2: Write the introduction spec**

Create `openspec/specs/pipelines/introduction.md`:

```markdown
# Introduction Pipeline

## Description
The entry point for every conversation. The AI greets the child with a warm
opening about the object, then asks one easy, concrete question.

## Trigger
User calls `POST /api/start` with an object name.

## Entry Conditions
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| object_name | string | Yes | The object to discuss (e.g., "apple", "cat") |
| age | integer | Yes | Child's age, 3-8 |
| attribute_pipeline_enabled | boolean | No | If true, skip to Attribute Activity intro |
| category_pipeline_enabled | boolean | No | If true, skip to Category Activity intro |

## Flow

### Step 1: Object Resolution
The system resolves `object_name` against the knowledge base:
- **Supported anchor**: Object exists in KB → use grounded facts
- **Mapped anchor** (high confidence): Surface object maps to supported anchor → bridge mode
- **Mapped anchor** (medium confidence): Surface object maps to anchor → confirmation mode
- **Unknown/unresolved**: Object not in KB → generic safe intro

### Step 2: Fun Fact Generation (if supported)
If the object is supported and grounded facts are available:
- Fetch 3-5 cached fun facts
- Randomly select one
- Apply 4-layer safety filtering (Gemini built-in + strict settings + is_safe_for_kids + streaming safety)
- On any error, gracefully fall back to non-grounded intro

### Step 3: Intro Generation
The AI produces a response with exactly 4 "beats":

1. **Excited reaction**: 1 sentence of warm enthusiasm
2. **Object confirmation**: 1 sentence confirming/identifying the object
3. **Optional sensory detail**: 1 concrete sensory observation (only if grounded)
4. **Opening question**: 1 easy, directly answerable question

### Step 4: Follow-up Question
A separate follow-up question is generated that:
- Grows naturally from the intro content
- Is concrete (not a knowledge test like "What color is it?")
- Is appropriate for the child's age

## Output Format

```json
{
  "response_type": "introduction",
  "selected_hook_type": "<hook_name>",
  "question_style": "open_ended" | "concrete",
  "session_id": "<uuid>",
  "finish": true
}
```

## Behavioral Rules

- The intro MUST NOT ask a quiz-style question ("What color is the apple?")
- The intro MUST be warm and encouraging, never clinical or dry
- If the object is unknown, the intro stays generic: "That sounds interesting! Tell me more about it."
- The `fun_fact` field is populated only when grounded facts are used
- `selected_hook_type` determines the conversational style for the entire session

## Transitions To
Whatever pipeline is active on the next `POST /api/continue` call:
- `attribute_lane_active=true` → Attribute Activity Pipeline
- `category_lane_active=true` → Category Activity Pipeline
- `bridge_phase=pre_anchor` → Bridge Pre-Anchor Pipeline
- None of the above → General Chat Pipeline

## Error Handling
- Object resolution failure → generic intro (non-blocking)
- Fun fact generation failure → intro without grounded facts (non-blocking)
- LLM API failure → SSE error event with `error_type: "llm_error"`
```

- [ ] **Step 3: Verify the spec renders correctly**

Run: `cat openspec/specs/pipelines/introduction.md | head -20`
Expected: No syntax errors, markdown renders properly.

- [ ] **Step 4: Commit**

```bash
git add openspec/specs/pipelines/introduction.md
git commit -m "docs: add behavioral spec for introduction pipeline

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Create Behavioral Spec for General Chat Pipeline

**Files:**
- Create: `openspec/specs/pipelines/general_chat.md`

- [ ] **Step 1: Write the general chat spec**

Create `openspec/specs/pipelines/general_chat.md`:

```markdown
# General Chat Pipeline

## Description
The default conversation path. The AI classifies the child's reply into one of
13 communicative intents, generates an appropriate response, and asks a follow-up
question.

## Trigger
Child sends a reply via `POST /api/continue` when no special lane is active.

## Flow

```
START --> analyze_input --> [route] --> (intent node) --> generate_question --> finalize --> END
```

## Nodes

### analyze_input
**Type:** Classifier (silent — no user-visible output)

**Inputs:**
- `child_answer`: The child's reply text
- `last_model_response`: The AI's previous full message
- `object_name`: Current conversation object
- `conversation_history`: Full message history

**Behavior:**
Classifies the child's reply into exactly one of 13 intents:

| Intent | Child's Behavior | Example |
|--------|-----------------|---------|
| CORRECT_ANSWER | Directly answered the previous question | "It's red" |
| INFORMATIVE | Shared unprompted knowledge | "Lions live in Africa" |
| CURIOSITY | Asked why/how/what | "Why is the sky blue?" |
| CLARIFYING_IDK | First "I don't know" | "I don't know" |
| GIVE_ANSWER_IDK | Second+ IDK or wrong answer | "I don't know" (again) |
| CLARIFYING_WRONG | Tried but was incorrect | "It's blue" (when it's red) |
| CLARIFYING_CONSTRAINT | "I don't have one" / "I've never seen one" | "I don't have a dog" |
| PLAY | Being silly or imaginative | "The apple can fly!" |
| EMOTIONAL | Expressed a feeling | "I'm scared of lions" |
| AVOIDANCE | Wants to stop or change topic | "I don't want to talk about this" |
| BOUNDARY | Asking about rules/safety | "Can I eat the whole thing?" |
| ACTION | Command or request | "Tell me a joke", "Repeat that" |
| SOCIAL | Asking about the AI | "How old are you?" |
| SOCIAL_ACKNOWLEDGMENT | Brief reaction | "wow", "cool" |
| CONCEPT_CONFUSION | Misunderstanding a concept | "What's a feline?" |
| FALLBACK_FREEFORM | Classifier failed or ambiguous | (anything unclear) |

**Outputs:**
- `intent_type`: The classified intent
- `new_object_name`: If child mentioned a new object (ACTION/AVOIDANCE only)
- `classification_status`: "success" | "fallback" | "error"
- `classification_failure_reason`: Error description (if error)

**Routing Rules:**
- `intent_type == CLARIFYING_IDK` AND `consecutive_struggle_count >= 2` → route to GIVE_ANSWER_IDK
- `intent_type == CORRECT_ANSWER` AND `correct_answer_count + 1 >= 2` AND `learning_anchor_active` → route to CLASSIFY_THEME first, then CORRECT_ANSWER
- All other intents → route directly to intent node

---

### Intent Nodes (Response Generators)

Each intent node produces a response with 2-3 beats, then a follow-up question
is generated separately.

**Common structure for most nodes:**
1. **Primary beat**: Direct response to the child's intent (answer, confirmation, empathy, etc.)
2. **Wow fact** (optional): One surprising related fact from KB
3. **Follow-up question**: Generated by `generate_question` node

**Key behavioral rules across all nodes:**
- Never echo the child's exact words verbatim as celebration
- Never use "Did you know...?" — state facts as direct sentences
- Never ask "How did you know that?"
- The follow-up question MUST grow from the last assistant message
- The follow-up question MUST be concrete and directly answerable

---

### generate_question
**Type:** Question generator (user-visible)

**Behavior:**
Generates a single follow-up question based on:
- The intent node's response
- The conversation history
- The current object and its attributes
- The `question_style` (open_ended or concrete)

**Rules:**
- Must be one sentence
- Must not repeat any phrase from the previous assistant message
- Must be appropriate for the child's age
- Must be directly answerable (not a knowledge test)

---

### finalize
**Type:** Assembler (silent — sends metadata)

**Behavior:**
Concatenates the intent response and follow-up question into `full_response_text`.
Sends the final SSE chunk with `finish=true` and all metadata fields.

## Output Format

```json
{
  "response_type": "<intent_type>",
  "intent_type": "<intent>",
  "full_response_text": "<response + question>",
  "correct_answer_count": 0,
  "nodes_executed": ["analyze_input", "<intent_node>", "generate_question", "finalize"],
  "finish": true
}
```

## State Transitions

| Condition | Next Turn Behavior |
|-----------|-------------------|
| `new_object_name` is set | Topic switch to new object |
| `conversation_complete=true` | Session ends |
| `is_stuck=true` | Topic suggestions offered |
| Default | Continue in General Chat Pipeline |

## Error Handling
- Intent classification failure → FALLBACK_FREEFORM node (graceful degradation)
- LLM API failure during response generation → SSE error event
- Question generation failure → Response without follow-up question (rare, non-blocking)
```

- [ ] **Step 2: Verify the spec renders correctly**

Run: `cat openspec/specs/pipelines/general_chat.md | head -20`
Expected: No syntax errors, markdown renders properly.

- [ ] **Step 3: Commit**

```bash
git add openspec/specs/pipelines/general_chat.md
git commit -m "docs: add behavioral spec for general chat pipeline

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Build Session Driver (Layer 1)

**Files:**
- Create: `tests/harness/__init__.py`, `tests/harness/session_driver.py`
- Create: `tests/test_harness_session_driver.py`
- Test: Uses existing `tests/conftest.py` fixtures (`client`, `app`, `mock_gemini_client`)

**Context:** The Session Driver wraps Flask's `app.test_client()` to drive conversation
turns through the actual HTTP API. It consumes SSE streams, concatenates chunks,
and extracts metadata from the final `finish=true` chunk.

The existing `tests/test_api_flow.py` has a `parse_sse()` function that we reuse.
The `StreamChunk` schema is in `schema.py` and has these key fields:
- `response`: text chunk
- `finish`: boolean (true for final chunk)
- `session_id`: UUID string
- `intent_type`, `response_type`, `nodes_executed`: metadata
- `correct_answer_count`, `is_stuck`, `conversation_complete`: state

- [ ] **Step 1: Create the harness package directory**

Run: `mkdir -p tests/harness && touch tests/harness/__init__.py`

- [ ] **Step 2: Write the failing test for TurnResult**

Create `tests/test_harness_session_driver.py`:

```python
import pytest
from tests.harness.session_driver import TurnResult


def test_turn_result_dataclass_exists():
    """TurnResult dataclass should be importable and instantiable."""
    result = TurnResult(
        session_id="test-session-123",
        full_response_text="Hello!",
        final_chunk={"finish": True},
        all_chunks=[{"finish": True}],
        events=[{"event": "complete", "data": {}}],
        transcript_entry={"role": "assistant", "text": "Hello!"},
        duration_ms=1500,
        error=None,
    )
    assert result.session_id == "test-session-123"
    assert result.full_response_text == "Hello!"
    assert result.error is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_harness_session_driver.py::test_turn_result_dataclass_exists -v`
Expected: FAIL with `ImportError: cannot import name 'TurnResult'`

- [ ] **Step 4: Write the TurnResult dataclass**

Create `tests/harness/session_driver.py`:

```python
"""Session Driver — Layer 1 of the E2E simulation test harness.

Wraps Flask's test client to drive conversation turns through the HTTP API,
consume SSE streams, and extract structured results.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TurnResult:
    """Structured result from a single conversation turn."""

    session_id: str
    full_response_text: str
    final_chunk: dict[str, Any]
    all_chunks: list[dict[str, Any]]
    events: list[dict[str, Any]]
    transcript_entry: dict[str, Any]
    duration_ms: int
    error: Optional[str] = None


def _parse_sse(response_data: bytes) -> list[dict[str, Any]]:
    """Parse SSE response bytes into a list of event/data dicts.

    Mirrors the parsing logic in tests/test_api_flow.py.
    """
    events = []
    text = response_data.decode("utf-8")
    blocks = text.split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
        lines = block.split("\n")
        event_type = None
        data = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:].strip())
                except json.JSONDecodeError:
                    data = line[6:].strip()
        if event_type:
            events.append({"event": event_type, "data": data})
    return events
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_harness_session_driver.py::test_turn_result_dataclass_exists -v`
Expected: PASS

- [ ] **Step 6: Write the failing test for SessionDriver.start()**

Append to `tests/test_harness_session_driver.py`:

```python
from tests.harness.session_driver import SessionDriver


def test_session_driver_start_returns_turn_result(client):
    """SessionDriver.start() should return a TurnResult with session_id set."""
    driver = SessionDriver(client)
    result = driver.start({
        "age": 6,
        "object_name": "apple",
    })
    assert isinstance(result, TurnResult)
    assert result.session_id is not None
    assert len(result.session_id) > 0
    assert result.error is None
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `pytest tests/test_harness_session_driver.py::test_session_driver_start_returns_turn_result -v`
Expected: FAIL with `ImportError: cannot import name 'SessionDriver'`

- [ ] **Step 8: Write the SessionDriver class with start() method**

Append to `tests/harness/session_driver.py`:

```python
class SessionDriver:
    """Drive conversation turns through the Flask HTTP API.

    Usage:
        driver = SessionDriver(app.test_client())
        result = driver.start({"age": 6, "object_name": "apple"})
        result2 = driver.continue_turn(result.session_id, "It is red")
    """

    def __init__(self, flask_client: Any) -> None:
        self.client = flask_client

    def start(self, payload: dict[str, Any]) -> TurnResult:
        """Start a new conversation.

        Args:
            payload: POST /api/start JSON body (age, object_name, etc.)

        Returns:
            TurnResult with session_id, full_response_text, and metadata.
        """
        import time

        start_time = time.time()
        response = self.client.post("/api/start", json=payload)

        if response.status_code != 200:
            duration_ms = int((time.time() - start_time) * 1000)
            return TurnResult(
                session_id="",
                full_response_text="",
                final_chunk={},
                all_chunks=[],
                events=[],
                transcript_entry={},
                duration_ms=duration_ms,
                error=f"HTTP {response.status_code}: {response.data.decode('utf-8')}",
            )

        events = _parse_sse(response.data)
        return self._build_turn_result(events, start_time)

    def _build_turn_result(
        self,
        events: list[dict[str, Any]],
        start_time: float,
        session_id_hint: Optional[str] = None,
    ) -> TurnResult:
        """Build a TurnResult from parsed SSE events."""
        import time

        duration_ms = int((time.time() - start_time) * 1000)

        chunks = [e["data"] for e in events if e["event"] == "chunk" and e["data"] is not None]
        full_text = "".join(
            str(c.get("response", "")) for c in chunks
        )

        final_chunk = {}
        for c in chunks:
            if c.get("finish"):
                final_chunk = c
                break

        # If no finish chunk found, use the last chunk as best effort
        if not final_chunk and chunks:
            final_chunk = chunks[-1]

        session_id = session_id_hint or ""
        if final_chunk:
            session_id = final_chunk.get("session_id", session_id)
        if not session_id and chunks:
            session_id = chunks[0].get("session_id", "")

        # Validate stream completed gracefully
        has_complete = any(e["event"] == "complete" for e in events)
        has_error = any(e["event"] == "error" for e in events)
        error = None
        if has_error:
            error_event = next(e for e in events if e["event"] == "error")
            error_data = error_event.get("data", {})
            error = error_data.get("user_message", str(error_data))
        elif not has_complete and not final_chunk.get("finish"):
            error = "Stream ended without complete or finish event"

        transcript_entry = {
            "role": "assistant",
            "text": full_text,
            "metadata": {
                "intent_type": final_chunk.get("intent_type"),
                "response_type": final_chunk.get("response_type"),
                "nodes_executed": final_chunk.get("nodes_executed", []),
            },
        }

        return TurnResult(
            session_id=session_id,
            full_response_text=full_text,
            final_chunk=final_chunk,
            all_chunks=chunks,
            events=events,
            transcript_entry=transcript_entry,
            duration_ms=duration_ms,
            error=error,
        )
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `pytest tests/test_harness_session_driver.py::test_session_driver_start_returns_turn_result -v`
Expected: PASS

- [ ] **Step 10: Write the failing test for SessionDriver.continue_turn()**

Append to `tests/test_harness_session_driver.py`:

```python
def test_session_driver_continue_turn_returns_turn_result(client):
    """SessionDriver.continue_turn() should return a TurnResult."""
    driver = SessionDriver(client)

    # Start a conversation first
    start_result = driver.start({
        "age": 6,
        "object_name": "apple",
    })
    assert start_result.error is None
    session_id = start_result.session_id

    # Continue the conversation
    continue_result = driver.continue_turn(session_id, "It is red")
    assert isinstance(continue_result, TurnResult)
    assert continue_result.session_id == session_id
    assert continue_result.error is None
    assert len(continue_result.full_response_text) > 0
```

- [ ] **Step 11: Run the test to verify it fails**

Run: `pytest tests/test_harness_session_driver.py::test_session_driver_continue_turn_returns_turn_result -v`
Expected: FAIL with `AttributeError: 'SessionDriver' object has no attribute 'continue_turn'`

- [ ] **Step 12: Write the continue_turn() method**

Append to `tests/harness/session_driver.py` inside the `SessionDriver` class
(after the `start` method, before `_build_turn_result`):

```python
    def continue_turn(self, session_id: str, child_input: str) -> TurnResult:
        """Continue an existing conversation.

        Args:
            session_id: The session ID from a previous turn.
            child_input: The child's reply text.

        Returns:
            TurnResult with the assistant's response and metadata.
        """
        import time

        start_time = time.time()
        payload = {
            "session_id": session_id,
            "child_input": child_input,
        }
        response = self.client.post("/api/continue", json=payload)

        if response.status_code != 200:
            duration_ms = int((time.time() - start_time) * 1000)
            return TurnResult(
                session_id=session_id,
                full_response_text="",
                final_chunk={},
                all_chunks=[],
                events=[],
                transcript_entry={},
                duration_ms=duration_ms,
                error=f"HTTP {response.status_code}: {response.data.decode('utf-8')}",
            )

        events = _parse_sse(response.data)
        return self._build_turn_result(events, start_time, session_id_hint=session_id)
```

- [ ] **Step 13: Run all harness tests to verify everything passes**

Run: `pytest tests/test_harness_session_driver.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 14: Commit**

```bash
git add tests/harness/ tests/test_harness_session_driver.py
git commit -m "feat: add Session Driver (Layer 1 of E2E test harness)

- TurnResult dataclass for structured turn output
- SessionDriver wrapping Flask test client
- SSE parsing, chunk concatenation, metadata extraction
- Error detection for incomplete streams

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Create First E2E Scenario

**Files:**
- Create: `tests/e2e_scenarios/intro_basic.yaml`

- [ ] **Step 1: Create the e2e scenarios directory**

Run: `mkdir -p tests/e2e_scenarios`

- [ ] **Step 2: Write the first scenario**

Create `tests/e2e_scenarios/intro_basic.yaml`:

```yaml
scenario: Basic introduction flow for a known object
given:
  age: 6
  object_name: "apple"
when:
  - action: start_conversation
    payload:
      age: 6
      object_name: "apple"
then:
  - assertion: stream_completed
  - assertion: response_not_empty
  - assertion: session_id_present
  - assertion: no_error_events
```

- [ ] **Step 3: Verify YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('tests/e2e_scenarios/intro_basic.yaml'))"`
Expected: No output (no errors).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e_scenarios/intro_basic.yaml
git commit -m "test: add first e2e scenario (basic introduction)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Plan Task | Status |
|--------------|-----------|--------|
| Install OpenSpec CLI | Task 1 | Covered |
| Initialize OpenSpec project | Task 1 | Covered |
| Behavioral spec for Introduction | Task 2 | Covered |
| Behavioral spec for General Chat | Task 3 | Covered |
| Session Driver (Layer 1) | Task 4 | Covered |
| E2E scenario format | Task 5 | Covered |

### 2. Placeholder Scan

- No "TBD", "TODO", or "implement later" found.
- No vague directives like "add appropriate error handling".
- All code blocks contain complete, runnable code.
- All file paths are exact.

### 3. Type Consistency

- `TurnResult` fields match usage in tests: `session_id` (str), `full_response_text` (str), `final_chunk` (dict), `error` (Optional[str]).
- `SessionDriver.start()` takes `dict[str, Any]` and returns `TurnResult`.
- `SessionDriver.continue_turn()` takes `str, str` and returns `TurnResult`.
- `_parse_sse()` signature matches the existing `parse_sse()` in `test_api_flow.py`.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-30-openspec-integration-phase1.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
