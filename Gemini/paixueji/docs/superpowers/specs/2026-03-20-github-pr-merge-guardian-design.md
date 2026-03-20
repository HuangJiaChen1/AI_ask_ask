# Design: GitHub PR Merge Guardian and Session Smoke Simulator

**Date:** 2026-03-20
**Status:** Approved

## Goal

Create a strict PR-processing workflow that reads GitHub PRs oldest-first, stops on the first blocked or failing PR, rebases the PR branch onto `main`, runs local verification, converts PR-note manual-smoke checks into deterministic simulator coverage when needed, and merges only after all gates pass.

## Skill Layout

Two skills will be created:

- Global skill: `github-pr-merge-guardian`
- Project-local skill: `session-smoke-simulator`

The global skill owns PR orchestration and merge policy. The project-local skill owns repo-specific translation of manual-smoke notes into executable session simulations.

## GitHub PR Merge Guardian Responsibilities

The global skill will:

- List open GitHub PRs oldest-first
- Select only the oldest open PR in a run
- Read PR body, comments, review state, mergeability, and required checks
- Stop immediately if approval or required checks are missing
- Check out the PR branch locally
- Rebase the PR branch onto `main`
- Run local repository verification
- Extract verification notes and manual-smoke instructions from PR context
- Invoke the project-local simulator skill when manual-smoke validation is required
- Merge the PR with a rebase merge only after all gates pass

## Session Smoke Simulator Responsibilities

The project-local skill will be intentionally overfit to this repository. It will:

- Parse PR notes that describe live-session or manual-smoke expectations
- Normalize each note into a deterministic scenario definition with setup, child inputs, and expected system behavior
- Search existing repo coverage first, especially `tests/` and `tests/integration_scenarios/`
- Reuse matching deterministic scenarios when they already exist
- Extend or create simulator coverage when no matching scenario exists
- Run the relevant scenario and nearby regression tests
- Return a clear pass/fail result to the orchestrator skill

## Execution Flow

1. Use `gh` to fetch open PRs and sort by age ascending.
2. Select the oldest open PR.
3. Read full PR context from GitHub.
4. Enforce GitHub approval and green required checks before any merge attempt.
5. Check out the PR branch and rebase it onto `main`.
6. Run repository-local verification commands.
7. Parse PR notes for manual-smoke or special verification requirements.
8. If a manual-smoke requirement exists, run the local simulator skill.
9. If no deterministic simulator exists yet for that note, extend the simulator first and then run it.
10. Merge with a rebase merge only if GitHub gates, local verification, and simulator checks all pass.
11. Stop after handling that PR, regardless of pass or fail.

## Repository-Specific Constraints

The simulator skill should assume this repository's current structure and verification patterns, including:

- Flask-based app flow in `paixueji_app.py`
- Session logic in `paixueji_assistant.py`
- Shared core logic in `stream/`
- Offline pytest coverage in `tests/`
- Existing real-session style scenarios in `tests/integration_scenarios/`

When a PR touches shared components called out in `CLAUDE.md`, verification must protect both the chat path and the critique path.

## Safety Rules

- Never skip a manual-smoke requirement
- Never ask the human to perform manual smoke testing as a fallback
- Never continue to later PRs after the first failure or block
- Never merge without GitHub approval and green required checks
- Never change the final merge strategy away from rebase merge

## Example Scenario Translation

For a PR note like:

`Manual smoke: simulate IDK -> wrong -> IDK in a live session and confirm 3rd response reveals the answer`

the simulator skill should convert that note into a deterministic multi-turn session scenario, map it to existing coverage if possible, or add a repo-specific test or scenario harness if needed, then run it as part of merge gating.

## Non-Goals

- Processing multiple PRs in one pass
- Allowing manual human verification as an acceptable substitute for deterministic coverage
- Using squash merge or merge commits
