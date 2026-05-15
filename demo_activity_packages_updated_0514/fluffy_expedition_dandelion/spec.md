# Fluffy Expedition Dandelion - Authoring Spec

> Migrated from `wonderlens-activity-fullstack-demo/backend/games/fluffy_expedition_dandelion.md` into the current five-file activity package format.

## Premise

The dandelion becomes the first fluffy friend in a texture quest. The child searches for three more soft, fuzzy, or fluffy things, describes each texture, gives each find a character name, and tells a tiny story about the fluffy friends meeting.

## Target

- **Template type:** cat5
- **Activity category:** Collection/Tracking Exploration (Out-of-Device)
- **Primary tier:** T0
- **Experience pillar:** Adventure
- **Game style:** `quest_collector`
- **Mechanic:** `collect`
- **Observation angle:** `texture`
- **Entity role:** `exemplar`

## Pedagogical Rationale

The original demo used naming_story. The latest package maps that lineage to Adventure / quest_collector: the criterion creates the mission, each find harvests texture details, and the final synthesis turns the collection into a shared story.

## Selection Trigger

Use when the photographed entity visibly suggests fluffiness, softness, fuzziness, seeds, petals, fur, moss, wool, or another safe tactile texture clue.

## Adaptation Rationale

The source demo remains the behavioral reference for tone, scenario order, role title, and reward language. This migration updates the package to the latest WonderLens contract: current pillar/style vocabulary, current `activity_signature` enums, machine-readable tag metadata, child recap payload, parent dashboard fragment, explicit asset tracking, and a single authoring scorecard in `spec.md`.


## Asset Brief

| asset_id | asset_type | requiredness | generation_timing | use_step | display_location | purpose | prompt_en/source | display_behavior | fallback_behavior | safety_constraints |
|---|---|---|---|---|---|---|---|---|---|---|
| `fluffy_expedition_icon_set_01` | icon | optional | pre_generated | prod.step_2; prod.step_3.round_1-3; prod.step_4 | collection_slot_icon_area | Provide small soft-texture icons for empty slots, hints, and the final fluffy-friend story path. | Create a small child-friendly icon set for a fluffy texture quest: dandelion seed puff, fuzzy moss, soft petal, woolly puff, and cloud placeholder. Use simple flat shapes, light background, no text, no brands, no realistic insects close-up. | Use icons as placeholders or hint markers only; accepted finds are represented by child photos. | If icons are unavailable, use generic rounded empty slots and text labels while preserving the child-photo collection. | No unsafe touching prompts, no sharp objects, no allergen claims, no brands, and no dense text. |

## Asset Usage Timeline

| asset_id | timing | load/generate moment | first display | visible range | location | interaction/use | persistence/hide behavior | fallback |
|---|---|---|---|---|---|---|---|---|
| `fluffy_expedition_icon_set_01` | pre_generated | Load before Step 2 if available; otherwise activate fallback UI immediately. | prod.step_2 | prod.step_2; prod.step_3.round_1-3; prod.step_4 | collection_slot_icon_area | Use icons as placeholders or hint markers only; accepted finds are represented by child photos. | Hide or replace the support scene/icon when the next round card or collection slot appears; keep child photos and progress state stable. | If icons are unavailable, use generic rounded empty slots and text labels while preserving the child-photo collection. |


## Extensibility Notes

- Replace `{runtime_entity}` with a safe photographed entity that carries the same bridge prerequisite, such as `dandelion` or a visually similar toy/object.
- Preserve the declared mechanic `collect` and retarget only the focal attribute `fluffy_soft_texture` or scene/card set when adapting the activity.
- Swap `fluffy_expedition_icon_set_01` for another approved support asset set with the same display timing and fallback behavior.

## Self-Evaluation Scorecard

Evaluated against `prod.md`, `tag_block.yaml`, `program.md` Phase 3, `activities/README.md`, and `docs/game_styles.md`.

| # | Dimension | Score | Notes |
|---|-----------|-------|-------|
| 1 | V1 Technical Compliance | PASS | Uses child speech, ordinary photos, and optional displayed support assets only. It does not require OCR, face/pose detection, IMU sensing, audio-quality scoring, or before/after state verification. |
| 2 | Hook & Transition | PASS | Step 1 grows from the photographed entity and opens with feeling or wonder before introducing the activity frame. |
| 3 | Edge Case Coverage | PASS | Every runtime dialogue step includes ideal, unexpected, and no-response paths with wait-time prompts; Cat5 packages include search/scaffold handling. |
| 4 | IB Completeness | PASS | The package defines key concepts, related concepts, KUD, ATL skills, and a closing that names the concept through the child's experience. |
| 5 | Tier Appropriateness | PASS | Rounds are short, concrete, and matched to the declared tier while preserving optional caregiver scaffolding. |
| 6 | Dialogue Specificity | PASS | AI lines, child branches, and follow-ups are concrete enough to run without inventing missing beats. |
| 7 | Screen & UI Completeness | PASS | Each step has a specific screen state, progress treatment, and asset fallback where visual support is optional. |
| 8 | Entity Mapping Alignment | N/A | This is a demo-source migration, not a mapping-informed assignment requiring entity YAML grounding. |
| 9 | Game Feel | PASS | The activity has a role title, visible progress, differentiated rounds, and an earned payoff connected to the child's answers. |
| 10 | Pillar Fidelity | PASS | The migrated pillar/style follows docs/game_styles.md lineage and preserves the original child action without forcing a mismatched scaffold. |

**Overall**: ALL PASS - direct demo migration is structurally valid and current-format complete.
