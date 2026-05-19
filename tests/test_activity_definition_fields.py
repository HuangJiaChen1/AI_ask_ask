import pytest
from activities import ActivityDefinition


def test_activity_definition_has_attributes_field():
    """attributes must be a core field, not buried in extra."""
    a = ActivityDefinition(
        activity_id="test",
        attributes=("red", "round"),
    )
    assert a.attributes == ("red", "round")


def test_activity_definition_has_preview_prompt_field():
    """preview_prompt must be separate from launch_prompt."""
    a = ActivityDefinition(
        activity_id="test",
        launch_prompt="Launch me",
        preview_prompt="Preview me",
    )
    assert a.launch_prompt == "Launch me"
    assert a.preview_prompt == "Preview me"


def test_from_dict_reads_attributes_and_preview_prompt():
    """from_dict must promote YAML attributes and preview_prompt to core fields."""
    data = {
        "activity_id": "polka_dot_patrol",
        "attributes": ["polka_dots", "spots", "circles"],
        "activity_signature": {
            "preview_prompt": "You noticed the polka dots on the {entity}. Let's find more!",
            "preview_label": "Polka Dot Patrol",
            "intro": "Find three polka-dotted things!",
        },
    }
    a = ActivityDefinition.from_dict(data)
    assert a.attributes == ("polka_dots", "spots", "circles")
    assert a.preview_prompt == "You noticed the polka dots on the {entity}. Let's find more!"
    assert a.launch_prompt == "You noticed the polka dots on the {entity}. Let's find more!"
    assert "attributes" not in a.extra
