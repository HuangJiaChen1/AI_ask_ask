# Time Machine Dinosaur - Authoring Spec

> Migrated from `wonderlens-activity-fullstack-demo/backend/games/time_machine_dinosaur.md` into the current five-file activity package format.

## Premise

A toy dinosaur enters a time machine and visits a jungle, a rumbling volcano, and a peaceful sunset lake. The child imagines what the dinosaur does in each time and sees how the same character changes with the setting.

## Target

- **Template type:** cat1
- **Activity category:** Sustained Verbal Interaction (In-Device)
- **Primary tier:** T0
- **Experience pillar:** Adventure
- **Game style:** `time_traveler`
- **Mechanic:** `imagine`
- **Observation angle:** `origin`
- **Entity role:** `subject`

## Pedagogical Rationale

The source demo already uses a time-machine metaphor, so the latest package formalizes it as Adventure / time_traveler. The repeated mechanic is imaginative narration rather than verified physical movement.

## Selection Trigger

Use when the photographed entity is a dinosaur toy, plush dinosaur, dinosaur figure, or dinosaur picture that can launch a pretend time journey.

## Adaptation Rationale

The source demo remains the behavioral reference for tone, scenario order, role title, and reward language. This migration updates the package to the latest WonderLens contract: current pillar/style vocabulary, current `activity_signature` enums, machine-readable tag metadata, child recap payload, parent dashboard fragment, explicit asset tracking, and a single authoring scorecard in `spec.md`.


## Asset Brief

| asset_id | asset_type | requiredness | generation_timing | use_step | display_location | purpose | prompt_en/source | display_behavior | fallback_behavior | safety_constraints |
|---|---|---|---|---|---|---|---|---|---|---|
| `time_machine_dinosaur_scene_set_01` | card_set | optional | pre_generated | prod.step_2.demo; prod.step_3.round_1-3; prod.step_4 | time_portal_scene_panel | Support the time jumps with three clear preschool scene cards and a final timeline display. | Create three friendly preschool time-travel scene cards for a toy dinosaur: lush prehistoric jungle with giant ferns, safe distant rumbling volcano with dramatic sky, and peaceful golden lake at sunset. Use rounded shapes, bright but gentle colors, no scary danger, no text, no brands. | Show each scene card as the time machine lands; at synthesis, place the three cards on a left-to-right timeline. | If cards are unavailable, keep the dinosaur photo inside a generic time portal and describe the scenes by voice only. | Volcano stays distant and non-threatening, no realistic injury, no scary predators, no brands, and no dense text. |

## Asset Usage Timeline

| asset_id | timing | load/generate moment | first display | visible range | location | interaction/use | persistence/hide behavior | fallback |
|---|---|---|---|---|---|---|---|---|
| `time_machine_dinosaur_scene_set_01` | pre_generated | Load before Step 2 if available; otherwise activate fallback UI immediately. | prod.step_2.demo | prod.step_2.demo; prod.step_3.round_1-3; prod.step_4 | time_portal_scene_panel | Show each scene card as the time machine lands; at synthesis, place the three cards on a left-to-right timeline. | Hide or replace the support scene/icon when the next round card or collection slot appears; keep child photos and progress state stable. | If cards are unavailable, keep the dinosaur photo inside a generic time portal and describe the scenes by voice only. |


## Extensibility Notes

- Replace `{runtime_entity}` with a safe photographed entity that carries the same bridge prerequisite, such as `dinosaur` or a visually similar toy/object.
- Preserve the declared mechanic `imagine` and retarget only the focal attribute `time_period_behavior` or scene/card set when adapting the activity.
- Swap `time_machine_dinosaur_scene_set_01` for another approved support asset set with the same display timing and fallback behavior.

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
