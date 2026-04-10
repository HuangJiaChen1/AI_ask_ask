---
name: auditing-user-behavior-coverage
description: Use when the behavior foundation, transitions, and scenarios are drafted and you need coverage matrices plus an explicit list of product ambiguities, code-doc conflicts, and likely untested paths.
---

# Auditing User Behavior Coverage

## Goal

Produce sections 6-7 of `USER_BEHAVIOR_SPEC.md`: the required coverage matrices and `Known unknowns`.

## Required Matrices

- `页面 × 用户状态`
- `用户状态 × 核心行为`
- `错误类型 × 页面响应`
- `权限级别 × 可见操作`
- `是否登录 × CTA 分支`
- `feature flag × UI 差异`

## Workflow

1. Compare the drafted sections against code, tests, and adapter hints.
2. Fill every matrix, using `N/A`, `unknown`, or `not found` where needed.
3. Record unresolved conflicts, implicit branches, and missing evidence in `Known unknowns`.

## Rules

- A missing cell is a bug in the spec. Fill it explicitly.
- A conflict belongs in `Known unknowns`, not in silent compromise.
- Favor leak detection over polish: this stage exists to expose holes.
