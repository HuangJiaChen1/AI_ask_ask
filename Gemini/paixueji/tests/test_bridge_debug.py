from bridge_debug import (
    build_activation_continuity_anchor,
    build_bridge_debug,
    build_bridge_trace_entry,
    bridge_verdict,
    detect_bridge_visibility,
    format_bridge_log_line,
)
from object_resolver import ObjectResolutionResult
from paixueji_assistant import PaixuejiAssistant
from unittest.mock import MagicMock


def test_detect_bridge_visibility_flags_missing_connection_for_cat_food_intro():
    debug = build_bridge_debug(
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        intro_mode="anchor_bridge",
        learning_anchor_active_before=False,
        learning_anchor_active_after=False,
        bridge_attempt_count_before=0,
        bridge_attempt_count_after=1,
        decision="intro_bridge",
        decision_reason="start high-confidence bridge",
        response_text="Hey! I see you have some cat food there. What does the cat food look like inside the bag?",
        bridge_context_summary="allowed: smell, eat, mouth, nose",
    )
    assert debug["bridge_visible_in_response"] is False
    assert "did not expose" in bridge_verdict(debug).lower()


def test_detect_bridge_visibility_accepts_explicit_relation_lane():
    debug = build_bridge_debug(
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        intro_mode="anchor_bridge",
        learning_anchor_active_before=False,
        learning_anchor_active_after=False,
        bridge_attempt_count_before=0,
        bridge_attempt_count_after=1,
        decision="intro_bridge",
        decision_reason="start high-confidence bridge",
        response_text="Cat food is what a cat eats. When a cat smells food, what helps it notice that smell first?",
        bridge_context_summary="allowed: smell, eat, mouth, nose",
    )
    assert debug["bridge_visible_in_response"] is True


def test_detect_bridge_visibility_uses_relation_focus_terms():
    visible, reason = detect_bridge_visibility(
        response_text="What helps it notice that yummy smell first?",
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_relation="food_for",
    )
    assert visible is True
    assert "focus term" in reason.lower()


def test_detect_bridge_visibility_allows_surface_object_plus_focus_terms():
    visible, reason = detect_bridge_visibility(
        response_text="Cat food smells strong. What helps it notice that smell first?",
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_relation="food_for",
    )
    assert visible is True
    assert "focus term" in reason.lower()


def test_detect_bridge_visibility_avoids_anchor_substring_false_positive():
    visible, reason = detect_bridge_visibility(
        response_text="These categories look funny.",
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_relation="food_for",
    )
    assert visible is False
    assert "did not expose" in reason.lower()


def test_build_bridge_trace_entry_uses_node_trace_shape():
    entry = build_bridge_trace_entry(
        node="driver:pre_anchor_gate",
        state_before={"anchor_status": "anchored_high", "learning_anchor_active": False},
        changes={"decision": "bridge_retry"},
        time_ms=3.2,
    )
    assert entry["node"] == "driver:pre_anchor_gate"
    assert entry["changes"]["decision"] == "bridge_retry"
    assert entry["state_changes"]["decision"] == "bridge_retry"
    assert entry["state_before"]["anchor_status"] == "anchored_high"
    assert entry["phase"] == "response"


def test_format_bridge_log_line_includes_ids_and_decision():
    line = format_bridge_log_line(
        session_id="abc",
        request_id="req",
        bridge_debug={
            "decision": "bridge_retry",
            "response_type": "bridge_retry",
            "anchor_status": "anchored_high",
            "bridge_attempt_count_before": 1,
            "bridge_attempt_count_after": 2,
            "pre_anchor_reply_type": "true_miss",
            "support_action": None,
            "pre_anchor_support_count_before": 0,
            "pre_anchor_support_count_after": 0,
            "bridge_followed": False,
            "bridge_follow_reason": "no lane term",
            "kb_mode": "bridge_context_only",
            "bridge_visible_in_response": False,
        },
    )
    assert "session=abc" in line
    assert "request=req" in line
    assert "decision=bridge_retry" in line
    assert "response_type=bridge_retry" in line
    assert "reply_type=true_miss" in line
    assert "support_action=None" in line
    assert "attempt_before=1" in line
    assert "attempt_after=2" in line
    assert "support_before=0" in line
    assert "support_after=0" in line
    assert "bridge_followed=False" in line
    assert "follow_reason='no lane term'" in line
    assert "kb_mode=bridge_context_only" in line
    assert "visibility=False" in line


def test_build_bridge_debug_skips_visibility_without_response_text():
    debug = build_bridge_debug(
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        intro_mode="anchor_bridge",
        learning_anchor_active_before=False,
        learning_anchor_active_after=False,
        bridge_attempt_count_before=0,
        bridge_attempt_count_after=1,
        decision="bridge_retry",
        decision_reason="child stayed on surface object",
    )
    assert debug["bridge_visible_in_response"] is None
    assert debug["bridge_visibility_reason"] == "response not evaluated yet"


def test_bridge_activation_debug_evaluates_visibility_from_response_text():
    debug = build_bridge_debug(
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        intro_mode="anchor_bridge",
        learning_anchor_active_before=False,
        learning_anchor_active_after=True,
        bridge_attempt_count_before=2,
        bridge_attempt_count_after=0,
        decision="bridge_activation",
        decision_reason="child followed bridge",
        response_type="bridge_activation",
        response_text="Your cat really likes wet food. What does your cat do when dinner is ready?",
    )
    assert debug["bridge_visible_in_response"] is True
    assert debug["bridge_visibility_reason"] != "response not evaluated yet"


def test_bridge_debug_includes_pre_anchor_reply_policy_fields():
    debug = build_bridge_debug(
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        intro_mode="anchor_bridge",
        learning_anchor_active_before=False,
        learning_anchor_active_after=False,
        bridge_attempt_count_before=1,
        bridge_attempt_count_after=1,
        pre_anchor_support_count_before=0,
        pre_anchor_support_count_after=1,
        decision="bridge_support",
        decision_reason="child asked for clarification",
        response_type="bridge_support",
        pre_anchor_reply_type="clarification_request",
        support_action="clarify",
    )

    assert debug["pre_anchor_reply_type"] == "clarification_request"
    assert debug["support_action"] == "clarify"
    assert debug["pre_anchor_support_count_before"] == 0
    assert debug["pre_anchor_support_count_after"] == 1


def test_build_activation_continuity_anchor_normalizes_kb_items():
    assert build_activation_continuity_anchor(
        {"kind": "physical_attribute", "dimension": "appearance", "attribute": "paw_pads"}
    ) == "physical.appearance.paw_pads"
    assert build_activation_continuity_anchor(
        {"kind": "engagement_item", "dimension": "behavior", "seed_text": "sniff the food"}
    ) == "engagement.behavior:sniff the food"


def test_build_bridge_debug_preserves_nested_activation_transition_payload():
    debug = build_bridge_debug(
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        intro_mode="anchor_bridge",
        learning_anchor_active_before=False,
        learning_anchor_active_after=False,
        bridge_attempt_count_before=1,
        bridge_attempt_count_after=1,
        decision="bridge_activation",
        decision_reason="activation continue",
        activation_transition={
            "before_state": {
                "activation_handoff_ready_before": True,
                "activation_last_question_before": "After she eats, does she lick her paw pads?",
            },
            "question_validation": {
                "source": "deterministic",
                "confidence": "high",
                "reason": "clear match",
                "handoff_ready_question": True,
            },
            "answer_validation": {
                "handoff_check_attempted": True,
                "answered_previous_question": False,
            },
            "outcome": {
                "handoff_result": "stayed_in_activation",
                "bridge_success": False,
            },
        },
    )

    assert debug["activation_transition"]["before_state"]["activation_handoff_ready_before"] is True
    assert debug["activation_transition"]["question_validation"]["confidence"] == "high"
    assert debug["activation_transition"]["question_validation"]["handoff_ready_question"] is True
    assert debug["activation_transition"]["answer_validation"]["answered_previous_question"] is False
    assert debug["activation_transition"]["outcome"]["bridge_success"] is False


def test_apply_resolution_records_session_resolution_debug():
    assistant = PaixuejiAssistant(client=MagicMock())
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
        )
    )
    assert assistant.session_resolution_debug["surface_object_name"] == "cat food"
    assert assistant.session_resolution_debug["anchor_object_name"] == "cat"
    assert assistant.session_resolution_debug["anchor_status"] == "anchored_high"
