import pytest
from types import SimpleNamespace
from stream.cares_handoff import (
    AttributeInterestRecord,
    compute_attribute_interest_score,
    on_attribute_turn,
    HandoffDecision,
    evaluate_handoff,
    MIN_INTEREST_FOR_HANDOFF,
)


def test_attribute_interest_record_defaults():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    assert record.attribute_id == "appearance.color"
    assert record.turns_explored == 0
    assert record.first_turn_index == 0
    assert record.last_turn_index == 0
    assert record.is_current is False
    assert record.child_initiated_count == 0
    assert record.child_returned_count == 0
    assert record.intent_history == []
    assert record.elaboration_turns == 0
    assert record.question_count == 0
    assert record.emotional_count == 0
    assert record.struggle_count == 0
    assert record.avoidance_count == 0
    assert record.explored_angle_ids == []
    assert record.angle_records == []


def test_compute_interest_score_empty_record():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    assert compute_attribute_interest_score(record) == 0.0


def test_compute_interest_score_all_correct_answers():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 3
    record.intent_history = ["CORRECT_ANSWER", "CORRECT_ANSWER", "CORRECT_ANSWER"]
    # base=(3/3)*50=50; streak=min(3*5,15)=15 -> 65
    assert compute_attribute_interest_score(record) == 65.0


def test_compute_interest_score_with_question():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 3
    record.intent_history = ["CORRECT_ANSWER", "CORRECT_ANSWER", "CORRECT_ANSWER"]
    record.question_count = 1
    # base=50; depth=min(1*6,25)=6; streak=15 -> 71
    assert compute_attribute_interest_score(record) == 71.0


def test_compute_interest_score_child_returned():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CORRECT_ANSWER", "CORRECT_ANSWER"]
    record.child_initiated_count = 1
    record.child_returned_count = 1
    # base=(2/2)*50=50; initiation=min(1*8+1*15,30)=23; streak=10 -> 83
    assert compute_attribute_interest_score(record) == 83.0


def test_compute_interest_score_with_elaboration():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["INFORMATIVE", "CURIOSITY"]
    record.elaboration_turns = 2
    # base=(2/2)*50=50; depth=min(2*4,25)=8; streak=10 -> 68
    assert compute_attribute_interest_score(record) == 68.0


def test_compute_interest_score_struggle_penalty():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CLARIFYING_IDK", "CLARIFYING_WRONG"]
    record.struggle_count = 2
    # base=0; streak=10; penalty=min(2*8,35)=16 -> 0 (clamped)
    assert compute_attribute_interest_score(record) == 0.0


def test_compute_interest_score_avoidance_penalty():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["AVOIDANCE", "BOUNDARY"]
    record.avoidance_count = 2
    # base=0; streak=10; penalty=min(2*12,35)=24 -> 0 (clamped)
    assert compute_attribute_interest_score(record) == 0.0


def test_compute_interest_score_emotional_bonus():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CORRECT_ANSWER", "EMOTIONAL"]
    record.elaboration_turns = 1
    record.emotional_count = 1
    # base=(2/2)*50=50; depth=min(1*4+1*5,25)=9; streak=10 -> 69
    assert compute_attribute_interest_score(record) == 69.0


def test_compute_interest_score_initiation_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["CORRECT_ANSWER"] * 10
    record.child_initiated_count = 10
    record.child_returned_count = 10
    # initiation=min(10*8+10*15,30)=30 (capped); streak=15
    score = compute_attribute_interest_score(record)
    assert score == 50.0 + 30.0 + 15.0  # base + initiation + streak


def test_compute_interest_score_depth_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["INFORMATIVE"] * 10
    record.elaboration_turns = 10
    record.question_count = 10
    record.emotional_count = 10
    # depth=min(10*4+10*6+10*5,25)=25 (capped); streak=15
    score = compute_attribute_interest_score(record)
    assert score == 50.0 + 25.0 + 15.0  # base + depth + streak


def test_compute_interest_score_penalty_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["CORRECT_ANSWER"] * 10
    record.struggle_count = 10
    record.avoidance_count = 10
    # penalty=min(10*8+10*12,35)=35 (capped)
    # base=50; streak=15; penalty=35 -> 30
    assert compute_attribute_interest_score(record) == 30.0


def _make_assistant_with_state(current_attr_id: str, explored_angle_ids: list = None):
    """Build a minimal mock assistant for testing."""
    assistant = SimpleNamespace()
    assistant.attribute_interest_records = {}
    state = SimpleNamespace()
    state.profile = SimpleNamespace(attribute_id=current_attr_id)
    state.explored_angle_ids = explored_angle_ids or []
    state.angle_records = []
    assistant.attribute_state = state
    assistant.consecutive_struggle_count = 0
    return assistant


def test_on_attribute_turn_creates_record():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(
        assistant=assistant,
        child_input="红色",
        intent_type="CORRECT_ANSWER",
        action_subtype=None,
        switch_result=switch,
        turn_index=1,
    )
    assert "appearance.color" in assistant.attribute_interest_records
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.turns_explored == 1
    assert record.first_turn_index == 1
    assert record.is_current is True


def test_on_attribute_turn_updates_turns():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(assistant, "红色", "CORRECT_ANSWER", None, switch, 1)
    on_attribute_turn(assistant, "亮红色", "CORRECT_ANSWER", None, switch, 2)
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.turns_explored == 2
    assert record.last_turn_index == 2


def test_on_attribute_turn_detects_question():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(assistant, "这是什么颜色吗？", "CURIOSITY", None, switch, 1)
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.question_count == 1


def test_on_attribute_turn_detects_return():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    # Explore color for 2 turns
    on_attribute_turn(assistant, "红色", "CORRECT_ANSWER", None, switch, 1)
    on_attribute_turn(assistant, "亮红色", "CORRECT_ANSWER", None, switch, 2)

    # Switch to shape
    assistant.attribute_state.profile.attribute_id = "appearance.shape"
    on_attribute_turn(assistant, "圆形", "CORRECT_ANSWER", None, switch, 3)

    # Return to color
    assistant.attribute_state.profile.attribute_id = "appearance.color"
    on_attribute_turn(assistant, "还是红色", "CORRECT_ANSWER", None, switch, 4)

    color_record = assistant.attribute_interest_records["appearance.color"]
    assert color_record.child_returned_count == 1
    assert color_record.turns_explored == 3  # 2 + 1 return


def test_on_attribute_turn_detects_initiation_via_switch():
    assistant = _make_assistant_with_state("appearance.color")
    # Child initiates switch TO color
    switch = SimpleNamespace(should_switch=True, target_attribute_id="appearance.color")
    on_attribute_turn(assistant, "说说颜色吧", "CORRECT_ANSWER", None, switch, 1)
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.child_initiated_count == 1


def test_on_attribute_turn_syncs_angles():
    assistant = _make_assistant_with_state("appearance.color", explored_angle_ids=["observation"])
    assistant.attribute_state.angle_records = [
        SimpleNamespace(angle_id="observation", turn_index=1, question_text="Q", response_text="R")
    ]
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(assistant, "红色", "CORRECT_ANSWER", None, switch, 1)
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.explored_angle_ids == ["observation"]


def test_on_attribute_turn_marks_other_attrs_not_current():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(assistant, "红色", "CORRECT_ANSWER", None, switch, 1)
    # Switch to shape
    assistant.attribute_state.profile.attribute_id = "appearance.shape"
    on_attribute_turn(assistant, "圆形", "CORRECT_ANSWER", None, switch, 2)
    color_record = assistant.attribute_interest_records["appearance.color"]
    assert color_record.is_current is False
    shape_record = assistant.attribute_interest_records["appearance.shape"]
    assert shape_record.is_current is True


def test_on_attribute_turn_counts_struggle():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(assistant, "不知道", "CLARIFYING_IDK", None, switch, 1)
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.struggle_count == 1


def test_on_attribute_turn_counts_avoidance():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(assistant, "不想聊这个", "AVOIDANCE", None, switch, 1)
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.avoidance_count == 1


def test_on_attribute_turn_action_bc_counts_avoidance():
    assistant = _make_assistant_with_state("appearance.color")
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    on_attribute_turn(assistant, "换一个", "ACTION", "B", switch, 1)
    record = assistant.attribute_interest_records["appearance.color"]
    assert record.avoidance_count == 1


def _make_assistant_for_handoff(
    current_attr_id="appearance.color",
    interest_records: dict | None = None,
    turn_count: int = 1,
    consecutive_struggle: int = 0,
    age: int = 6,
):
    assistant = SimpleNamespace()
    assistant.attribute_interest_records = interest_records or {}
    assistant.current_attribute_id = current_attr_id  # convenience
    state = SimpleNamespace()
    state.profile = SimpleNamespace(attribute_id=current_attr_id)
    state.turn_count = turn_count
    assistant.attribute_state = state
    assistant.consecutive_struggle_count = consecutive_struggle
    assistant.age = age
    return assistant


def test_evaluate_handoff_continue_default():
    assistant = _make_assistant_for_handoff(
        interest_records={
            "appearance.color": AttributeInterestRecord(
                attribute_id="appearance.color",
                turns_explored=2,
                intent_history=["CORRECT_ANSWER", "CORRECT_ANSWER"],
                is_current=True,
            )
        }
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.CONTINUE


def test_evaluate_handoff_engage_struggle_streak():
    assistant = _make_assistant_for_handoff(
        consecutive_struggle=3,
        interest_records={
            "appearance.color": AttributeInterestRecord(
                attribute_id="appearance.color", turns_explored=3, is_current=True
            )
        },
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.REENGAGE
    assert "struggle_streak_3" in reason


def test_evaluate_handoff_critical_disengagement():
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=2,
        intent_history=["CLARIFYING_IDK", "AVOIDANCE"],
        is_current=True,
    )
    rec.struggle_count = 1
    rec.avoidance_count = 1
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=2,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.REENGAGE
    assert "critical_disengagement" in reason


def test_evaluate_handoff_continue_switch():
    assistant = _make_assistant_for_handoff(
        interest_records={
            "appearance.color": AttributeInterestRecord(
                attribute_id="appearance.color", turns_explored=1, is_current=True
            ),
            "appearance.shape": AttributeInterestRecord(
                attribute_id="appearance.shape", turns_explored=0, is_current=False
            ),
        }
    )
    switch = SimpleNamespace(should_switch=True, target_attribute_id="appearance.shape")
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.CONTINUE_SWITCH
    assert meta["target_attribute"] == "appearance.shape"


def test_evaluate_handoff_exit_lane_timeout_no_interest():
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=8,
        intent_history=["CORRECT_ANSWER"] * 6 + ["CLARIFYING_IDK"] * 2,
        is_current=True,
    )
    rec.struggle_count = 2
    # base=(6/8)*50=37.5; penalty=min(2*8,35)=16; score=21.5 (above 20, below 40)
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=8,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.EXIT_LANE
    assert "timeout_no_interest" in reason


def test_evaluate_handoff_exit_lane_timeout_with_memory():
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=8,
        intent_history=["CORRECT_ANSWER"] * 7 + ["CLARIFYING_IDK"],
        is_current=True,
    )
    rec.struggle_count = 1
    # base=(7/8)*50=43.75; streak=15; penalty=8 -> 50.75 (below 60, above 40)
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=8,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.EXIT_LANE
    assert "timeout_with_memory" in reason
    assert meta["best_attribute"] == "appearance.color"


def test_evaluate_handoff_handoff_now_current_best():
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2  # +16 initiation, score = 50 + 16 = 66 >= 60
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    # Mock select_best_activity returning a matched SelectionResult
    from unittest.mock import patch
    mock_activity = SimpleNamespace(activity_id="act1", name="Test", launch_prompt="Go!")
    mock_result = SimpleNamespace(
        activity=mock_activity,
        selector_score=75.0,
        decision="matched",
        fallback_reason=None,
    )
    with patch("stream.cares_handoff.select_best_activity", return_value=mock_result):
        decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.HANDOFF_NOW
    assert meta["target_attribute"] == "appearance.color"


def test_evaluate_handoff_handoff_now_no_activity_degrades_to_continue():
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    from unittest.mock import patch
    mock_result = SimpleNamespace(
        activity=None,
        selector_score=45.0,
        decision="none",
        fallback_reason="score_below_threshold",
    )
    with patch("stream.cares_handoff.select_best_activity", return_value=mock_result):
        decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.CONTINUE
    assert "no_activity_for_best" in reason


# ── Fix 1 regression: _build_context must pass observation angles and entity_info ──

def _make_assistant_for_fix1(
    current_attr_id="appearance.covering",
    interest_records=None,
    current_angle_id="observation",
    explored_angle_ids=None,
    anchor_object_name="cat",
    age=6,
):
    assistant = _make_assistant_for_handoff(
        current_attr_id=current_attr_id,
        interest_records=interest_records,
        age=age,
    )
    assistant.anchor_object_name = anchor_object_name
    assistant.attribute_state.current_angle_id = current_angle_id
    assistant.attribute_state.explored_angle_ids = explored_angle_ids or []
    return assistant


def test_evaluate_handoff_observation_angles_and_entity_info_for_cat_covering():
    """
    Regression: _build_context() was passing exploration angles
    (observation, comparison) where observation angles (pattern, texture)
    were expected, and entity_info was hardcoded to None.

    For appearance.covering on a cat object with interest ~66,
    this caused select_best_activity to score the best activity at
    only 48 points, degrading HANDOFF_NOW to CONTINUE.
    """
    record = AttributeInterestRecord(
        attribute_id="appearance.covering",
        turns_explored=6,
        first_turn_index=1,
        last_turn_index=6,
        is_current=True,
        intent_history=["CURIOSITY", "INFORMATIVE", "CURIOSITY", "CORRECT_ANSWER", "INFORMATIVE", "CURIOSITY"],
        elaboration_turns=6,
        question_count=3,
        emotional_count=0,
        explored_angle_ids=["observation", "comparison", "preference"],
    )
    interest_score = compute_attribute_interest_score(record)
    assert interest_score >= 60, f"Expected interest >= 60, got {interest_score}"

    assistant = _make_assistant_for_fix1(
        current_attr_id="appearance.covering",
        interest_records={"appearance.covering": record},
        current_angle_id="observation",
        explored_angle_ids=["observation", "comparison", "preference"],
        anchor_object_name="cat",
        age=6,
    )

    from unittest.mock import patch
    captured_contexts = []

    def capture_select_best_activity(*, attribute_id, interest_score, age, conversation_context):
        captured_contexts.append(conversation_context)
        mock_activity = SimpleNamespace(activity_id="test_activity", name="Test", launch_prompt="Go!")
        return SimpleNamespace(
            activity=mock_activity,
            selector_score=75.0,
            decision="matched",
            fallback_reason=None,
        )

    with patch("stream.cares_handoff.select_best_activity", side_effect=capture_select_best_activity):
        decision, reason, meta = evaluate_handoff(assistant, SimpleNamespace(should_switch=False, target_attribute_id=None))

    assert decision == HandoffDecision.HANDOFF_NOW, (
        f"Expected HANDOFF_NOW for interest={interest_score:.0f}, got {decision.value} "
        f"with reason={reason}"
    )
    assert meta.get("activity") is not None, "Expected an activity to be selected"
    assert len(captured_contexts) >= 1
    ctx = captured_contexts[0]
    assert "pattern" in ctx.get("angles", []), f"angles should contain 'pattern', got {ctx.get('angles')}"
    assert ctx.get("entity_info") == {"entity_class": ["cat"]}, (
        f"entity_info should contain cat class, got {ctx.get('entity_info')}"
    )


def test_evaluate_handoff_bound_activity_eligible_with_entity_class():
    """
    dream_whisperer_cat requires entity_class: ["cat"].
    When anchor_object_name is "cat", entity_info must contain
    {"entity_class": ["cat"]} so the bound activity is eligible.
    """
    record = AttributeInterestRecord(
        attribute_id="emotion.state",
        turns_explored=6,
        first_turn_index=1,
        last_turn_index=6,
        is_current=True,
        intent_history=["EMOTIONAL", "INFORMATIVE", "EMOTIONAL", "CORRECT_ANSWER", "EMOTIONAL", "CURIOSITY"],
        elaboration_turns=6,
        emotional_count=3,
        explored_angle_ids=["observation", "comparison"],
    )
    interest_score = compute_attribute_interest_score(record)
    assert interest_score >= 60, f"Expected interest >= 60, got {interest_score}"

    assistant = _make_assistant_for_fix1(
        current_attr_id="emotion.state",
        interest_records={"emotion.state": record},
        anchor_object_name="cat",
        age=6,
    )

    from unittest.mock import patch
    captured_contexts = []

    def capture_select_best_activity(*, attribute_id, interest_score, age, conversation_context):
        captured_contexts.append(conversation_context)
        # Return a mock activity so evaluate_handoff returns HANDOFF_NOW
        mock_activity = SimpleNamespace(activity_id="dream_whisperer_cat", name="Test", launch_prompt="Go!")
        return SimpleNamespace(
            activity=mock_activity,
            selector_score=75.0,
            decision="matched",
            fallback_reason=None,
        )

    with patch("stream.cares_handoff.select_best_activity", side_effect=capture_select_best_activity):
        decision, reason, meta = evaluate_handoff(assistant, SimpleNamespace(should_switch=False, target_attribute_id=None))

    assert decision == HandoffDecision.HANDOFF_NOW
    assert len(captured_contexts) >= 1
    ctx = captured_contexts[0]
    assert ctx.get("entity_info") == {"entity_class": ["cat"]}, (
        f"entity_info should contain cat class, got {ctx.get('entity_info')}"
    )
    assert "emotion" in ctx.get("angles", []), (
        f"angles should contain observation angle 'emotion', got {ctx.get('angles')}"
    )
    assert ctx.get("dominant_angle") == "emotion", (
        f"dominant_angle should be 'emotion', got {ctx.get('dominant_angle')}"
    )
