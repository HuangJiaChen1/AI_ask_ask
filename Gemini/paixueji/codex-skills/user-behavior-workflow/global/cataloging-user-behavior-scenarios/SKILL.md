---
name: cataloging-user-behavior-scenarios
description: Use when you have the product transition map and need a scenario catalog with stable IDs, expected UI and backend behavior, edge cases, analytics notes, and open questions.
---

# Cataloging User Behavior Scenarios

## Goal

Produce section 5 of `USER_BEHAVIOR_SPEC.md` as a scenario catalog.

## Workflow

1. Expand each transition or meaningful branch into one or more scenario records.
2. Assign stable IDs using domain-style prefixes such as `AUTH`, `CHAT`, `STATE`, `ERROR`, or a repo-specific equivalent.
3. Keep each scenario minimal but complete.

## Required Fields

- `trigger`
- `preconditions`
- `steps`
- `expected UI`
- `expected backend behavior`
- `analytics event`
- `edge cases`
- `open questions`

## Rules

- If analytics evidence is absent, write `not found`.
- If a branch is only partially evidenced, keep the scenario and note the gap in `open questions`.
- Reuse the exact behavior implied by the transition rows; do not invent extra branches here.
