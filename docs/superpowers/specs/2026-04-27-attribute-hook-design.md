# Attribute Pipeline Hook Design

## Summary

The attribute pipeline should not consume the full general-chat hook taxonomy directly. The current `hook_type` taxonomy serves broad chat engagement, while the attribute pipeline needs a narrower contract: observable-only intros that keep the child focused on attributes present in the object.

This design keeps a single shared hook taxonomy in `hook_types.json`, but adds an attribute-specific metadata field. The attribute pipeline will filter hook candidates using that field and will select only observable-safe hooks. General chat will continue using the broader taxonomy unchanged.

## Problem

Today, hook types are used for two different concerns:

1. Creative intro shaping for general chat.
2. Behavioral control that influences downstream question style.

That coupling makes the attribute pipeline fragile. Some hooks are useful for general engagement but are poor fits for attribute elicitation because they steer the child into fantasy, role play, emotional projection, or hypothetical redesign instead of visible object properties.

## Goals

- Preserve the existing general-chat hook taxonomy.
- Add a hard allow-list for attribute intros.
- Restrict attribute intros to observable-only hooks.
- Prevent imaginative hooks from being selected in the attribute pipeline.
- Make the attribute eligibility decision declarative in hook metadata.

## Non-Goals

- Replacing the general chat hook taxonomy.
- Introducing graded attribute suitability labels.
- Supporting imaginative intros in the attribute pipeline.
- Designing a separate attribute-only taxonomy.

## Proposed Data Shape

Each hook entry in `hook_types.json` may include an attribute-specific field:

- `attribute_mode: "observable"` for hooks that are valid in the attribute pipeline
- omitted or `null` for hooks that are not valid in the attribute pipeline

This field is a hard allow-list. If a hook does not explicitly declare `attribute_mode: "observable"`, the attribute pipeline must treat it as unsupported.

## Selection Rules

### General Chat

General chat continues to select from the full hook taxonomy using existing selection logic.

### Attribute Pipeline

The attribute pipeline selects from a pre-filtered pool containing only hooks with `attribute_mode: "observable"`.

This means:

- non-observable hooks remain valid for general chat
- non-observable hooks are impossible to select for attribute intros
- filtering happens at hook selection time, not after selection

## Observable-Safe Criteria

A hook is observable-safe only if its concept and examples keep the child grounded in properties that are visibly or directly present in the object.

Allowed signals include:

- color
- shape
- part
- size
- texture
- visible relation between parts
- concrete visual or sensory details

Disallowed signals include:

- fantasy or magic scenarios
- role play or character insertion
- emotional projection onto the object
- hypothetical redesign or superpowers
- questions whose answer depends mainly on imagination rather than observation

## Hook Review Guidance

Based on the current taxonomy, the expected review outcome is:

- likely allowed: `细节发现`
- possibly allowed only after review and rewrite: `选择偏好`
- likely disallowed: `想象导向`, `角色代入`, `情绪投射`, `创意改造`
- case-by-case review: `经验、生活链接`, because it can shift attention away from object attributes

The allow-list should be driven by whether examples are answerable from the object itself, not by whether the hook is engaging in general chat.

## Downstream Semantics

The attribute pipeline should stop depending on the broad creative hook taxonomy as an implicit behavioral contract.

Today, raw hook names also contribute to downstream `question_style` behavior. For the attribute path, the stronger contract should become:

- this intro is observable-safe
- this intro is valid for attribute elicitation

That reduces leakage from general-chat taxonomy decisions into attribute-pipeline behavior.

## Why This Approach

### Chosen Approach: Shared Taxonomy + Attribute Metadata

This design keeps one shared source of truth for hook names, concepts, and examples while adding a narrow attribute-specific contract.

Benefits:

- no duplication of hook definitions
- explicit attribute compatibility
- easy review of which hooks are allowed
- low implementation surface compared with creating a second taxonomy

### Alternatives Considered

#### Graded fit labels

Rejected because the attribute pipeline should be deterministic and observable-only. A softer model such as `strong | weak | disallowed` invites ambiguity and future exceptions.

#### Separate attribute-only taxonomy

Rejected because it would create extra maintenance burden and duplicate concepts that already exist in the shared hook set.

## Testing Implications

The implementation should verify at least:

- the attribute pipeline only selects hooks marked `attribute_mode: "observable"`
- unsupported hooks are never selected in the attribute path
- general chat selection remains unchanged
- any downstream logic that depends on intro semantics still behaves correctly when the attribute path uses the filtered subset

## Open Questions Resolved

- Observable-only or allow imagination? Resolved: observable-only.
- Soft suitability or hard allow-list? Resolved: hard allow-list.
- Shared taxonomy or separate taxonomy? Resolved: shared taxonomy with attribute-specific metadata.

## Scope Boundary

This design is intentionally limited to hook taxonomy and selection semantics for the attribute pipeline. It does not redesign the general chat intro system or broader conversation style taxonomy.
