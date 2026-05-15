from __future__ import annotations

from dataclasses import dataclass, field

from stream.exploration_angles import AngleCoverageRecord


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_INTEREST_FOR_HANDOFF = 60
MAX_SESSION_TURNS = 8
EXIT_LANE_INTEREST = 40


# ---------------------------------------------------------------------------
# Interest record
# ---------------------------------------------------------------------------
@dataclass
class AttributeInterestRecord:
    attribute_id: str

    # Basic exploration data
    turns_explored: int = 0
    first_turn_index: int = 0
    last_turn_index: int = 0
    is_current: bool = False

    # Proactive signals (most important)
    child_initiated_count: int = 0
    child_returned_count: int = 0

    # Engagement quality
    intent_history: list[str] = field(default_factory=list)
    elaboration_turns: int = 0
    question_count: int = 0
    emotional_count: int = 0

    # Negative signals
    struggle_count: int = 0
    avoidance_count: int = 0

    # Angle coverage (mirrors DiscoverySessionState)
    explored_angle_ids: list[str] = field(default_factory=list)
    angle_records: list[AngleCoverageRecord] = field(default_factory=list)


def compute_attribute_interest_score(record: AttributeInterestRecord) -> float:
    """Compute interest score for a single attribute (0-100)."""
    if record.turns_explored == 0:
        return 0.0

    # Base engagement (0-50)
    positive_intents = {
        "CORRECT_ANSWER",
        "INFORMATIVE",
        "CURIOSITY",
        "PLAY",
        "EMOTIONAL",
    }
    positive = sum(1 for it in record.intent_history if it in positive_intents)
    base = (positive / record.turns_explored) * 50

    # Initiation (0-30)
    initiation = min(
        record.child_initiated_count * 8 + record.child_returned_count * 15,
        30,
    )

    # Depth (0-25)
    depth = min(
        record.elaboration_turns * 4
        + record.question_count * 6
        + record.emotional_count * 5,
        25,
    )

    # Negative penalty
    penalty = min(
        record.struggle_count * 8 + record.avoidance_count * 12,
        35,
    )

    return max(0.0, base + initiation + depth - penalty)


def on_attribute_turn(
    assistant,
    child_input: str,
    intent_type: str,
    action_subtype: str | None,
    switch_result,
    turn_index: int,
) -> None:
    """Update the interest record for the current attribute after one turn.

    Args:
        assistant: The PaixuejiAssistant instance.
        child_input: Raw child input text.
        intent_type: Uppercase intent type from classify_intent.
        action_subtype: ACTION subtype (A/B/C/D) or None.
        switch_result: Object with `should_switch` and `target_attribute_id`.
        turn_index: Current turn index.
    """
    current_attr = assistant.attribute_state.profile.attribute_id
    records = assistant.attribute_interest_records

    # Get or create record
    if current_attr not in records:
        records[current_attr] = AttributeInterestRecord(attribute_id=current_attr)

    record = records[current_attr]

    # Initialize on first exploration
    if record.turns_explored == 0:
        record.first_turn_index = turn_index

    # Detect "return": previously explored and not currently active
    if record.turns_explored > 0 and not record.is_current:
        record.child_returned_count += 1

    # Basic data
    record.turns_explored += 1
    record.last_turn_index = turn_index
    record.intent_history.append(intent_type)
    record.is_current = True

    # Proactive: topic switch detector says child initiated this attribute
    if (
        switch_result.should_switch
        and switch_result.target_attribute_id == current_attr
    ):
        record.child_initiated_count += 1

    # Engagement quality
    if intent_type in ("INFORMATIVE", "CURIOSITY", "EMOTIONAL"):
        record.elaboration_turns += 1
    if any(marker in child_input for marker in ("?", "吗", "什么", "呢")):
        record.question_count += 1
    if intent_type == "EMOTIONAL":
        record.emotional_count += 1

    # Negative signals
    if intent_type in ("CLARIFYING_IDK", "CLARIFYING_WRONG"):
        record.struggle_count += 1
    if intent_type in ("AVOIDANCE", "BOUNDARY"):
        record.avoidance_count += 1
    if intent_type == "ACTION" and action_subtype in ("B", "C"):
        record.avoidance_count += 1

    # Sync angle coverage from DiscoverySessionState
    record.explored_angle_ids = list(assistant.attribute_state.explored_angle_ids)
    record.angle_records = list(assistant.attribute_state.angle_records)

    # Mark all other attributes as not current
    for attr_id, other_record in records.items():
        if attr_id != current_attr:
            other_record.is_current = False
