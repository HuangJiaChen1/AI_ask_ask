import pytest

from category_activity import (
    CATEGORY_ACTIVITY_READY_TURN_THRESHOLD,
    build_category_debug,
    build_category_profile,
    classify_category_reply,
    evaluate_category_activity_readiness,
    start_category_session,
)


def test_build_category_profile_uses_known_domain_template():
    profile = build_category_profile("animals", "cat")

    assert profile.category_id == "animals"
    assert profile.category_label == "Animals"
    assert profile.domain == "animals"
    assert "animals" in profile.activity_target


def test_build_category_profile_falls_back_for_unknown_domain():
    profile = build_category_profile("mystery_domain", "thing")

    assert profile.category_id is None
    assert profile.category_label == "Category"
    assert profile.domain is None
    assert profile.activity_target == "exploring different kinds of things in our world"


@pytest.mark.parametrize(
    ("child_reply", "reply_type", "counted_turn", "state_action"),
    [
        ("I don't know", "uncertainty", False, "scaffold_category"),
        ("I don't want this", "constraint_avoidance", False, "low_pressure_repair"),
        ("Let's play a game", "activity_command", False, "acknowledge_keep_category"),
        ("Why do animals have tails?", "curiosity", True, "answer_and_reconnect"),
        ("Cars can race fast", "category_drift", True, "accept_comparison_keep_category"),
        ("I like dogs and cats", "aligned", True, "continue_category_lane"),
    ],
)
def test_classify_category_reply_handles_category_lane_cases(
    child_reply,
    reply_type,
    counted_turn,
    state_action,
):
    profile = build_category_profile("animals", "cat")
    state = start_category_session(object_name="cat", profile=profile, age=6)

    decision = classify_category_reply(state, child_reply)

    assert decision.reply_type == reply_type
    assert decision.category_id == "animals"
    assert decision.counted_turn is counted_turn
    assert decision.state_action == state_action


def test_category_readiness_uses_two_engaged_turn_threshold():
    profile = build_category_profile("animals", "cat")
    state = start_category_session(object_name="cat", profile=profile, age=6)

    first = classify_category_reply(state, "I like dogs too")
    if first.counted_turn:
        state.turn_count += 1
    first_ready = evaluate_category_activity_readiness(state, first)
    assert first_ready.activity_ready is False
    assert first_ready.engaged_turn_count == 1
    assert first_ready.readiness_threshold == CATEGORY_ACTIVITY_READY_TURN_THRESHOLD

    second = classify_category_reply(state, "Why do animals have fur?")
    if second.counted_turn:
        state.turn_count += 1
    second_ready = evaluate_category_activity_readiness(state, second)
    assert second_ready.activity_ready is True
    assert second_ready.chat_phase_complete is True
    assert second_ready.state_action == "invite_category_activity"


def test_build_category_debug_serializes_profile_state_reply_and_readiness():
    profile = build_category_profile("vehicles", "car")
    state = start_category_session(object_name="car", profile=profile, age=6)
    reply = classify_category_reply(state, "Cars can go fast")
    if reply.counted_turn:
        state.turn_count += 1
    readiness = evaluate_category_activity_readiness(state, reply)

    debug = build_category_debug(
        decision="category_activity",
        profile=profile,
        state=state,
        reason="child stayed in category lane",
        reply=reply,
        readiness=readiness,
        response_text="Cars are one kind of vehicle. What other vehicles do you know?",
    )

    assert debug["decision"] == "category_activity"
    assert debug["profile"]["category_id"] == "vehicles"
    assert debug["state"]["profile"]["category_label"] == "Vehicles"
    assert debug["reply"]["reply_type"] == "aligned"
    assert debug["readiness"]["engaged_turn_count"] == 1
    assert "What other vehicles do you know?" in debug["response_text"]
