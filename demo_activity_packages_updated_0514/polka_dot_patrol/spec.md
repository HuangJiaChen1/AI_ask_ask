# Polka Dot Patrol — Authoring Spec

> Category 5 (Collection/Tracking Exploration) · Property-bridge on pattern · Exemplified by `ladybug`

## Premise

After the child photographs a ladybug, the AI gasps at its beautiful polka-dotted shell and asks an imaginative question: do those tiny black dots look like buttons, or maybe little windows? The child becomes a "Polka-Dot Patrol Officer" and heads out on a detective adventure to find 3 more things nearby that have dots, spots, or circles — a spotted mushroom, a speckled pebble, a flower with circular markings. Each round the child describes the pattern they found. At synthesis, the child places all three finds side by side and examines how the "same" pattern is actually different every time: big blotchy spots on a mushroom, tiny speckles on a pebble, perfect round circles on a flower petal. The child gives each find a playful name ("Freckle Stone," "Polka Petal") and earns the Polka-Dot Patrol Officer badge.

## Target

- **IB axis:** Form (primary, via pattern as a property) + Connection (secondary, via the surprising link between unrelated spotted things)
- **Primary rung:** T1 (ages 4–6)
- **Tier elasticity:** T0–T2 (±1)
- **Age tier:** child can look closely, compare dot sizes, and verbalize how one pattern differs from another.

## Pedagogical rationale

Pattern is the most abstract of the observable properties — it isn't the object, it sits *on* the object — and T1 children usually see "spotted things" as a flat category. This game makes the child zoom in: yes, a ladybug and a flower both have dots, but the dots themselves behave differently. Big splotches, tiny speckles, and perfect circles are all "the pattern of dots" and also obviously different patterns. This concrete same-but-different comparison is exactly the cognitive move the IB Key Concept of **Form** is pointing at, and it builds into **Connection** when the child sees that unrelated items (bug, stone, petal) share a visual signature.

The creative-naming layer ("Freckle Stone," "Polka Petal") turns scientific observation into personal expression, keeping the activity in the imagination register rather than letting it collapse into a rote sort.

## Selection trigger

Fires whenever the matcher finds a pattern property — specifically dots, spots, or repeating round marks — on the photographed entity. The ladybug is the canonical exemplar, but the activity works for any entity whose detected pattern is dot-based.

Drives off a pattern trigger:

- primary bridge: `pattern` (the dot/spot/circle signature)
- secondary bridges: `color` (the dot's color vs the background), `shape` (the dot as shape)

Because the trigger is pattern-as-property, the entity functions as an *exemplar* of polka-dot pattern rather than the subject of the activity. The role pivot is surfaced via `activity_signature.role_pivot_note`.

## Experience pillar & game style

- **Pillar:** Adventure
- **Game style:** `quest_collector` (criterion-driven collection of 3 spotted things, with comparison plus patrol-story synthesis)
- **Mechanic:** `collect`
- **Observation angle:** `pattern`
- **Entity role:** `exemplar` (parameterized — the ladybug is one example of the polka-dot pattern class)

## Demo Source Migration Notes

This canonical package covers the current frontend demo source `wonderlens-activity-fullstack-demo/backend/games/polka_dot_patrol.md`. The older demo source used `comparison_chart`; this package keeps the latest Adventure / `quest_collector` migration because it preserves the dot-finding mission and adds the required patrol-story payoff. Demo icon catalogs are treated as optional UI support only; the package runtime depends on the child photo slots and generic pattern UI, not on prebuilt image files.

## Self-Evaluation Scorecard

Evaluated against `prod.md`, `tag_block.yaml`, `program.md` Phase 3, and `templates.md` Adventure + Cat5 rules.

| # | Dimension | Score | Notes |
|---|-----------|-------|-------|
| 1 | V1 Technical Compliance | PASS | Multi-photo collection is allowed; each photo is assessed independently for visible dots/spots/circles. No blocked OCR, face/pose, IMU, non-speech audio, or state-change detection is required. |
| 2 | Hook & Transition | PASS | Step 1 starts with delight in the ladybug's polka dots and grows into a patrol mission to find more spotted things, without a sudden quiz-like task assignment. |
| 3 | Edge Case Coverage | PASS | Every dialogue step now has three child response paths, including no-response branches with waits. The outdoor stuck branch gives concrete hints for flowers, ground, leaves, and bark. |
| 4 | IB Completeness | PASS | Form + Connection are named in Basic Info, tag metadata, and the closing. KUD covers dot vocabulary, same/different comparison, observation, analysis, and creative naming/storytelling. |
| 5 | Tier Appropriateness | PASS | The T1 hunt uses concrete visual language (dots, spots, speckles, circles), a 3-find mission, and short comparison/naming prompts suitable for ages 4-6. |
| 6 | Dialogue Specificity | PASS | AI lines are concrete spoken copy with tone markers; the patrol setup, per-find reactions, comparison prompts, naming prompt, and parade narration are all explicit. |
| 7 | Screen & UI Completeness | PASS | Each step has specific screen treatment: highlighted ladybug dots, mission card, collection slots, comparison labels, dotted parade path, badge, concept words, and spotted confetti. |
| 8 | Entity Mapping Alignment | N/A | Parameterized pattern-property activity; it is not a mapping-informed assignment with a required entity YAML read. |
| 9 | Game Feel | PASS | The patrol mission has visible progress, the final find completes the set, and the new parade story gives the named finds an earned payoff beyond a static comparison chart. |
| 10 | Pillar Fidelity | PASS | Adventure is now explicit. The activity uses a quest criterion, collection progress, detail naming, and a final patrol-story journey, so `quest_collector` is no longer just a metadata label. |

**Overall**: ALL PASS — 2 issues found and fixed during self-evaluation: the runtime Basic Info still used retired `comparison_chart` wording, and the previous synthesis stopped before the Adventure-style story payoff.
