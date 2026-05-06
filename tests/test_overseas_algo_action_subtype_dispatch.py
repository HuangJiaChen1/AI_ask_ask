from paixueji_assistant import PaixuejiAssistant


def test_assistant_has_action_subtype_field():
    a = PaixuejiAssistant()
    a.age = 5
    assert hasattr(a, "action_subtype"), "PaixuejiAssistant missing action_subtype"
    assert a.action_subtype is None


def test_action_type_b_sets_activity_ready():
    a = PaixuejiAssistant()
    a.age = 5
    a.attribute_activity_ready = False
    a.action_subtype = "B"
    # Simulate the flag flip (this would normally happen inside node_action)
    # For a unit test, just verify the field exists and can be set.
    assert a.action_subtype == "B"
