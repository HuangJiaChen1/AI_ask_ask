# Mood Changer Dog - Authoring Spec

> Migrated from `wonderlens-activity-fullstack-demo/backend/games/mood_changer_dog.md` into the current five-file activity package format.

## Premise

A photographed stuffed dog becomes a tiny performer with feelings inside. The child becomes an Emotion Translator and speaks for the dog when sunshine, a bump, and a favorite treat change the dog's mood.

## Target

- **Template type:** cat1
- **Activity category:** Sustained Verbal Interaction (In-Device)
- **Primary tier:** T0
- **Experience pillar:** Performance
- **Game style:** `voice_stage`
- **Mechanic:** `motion_voice`
- **Observation angle:** `emotion`
- **Entity role:** `subject`

## Pedagogical Rationale

The original demo used voice_acting. The latest package maps it to Performance / voice_stage because the child performs in role and receives warm audience-style reactions after each feeling voice.

## Selection Trigger

Use when the photographed entity is a dog, puppy, stuffed dog, plush dog, or toy dog with visible friendly features such as soft fur or floppy ears.

## Adaptation Rationale

The source demo remains the behavioral reference for tone, scenario order, role title, and reward language. This migration updates the package to the latest WonderLens contract: current pillar/style vocabulary, current `activity_signature` enums, machine-readable tag metadata, child recap payload, parent dashboard fragment, explicit asset tracking, and a single authoring scorecard in `spec.md`.


## Asset Brief

| asset_id | asset_type | requiredness | generation_timing | use_step | display_location | purpose | prompt_en/source | display_behavior | fallback_behavior | safety_constraints |
|---|---|---|---|---|---|---|---|---|---|---|
| `mood_changer_dog_scene_set_01` | card_set | optional | pre_generated | prod.step_2.demo; prod.step_3.round_1-3; prod.step_4 | stage_scene_panel | Support the three feeling situations with simple expressive dog scene cards. | Create three friendly preschool scene cards for a soft stuffed dog: cozy dog in warm sunshine, surprised dog after a harmless little bump, and excited dog smelling a favorite treat. Use light backgrounds, rounded shapes, clear feeling cues, no injury detail, no text, no brands. | Show the relevant feeling card during each round while keeping the child's photographed dog as the performer anchor. | If cards are unavailable, keep the photographed dog and use generic stage lights, heart icons, and voice description only. | No scary pain, no realistic injury, no brands, no unsafe dog behavior, and no dense text. |

## Asset Usage Timeline

| asset_id | timing | load/generate moment | first display | visible range | location | interaction/use | persistence/hide behavior | fallback |
|---|---|---|---|---|---|---|---|---|
| `mood_changer_dog_scene_set_01` | pre_generated | Load before Step 2 if available; otherwise activate fallback UI immediately. | prod.step_2.demo | prod.step_2.demo; prod.step_3.round_1-3; prod.step_4 | stage_scene_panel | Show the relevant feeling card during each round while keeping the child's photographed dog as the performer anchor. | Hide or replace the support scene/icon when the next round card or collection slot appears; keep child photos and progress state stable. | If cards are unavailable, keep the photographed dog and use generic stage lights, heart icons, and voice description only. |


## Extensibility Notes

- Replace `{runtime_entity}` with a safe photographed entity that carries the same bridge prerequisite, such as `dog` or a visually similar toy/object.
- Preserve the declared mechanic `motion_voice` and retarget only the focal attribute `dog_feeling_voice` or scene/card set when adapting the activity.
- Swap `mood_changer_dog_scene_set_01` for another approved support asset set with the same display timing and fallback behavior.

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
