import pytest

from attribute_activity import (
    AttributeProfile,
    AttributeSessionState,
    build_attribute_debug,
    find_mock_attribute_profile,
    start_attribute_session,
)


@pytest.mark.parametrize(
    ("object_name", "attribute_id", "label", "branch"),
    [
        ("apple", "surface_shiny_smooth", "shiny smooth skin", "in_kb"),
        ("cat", "fur_paws_soft", "soft fur and paws", "in_kb"),
        ("cat food", "strong_smell", "strong smell", "anchored_not_in_kb"),
        ("spaceship fuel", "sparkle_glow", "pretend sparkly glow", "unresolved_not_in_kb"),
        ("ball", "round_rolls", "round rolling shape", "in_kb"),
    ],
)
def test_find_mock_attribute_profile_returns_supported_profile(object_name, attribute_id, label, branch):
    profile = find_mock_attribute_profile(object_name)

    assert isinstance(profile, AttributeProfile)
    assert profile.attribute_id == attribute_id
    assert profile.label == label
    assert profile.branch == branch
    assert profile.activity_target


def test_find_mock_attribute_profile_returns_none_for_unsupported_object():
    assert find_mock_attribute_profile("plain thing") is None


@pytest.mark.parametrize("object_name", ["cat food", "spaceship fuel"])
def test_attribute_session_does_not_require_surface_or_anchor_objects(object_name):
    profile = find_mock_attribute_profile(object_name)

    state = start_attribute_session(object_name=object_name, profile=profile, age=6)

    assert isinstance(state, AttributeSessionState)
    assert state.object_name == object_name
    assert state.profile.attribute_id == profile.attribute_id
    assert state.surface_object_name is None
    assert state.anchor_object_name is None
    assert state.turn_count == 0
    assert state.activity_ready is False


def test_build_attribute_debug_includes_profile_state_and_reason():
    profile = find_mock_attribute_profile("apple")
    state = start_attribute_session(object_name="apple", profile=profile, age=6)

    debug = build_attribute_debug(
        decision="attribute_lane_started",
        profile=profile,
        state=state,
        reason="selected by test",
    )

    assert debug["decision"] == "attribute_lane_started"
    assert debug["profile"]["attribute_id"] == "surface_shiny_smooth"
    assert debug["state"]["profile"]["label"] == "shiny smooth skin"
    assert debug["reason"] == "selected by test"
