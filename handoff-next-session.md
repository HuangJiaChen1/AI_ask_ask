# Handoff: Implement fun_fact Dead Code Removal

## Context

The `fun_fact` feature (Google Search grounded fun-fact generation) is dead code that has been fully analyzed and planned for removal. This handoff is for a fresh session to execute the implementation.

## What Was Done

- **Plan created**: `docs/superpowers/plans/2026-05-22-remove-fun-fact-dead-code.md`
- **Analysis complete**: All 10 tasks mapped to specific files and line numbers
- **Verification**: `node_generate_fun_fact` is defined but never `add_node`-ed to the LangGraph workflow. Safe to delete.

## What to Do Next

**Execute the plan using Approach 2 (Inline Execution) in a new git worktree.**

### Execution Approach

Use `superpowers:executing-plans` skill with inline execution. The plan has 10 tasks; execute them sequentially with commits after each task.

### Critical Files to Modify

| File | Action | Key Lines |
|------|--------|-----------|
| `stream/fun_fact.py` | **Delete** | Entire file (229 lines) |
| `stream/__init__.py` | Modify | Remove import + `__all__` entry |
| `graph.py` | Modify | Remove 4 state fields + `node_generate_fun_fact` function |
| `paixueji_prompts.py` | Modify | Remove 2 prompt constants + dict entries |
| `paixueji_app.py` | Modify | Remove state init fields + optimizer example |
| `schema.py` | Modify | Remove 4 fields from `StreamChunk` |
| `prompt_optimizer.py` | Modify | Remove `_run_grounding` + fun_fact branches |
| `trace_schema.py` | Modify | Update docstring examples |
| `trace_assembler.py` | Modify | Remove fun_fact prompts from JSON schema string |
| `tests/*` (6 files) | Modify | Remove fun_fact fields from test state dicts |
| `tests/test_dead_code_cleanup.py` | **Create** | Regression test for zero residual references |

### Key Technical Notes

1. **Do NOT use `git rm`** for the first step — the plan says to, but use standard file deletion and then stage.
2. **Prompt optimizer changes**: After removing `fun_fact_structuring_prompt` branch, the next `elif` becomes `if`.
3. **Test changes**: Some test files use `None` for fun_fact fields, others use `""` — remove whichever is present.
4. **Regression test**: The new `tests/test_dead_code_cleanup.py` should grep for `fun.?fact\|real_facts` and expect exit code 1 (no matches).

### Verification Steps

1. Run `pytest tests/ -v` after all changes — expect all tests pass.
2. Run the new regression test: `pytest tests/test_dead_code_cleanup.py -v`.
3. Final check: `grep -r -n -E "fun.?fact|real_facts" --include="*.py" stream/ graph.py paixueji_app.py schema.py prompt_optimizer.py trace_schema.py trace_assembler.py paixueji_prompts.py tests/` should return no matches (exit code 1).

## Skills to Use

- `superpowers:using-git-worktrees` — Create a new worktree for this work
- `superpowers:executing-plans` — Execute the plan inline

## Artifacts

- **Plan**: `docs/superpowers/plans/2026-05-22-remove-fun-fact-dead-code.md`
- **Original analysis plan**: `.claude/plans/fun-fact-dig-deep-code-whimsical-lamport.md`
