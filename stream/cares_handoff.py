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
