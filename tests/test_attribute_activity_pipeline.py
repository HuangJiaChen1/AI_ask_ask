"""Tests for the attribute activity pipeline — select_attribute_profile,
session state, and build_attribute_debug."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from attribute_activity import (
    AttributeProfile,
    DiscoverySessionState,
    build_attribute_debug,
    select_attribute_profile,
    start_attribute_session,
)


def _make_profile(
    attribute_id: str = "appearance.body_color",
    label: str = "body color",
) -> AttributeProfile:
    return AttributeProfile(
        attribute_id=attribute_id,
        label=label,
        activity_target="noticing and describing what apple looks like — specifically, apple's body color",
        branch="in_kb",
        object_examples=("apple",),
    )


# -- select_attribute_profile -------------------------------------------------

@pytest.mark.asyncio
async def test_select_attribute_profile_gemini_selects_from_dynamic_candidates():
    client = MagicMock()
    response = MagicMock()
    response.text = '{"attribute_id":"senses.taste","confidence":"high","reason":"smell is salient for food"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value="food"):
        profile, debug = await select_attribute_profile(
            object_name="cat food",
            age=6,
            anchor_status="anchored_high",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert profile.attribute_id == "senses.taste"
    assert profile.label == "taste"
    assert "cat food" in profile.activity_target
    assert debug["decision"] == "attribute_selected"
    assert debug["source"] == "gemini"


@pytest.mark.asyncio
async def test_select_attribute_profile_falls_back_to_first_candidate_on_invalid_json():
    client = MagicMock()
    response = MagicMock()
    response.text = "not json at all"
    client.aio.models.generate_content = AsyncMock(return_value=response)

    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value="food"):
        profile, debug = await select_attribute_profile(
            object_name="cat food",
            age=6,
            anchor_status="unresolved",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert "." in profile.attribute_id
    assert debug["source"] == "first_candidate_fallback"


@pytest.mark.asyncio
async def test_select_attribute_profile_returns_none_when_no_candidates():
    client = MagicMock()
    with patch("attribute_activity.get_candidate_sub_attributes", return_value=[]):
        with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value=None):
            profile, debug = await select_attribute_profile(
                object_name="impossible thing",
                age=3,
                anchor_status="unresolved",
                client=client,
                config={"model_name": "gemini-test"},
            )

    assert profile is None
    assert debug["decision"] == "no_attribute_match_fallback"


@pytest.mark.asyncio
async def test_select_attribute_profile_branch_in_kb_for_exact_supported():
    client = MagicMock()
    response = MagicMock()
    response.text = '{"attribute_id":"appearance.body_color","confidence":"high","reason":"color is salient"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value="animals"):
        profile, debug = await select_attribute_profile(
            object_name="cat",
            age=4,
            anchor_status="exact_supported",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert profile.branch == "in_kb"


@pytest.mark.asyncio
async def test_select_attribute_profile_branch_unresolved_for_unresolved_anchor():
    client = MagicMock()
    response = MagicMock()
    response.text = '{"attribute_id":"appearance.color","confidence":"medium","reason":"generic attribute"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value=None):
        profile, debug = await select_attribute_profile(
            object_name="quantum computer",
            age=6,
            anchor_status="unresolved",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert profile.branch == "unresolved_not_in_kb"


# -- session state ------------------------------------------------------------

def test_start_attribute_session_creates_state_with_correct_defaults():
    state = start_attribute_session(
        object_name="cat food",
        profile=_make_profile("senses.taste", "taste"),
        age=6,
    )

    assert isinstance(state, DiscoverySessionState)
    assert state.object_name == "cat food"
    assert state.turn_count == 0
    assert state.activity_ready is False
    assert state.surface_object_name is None
    assert state.anchor_object_name is None


def test_start_attribute_session_defaults_none_age_to_six():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=None)
    assert state.age == 6


def test_start_attribute_session_preserves_explicit_zero_age():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=0)
    assert state.age == 0


def test_start_attribute_session_stores_surface_and_anchor_names():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
        surface_object_name="red apple",
        anchor_object_name="apple",
    )

    assert state.surface_object_name == "red apple"
    assert state.anchor_object_name == "apple"


# -- build_attribute_debug ----------------------------------------------------

def test_build_attribute_debug_includes_profile_state_and_reason():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=6)

    debug = build_attribute_debug(
        decision="attribute_lane_started",
        profile=state.profile,
        state=state,
        reason="selected by test",
    )

    assert debug["decision"] == "attribute_lane_started"
    assert debug["profile"]["attribute_id"] == "appearance.body_color"
    assert debug["state"]["turn_count"] == 0
    assert debug["reason"] == "selected by test"
    assert debug["activity_marker_detected"] is False


def test_build_attribute_debug_with_marker_detected():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=6)

    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="marker detected in follow-up",
        activity_marker_detected=True,
        intent_type="correct_answer",
    )

    assert debug["activity_marker_detected"] is True
    assert debug["intent_type"] == "correct_answer"


def test_build_attribute_debug_with_marker_reason():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=6)

    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="marker detected in follow-up",
        activity_marker_detected=True,
        activity_marker_reason="Child explored color through comparison and preference",
        intent_type="correct_answer",
    )

    assert debug["activity_marker_detected"] is True
    assert debug["activity_marker_reason"] == "Child explored color through comparison and preference"
    assert debug["intent_type"] == "correct_answer"


def test_reason_regex_strips_reason_line():
    import re
    _REASON_RE = re.compile(r"REASON:\s*(.+?)(?:\n|$)")

    # Basic stripping
    text = "Some question\nREASON: child is ready\n"
    assert _REASON_RE.sub("", text) == "Some question\n"

    # No reason present
    text2 = "Some question\n"
    assert _REASON_RE.sub("", text2) == "Some question\n"

    # Reason at end without newline
    text3 = "Some question\nREASON: child is ready"
    assert _REASON_RE.sub("", text3) == "Some question\n"


# -- angle coverage tracking (CARES Phase 0) ----------------------------------

from stream.exploration_angles import AngleCoverageRecord


def test_start_attribute_session_initializes_empty_angle_tracking():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )
    assert state.explored_angle_ids == []
    assert state.angle_records == []
    assert state.current_angle_id is None


def test_discovery_session_state_record_angle():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )
    state.record_angle(
        turn_index=1,
        angle_id="observation",
        question_text="What color do you see?",
        response_text="It is red!",
    )
    assert state.explored_angle_ids == ["observation"]
    assert len(state.angle_records) == 1
    assert state.angle_records[0].angle_id == "observation"
    assert state.angle_records[0].turn_index == 1


def test_discovery_session_state_record_multiple_angles():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )
    state.record_angle(1, "observation", "Q1", "R1")
    state.record_angle(2, "comparison", "Q2", "R2")
    assert state.explored_angle_ids == ["observation", "comparison"]
    assert state.angle_records[1].angle_id == "comparison"


def test_build_attribute_debug_includes_angle_fields():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=6)
    state.record_angle(1, "observation", "Q1", "R1")
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="test",
    )
    assert debug["state"]["explored_angle_ids"] == ["observation"]
    assert len(debug["state"]["angle_records"]) == 1
    assert debug["state"]["angle_records"][0]["angle_id"] == "observation"


from stream.cares_handoff import AttributeInterestRecord


def test_assistant_initializes_empty_interest_records():
    from paixueji_assistant import PaixuejiAssistant
    assistant = PaixuejiAssistant(config_path="config.json", age_prompts_path="age_prompts.json")
    assert assistant.attribute_interest_records == {}


# -- prompt builder tests (CARES Phase 1 refactor) ----------------------------

from paixueji_app import (
    _build_continue_guide,
    _build_handoff_guide,
    _build_exit_guide,
    _build_reengage_guide,
)
from stream.exploration_angles import EXPLORATION_ANGLES


_SAFETY = "SENSORY SAFETY: Do NOT invite touch, smell, taste."


def _observation_angle():
    return EXPLORATION_ANGLES["physical"][0]


def _comparison_angle():
    return EXPLORATION_ANGLES["physical"][1]


def test_build_continue_guide_contains_angle_block():
    guide = _build_continue_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        selected_angle=_observation_angle(),
        explored_angle_ids=[],
        turn_count=1,
    )
    assert "[NEXT SUGGESTED ANGLE: observation]" in guide
    assert "Ask what the child notices or sees about the color" in guide


def test_build_continue_guide_has_inactive_handoff():
    guide = _build_continue_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        selected_angle=_observation_angle(),
        explored_angle_ids=[],
        turn_count=1,
        current_score=45,
        total_turns=3,
    )
    assert "HANDOFF MODE: INACTIVE" in guide
    assert "Do NOT output [ACTIVITY_READY]" in guide
    assert "Current interest score: 45/100" in guide
    assert "Session turns: 3" in guide


def test_build_handoff_guide_no_angle_block():
    guide = _build_handoff_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        activity=None,
        target_attribute="appearance.color",
        readiness_score=68,
        turn_count=5,
    )
    assert "[NEXT SUGGESTED ANGLE" not in guide
    assert "Your RESPONSE should:" not in guide
    assert "Example of a good question:" not in guide


def test_build_handoff_guide_contains_activity_name():
    class FakeActivity:
        name = "Color Matching Game"
        description = "Match colors with objects around you"

    guide = _build_handoff_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        activity=FakeActivity(),
        target_attribute="appearance.color",
        readiness_score=68,
        turn_count=5,
    )
    assert "Color Matching Game" in guide
    assert "[BRIDGE TO ACTIVITY]" in guide
    assert "Mention the activity by name" in guide
    assert "End with [ACTIVITY_READY]" in guide


def test_build_exit_guide_no_angle_block():
    guide = _build_exit_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        best_attribute="appearance.color",
        best_score=48,
        explored_attributes=["appearance.color", "appearance.shape"],
        total_turns=8,
    )
    assert "[NEXT SUGGESTED ANGLE" not in guide
    assert "Your RESPONSE should:" not in guide


def test_build_exit_guide_has_wrapup_instruction():
    guide = _build_exit_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        best_attribute="appearance.color",
        best_score=48,
        explored_attributes=["appearance.color"],
        total_turns=8,
    )
    assert "EXIT MODE: ACTIVE" in guide
    assert "[WRAP-UP]" in guide
    assert "Thank the child" in guide
    assert "what they want to talk about" in guide
    assert "why/how/causal questions" in guide
    assert "Outputting [ACTIVITY_READY]" in guide


def test_build_reengage_guide_simple_angle_only():
    guide = _build_reengage_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        selected_angle=_observation_angle(),
        explored_angle_ids=["observation"],
        turn_count=3,
        struggle_count=3,
    )
    assert "[NEXT SUGGESTED ANGLE: observation]" in guide
    assert "REENGAGE MODE: ACTIVE" in guide


def test_build_reengage_guide_uses_comparison_when_observation_used():
    guide = _build_reengage_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        selected_angle=_comparison_angle(),
        explored_angle_ids=["observation"],
        turn_count=3,
        struggle_count=3,
    )
    assert "[NEXT SUGGESTED ANGLE: comparison]" in guide


def test_build_reengage_guide_simplification_instruction():
    guide = _build_reengage_guide(
        attribute_label="color",
        activity_target="noticing colors",
        sensory_safety_rules=_SAFETY,
        selected_angle=_observation_angle(),
        explored_angle_ids=[],
        turn_count=3,
        struggle_count=3,
        current_score=15,
    )
    assert "The child is struggling" in guide
    assert "MUCH simpler" in guide
    assert "Consecutive struggle count: 3" in guide
    assert "Current interest score: 15/100" in guide
    assert "Causal or how/why questions" in guide
