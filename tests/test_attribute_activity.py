import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from activities import ActivityDefinition
from attribute_activity import (
    DiscoverySessionState,
    select_activities_for_object,
    start_attribute_session,
    build_attribute_debug,
)


def test_discovery_session_state_activity_fields():
    state = DiscoverySessionState(
        object_name="cat",
        age=6,
        primary_activity=ActivityDefinition(activity_id="test", name="Test"),
    )
    assert state.primary_activity.activity_id == "test"
    assert state.verified_properties == {}


@pytest.mark.asyncio
async def test_select_activities_for_object_no_eligible():
    """When no eligible activities, return None and a debug dict."""
    with patch("attribute_activity.get_eligible_activities_for_object", return_value=[]):
        state, debug = await select_activities_for_object(
            object_name="cat",
            anchor_name="cat",
            age=6,
            client=MagicMock(),
            config={"model_name": "gemini-2.0-flash-lite"},
        )
    assert state is None
    assert debug["decision"] == "no_eligible"


def test_start_attribute_session():
    activity = ActivityDefinition(activity_id="color_chaser", name="Color Chaser")
    state = DiscoverySessionState(
        object_name="cat",
        age=6,
        primary_activity=activity,
    )
    session = start_attribute_session(state)
    assert session.primary_activity == activity
    assert session.turn_count == 0


def test_build_attribute_debug():
    activity = ActivityDefinition(activity_id="test", name="Test")
    state = DiscoverySessionState(object_name="cat", age=6, primary_activity=activity)
    debug = build_attribute_debug(
        decision="test",
        state=state,
        reason="test reason",
    )
    assert debug["decision"] == "test"
    assert debug["reason"] == "test reason"
