import pytest
from stream.cares_handoff import AttributeInterestRecord


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
