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
