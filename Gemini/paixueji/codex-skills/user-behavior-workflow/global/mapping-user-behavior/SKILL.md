---
name: mapping-user-behavior
description: Use when you need a compact, evidence-backed USER_BEHAVIOR_SPEC.md for an existing product, including user surfaces, user states, transition tables, scenario catalogs, coverage matrices, and known unknowns instead of long prose.
---

# Mapping User Behavior

## Overview

Generate a compact `USER_BEHAVIOR_SPEC.md` with a fixed 7-section structure. Prefer tables and explicit evidence over prose. Unknowns stay unknown.

Read `codex-skills/user-behavior-workflow/references/spec-template.md` before writing the final document. If `codex-skills/user-behavior-adapter/manifest.yaml` exists, use it first.

## Workflow

1. Discover adapter hints, output path, exclusions, and primary evidence sources.
2. Default to a full-product baseline unless the user explicitly narrows scope.
3. Use the child skills in this order:
   - `discovering-user-behavior-foundation`
   - `mapping-user-state-transitions`
   - `cataloging-user-behavior-scenarios`
   - `auditing-user-behavior-coverage`
4. If the platform supports subagents, use a fresh subagent for each child skill and pass only the compressed output forward. If subagents are unavailable, run the same stages sequentially in the current agent.
5. Merge the stage outputs into `USER_BEHAVIOR_SPEC.md` in the fixed section order.
6. Return only a short summary plus the highest-signal `Known unknowns`.

## Rules

- Do not emit a long essay.
- Do not change the 7-section order.
- Do not skip a coverage matrix; use `N/A`, `unknown`, or `not found` when evidence is missing.
- Treat code and tests as current-behavior evidence.
- Treat docs as intent evidence.
- If sources conflict, preserve the conflict and surface it in `Known unknowns`.
