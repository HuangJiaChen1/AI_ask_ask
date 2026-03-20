# Paixueji Repo Map

## Core Runtime Files

- `paixueji_app.py`: Flask entry point and API routes such as session start and continue
- `paixueji_assistant.py`: session state and assistant behavior, including counters like consecutive IDK handling
- `graph.py`: shared LangGraph workflow
- `stream/`: shared generation, validation, question, and helper logic used across chat and critique paths

## Important Shared-Core Risk

`CLAUDE.md` says changes in shared `stream/`, prompts, schema, or session logic can break both the live chat path and the critique system. If a PR touches shared code, run verification that protects both sides, not just the conversational path that the manual note mentions.

## Existing Verification Surfaces

- `tests/test_all_endpoints.py`: endpoint-focused regression coverage
- `tests/test_api_flow.py`: API and flow behavior
- `tests/test_guide_flow.py`: guide-mode and multi-step flow coverage
- `tests/test_fix_verification.py`: focused behavior checks including IDK escalation
- `tests/integration_scenarios/run_all_real.py`: real-LLM scenario runner
- `tests/integration_scenarios/fix4_two_idk_turns.py`: concrete multi-turn IDK scenario

## Use This Reference For

- finding the right starting point for a PR-note scenario
- deciding whether a note maps to unit tests, API flow tests, or integration scenarios
- spotting when a "manual smoke" note is really about shared-core behavior
