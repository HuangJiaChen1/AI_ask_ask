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
