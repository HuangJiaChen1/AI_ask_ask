"""Tests for exploration angle pool and selection logic."""

import pytest
from stream.exploration_angles import (
    EXPLORATION_ANGLES,
    PHYSICAL_DIMENSIONS,
    AngleCoverageRecord,
    select_next_angle,
)


def test_select_next_angle_returns_first_for_empty_explored():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=0)
    assert result["angle_id"] == "observation"


def test_select_next_angle_cycles_after_all_used():
    physical_ids = [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]
    result = select_next_angle(explored_angle_ids=physical_ids, dimension="appearance", interest_score=0)
    # All used; should cycle to first (skip-last logic doesn't apply when all are used)
    assert result["angle_id"] == "observation"


def test_select_next_angle_skips_last_when_all_used():
    physical_ids = [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]
    result = select_next_angle(
        explored_angle_ids=physical_ids + ["observation"],  # observation was just used
        dimension="appearance",
        interest_score=0,
    )
    # observation was most recent; skip it if possible
    assert result["angle_id"] != "observation"


def test_select_next_angle_low_interest_restricts_angles():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=20)
    # < 30 should only return observation or comparison
    assert result["angle_id"] in ("observation", "comparison")


def test_select_next_angle_medium_interest_excludes_causal():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=40)
    # 30-55 should exclude causal
    assert result["angle_id"] != "causal"


def test_select_next_angle_high_interest_unlocks_all():
    result = select_next_angle(explored_angle_ids=[], dimension="appearance", interest_score=60)
    # >= 55 should unlock all including causal
    assert result["angle_id"] in [a["angle_id"] for a in EXPLORATION_ANGLES["physical"]]


def test_select_next_angle_uses_engagement_pool_for_emotion():
    result = select_next_angle(explored_angle_ids=[], dimension="emotion", interest_score=0)
    assert result["angle_id"] in [a["angle_id"] for a in EXPLORATION_ANGLES["engagement"]]


def test_select_next_angle_no_consecutive_repeat():
    explored = []
    prev = None
    for _ in range(10):
        angle = select_next_angle(explored_angle_ids=explored, dimension="appearance", interest_score=0)
        if prev is not None:
            assert angle["angle_id"] != prev, f"angle {angle['angle_id']} repeated consecutively"
        explored.append(angle["angle_id"])
        prev = angle["angle_id"]


def test_angle_coverage_record_dataclass():
    record = AngleCoverageRecord(
        angle_id="observation",
        turn_index=1,
        question_text="What color do you see?",
        response_text="It is red!",
    )
    assert record.angle_id == "observation"
    assert record.turn_index == 1
