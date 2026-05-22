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
    # base=(3/3)*60=60; streak=min(3*5,20)=15 -> 75
    assert compute_attribute_interest_score(record) == 75.0


def test_compute_interest_score_with_question():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 3
    record.intent_history = ["CORRECT_ANSWER", "CORRECT_ANSWER", "CORRECT_ANSWER"]
    record.question_count = 1
    # base=60; depth=min(1*6,25)=6; streak=15 -> 81
    assert compute_attribute_interest_score(record) == 81.0


def test_compute_interest_score_child_returned():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CORRECT_ANSWER", "CORRECT_ANSWER"]
    record.child_initiated_count = 1
    record.child_returned_count = 1
    # base=(2/2)*60=60; initiation=min(1*8+1*15,30)=23; streak=10 -> 93
    assert compute_attribute_interest_score(record) == 93.0


def test_compute_interest_score_with_elaboration():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["INFORMATIVE", "CURIOSITY"]
    record.elaboration_turns = 2
    # base=(2/2)*60=60; depth=min(2*4,25)=8; streak=10 -> 78
    assert compute_attribute_interest_score(record) == 78.0


def test_compute_interest_score_struggle_penalty():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CLARIFYING_IDK", "CLARIFYING_WRONG"]
    record.struggle_count = 2
    # base=0; streak=10; penalty=min(2*4,35)=8 -> 2
    assert compute_attribute_interest_score(record) == 2.0


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
    # base=(2/2)*60=60; depth=min(1*4+1*5,25)=9; streak=10 -> 79
    assert compute_attribute_interest_score(record) == 79.0


def test_compute_interest_score_initiation_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["CORRECT_ANSWER"] * 10
    record.child_initiated_count = 10
    record.child_returned_count = 10
    # initiation=min(10*8+10*15,30)=30 (capped); streak=20
    score = compute_attribute_interest_score(record)
    assert score == 60.0 + 30.0 + 20.0  # base + initiation + streak


def test_compute_interest_score_depth_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["INFORMATIVE"] * 10
    record.elaboration_turns = 10
    record.question_count = 10
    record.emotional_count = 10
    # depth=min(10*4+10*6+10*5,25)=25 (capped); streak=20
    score = compute_attribute_interest_score(record)
    assert score == 60.0 + 25.0 + 20.0  # base + depth + streak


def test_compute_interest_score_penalty_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["CORRECT_ANSWER"] * 10
    record.struggle_count = 10
    record.avoidance_count = 10
    # penalty=min(10*4+10*12,35)=35 (capped)
    # base=60; streak=20; penalty=35 -> 45
    assert compute_attribute_interest_score(record) == 45.0


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
    primary_activity=None,
):
    assistant = SimpleNamespace()
    assistant.attribute_interest_records = interest_records or {}
    assistant.current_attribute_id = current_attr_id  # convenience
    state = SimpleNamespace()
    state.profile = SimpleNamespace(attribute_id=current_attr_id)
    state.turn_count = turn_count
    state.primary_activity = primary_activity
    state.verification_queue = []
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
        intent_history=["CORRECT_ANSWER"] * 4 + ["CLARIFYING_IDK"] * 4,
        is_current=True,
    )
    rec.struggle_count = 4
    # base=(4/8)*60=30; streak=20; penalty=min(4*4,35)=16; score=34 (below 40)
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
        intent_history=["CORRECT_ANSWER"] * 5 + ["CLARIFYING_IDK"] * 3,
        is_current=True,
    )
    rec.struggle_count = 3
    # base=(5/8)*60=37.5; streak=20; penalty=min(3*4,35)=12; score=45.5 (below 50, above 40)
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=8,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.EXIT_LANE
    assert "timeout_with_memory" in reason
    assert meta["best_attribute"] == "appearance.color"


def test_evaluate_handoff_handoff_now_with_primary_activity():
    """When interest >= threshold and primary_activity exists -> HANDOFF_NOW."""
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2  # score = 60 + 16 = 76 >= 50
    mock_activity = SimpleNamespace(
        activity_id="fluffy_expedition_dandelion",
        name="Find three fluffy friends",
        observation_angle="texture",
    )
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
        primary_activity=mock_activity,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.HANDOFF_NOW
    assert meta["target_attribute"] == "appearance.color"
    assert meta["activity"] is mock_activity
    assert meta["readiness_score"] >= 50


def test_evaluate_handoff_no_primary_activity_degrades_to_continue():
    """When interest >= threshold but no primary_activity -> CONTINUE."""
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2  # score >= 50
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
        primary_activity=None,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.CONTINUE
    assert "no_primary_activity" in reason


def test_evaluate_handoff_probe_for_pending_verification():
    """Pending verification blocks handoff even with high interest."""
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2

    mock_activity = SimpleNamespace(
        activity_id="fluffy_expedition_dandelion",
        name="Find three fluffy friends",
    )
    mock_verification = SimpleNamespace(
        status="pending",
        property="has_fluffy_fur",
        for_activity_id="fluffy_expedition_dandelion",
    )

    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
        primary_activity=mock_activity,
    )
    assistant.attribute_state.verification_queue = [mock_verification]

    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.PROBE
    assert "properties_pending_verification" in reason


def test_evaluate_handoff_rejected_verification_blocks_handoff():
    """Rejected verification for primary activity blocks handoff."""
    rec = AttributeInterestRecord(
        attribute_id="appearance.color",
        turns_explored=5,
        intent_history=["CORRECT_ANSWER"] * 5,
        is_current=True,
    )
    rec.child_initiated_count = 2

    mock_activity = SimpleNamespace(
        activity_id="fluffy_expedition_dandelion",
        name="Find three fluffy friends",
    )
    mock_verification = SimpleNamespace(
        status="rejected",
        property="has_fluffy_fur",
        for_activity_id="fluffy_expedition_dandelion",
    )

    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
        primary_activity=mock_activity,
    )
    assistant.attribute_state.verification_queue = [mock_verification]

    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.CONTINUE
    assert "primary_property_rejected" in reason


