from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from stream.exploration_angles import AngleCoverageRecord

from activities import select_best_activity, SelectionResult, _attribute_to_angles, MIN_SCORE_FOR_HANDOFF

logger = logging.getLogger(__name__)


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


def compute_attribute_interest_score_breakdown(record: AttributeInterestRecord) -> dict[str, float]:
    """Return component breakdown of the interest score."""
    if record.turns_explored == 0:
        return {"base": 0.0, "initiation": 0.0, "depth": 0.0, "streak": 0.0, "penalty": 0.0, "total": 0.0}

    positive_intents = {
        "CORRECT_ANSWER", "INFORMATIVE", "CURIOSITY", "PLAY", "EMOTIONAL",
    }
    positive = sum(1 for it in record.intent_history if it in positive_intents)
    base = (positive / record.turns_explored) * 50

    initiation = min(record.child_initiated_count * 8 + record.child_returned_count * 15, 30)

    depth = min(record.elaboration_turns * 4 + record.question_count * 6 + record.emotional_count * 5, 25)

    streak = min(record.turns_explored * 5, 15)

    penalty = min(record.struggle_count * 8 + record.avoidance_count * 12, 35)

    total = max(0.0, base + initiation + depth + streak - penalty)
    return {
        "base": base,
        "initiation": initiation,
        "depth": depth,
        "streak": streak,
        "penalty": penalty,
        "total": total,
    }


def compute_attribute_interest_score(record: AttributeInterestRecord) -> float:
    """Compute interest score for a single attribute (0-100)."""
    return compute_attribute_interest_score_breakdown(record)["total"]


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


class HandoffDecision(Enum):
    CONTINUE = "continue"
    CONTINUE_SWITCH = "continue_switch"
    HANDOFF_NOW = "handoff_now"
    REENGAGE = "reengage"
    EXIT_LANE = "exit_lane"
    PROBE = "probe"


def evaluate_handoff(assistant, switch_result) -> tuple[HandoffDecision, str, dict[str, Any]]:
    """Evaluate handoff decision based on interest scores and session state."""
    records = assistant.attribute_interest_records
    total_turns = sum(r.turns_explored for r in records.values())

    # Compute scores for all attributes
    scored = [
        (aid, compute_attribute_interest_score(r))
        for aid, r in records.items()
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_attr, best_score = scored[0] if scored else (None, 0)
    current_attr = assistant.attribute_state.profile.attribute_id
    current_record = records.get(current_attr)
    current_score = compute_attribute_interest_score(current_record) if current_record else 0

    # Build conversation context for selection
    def _build_context() -> dict[str, Any]:
        # Map CARES attribute ID → Tag Block observation angles (not exploration angles)
        observation_angles = _attribute_to_angles(current_attr)
        dominant = observation_angles[0] if observation_angles else ""

        # Entity class from anchor object name for bound-activity eligibility
        anchor = getattr(assistant, "anchor_object_name", None)
        entity_info = {"entity_class": [anchor]} if anchor else None

        return {
            "dominant_angle": dominant,
            "secondary_angles": list(observation_angles),
            "angles": list(observation_angles),
            "entity_depth": "property_focused",
            "recent_activities": [],
            "entity_info": entity_info,
            "extracted_properties": None,
        }

    # 1. Severe disengagement -> REENGAGE
    if assistant.consecutive_struggle_count >= 3:
        logger.info("[gate_2_evaluate] decision=REENGAGE, reason=struggle_streak_3, pass=false")
        return HandoffDecision.REENGAGE, "struggle_streak_3", {}

    if total_turns >= 2 and current_score < 20:
        logger.info("[gate_2_evaluate] decision=REENGAGE, reason=critical_disengagement, pass=false")
        return HandoffDecision.REENGAGE, "critical_disengagement", {}

    # 2. Clear switch signal -> CONTINUE_SWITCH
    if switch_result.should_switch and switch_result.target_attribute_id:
        target = switch_result.target_attribute_id
        if any(aid == target for aid, _ in scored):
            logger.info("[gate_2_evaluate] decision=CONTINUE_SWITCH, reason=detector:%s, pass=true", target)
            return HandoffDecision.CONTINUE_SWITCH, f"detector:{target}", {
                "target_attribute": target,
                "reason": "child_showed_clear_interest",
            }

    # 3. Attribute meets threshold -> HANDOFF_NOW
    logger.info(
        "[gate_1_interest] score=%.0f, threshold=%d, pass=%s",
        best_score, MIN_INTEREST_FOR_HANDOFF, best_score >= MIN_INTEREST_FOR_HANDOFF,
    )
    if best_score >= MIN_INTEREST_FOR_HANDOFF:
        conversation_context = _build_context()

        selection = select_best_activity(
            attribute_id=best_attr,
            interest_score=best_score,
            age=assistant.age or 6,
            conversation_context=conversation_context,
        )
        activity = selection.activity

        logger.info(
            "[gate_3_activity_score] best_score=%.0f, threshold=%d, activity_id=%s, selector_score=%.0f, decision=%s, pass=%s",
            best_score,
            MIN_SCORE_FOR_HANDOFF,
            selection.activity.activity_id if selection.activity else None,
            selection.selector_score,
            selection.decision,
            selection.activity is not None and selection.selector_score >= MIN_SCORE_FOR_HANDOFF,
        )

        # Gate 3b: Verification status check
        verification_queue = getattr(
            getattr(assistant, "attribute_state", None), "verification_queue", None
        )
        if verification_queue:
            pending = [v for v in verification_queue if v.status == "pending"]
            primary_activity = getattr(
                getattr(assistant, "attribute_state", None), "primary_activity", None
            )
            primary_activity_id = primary_activity.activity_id if primary_activity else None
            if primary_activity_id:
                rejected_for_primary = [
                    v for v in verification_queue
                    if v.status == "rejected" and v.for_activity_id == primary_activity_id
                ]
                if rejected_for_primary:
                    return HandoffDecision.CONTINUE, "primary_property_rejected", {
                        "target_attribute": best_attr,
                        "rejected_properties": [v.property for v in rejected_for_primary],
                        "readiness_score": best_score,
                    }

            if pending:
                return HandoffDecision.PROBE, "properties_pending_verification", {
                    "target_attribute": best_attr,
                    "pending_properties": [v.property for v in pending],
                    "readiness_score": best_score,
                }

        if activity:
            if best_attr == current_attr:
                return HandoffDecision.HANDOFF_NOW, f"current_best:{best_score:.0f}", {
                    "target_attribute": best_attr,
                    "activity": activity,
                    "readiness_score": best_score,
                    "selection_result": selection,
                }

            if current_score >= 50:
                current_selection = select_best_activity(
                    attribute_id=current_attr,
                    interest_score=current_score,
                    age=assistant.age or 6,
                    conversation_context=conversation_context,
                )
                current_activity = current_selection.activity
                if current_activity:
                    return HandoffDecision.HANDOFF_NOW, f"current_good:{current_score:.0f}", {
                        "target_attribute": current_attr,
                        "activity": current_activity,
                        "readiness_score": current_score,
                        "note": f"global_best_is_{best_attr}_but_current_is_good_enough",
                        "selection_result": current_selection,
                    }

            return HandoffDecision.HANDOFF_NOW, f"global_best:{best_attr}:{best_score:.0f}", {
                "target_attribute": best_attr,
                "activity": activity,
                "readiness_score": best_score,
                "current_attribute": current_attr,
                "bridge_context": f"child_previously_explored_{best_attr}_with_score_{best_score:.0f}",
                "selection_result": selection,
            }

        # Selection returned no activity -> degrade to CONTINUE
        logger.info(
            "[gate_2_evaluate] decision=CONTINUE, reason=no_activity_for_best:%.0f, pass=false",
            best_score,
        )
        return HandoffDecision.CONTINUE, f"no_activity_for_best:{best_score:.0f}", {
            "current_attribute": current_attr,
            "current_score": current_score,
            "best_attribute": best_attr,
            "best_score": best_score,
            "selection_result": selection,
        }

    # 4. Session timeout without threshold met -> EXIT_LANE
    if total_turns >= MAX_SESSION_TURNS:
        if best_score >= EXIT_LANE_INTEREST:
            logger.info(
                "[gate_2_evaluate] decision=EXIT_LANE, reason=timeout_with_memory:%s:%.0f, pass=true",
                best_attr, best_score,
            )
            return HandoffDecision.EXIT_LANE, f"timeout_with_memory:{best_attr}:{best_score:.0f}", {
                "best_attribute": best_attr,
                "best_score": best_score,
                "reason": "session_long_but_interest_detected",
            }
        else:
            logger.info("[gate_2_evaluate] decision=EXIT_LANE, reason=timeout_no_interest, pass=false")
            return HandoffDecision.EXIT_LANE, "timeout_no_interest", {
                "reason": "session_long_no_meaningful_interest",
            }

    # 5. Default: continue
    logger.info(
        "[gate_2_evaluate] decision=CONTINUE, reason=building:%.0f, pass=false",
        current_score,
    )
    return HandoffDecision.CONTINUE, f"building:{current_score:.0f}", {
        "current_attribute": current_attr,
        "current_score": current_score,
        "best_attribute": best_attr,
        "best_score": best_score,
    }
