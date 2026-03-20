# GitHub PR Merge Guardian Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reusable global skill that orchestrates strict GitHub PR rebasing and merging, plus a project-local skill that overfits Paixueji's session and test structure to replace manual-smoke requests with deterministic simulator work.

**Architecture:** Split responsibilities between a global orchestration skill and a repo-local simulator skill. Use concise `SKILL.md` workflow instructions plus targeted reference files so the orchestrator can remain reusable while the Paixueji simulator guidance can be repo-specific and detailed.

**Tech Stack:** Markdown skills, YAML metadata, Python skill scaffolding scripts

---

## Chunk 1: Global Skill Scaffold

### Task 1: Initialize the global `github-pr-merge-guardian` skill

**Files:**
- Create: `/Users/huangjiachen/.codex/skills/github-pr-merge-guardian/SKILL.md`
- Create: `/Users/huangjiachen/.codex/skills/github-pr-merge-guardian/agents/openai.yaml`
- Create: `/Users/huangjiachen/.codex/skills/github-pr-merge-guardian/references/`

- [ ] **Step 1: Initialize the skill directory with references support**

Run: `python /Users/huangjiachen/.codex/skills/.system/skill-creator/scripts/init_skill.py github-pr-merge-guardian --path /Users/huangjiachen/.codex/skills --resources references --interface display_name="GitHub PR Merge Guardian" --interface short_description="Strict GitHub PR gating, rebase, and merge workflow" --interface default_prompt="Use $github-pr-merge-guardian to inspect the oldest open PR, verify all gates, and merge only if everything passes."`
Expected: skill directory plus `SKILL.md`, `agents/openai.yaml`, and `references/`

- [ ] **Step 2: Verify the scaffold exists**

Run: `find /Users/huangjiachen/.codex/skills/github-pr-merge-guardian -maxdepth 2 -type f | sort`
Expected: shows `SKILL.md`, `agents/openai.yaml`, and any created reference files

## Chunk 2: Global Skill Content

### Task 2: Replace the scaffold with the final global workflow

**Files:**
- Modify: `/Users/huangjiachen/.codex/skills/github-pr-merge-guardian/SKILL.md`
- Create: `/Users/huangjiachen/.codex/skills/github-pr-merge-guardian/references/merge-gates.md`

- [ ] **Step 1: Write the final `SKILL.md`**

Include:
- oldest-first PR selection
- stop-on-first-failure behavior
- GitHub approval and required-check gates
- local rebase onto `main`
- invocation contract for the project-local `session-smoke-simulator`
- rebase-merge-only completion rule

- [ ] **Step 2: Add a compact reference file for merge gates**

Document:
- required GitHub checks versus local verification
- failure conditions that must stop the workflow
- assumptions about `gh`, `git`, and clean working state

- [ ] **Step 3: Validate the global skill**

Run: `python /Users/huangjiachen/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/huangjiachen/.codex/skills/github-pr-merge-guardian`
Expected: `Skill is valid!`

## Chunk 3: Project-Local Skill Scaffold

### Task 3: Initialize the local `session-smoke-simulator` skill

**Files:**
- Create: `/Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/SKILL.md`
- Create: `/Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/agents/openai.yaml`
- Create: `/Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/references/`

- [ ] **Step 1: Initialize the local skill directory with references support**

Run: `python /Users/huangjiachen/.codex/skills/.system/skill-creator/scripts/init_skill.py session-smoke-simulator --path /Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills --resources references --interface display_name="Session Smoke Simulator" --interface short_description="Paixueji live-session smoke simulation workflow" --interface default_prompt="Use $session-smoke-simulator at /Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator to convert PR manual-smoke notes into deterministic Paixueji session verification."`
Expected: local skill directory plus `SKILL.md`, `agents/openai.yaml`, and `references/`

- [ ] **Step 2: Verify the scaffold exists**

Run: `find /Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator -maxdepth 2 -type f | sort`
Expected: shows `SKILL.md`, `agents/openai.yaml`, and any created reference files

## Chunk 4: Project-Local Skill Content

### Task 4: Replace the scaffold with Paixueji-specific simulator guidance

**Files:**
- Modify: `/Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/SKILL.md`
- Create: `/Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/references/repo-map.md`
- Create: `/Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/references/manual-smoke-patterns.md`

- [ ] **Step 1: Write the final repo-local `SKILL.md`**

Include:
- how to read PR-note manual-smoke statements
- how to map them to Paixueji's `tests/` and `tests/integration_scenarios/`
- how to extend deterministic scenario coverage when no existing case matches
- how to verify both shared-core paths when shared modules are touched
- a hard rule against asking the human to perform manual smoke tests

- [ ] **Step 2: Add `repo-map.md`**

Document:
- app/session entry points
- shared `stream/` risks
- relevant test files and scenario runners already present in this repo

- [ ] **Step 3: Add `manual-smoke-patterns.md`**

Document:
- how to translate note text into setup, turn sequence, and expected assertions
- the example `IDK -> wrong -> IDK` path
- when to prefer extending an existing scenario file versus adding a new one

- [ ] **Step 4: Validate the local skill**

Run: `python /Users/huangjiachen/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator`
Expected: `Skill is valid!`

## Chunk 5: Final Verification

### Task 5: Confirm the created skills match the approved design

**Files:**
- Review: `/Users/huangjiachen/.codex/skills/github-pr-merge-guardian/SKILL.md`
- Review: `/Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/SKILL.md`

- [ ] **Step 1: Read back both skill files**

Run: `sed -n '1,220p' /Users/huangjiachen/.codex/skills/github-pr-merge-guardian/SKILL.md`
Expected: global orchestration workflow matches the approved design

Run: `sed -n '1,260p' /Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji/codex-skills/session-smoke-simulator/SKILL.md`
Expected: repo-local simulator workflow matches the approved design

- [ ] **Step 2: Report any constraints**

Call out:
- global skill installation required elevated filesystem access
- project-local skill is intentionally overfit to this repository
