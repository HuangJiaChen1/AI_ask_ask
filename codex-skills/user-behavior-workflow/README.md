# User Behavior Workflow Skills

This directory stores the repo-managed source of truth for the global `mapping-user-behavior` workflow.

## Layout

- `global/` contains the five installable global skills.
- `references/spec-template.md` defines the fixed `USER_BEHAVIOR_SPEC.md` shape.
- `../install_user_behavior_skills.py` installs the global skills into `~/.agents/skills`.

## Installation

```bash
python codex-skills/install_user_behavior_skills.py
```

The installer creates symlinks by default so the installed global skills stay synced to this repository copy.
