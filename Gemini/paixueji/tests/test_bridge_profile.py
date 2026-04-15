from unittest.mock import MagicMock

from bridge_profile import BridgeProfile, infer_bridge_profile


def test_infer_bridge_profile_recovers_fenced_json():
    client = MagicMock()
    client.models.generate_content.return_value.text = """```json
{
  "bridge_intent": "Bridge from the food to how the cat notices and eats it.",
  "good_question_angles": ["how the cat smells it", "how the cat starts eating it"],
  "avoid_angles": ["unrelated cat body parts"],
  "steer_back_rule": "Acknowledge briefly, then return to noticing or eating.",
  "focus_cues": ["smell", "eat", "sniff", "smell"]
}
```"""

    profile, debug = infer_bridge_profile(
        "cat food",
        "cat",
        "food_for",
        client,
        {"model_name": "mock"},
    )

    assert isinstance(profile, BridgeProfile)
    assert profile.surface_object_name == "cat food"
    assert profile.anchor_object_name == "cat"
    assert profile.relation == "food_for"
    assert profile.focus_cues == ("smell", "eat", "sniff")
    assert debug["raw_model_payload_kind"] == "fenced_json"
    assert debug["json_recovery_applied"] is True


def test_infer_bridge_profile_normalizes_and_validates_lists():
    client = MagicMock()
    client.models.generate_content.return_value.text = """{
  "bridge_intent": " Bridge from the leash to how the dog uses it. ",
  "good_question_angles": [" how the dog wears it ", "", "how the leash helps on walks", "how the dog wears it"],
  "avoid_angles": ["", " unrelated fur details "],
  "steer_back_rule": " Keep the child on the use/handling lane. ",
  "focus_cues": [" hold ", "", "wear", "hold"]
}"""

    profile, debug = infer_bridge_profile(
        "dog leash",
        "dog",
        "used_with",
        client,
        {"model_name": "mock"},
    )

    assert isinstance(profile, BridgeProfile)
    assert profile.bridge_intent == "bridge from the leash to how the dog uses it."
    assert profile.good_question_angles == (
        "how the dog wears it",
        "how the leash helps on walks",
    )
    assert profile.avoid_angles == ("unrelated fur details",)
    assert profile.steer_back_rule == "keep the child on the use/handling lane."
    assert profile.focus_cues == ("hold", "wear")
    assert debug["raw_model_payload_kind"] == "plain_json"


def test_infer_bridge_profile_rejects_missing_semantic_content():
    client = MagicMock()
    client.models.generate_content.return_value.text = """{
  "bridge_intent": "",
  "good_question_angles": [],
  "avoid_angles": [],
  "steer_back_rule": "",
  "focus_cues": []
}"""

    profile, debug = infer_bridge_profile(
        "cat food",
        "cat",
        "food_for",
        client,
        {"model_name": "mock"},
    )

    assert profile is None
    assert debug["decision_reason"] == "invalid_bridge_profile_payload"


def test_infer_bridge_profile_handles_missing_model_client():
    profile, debug = infer_bridge_profile(
        "cat food",
        "cat",
        "food_for",
        None,
        {"model_name": "mock"},
    )

    assert profile is None
    assert debug["decision_reason"] == "no_model_client"
