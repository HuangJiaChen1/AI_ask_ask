---
name: mapping-user-state-transitions
description: Use when you already know the product surfaces and user states and need a compact state transition table with guards, UI outcomes, backend effects, and evidence.
---

# Mapping User State Transitions

## Goal

Produce section 4 of `USER_BEHAVIOR_SPEC.md` as a transition table.

## Required Columns

`current state | action | next state | guard / condition | UI result | backend effect | evidence`

## Workflow

1. Start from the surfaced states and user actions, not from implementation internals.
2. Trace the smallest evidence-backed transitions through code, tests, and flow docs.
3. Merge duplicate transitions only when they are behaviorally identical.
4. Mark any missing field as `unknown` instead of guessing.

## Rules

- One row per distinct user-observable branch.
- Guards belong in `guard / condition`, not hidden in prose.
- Backend effects must stay concrete: session created, SSE stream opened, state flag reset, request returns 404, and similar.
- If UI result and backend effect disagree across sources, keep the row and flag the conflict.
