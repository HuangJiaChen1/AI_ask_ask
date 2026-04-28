from unittest.mock import MagicMock

from object_resolver import ObjectResolutionResult, resolve_object_input
from paixueji_assistant import PaixuejiAssistant
from resolution_debug import build_resolution_debug


def test_fenced_json_resolver_output_recovers_to_high_anchor():
    client = MagicMock()
    client.models.generate_content.side_effect = [
        MagicMock(text="""```json
{
  "anchor_object_name": "cat",
  "relation": "food_for",
  "confidence_band": "high"
}
```"""),
        MagicMock(text="""```json
{
  "bridge_intent": "Bridge from the food to how the cat notices and eats it.",
  "good_question_angles": ["how the cat smells it", "how the cat starts eating it"],
  "avoid_angles": ["unrelated cat body parts"],
  "steer_back_rule": "Acknowledge briefly, then return to noticing or eating.",
  "focus_cues": ["smell", "eat"]
}
```"""),
    ]

    result = resolve_object_input("cat food", age=6, client=client, config={"model_name": "mock"})

    assert result.anchor_status == "anchored_high"
    assert result.anchor_object_name == "cat"
    assert result.anchor_relation == "food_for"
    assert result.bridge_profile is not None
    assert result.resolution_debug["raw_model_payload_kind"] == "fenced_json"
    assert result.resolution_debug["json_recovery_applied"] is True


def test_prose_wrapped_json_resolver_output_recovers_to_high_anchor():
    client = MagicMock()
    client.models.generate_content.side_effect = [
        MagicMock(text='Here is the JSON: {"anchor_object_name":"cat","relation":"food_for","confidence_band":"high"}'),
        MagicMock(text='{"bridge_intent":"Bridge from food to cat eating.","good_question_angles":["how the cat smells it"],"avoid_angles":["unrelated body parts"],"steer_back_rule":"Return to noticing or eating.","focus_cues":["smell"]}'),
    ]

    result = resolve_object_input("cat food", age=6, client=client, config={"model_name": "mock"})

    assert result.anchor_status == "anchored_high"
    assert result.anchor_object_name == "cat"
    assert result.bridge_profile is not None
    assert result.resolution_debug["raw_model_payload_kind"] == "wrapped_json"
    assert result.resolution_debug["json_recovery_applied"] is True


def test_invalid_primary_payload_still_allows_relation_repair_when_single_candidate_exists():
    client = MagicMock()
    client.models.generate_content.side_effect = [
        MagicMock(text="```json\nnot actually json\n```"),
        MagicMock(text='{"relation":"food_for","confidence_band":"high"}'),
        MagicMock(text='{"bridge_intent":"Bridge from food to cat eating.","good_question_angles":["how the cat smells it"],"avoid_angles":["unrelated body parts"],"steer_back_rule":"Return to noticing or eating.","focus_cues":["smell"]}'),
    ]

    result = resolve_object_input("cat food", age=6, client=client, config={"model_name": "mock"})

    assert result.anchor_status == "anchored_high"
    assert result.anchor_object_name == "cat"
    assert result.resolution_debug["decision_source"] == "relation_repair"


def test_resolution_debug_tracks_payload_kind_and_recovery():
    debug = build_resolution_debug(
        surface_object_name="cat food",
        decision_source="model_inference",
        decision_reason="high_confidence_valid_anchor",
        candidate_anchors=["cat"],
        model_attempted=True,
        raw_model_response='```json {"anchor_object_name":"cat"} ```',
        raw_model_payload_kind="fenced_json",
        json_recovery_applied=True,
        anchor_object_name="cat",
        anchor_status="anchored_high",
        bridge_profile_status="ready",
        bridge_profile_reason="bridge_profile_inferred",
    )

    assert debug["raw_model_payload_kind"] == "fenced_json"
    assert debug["json_recovery_applied"] is True
    assert debug["bridge_profile_status"] == "ready"


def test_apply_resolution_keeps_parser_recovery_fields():
    assistant = PaixuejiAssistant(client=None)
    assistant.apply_resolution(
        ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
            bridge_profile=None,
            resolution_debug={
                "decision_source": "model_inference",
                "raw_model_payload_kind": "wrapped_json",
                "json_recovery_applied": True,
                "bridge_profile_status": "ready",
            },
        )
    )

    assert assistant.session_resolution_debug["raw_model_payload_kind"] == "wrapped_json"
    assert assistant.session_resolution_debug["json_recovery_applied"] is True
    assert assistant.session_resolution_debug["bridge_profile_status"] == "ready"
