"""
Regression tests for the orange cat diagnostic report.

Issues being diagnosed:
1. fluffy_expedition_dandelion selected for "orange cat" with hardcoded dandelion prompt
2. No verification of "fluffy" property — parameterized activity assumed applicable
3. dream_whisperer_cat not selected despite being cat-specific
4. Follow-up questions lack activity-pushing intent
"""
import pytest
from activities import (
    ActivityDefinition,
    _is_eligible,
    get_eligible_activities_for_object,
    _load_catalog,
)
from attribute_activity import AttributeProfile


# ── Issue 1: Parameterized activities pass Layer 1 eligibility ──

def test_parameterized_activity_passes_layer_one_eligibility():
    """
    Parameterized activities always pass Layer 1 (_is_eligible).
    The LLM in Layer 2 (discover_talkable_activities) judges plausibility.
    """
    catalog = _load_catalog()
    fluffy = next((a for a in catalog if a.activity_id == "fluffy_expedition_dandelion"), None)
    assert fluffy is not None, "fluffy_expedition_dandelion should exist in catalog"
    assert fluffy.entity_binding == "parameterized"

    # Layer 1 always passes for parameterized activities
    is_eligible = _is_eligible(fluffy, "T1")
    assert is_eligible is True


def test_parameterized_activity_in_eligible_list_for_object():
    """
    get_eligible_activities_for_object includes parameterized activities.
    """
    eligible = get_eligible_activities_for_object("cat", 5)
    activity_ids = [a.activity_id for a in eligible]
    assert "fluffy_expedition_dandelion" in activity_ids
    assert "polka_dot_patrol" in activity_ids


# ── Issue 2: dream_whisperer_cat excluded due to missing entity_class in cats.yaml ──

def test_dream_whisperer_cat_eligibility_with_real_db():
    """
    BUG: cats.yaml has no 'entity_class' field, so _find_entity('cat') returns
    a dict without 'entity_class'. This causes dream_whisperer_cat
    (entity_class_filter=[cat]) to fail the bound eligibility check.
    """
    from stream.db_loader import _find_entity

    entity_info = _find_entity("cat")
    assert entity_info is not None, "cat should exist in mappings DB"

    # The bug: entity_info has no 'entity_class' key
    entity_classes = set(entity_info.get("entity_class", []))
    print(f"entity_classes for 'cat': {entity_classes}")

    catalog = _load_catalog()
    dream = next((a for a in catalog if a.activity_id == "dream_whisperer_cat"), None)
    assert dream is not None, "dream_whisperer_cat should exist in catalog"
    assert dream.entity_binding == "bound"
    assert dream.entity_class_filter == ("cat",)

    is_eligible = _is_eligible(dream, "T1", entity_info=entity_info)
    assert is_eligible is True


def test_dream_whisperer_cat_eligibility_with_matching_entity_name():
    """
    When entity_info has matching entity_name, dream_whisperer_cat is eligible.
    """
    catalog = _load_catalog()
    dream = next((a for a in catalog if a.activity_id == "dream_whisperer_cat"), None)
    assert dream is not None

    fixed_entity_info = {"entity_name": "Cat"}
    is_eligible = _is_eligible(dream, "T1", entity_info=fixed_entity_info)
    assert is_eligible is True


# ── Issue 3: Hardcoded dandelion prompt in fluffy_expedition_dandelion ──

def test_fluffy_expedition_preview_prompt_contains_hardcoded_entity():
    """
    BUG: fluffy_expedition_dandelion's preview_prompt is hardcoded with
    "This dandelion is fluffy..." which is inappropriate for non-dandelion objects.
    """
    catalog = _load_catalog()
    fluffy = next((a for a in catalog if a.activity_id == "fluffy_expedition_dandelion"), None)
    assert fluffy is not None

    # The preview_prompt should be entity-agnostic or use a placeholder
    assert "dandelion" in fluffy.preview_prompt.lower(), (
        "preview_prompt contains hardcoded 'dandelion'"
    )

    # When this activity is selected for "orange cat", the activity_target
    # becomes this dandelion-specific prompt
    profile = AttributeProfile(
        attribute_id=f"activity.{fluffy.activity_id}",
        label=fluffy.name,
        activity_target=fluffy.preview_prompt or fluffy.description,
        branch="in_kb",
        object_examples=("orange cat",),
    )
    assert "dandelion" in profile.activity_target.lower(), (
        "BUG: activity_target for orange cat contains 'dandelion'"
    )


# ── Issue 4: _build_continue_guide does not include activity_target ──

# Inline copies to avoid importing Flask-dependent paixueji_app.py
def _build_common_preamble(sensory_safety_rules, attribute_label, turn_count, explored_angle_ids):
    used_angles = ", ".join(explored_angle_ids) if explored_angle_ids else "(none yet)"
    return f"""{sensory_safety_rules}

[CONVERSATION COVERAGE]
Attribute: {attribute_label}
Turns explored: {turn_count}
Angles already used: {used_angles}"""


def _build_angle_block(selected_angle, attribute_label):
    return f"""[CURRENT ANGLE]
Angle: {selected_angle['angle_id']}
Instruction: {selected_angle['instruction']}
Example: {selected_angle.get('example', '')}"""


def _build_used_angles_block(explored_angle_ids, attribute_label):
    if not explored_angle_ids:
        return "(none yet)"
    return "\n".join(f"- {a}" for a in explored_angle_ids)


def _build_common_antipatterns(attribute_label):
    return f"""ANTI-PATTERNS -- NEVER produce these:
- "What {attribute_label} is it?" -- quiz
- "Do you know what {attribute_label} it has?" -- quiz with wrapper"""


def _build_continue_guide(
    attribute_label,
    activity_target,
    sensory_safety_rules,
    selected_angle,
    explored_angle_ids,
    turn_count,
    current_score=0.0,
    total_turns=0,
    explored_attributes=None,
):
    preamble = _build_common_preamble(sensory_safety_rules, attribute_label, turn_count, explored_angle_ids)
    angle_block = _build_angle_block(selected_angle, attribute_label)
    used_angles_block = _build_used_angles_block(explored_angle_ids, attribute_label)
    explored_attrs_str = ", ".join(explored_attributes) if explored_attributes else "(none yet)"
    antipatterns = _build_common_antipatterns(attribute_label)

    return f"""{preamble}

{angle_block}

Already-used angles (try something different if possible):
{used_angles_block}

{antipatterns}

---

[SYSTEM CONTEXT]
Current attribute: {attribute_label}
Current interest score: {current_score:.0f}/100
Session turns: {total_turns}
Explored attributes: {explored_attrs_str}

HANDOFF MODE: INACTIVE
Continue exploring the current attribute. Do NOT output [ACTIVITY_READY].
"""


def test_build_continue_guide_omits_activity_target():
    """
    BUG: _build_continue_guide receives activity_target but never includes it
    in the returned prompt. The LLM has no idea what the actual activity goal is.
    """
    selected_angle = {
        "angle_id": "observation",
        "instruction": "Ask the child to observe",
        "example": "What do you see?",
    }

    guide = _build_continue_guide(
        attribute_label="Find three fluffy friends",
        activity_target="Find three soft or fuzzy things nearby and name them.",
        sensory_safety_rules="SAFETY RULES",
        selected_angle=selected_angle,
        explored_angle_ids=[],
        turn_count=0,
    )

    # The activity_target is completely absent from the guide prompt
    assert "activity_target" not in guide.lower()
    assert "Find three soft or fuzzy things" not in guide, (
        "BUG: activity_target is not included in continue guide prompt"
    )
    # The LLM only sees "Current attribute: Find three fluffy friends"
    # but has no context about what the activity actually entails
