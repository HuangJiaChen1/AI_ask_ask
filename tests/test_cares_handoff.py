import pytest
from types import SimpleNamespace
from stream.cares_handoff import AttributeInterestRecord, compute_attribute_interest_score, on_attribute_turn


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
    # base = (3/3)*50 = 50; initiation=0; depth=0; penalty=0 -> 50
    assert compute_attribute_interest_score(record) == 50.0


def test_compute_interest_score_with_question():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 3
    record.intent_history = ["CORRECT_ANSWER", "CORRECT_ANSWER", "CORRECT_ANSWER"]
    record.question_count = 1
    # base=50; initiation=0; depth=min(1*6,25)=6; penalty=0 -> 56
    assert compute_attribute_interest_score(record) == 56.0


def test_compute_interest_score_child_returned():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CORRECT_ANSWER", "CORRECT_ANSWER"]
    record.child_initiated_count = 1
    record.child_returned_count = 1
    # base=(2/2)*50=50; initiation=min(1*8+1*15,30)=23;
    # depth=0; penalty=0 -> 73
    assert compute_attribute_interest_score(record) == 73.0


def test_compute_interest_score_with_elaboration():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["INFORMATIVE", "CURIOSITY"]
    record.elaboration_turns = 2
    # base=(2/2)*50=50; initiation=0; depth=min(2*4,25)=8; penalty=0 -> 58
    assert compute_attribute_interest_score(record) == 58.0


def test_compute_interest_score_struggle_penalty():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CLARIFYING_IDK", "CLARIFYING_WRONG"]
    record.struggle_count = 2
    # base=0; initiation=0; depth=0; penalty=min(2*8,35)=16 -> 0 (clamped)
    assert compute_attribute_interest_score(record) == 0.0


def test_compute_interest_score_avoidance_penalty():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["AVOIDANCE", "BOUNDARY"]
    record.avoidance_count = 2
    # base=0; initiation=0; depth=0; penalty=min(2*12,35)=24 -> 0 (clamped)
    assert compute_attribute_interest_score(record) == 0.0


def test_compute_interest_score_emotional_bonus():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 2
    record.intent_history = ["CORRECT_ANSWER", "EMOTIONAL"]
    record.elaboration_turns = 1
    record.emotional_count = 1
    # base=(2/2)*50=50; initiation=0;
    # depth=min(1*4+1*5,25)=9; penalty=0 -> 59
    assert compute_attribute_interest_score(record) == 59.0


def test_compute_interest_score_initiation_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["CORRECT_ANSWER"] * 10
    record.child_initiated_count = 10
    record.child_returned_count = 10
    # initiation=min(10*8+10*15,30)=30 (capped)
    score = compute_attribute_interest_score(record)
    assert score == 50.0 + 30.0  # base + initiation


def test_compute_interest_score_depth_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["INFORMATIVE"] * 10
    record.elaboration_turns = 10
    record.question_count = 10
    record.emotional_count = 10
    # depth=min(10*4+10*6+10*5,25)=25 (capped)
    score = compute_attribute_interest_score(record)
    assert score == 50.0 + 25.0  # base + depth


def test_compute_interest_score_penalty_cap():
    record = AttributeInterestRecord(attribute_id="appearance.color")
    record.turns_explored = 10
    record.intent_history = ["CORRECT_ANSWER"] * 10
    record.struggle_count = 10
    record.avoidance_count = 10
    # penalty=min(10*8+10*12,35)=35 (capped)
    # base=50; penalty=35 -> 15
    assert compute_attribute_interest_score(record) == 15.0


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
