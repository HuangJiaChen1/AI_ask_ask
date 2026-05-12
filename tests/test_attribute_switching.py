# tests/test_attribute_switching.py
import pytest
from paixueji_assistant import PaixuejiAssistant
from attribute_activity import AttributeProfile, start_attribute_session


def test_switch_to_fallback():
    assistant = PaixuejiAssistant(client=None)
    primary = AttributeProfile(
        attribute_id="appearance.color", label="color",
        activity_target="exploring colors", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    fallback = AttributeProfile(
        attribute_id="appearance.shape", label="shape",
        activity_target="exploring shapes", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    primary_with_fb = AttributeProfile(
        attribute_id=primary.attribute_id, label=primary.label,
        activity_target=primary.activity_target, branch=primary.branch,
        object_examples=primary.object_examples,
        fallback_attributes=(fallback,),
    )
    state = start_attribute_session(object_name="apple", profile=primary_with_fb, age=5)
    assistant.start_attribute_lane(state, primary_with_fb)
    success = assistant.switch_attribute_topic("appearance.shape")
    assert success is True
    assert assistant.attribute_state.profile.attribute_id == "appearance.shape"
    assert assistant.attribute_state.switched_to == "appearance.shape"
    fallback_ids = [f.attribute_id for f in assistant.attribute_state.profile.fallback_attributes]
    assert "appearance.color" in fallback_ids


def test_switch_to_invalid_target():
    assistant = PaixuejiAssistant(client=None)
    primary = AttributeProfile(
        attribute_id="appearance.color", label="color",
        activity_target="exploring colors", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    state = start_attribute_session(object_name="apple", profile=primary, age=5)
    assistant.start_attribute_lane(state, primary)
    success = assistant.switch_attribute_topic("nonexistent.attribute")
    assert success is False
    assert assistant.attribute_state.profile.attribute_id == "appearance.color"


def test_focus_topic_parameter_exists():
    """Verify ask_followup_question_stream accepts focus_topic parameter."""
    import inspect
    from stream.question_generators import ask_followup_question_stream
    sig = inspect.signature(ask_followup_question_stream)
    assert "focus_topic" in sig.parameters
    assert sig.parameters["focus_topic"].default == "same attribute or same detail"


def test_detector_applies_switch_before_generator():
    """Switch applied before response generator sees the topic."""
    from paixueji_assistant import PaixuejiAssistant
    from attribute_activity import AttributeProfile, start_attribute_session

    assistant = PaixuejiAssistant(client=None)
    primary = AttributeProfile(
        attribute_id="appearance.color", label="color",
        activity_target="exploring colors", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    fallback = AttributeProfile(
        attribute_id="appearance.shape", label="shape",
        activity_target="exploring shapes", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    primary_with_fb = AttributeProfile(
        attribute_id=primary.attribute_id, label=primary.label,
        activity_target=primary.activity_target, branch=primary.branch,
        object_examples=primary.object_examples,
        fallback_attributes=(fallback,),
    )
    state = start_attribute_session(object_name="apple", profile=primary_with_fb, age=5)
    assistant.start_attribute_lane(state, primary_with_fb)

    # Simulate detector having already run and decided to switch
    success = assistant.switch_attribute_topic("appearance.shape", reason="detector_decided")
    assert success is True

    # Generator would now receive the POST-SWITCH profile
    assert assistant.attribute_state.profile.attribute_id == "appearance.shape"
    assert assistant.attribute_state.profile.label == "shape"
    assert assistant.attribute_state.switched_to == "appearance.shape"
    assert assistant.attribute_state.switch_reason == "detector_decided"


def test_attribute_activity_target_includes_matched_activity():
    """attribute_activity_target exposes activity_id/name/launch_prompt when matched."""
    assistant = PaixuejiAssistant(client=None)
    assistant.attribute_profile = AttributeProfile(
        attribute_id="appearance.color", label="color",
        activity_target="exploring colors", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    assistant.attribute_matched_activity = {
        "activity_id": "color_exploration_v1",
        "name": "Color Explorer",
        "launch_prompt": "Let's play Color Explorer! Find three red things.",
    }
    target = assistant.attribute_activity_target()
    assert target["activity_id"] == "color_exploration_v1"
    assert target["activity_name"] == "Color Explorer"
    assert target["launch_prompt"] == "Let's play Color Explorer! Find three red things."


def test_clear_attribute_lane_clears_matched_activity():
    """clear_attribute_lane nullifies attribute_matched_activity."""
    assistant = PaixuejiAssistant(client=None)
    primary = AttributeProfile(
        attribute_id="appearance.color", label="color",
        activity_target="exploring colors", branch="in_kb",
        object_examples=("apple",), fallback_attributes=(),
    )
    state = start_attribute_session(object_name="apple", profile=primary, age=5)
    assistant.start_attribute_lane(state, primary)
    assistant.attribute_matched_activity = {"activity_id": "x"}
    assistant.clear_attribute_lane()
    assert assistant.attribute_matched_activity is None
