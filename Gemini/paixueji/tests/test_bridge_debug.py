from bridge_debug import (
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
            "anchor_status": "anchored_high",
            "bridge_attempt_count_after": 2,
        },
    )
    assert "session=abc" in line
    assert "request=req" in line
    assert "decision=bridge_retry" in line


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
