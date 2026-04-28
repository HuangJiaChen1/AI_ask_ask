---
name: discovering-user-behavior-foundation
description: Use when establishing the scope, user surfaces, and user states for an existing product before mapping detailed transitions or scenarios.
---

# Discovering User Behavior Foundation

## Goal

Produce the structured inputs for sections 1-3 of `USER_BEHAVIOR_SPEC.md`: `Scope`, `User surfaces`, and `User states`.

## Workflow

1. Read adapter hints first when available.
2. Search entrypoints, routes, visible controls, tests, and flow docs.
3. Separate what is implemented now from internal-only or unreleased behavior.
4. Output only:
   - `scope_includes`
   - `scope_excludes`
   - `surfaces[]` with `name` and `evidence`
   - `states[]` with `name`, `entry_condition`, `exit_condition`, and `evidence`
   - `unknowns[]`

## Rules

- Surfaces are entry surfaces, not detailed step lists.
- States are user-visible or permission-relevant states, not low-level transport internals.
- If a candidate surface or state cannot be evidenced, put it in `unknowns[]` instead of promoting it.
