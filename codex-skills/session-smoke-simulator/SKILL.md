---
name: session-smoke-simulator
description: Convert Paixueji PR manual-smoke and live-session notes into deterministic verification. Use when working in this Paixueji repository and a PR note asks for manual testing of multi-turn chat behavior, IDK or wrong-answer flows, session-state transitions, SSE API flows, or other live-session checks. Reuse `tests/` and `tests/integration_scenarios/` when possible, and extend repo-specific coverage instead of asking the human to test manually.
---

# Session Smoke Simulator

## Overview

Turn Paixueji manual-smoke notes into deterministic verification that can gate a PR. Prefer existing tests and integration scenarios first; when they do not cover the required behavior, extend the repository's own coverage rather than falling back to human testing.

Read `references/repo-map.md` before touching unfamiliar parts of the app. Read `references/manual-smoke-patterns.md` when translating PR notes into assertions or choosing between extending an existing scenario and adding a new one.

## Workflow

1. Copy the exact manual-smoke note from the PR.
2. Normalize it into:
   - setup and entry point
   - ordered child/user inputs
   - expected response or state transition
   - verification surface such as API response, streamed text, session state, or scenario output
3. Search existing coverage in:
   - `tests/`
   - `tests/integration_scenarios/`
   - any nearby regression tests for the touched behavior
4. If an existing deterministic test already covers the note, run it and report the result.
5. If no existing deterministic test covers the note, extend the closest existing test or scenario.
6. Run the new or updated deterministic coverage plus nearby regressions.
7. Return a concise pass/fail result that the orchestrator skill can treat as a merge gate.

## Repository Rules

- Do not ask the human to run a manual smoke test.
- Do not treat "manual smoke" as optional.
- Prefer extending existing Paixueji tests over inventing a separate harness.
- Keep new coverage close to the current repo structure and naming patterns.
- If a change touches shared `stream/` or prompt/session code, verify both shared-core paths described in `CLAUDE.md`.

## Choosing the Verification Surface

Prefer the narrowest deterministic surface that proves the PR note:

1. existing unit or focused pytest case
2. existing integration scenario runner under `tests/integration_scenarios/`
3. a new deterministic scenario in the same area as the current coverage

Avoid browser-only or human-observed checks unless there is no narrower deterministic surface, and if there is no narrower surface, create one.

## Translating PR Notes

When a note says something like:

`Manual smoke: simulate IDK -> wrong -> IDK in a live session and confirm 3rd response reveals the answer`

translate it into:

- entry point: the existing start/continue session flow
- turn sequence: `IDK`, `wrong`, `IDK`
- expected outcome: the third assistant response reveals the answer instead of repeating another hint
- likely coverage target: the closest existing IDK escalation or live-session scenario test

Use existing scenario files as anchors before adding new files.

## Reporting

Always return:

- the PR note being verified
- the test or scenario file used
- whether coverage was reused or extended
- the exact pass/fail outcome
- any follow-up required before merge
