# Paixueji — Claude Code Context

## Commands

| Action | Command |
|:---|:---|
| Run app | `python paixueji_app.py` → http://localhost:5001 |
| Run all tests | `pytest` |
| Run one test file | `pytest tests/test_guide_flow.py` |
| Run one test function | `pytest tests/test_api_flow.py::test_function_name` |
| Install deps | `pip install -r requirements.txt` |
| Auth | `export GOOGLE_APPLICATION_CREDENTIALS="path/to/credentials.json"` |

---

## ⚠️ Critical Consistency Rule

**This codebase contains two separate systems that share a common core (`stream/`).
A change in any shared component must be verified against BOTH systems before committing.**

| Shared component | Used by Chat | Used by Critique |
|:---|:---:|:---:|
| `stream/` module (all files) | ✓ | ✓ |
| `paixueji_prompts.py` | ✓ | ✓ |
| `schema.py` (`StreamChunk`) | ✓ | ✓ |
| `stream/utils.py` | ✓ | ✓ |
| `paixueji_assistant.py` session state | ✓ | ✓ |

Changing a generator signature, a `StreamChunk` field, a prompt template, or a utility function
in `stream/` can silently break the critique pipeline even if the live chat still works.
Always test both paths.

---

## Architecture: Two Systems, One Codebase

### Chat System (real-time)
```
Flask API (/api/start, /api/continue)
  → async_gen_to_sync() bridge (paixueji_app.py)
  → LangGraph workflow (graph.py)
  → stream/ generators
  → Gemini API (Vertex AI)
  → SSE chunks → browser
```

### Critique System (post-hoc, offline)
```
/api/critique endpoint
  → background thread (paixueji_app.py)
  → tests/quality/pipeline.py
  → stream/ generators + paixueji_prompts.py
  → Gemini API
  → report saved to reports/
```

Both systems are driven by the same `stream/` functions, `schema.py` types, and prompt strings.

---

## The `stream/` Module (Shared Core)

All public functions are re-exported via `stream/__init__.py`. Files:

| File | Responsibility |
|:---|:---|
| `response_generators.py` | 6 async generators: feedback, correction, explanation, topic-switch, etc. |
| `question_generators.py` | 3 async generators: introduction, follow-up, completion |
| `validation.py` | `decide_topic_switch_with_validation()` — engagement + correctness + switch decision |
| `focus_mode.py` | DEPTH mode state machine |
| `fun_fact.py` | Two-step grounded fact generation (grounding → structuring) |
| `utils.py` | Message cleaning, format conversion, `extract_previous_question()` |

---

## LangGraph Workflow (`graph.py`)

- **State:** `PaixuejiState` TypedDict (~30 fields) — the single shared state object across all nodes.
- **Tracing:** 13 async nodes decorated with `@trace_node`, which captures execution time and state diffs into `nodes_executed`.

**Chat-mode node path:**
```
analyze_input → route_logic → generate_response → generate_question → finalize
```

**Completion path:**
```
correct_answer threshold → classify_theme → chat_complete → finalize
```

Conditional edges branch on `response_type`, `intent_type`, and the correct-answer threshold.

---

## Runtime-Overridable Behaviour (Self-Evolution)

The app reads these JSON files on every request — no restart required:

| File | Overrides |
|:---|:---|
| `prompt_overrides.json` | `INPUT_ANALYZER_RULES`, `THEME_NAVIGATOR_RULES` in `paixueji_prompts.py` |
| `router_overrides.json` | Data-driven routing decisions |

---

## Config Files

| File | Purpose |
|:---|:---|
| `config.json` | Model names, GCP project/location, temperature, max_tokens |
| `age_prompts.json` | Age-band language guidance (3-4, 5-6, 7-8 years) |
| `object_prompts.json` | 3-level category taxonomy |
| `themes.json` | IB PYP theme definitions |

---

## Session & Async Model

- Sessions are stored **in-memory** in the `sessions` dict (`paixueji_app.py`). All session data is lost on restart.
- Flask (sync) bridges to async LangGraph via `async_gen_to_sync()` in `paixueji_app.py`.
- Responses stream to the browser via SSE; the client listens for `chunk` events.

---

## Tests

- `tests/conftest.py` mocks the Gemini client — all tests run **offline**.
- Test files: `test_all_endpoints.py`, `test_api_flow.py`, `test_guide_flow.py`.
- Quality/critique tests live in `tests/quality/`.

See also: `OPERATIONAL_ARCHITECTURE.md` for system topology and known issues (leaks, orphan threads).
