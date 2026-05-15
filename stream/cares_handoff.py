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
