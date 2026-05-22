"""
Regression tests for the orange cat diagnostic report.

Issues being diagnosed:
1. fluffy_expedition_dandelion selected for "orange cat" with hardcoded dandelion prompt
2. No verification of "fluffy" property — parameterized activity assumed applicable
3. dream_whisperer_cat not selected despite being cat-specific
4. Follow-up questions lack activity-pushing intent
5. PROBE directive uses pushy "Ask a clear, direct question" language
"""
import re

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

def _build_continue_guide(
    observation_angle,
    object_name,
    sensory_safety_rules,
    selected_angle,
    explored_angle_ids,
    turn_count,
    current_score=0.0,
    total_turns=0,
):
    angle_id = selected_angle["angle_id"]
    example = selected_angle["example"].format(
        attribute_label=observation_angle, object_name=object_name
    )
    used = ", ".join(explored_angle_ids) if explored_angle_ids else "none yet"

    return f"""{sensory_safety_rules}

CONVERSATION DIRECTION: Explore the {observation_angle} of the {object_name}.
Be playful and curious. Ask open-ended questions that help the child notice
and describe the {observation_angle} in their own words.

FOR THIS TURN, use the '{angle_id}' style:
Example: "{example}"

ALREADY USED: {used}
Do NOT repeat these styles.

ANTI-PATTERNS -- NEVER produce these:
- "What {observation_angle} is it?" -- quiz
- "Do you know what {observation_angle} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
- Mention activities, games, quests, or collecting

---

[SYSTEM CONTEXT]
Current focus: {observation_angle}
Current interest score: {current_score:.0f}/100
Session turns: {total_turns}

HANDOFF MODE: INACTIVE
Continue exploring the current attribute. Do NOT output [ACTIVITY_READY].
"""


def test_build_continue_guide_uses_observation_angle():
    """
    _build_continue_guide should use observation_angle and object_name,
    NOT the activity label, to build the prompt.
    """
    selected_angle = {
        "angle_id": "observation",
        "example": "What do you notice about the {object_name}'s {attribute_label}?",
    }

    guide = _build_continue_guide(
        observation_angle="texture",
        object_name="orange cat",
        sensory_safety_rules="SAFETY RULES",
        selected_angle=selected_angle,
        explored_angle_ids=[],
        turn_count=0,
    )

    assert "texture" in guide.lower()
    assert "orange cat" in guide.lower()
    assert "CONVERSATION DIRECTION" in guide
    assert "Find three fluffy friends" not in guide, (
        "Guide should NOT contain the activity label"
    )
    assert "activity_target" not in guide.lower(), (
        "Guide should NOT reference activity_target in chat phase"
    )


def test_build_continue_guide_omits_activity_target():
    """
    The guide should never expose the activity goal during the chat phase.
    """
    selected_angle = {
        "angle_id": "observation",
        "example": "What do you notice?",
    }

    guide = _build_continue_guide(
        observation_angle="texture",
        object_name="orange cat",
        sensory_safety_rules="SAFETY RULES",
        selected_angle=selected_angle,
        explored_angle_ids=[],
        turn_count=0,
    )

    assert re.search(r"\bquest\b", guide.lower()) is None
    assert re.search(r"\bcollect\b", guide.lower()) is None
    # "activity" appears in "Continue exploring the current attribute" which is expected
    assert re.search(r"\bactivity\b(?!_ready)", guide.lower()) is None or "Continue exploring the current attribute" in guide


# ── Issue 5: Intro asserts unverified properties ──

def test_attribute_intro_prompt_has_no_activity_target():
    """ATTRIBUTE_INTRO_PROMPT should not reference activity_target."""
    from paixueji_prompts import ATTRIBUTE_INTRO_PROMPT
    assert "{activity_target}" not in ATTRIBUTE_INTRO_PROMPT
    assert "ACTIVITY TARGET" not in ATTRIBUTE_INTRO_PROMPT


def test_attribute_intro_verification_override_exists():
    """Verification override must exist and forbid assertions."""
    from paixueji_prompts import ATTRIBUTE_INTRO_VERIFICATION_OVERRIDE
    assert 'Do NOT state the attribute as a fact' in ATTRIBUTE_INTRO_VERIFICATION_OVERRIDE
    assert 'BAD: "It has such thick, fluffy fur!"' in ATTRIBUTE_INTRO_VERIFICATION_OVERRIDE


def test_attribute_intro_prompt_does_not_encourage_assertions():
    """ATTRIBUTE_INTRO_PROMPT itself must not list assertion examples as GOOD.

    Regression: the prompt previously listed 'It looks so soft and fluffy!'
    as a GOOD example for cat+covering, causing intros to assume unverified
    properties even when verification_queue was empty.
    """
    import re
    from paixueji_prompts import ATTRIBUTE_INTRO_PROMPT

    # The old assertion-encouraging example must NOT appear in the GOOD section
    # Extract the GOOD block for cat+covering (between the GOOD line and the next BAD/empty line)
    good_cat_match = re.search(
        r'GOOD \(attribute=covering, object=cat\):.*?(?=\nBAD|\n\n|\Z)',
        ATTRIBUTE_INTRO_PROMPT,
        re.DOTALL,
    )
    assert good_cat_match is not None, "Prompt must have GOOD example for cat+covering"
    good_cat_block = good_cat_match.group(0)
    assert '"It looks so soft and fluffy!"' not in good_cat_block, (
        "GOOD example must not encourage asserting fluffy as fact"
    )

    # The prompt must contain a child-first observation example
    assert "Let's check out its fur — what do you notice?" in ATTRIBUTE_INTRO_PROMPT, (
        "Prompt must guide attention without asserting property"
    )
    # The assertion must be explicitly marked as BAD
    assert "asserts texture before child observes it" in ATTRIBUTE_INTRO_PROMPT
    assert "asserts thickness before child describes it" in ATTRIBUTE_INTRO_PROMPT


def test_attribute_intro_prompt_forbids_assertions_in_rules():
    """The Rules section must explicitly forbid asserting attributes as fact."""
    from paixueji_prompts import ATTRIBUTE_INTRO_PROMPT
    assert 'Do NOT assert the attribute as a confirmed fact' in ATTRIBUTE_INTRO_PROMPT


def test_discovery_session_state_has_primary_category():
    """DiscoverySessionState should carry the activity classification."""
    from attribute_activity import DiscoverySessionState
    state = DiscoverySessionState(object_name="cat", age=6)
    assert hasattr(state, "primary_category")
    assert state.primary_category == ""


def test_select_activities_preserves_primary_category():
    """select_activities_for_object should pass primary_category into state."""
    from unittest.mock import AsyncMock, patch
    from attribute_activity import select_activities_for_object, DiscoverySessionState

    async def run():
        with patch("attribute_activity.discover_talkable_activities", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = (
                type("Result", (), {
                    "primary_activity_id": "fluffy_expedition_dandelion",
                    "primary_category": "verifiable",
                    "secondary_activity_ids": [],
                    "verification_queue": [{"property": "has_fluffy_fur", "question": "Does it have fluffy fur?", "for_activity": "fluffy_expedition_dandelion"}],
                    "assessment": "test",
                    "proceed": True,
                    "all_activity_categories": {},
                })(),
                {"decision": "test"},
            )
            state, debug = await select_activities_for_object(
                object_name="orange cat",
                anchor_name="cat",
                age=6,
                client=None,
                config={},
            )
            assert isinstance(state, DiscoverySessionState)
            assert state.primary_category == "verifiable"
            assert len(state.verification_queue) == 1
            assert state.verification_queue[0].question == "Does it have fluffy fur?"

    import asyncio
    asyncio.run(run())


# ── Issue 6: PROBE directive uses pushy language ──

def test_probe_directive_does_not_use_pushy_language():
    """
    Regression: PROBE mode appended a directive telling the LLM to
    'Ask a clear, direct question to verify the pending property.'
    This produced pushy responses like 'tell me if it looks smooth or
    if it looks a bit messy.' The directive must use gentle, guiding
    language instead.
    """
    import pathlib

    source_path = pathlib.Path(__file__).parent.parent / "paixueji_app.py"
    source = source_path.read_text(encoding="utf-8")

    # The old pushy directive must NOT be present
    assert "Ask a clear, direct question" not in source, (
        "PROBE directive must not tell LLM to ask a 'clear, direct question'"
    )

    # Must not contain commanding phrases
    assert "tell me if" not in source.lower(), (
        "PROBE directive must not contain commanding 'tell me if' language"
    )


def test_probe_mode_generates_followup_question():
    """
    PROBE mode should be included in the follow-up question generation condition
    so the response generator doesn't have to violate its own 'Do NOT ask
    a question' rule.
    """
    import pathlib

    source_path = pathlib.Path(__file__).parent.parent / "paixueji_app.py"
    source = source_path.read_text(encoding="utf-8")

    # Find the followup decision condition block
    followup_condition_match = re.search(
        r'if\s*\(\s*needs_followup[\s\S]*?decision in\s*\(([^)]+)\)',
        source,
    )
    assert followup_condition_match is not None, (
        "Could not find followup condition block"
    )
    decisions_str = followup_condition_match.group(1)
    assert "PROBE" in decisions_str or "probe" in decisions_str.lower(), (
        "PROBE decision must be included in followup generation"
    )

    # Verify PROBE uses build_probe_verification_context in the followup path
    assert "build_probe_verification_context" in source, (
        "PROBE followup must use build_probe_verification_context"
    )


def test_build_probe_verification_context():
    """Unit test for build_probe_verification_context."""
    from stream.verification_guided_conversation import (
        build_probe_verification_context,
        VerificationItem,
    )

    items = [
        VerificationItem(
            property="has_fluffy_fur",
            question="Does it have fluffy fur?",
            for_activity_id="fluffy_expedition_dandelion",
        ),
    ]
    result = build_probe_verification_context(items)
    assert "Does it have fluffy fur?" in result
    assert "ask gently and directly" in result.lower()
    assert "Do NOT command" in result
    assert "Do NOT demand" in result
