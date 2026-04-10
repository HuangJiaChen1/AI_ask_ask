# User Behavior Adapter

Repository-local hints for the `mapping-user-behavior` global workflow.

## Purpose

- Anchor the workflow to repo-specific terminology and evidence sources.
- Keep project assumptions out of the global skills.
- Let the orchestrator discover the right output path and exclusions without extra user input.

## Contract

- `manifest.yaml` is the source of truth.
- Paths are repository-relative.
- `primary_sources` are searched first.
- `unreleased_markers` flag content that should be excluded from the baseline spec unless the user explicitly asks for unreleased behavior.
