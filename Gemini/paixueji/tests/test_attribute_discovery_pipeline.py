"""Tests for the LLM-driven attribute discovery pipeline.

Covers the public API contract: simplified session state, debug payload shape,
prompt invariants, and build_attribute_debug behavior.
"""

import pytest

from attribute_activity import (
    AttributeProfile,
    DiscoverySessionState,
    build_attribute_debug,
    start_attribute_session,
)
from paixueji_prompts import ATTRIBUTE_SOFT_GUIDE


def _make_profile(
    attribute_id: str = "appearance.body_color",
    label: str = "body color",
) -> AttributeProfile:
    return AttributeProfile(
        attribute_id=attribute_id,
        label=label,
        activity_target="noticing and describing what apple looks like — specifically, apple's body color",
        branch="in_kb",
        object_examples=("apple",),
    )


def _make_state() -> DiscoverySessionState:
    return start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )


# -- Session state -----------------------------------------------------------

def test_start_attribute_session_builds_state_with_all_fields():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=None,
        surface_object_name="red apple",
        anchor_object_name="apple",
    )

    assert state.object_name == "apple"
    assert state.profile.attribute_id == "appearance.body_color"
    assert state.age == 6
    assert state.turn_count == 0
    assert state.activity_ready is False
    assert state.surface_object_name == "red apple"
    assert state.anchor_object_name == "apple"


def test_start_attribute_session_preserves_explicit_zero_age():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=0)
    assert state.age == 0


def test_session_state_debug_dict_omits_heuristic_fields():
    debug = _make_state().to_debug_dict()

    for retired in ("substantive_turns", "attribute_touches", "intent_history", "touch_result", "readiness"):
        assert retired not in debug


def test_session_state_supports_simple_transitions():
    state = _make_state()

    state.turn_count += 1
    assert state.turn_count == 1
    assert state.activity_ready is False

    state.activity_ready = True
    assert state.activity_ready is True


# -- build_attribute_debug ---------------------------------------------------

def test_build_attribute_debug_includes_marker_flag():
    state = _make_state()
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="marker detected in follow-up",
        activity_marker_detected=True,
        response_text="Can you spot anything else around you that's bright red?",
        intent_type="correct_answer",
    )

    assert debug["decision"] == "attribute_activity"
    assert debug["activity_marker_detected"] is True
    assert debug["intent_type"] == "correct_answer"
    assert "touch_result" not in debug
    assert "readiness" not in debug


def test_build_attribute_debug_defaults_marker_flag_to_false():
    state = _make_state()
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
    )
    assert debug["activity_marker_detected"] is False


# -- ATTRIBUTE_SOFT_GUIDE invariants -----------------------------------------

def test_soft_guide_defines_marker_and_llm_decides_timing():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "[activity_ready]" in guide_lower
    assert "you feel" in guide_lower or "when you" in guide_lower


def test_soft_guide_requests_reason_line():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "reason:" in guide_lower
    assert "invisible to the child" in guide_lower


def test_soft_guide_rejects_hard_lock_and_quiz_patterns():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "must stay on" not in guide_lower
    assert "do not move on until" not in guide_lower


def test_soft_guide_warns_about_premature_handoff():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "premature" in guide_lower or "too early" in guide_lower or "shallow" in guide_lower
    assert "breaks the experience" in guide_lower or "break" in guide_lower
