# Manual Smoke Translation Patterns

## Translation Template

Rewrite each PR note into four fields:

- setup: request path, fixtures, or existing scenario entry point
- turn sequence: exact child/user messages in order
- oracle: what must be true at the end
- surface: which test or scenario can observe the oracle

## Preferred Mapping Order

1. nearest existing pytest assertion
2. nearest existing file under `tests/integration_scenarios/`
3. new deterministic scenario added alongside related coverage

## Common Paixueji Patterns

### IDK Escalation

Signals:

- `IDK`
- `I don't know`
- repeated confusion

Look first at:

- `tests/test_fix_verification.py`
- `tests/integration_scenarios/fix4_two_idk_turns.py`
- `tests/integration_scenarios/run_all_real.py`

### Wrong-Answer Correction

Signals:

- wrong guess followed by hint or correction
- confirm direct answer appears after repeated failure

Look first at:

- `tests/test_api_flow.py`
- `tests/test_guide_flow.py`
- nearby files that mention `CLARIFYING_WRONG` or `GIVE_ANSWER_IDK`

### Live Session / Multi-Turn Flow

Signals:

- `live session`
- `3rd response`
- conversation order matters

Prefer:

- API flow tests when the behavior is deterministic at the route/session layer
- integration scenarios when order and streamed behavior are central

## Example

PR note:

`Manual smoke: simulate IDK -> wrong -> IDK in a live session and confirm 3rd response reveals the answer`

Translation:

- setup: session start plus existing IDK-capable assistant state
- turn sequence: `I don't know`, wrong answer, `I don't know`
- oracle: the third assistant response should reveal the answer directly
- surface: extend existing IDK scenario coverage if no current test captures the wrong-answer middle turn

## Hard Rule

If no deterministic coverage exists yet, add it. Do not ask the human to perform the scenario manually.
