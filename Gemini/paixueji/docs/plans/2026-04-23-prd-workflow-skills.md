# PRD Workflow Skills Implementation Plan

> **For agentic workers:** REQUIRED: Use subagent-driven-development (if subagents available) or executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create 5 global Qoder skills (1 orchestrator + 4 phase skills) plus reference files that implement a PRD workflow with three-layer behavior deviation framework.

**Architecture:** Orchestrator pattern — `prd` skill dispatches 4 phase skills sequentially, each conducts multi-turn dialogue and writes to a shared PRD file. Phase skills can also be invoked independently.

**Tech Stack:** Qoder skill SKILL.md format (YAML frontmatter + Markdown body), following patterns from existing skills like `experiment` and `writing-skills`.

**Design spec:** `docs/specs/2026-04-23-prd-workflow-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `~/.qoder/skills/prd/SKILL.md` | Orchestrator: workflow, gates, phase dispatch, file management |
| `~/.qoder/skills/prd/references/prd-template.md` | Full PRD template skeleton (all sections) |
| `~/.qoder/skills/prd/references/deviation-probe.md` | Three-layer framework detailed guide for prd-detailing |
| `~/.qoder/skills/prd/assets/completeness-checklist.md` | Post-completion self-check |
| `~/.qoder/skills/prd-scoping/SKILL.md` | Phase 1: scope, goals, out-of-scope, success criteria |
| `~/.qoder/skills/prd-detailing/SKILL.md` | Phase 2: interaction points, deviation probe, behavior trees |
| `~/.qoder/skills/prd-constraints/SKILL.md` | Phase 3: hard/soft constraints, assumptions, expectations |
| `~/.qoder/skills/prd-ops-planning/SKILL.md` | Phase 4: test strategy, monitoring, rollback, performance |

---

### Task 1: Create directory structure

**Files:**
- Create: `~/.qoder/skills/prd/SKILL.md`
- Create: `~/.qoder/skills/prd/references/prd-template.md`
- Create: `~/.qoder/skills/prd/references/deviation-probe.md`
- Create: `~/.qoder/skills/prd/assets/completeness-checklist.md`
- Create: `~/.qoder/skills/prd-scoping/SKILL.md`
- Create: `~/.qoder/skills/prd-detailing/SKILL.md`
- Create: `~/.qoder/skills/prd-constraints/SKILL.md`
- Create: `~/.qoder/skills/prd-ops-planning/SKILL.md`

- [ ] **Step 1: Create directories**

```bash
mkdir -p ~/.qoder/skills/prd/references
mkdir -p ~/.qoder/skills/prd/assets
mkdir -p ~/.qoder/skills/prd-scoping
mkdir -p ~/.qoder/skills/prd-detailing
mkdir -p ~/.qoder/skills/prd-constraints
mkdir -p ~/.qoder/skills/prd-ops-planning
```

Run: `ls -R ~/.qoder/skills/prd ~/.qoder/skills/prd-scoping ~/.qoder/skills/prd-detailing ~/.qoder/skills/prd-constraints ~/.qoder/skills/prd-ops-planning`
Expected: All directories exist

---

### Task 2: Create prd-template.md (reference file)

**Files:**
- Create: `~/.qoder/skills/prd/references/prd-template.md`

- [ ] **Step 1: Write the PRD template**

Write the full template with all sections from the design spec. Each section has an HTML comment indicating which phase fills it.

- [ ] **Step 2: Verify template file exists**

Run: `cat ~/.qoder/skills/prd/references/prd-template.md | head -5`
Expected: Shows `# PRD: [Feature Name]`

---

### Task 3: Create deviation-probe.md (reference file)

**Files:**
- Create: `~/.qoder/skills/prd/references/deviation-probe.md`

- [ ] **Step 1: Write the three-layer deviation framework guide**

Write the detailed guide containing:
- Layer 1: 5 dimensions with per-dimension追问 templates and product-agnostic examples
- Layer 2: Context sensitivity questions with examples
- Layer 3: State accumulation questions with examples
- A "final sweep" prompt for unclassified behaviors
- The validation table from the design spec as evidence the framework works

- [ ] **Step 2: Verify file exists**

Run: `wc -l ~/.qoder/skills/prd/references/deviation-probe.md`
Expected: 80+ lines

---

### Task 4: Create completeness-checklist.md (asset file)

**Files:**
- Create: `~/.qoder/skills/prd/assets/completeness-checklist.md`

- [ ] **Step 1: Write the completeness checklist**

Write the self-check from the design spec covering:
- Per-phase minimum requirements (4 sections)
- Cross-section consistency checks (4 items)

- [ ] **Step 2: Verify file exists**

Run: `cat ~/.qoder/skills/prd/assets/completeness-checklist.md | head -3`
Expected: Shows `# PRD Completeness Checklist`

---

### Task 5: Create prd-scoping SKILL.md

**Files:**
- Create: `~/.qoder/skills/prd-scoping/SKILL.md`

- [ ] **Step 1: Write prd-scoping SKILL.md**

Must include:
- YAML frontmatter: `name: prd-scoping`, `description: Use when defining the scope, goals, and success criteria for a new feature before diving into implementation details`
- Overview: 1-2 sentences
- Dialogue flow: 7-step sequence from design spec
- PRD sections written: Overview, Goals, Out of Scope, Success Criteria
- Gate: Out of Scope >= 1, Success Criteria >= 1 verifiable criterion
- Red flags table: what goes wrong + correction

- [ ] **Step 2: Verify frontmatter format**

Run: `head -4 ~/.qoder/skills/prd-scoping/SKILL.md`
Expected: Shows proper YAML frontmatter with name and description

---

### Task 6: Create prd-detailing SKILL.md

**Files:**
- Create: `~/.qoder/skills/prd-detailing/SKILL.md`

- [ ] **Step 1: Write prd-detailing SKILL.md**

Must include:
- YAML frontmatter: `name: prd-detailing`, `description: Use when detailing a feature's interaction points, user behavior branches, and implementation approach after scope is defined`
- Overview: 1-2 sentences, referencing deviation-probe.md
- Dialogue flow: 5-step sequence from design spec
- Three-layer probe summary (concise — full detail is in deviation-probe.md, not duplicated here)
- PRD sections written: Interaction Points, Behavior Decision Trees, Implementation Approach
- Gate: All 5 dimensions addressed for every interaction point
- Red flags table

- [ ] **Step 2: Verify file loads and references deviation-probe.md**

Run: `grep -c "deviation-probe" ~/.qoder/skills/prd-detailing/SKILL.md`
Expected: >= 1

---

### Task 7: Create prd-constraints SKILL.md

**Files:**
- Create: `~/.qoder/skills/prd-constraints/SKILL.md`

- [ ] **Step 1: Write prd-constraints SKILL.md**

Must include:
- YAML frontmatter: `name: prd-constraints`, `description: Use when capturing hard constraints, soft constraints, assumptions, and expectations for a feature after its behavior has been detailed`
- Overview: 1-2 sentences
- Dialogue flow: 7-step sequence from design spec
- PRD sections written: Hard Constraints, Soft Constraints, Assumptions (with fallback), Expectations
- Gate: Hard Constraints >= 1, every Assumption has fallback
- Key追问: "If this isn't written in the PRD, would an implementer know it?"
- Red flags table

- [ ] **Step 2: Verify file**

Run: `head -4 ~/.qoder/skills/prd-constraints/SKILL.md`
Expected: Shows proper YAML frontmatter

---

### Task 8: Create prd-ops-planning SKILL.md

**Files:**
- Create: `~/.qoder/skills/prd-ops-planning/SKILL.md`

- [ ] **Step 1: Write prd-ops-planning SKILL.md**

Must include:
- YAML frontmatter: `name: prd-ops-planning`, `description: Use when defining test strategy, monitoring, rollback plan, and performance expectations for a feature after constraints are captured`
- Overview: 1-2 sentences
- Dialogue flow: 6-step sequence from design spec
- PRD sections written: Test Strategy, Monitoring, Rollback Plan, Performance Expectations
- Gate: Rollback Plan not empty, Test Strategy covers critical branches
- Red flags table

- [ ] **Step 2: Verify file**

Run: `head -4 ~/.qoder/skills/prd-ops-planning/SKILL.md`
Expected: Shows proper YAML frontmatter

---

### Task 9: Create prd orchestrator SKILL.md

**Files:**
- Create: `~/.qoder/skills/prd/SKILL.md`

- [ ] **Step 1: Write prd orchestrator SKILL.md**

Must include:
- YAML frontmatter: `name: prd`, `description: Use when starting a new feature and needing to create a detailed Product Requirement Document through structured multi-turn dialogue`
- Overview: 1-2 sentences
- Workflow: 7-step sequence from design spec
- Non-negotiable gates table (5 gates)
- Orchestrator responsibilities boundary (does / does not)
- Phase dispatch: which skill to invoke for each phase
- File management: PRD creation from template, save path convention
- Post-phase self-check using completeness-checklist.md
- Red flags table

- [ ] **Step 2: Verify all cross-references are correct**

Run: `grep -c "prd-scoping\|prd-detailing\|prd-constraints\|prd-ops-planning\|prd-template\|deviation-probe\|completeness-checklist" ~/.qoder/skills/prd/SKILL.md`
Expected: >= 7 (each reference at least once)

---

### Task 10: Verify all skills are discoverable

- [ ] **Step 1: List all created files**

Run: `find ~/.qoder/skills/prd* -type f -name "*.md" | sort`
Expected: 8 files listed

- [ ] **Step 2: Verify all YAML frontmatter is valid**

Run: `for f in ~/.qoder/skills/prd*/SKILL.md; do echo "=== $f ==="; head -4 "$f"; done`
Expected: Each shows proper `---` delimiters with `name:` and `description:` fields

- [ ] **Step 3: Verify no skill SKILL.md exceeds 500 words**

Run: `for f in ~/.qoder/skills/prd*/SKILL.md; do echo "$f: $(wc -w < "$f") words"; done`
Expected: All under 500 words (per writing-skills guidance for non-frequently-loaded skills)

- [ ] **Step 4: Commit**

```bash
cd ~/.qoder/skills
git add prd/ prd-scoping/ prd-detailing/ prd-constraints/ prd-ops-planning/
git commit -m "feat: add PRD workflow skills (orchestrator + 4 phase skills)"
```
