# CARES Phase 1: 核心评分系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现跨轮次兴趣评分档案 (`AttributeInterestRecord`) 和 handoff 决策引擎 (`evaluate_handoff`)，接入现有属性管道驱动角度解锁和 prompt 状态显示。

**Architecture:** 在 `stream/cares_handoff.py` 中实现纯函数式的评分与决策逻辑（无 LLM 依赖，可单元测试）。`PaixuejiAssistant` 持有 `attribute_interest_records` 字典。`paixueji_app.py` 的 `stream_attribute_activity` 每轮调用 `on_attribute_turn` 更新档案，然后用真实兴趣分驱动 `select_next_angle`，并将 `evaluate_handoff` 的决策注入 prompt。保留现有 `[ACTIVITY_READY]` 验证逻辑作为安全网。

**Tech Stack:** Python 3.12, dataclasses, pytest, 现有 Flask SSE 流式管道

---

## File Structure

| File | Responsibility |
|------|---------------|
| `stream/cares_handoff.py` (new) | `AttributeInterestRecord`, `compute_attribute_interest_score`, `on_attribute_turn`, `HandoffDecision`, `evaluate_handoff`, 常量 |
| `stream/__init__.py` (modify) | 导出 cares_handoff 符号 |
| `paixueji_assistant.py` (modify) | 新增 `attribute_interest_records` 字段 |
| `paixueji_app.py` (modify) | 接入评分更新、角度选择、决策注入 prompt |
| `tests/test_cares_handoff.py` (new) | 评分公式和决策引擎的 20+ 单元测试 |
| `tests/test_attribute_activity_pipeline.py` (modify) | 验证 assistant 初始化时兴趣记录为空 |

---

## Pre-Read: Existing Code Patterns

Before starting, read these existing files to understand current patterns:
- `stream/exploration_angles.py` — `AngleCoverageRecord`, `EXPLORATION_ANGLES`, `select_next_angle`
- `attribute_activity.py` — `DiscoverySessionState`, `AttributeProfile`
- `paixueji_assistant.py` — `PaixuejiAssistant.__init__`, `clear_attribute_lane`, `switch_attribute_topic`
- `paixueji_app.py` lines 65-137 — `_build_angle_aware_guide`; lines 1395-1715 — `stream_attribute_activity`

---

## Task 1: `AttributeInterestRecord` Dataclass

**Files:**
- Create: `stream/cares_handoff.py`
- Test: `tests/test_cares_handoff.py`

**Background:** Each explored attribute needs a persistent interest profile that survives attribute switches. This dataclass tracks turns, intent history, proactive signals, and angle coverage.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cares_handoff.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cares_handoff.py::test_attribute_interest_record_defaults -v`
Expected: FAIL with "ImportError: cannot import name 'AttributeInterestRecord'"

- [ ] **Step 3: Write minimal implementation**

```python
# stream/cares_handoff.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cares_handoff.py::test_attribute_interest_record_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stream/cares_handoff.py tests/test_cares_handoff.py
git commit -m "feat: add AttributeInterestRecord dataclass for CARES Phase 1"
```

---

## Task 2: `compute_attribute_interest_score`

**Files:**
- Modify: `stream/cares_handoff.py`
- Test: `tests/test_cares_handoff.py`

**Background:** The score formula has four components: base engagement (0-50), initiation (0-30), depth (0-25), and penalty (up to 35). The key property is that it is the ONLY handoff threshold — no hard turn count.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cares_handoff.py (append)
from stream.cares_handoff import compute_attribute_interest_score


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
    record.intent_history = ["CORRECT_ANSWER", "EMOTIONAL"]
    record.child_initiated_count = 1
    record.child_returned_count = 1
    # base=(2/2)*50=50; initiation=min(1*8+1*15,30)=23;
    # depth=min(1*5,25)=5; penalty=0 -> 78
    assert compute_attribute_interest_score(record) == 78.0


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cares_handoff.py -k "test_compute_interest_score" -v`
Expected: All FAIL with "ImportError: cannot import name 'compute_attribute_interest_score'"

- [ ] **Step 3: Write minimal implementation**

```python
# stream/cares_handoff.py (append after AttributeInterestRecord)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cares_handoff.py -k "test_compute_interest_score" -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add stream/cares_handoff.py tests/test_cares_handoff.py
git commit -m "feat: compute_attribute_interest_score with full test coverage"
```

---

## Task 3: `on_attribute_turn` — Per-Turn Update Logic

**Files:**
- Modify: `stream/cares_handoff.py`
- Test: `tests/test_cares_handoff.py`

**Background:** This function is called once per attribute pipeline turn. It finds or creates the `AttributeInterestRecord` for the current attribute and updates all counters. It also detects "returns" (child coming back to a previously explored attribute) and syncs angle coverage from `DiscoverySessionState`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cares_handoff.py (append)
from types import SimpleNamespace
from stream.cares_handoff import on_attribute_turn


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cares_handoff.py -k "test_on_attribute_turn" -v`
Expected: All FAIL with "ImportError: cannot import name 'on_attribute_turn'"

- [ ] **Step 3: Write minimal implementation**

```python
# stream/cares_handoff.py (append after compute_attribute_interest_score)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cares_handoff.py -k "test_on_attribute_turn" -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add stream/cares_handoff.py tests/test_cares_handoff.py
git commit -m "feat: on_attribute_turn per-turn interest record update"
```

---

## Task 4: `HandoffDecision` Enum + `evaluate_handoff`

**Files:**
- Modify: `stream/cares_handoff.py`
- Test: `tests/test_cares_handoff.py`

**Background:** The decision engine is the heart of CARES. It evaluates 5 possible decisions based on interest scores, struggle streaks, topic switches, and session length. Phase 1 uses the existing `get_activity_for_attribute` for activity matching (full `select_best_activity` comes in Phase 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cares_handoff.py (append)
from stream.cares_handoff import HandoffDecision, evaluate_handoff, MIN_INTEREST_FOR_HANDOFF


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
        intent_history=["CORRECT_ANSWER"] * 4 + ["CLARIFYING_IDK"] * 4,
        is_current=True,
    )
    rec.struggle_count = 4
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
        intent_history=["CORRECT_ANSWER"] * 8,
        is_current=True,
    )
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
    assistant = _make_assistant_for_handoff(
        interest_records={"appearance.color": rec},
        turn_count=5,
        age=6,
    )
    switch = SimpleNamespace(should_switch=False, target_attribute_id=None)
    # Need to mock get_activity_for_attribute — we'll patch it
    from unittest.mock import patch
    with patch("stream.cares_handoff.get_activity_for_attribute", return_value=SimpleNamespace(activity_id="act1")):
        decision, reason, meta = evaluate_handoff(assistant, switch)
    assert decision == HandoffDecision.HANDOFF_NOW
    assert meta["target_attribute"] == "appearance.color"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cares_handoff.py -k "test_evaluate_handoff" -v`
Expected: All FAIL with ImportError for HandoffDecision / evaluate_handoff

- [ ] **Step 3: Write minimal implementation**

```python
# stream/cares_handoff.py (append at end)

from enum import Enum
from typing import Any

from activities import get_activity_for_attribute


class HandoffDecision(Enum):
    CONTINUE = "continue"
    CONTINUE_SWITCH = "continue_switch"
    HANDOFF_NOW = "handoff_now"
    REENGAGE = "reengage"
    EXIT_LANE = "exit_lane"


def evaluate_handoff(assistant, switch_result) -> tuple[HandoffDecision, str, dict[str, Any]]:
    """Evaluate handoff decision based on interest scores and session state.

    Returns: (decision, reason_string, metadata_dict)
    """
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

    # 1. Severe disengagement -> REENGAGE
    if assistant.consecutive_struggle_count >= 3:
        return HandoffDecision.REENGAGE, "struggle_streak_3", {}

    if total_turns >= 2 and current_score < 20:
        return HandoffDecision.REENGAGE, "critical_disengagement", {}

    # 2. Clear switch signal -> CONTINUE_SWITCH
    if switch_result.should_switch and switch_result.target_attribute_id:
        target = switch_result.target_attribute_id
        if any(aid == target for aid, _ in scored):
            return HandoffDecision.CONTINUE_SWITCH, f"detector:{target}", {
                "target_attribute": target,
                "reason": "child_showed_clear_interest",
            }

    # 3. Attribute meets threshold -> HANDOFF_NOW
    if best_score >= MIN_INTEREST_FOR_HANDOFF:
        activity = get_activity_for_attribute(best_attr, assistant.age or 6)
        if activity:
            if best_attr == current_attr:
                return HandoffDecision.HANDOFF_NOW, f"current_best:{best_score:.0f}", {
                    "target_attribute": best_attr,
                    "activity": activity,
                    "readiness_score": best_score,
                }

            if current_score >= 50:
                current_activity = get_activity_for_attribute(current_attr, assistant.age or 6)
                if current_activity:
                    return HandoffDecision.HANDOFF_NOW, f"current_good:{current_score:.0f}", {
                        "target_attribute": current_attr,
                        "activity": current_activity,
                        "readiness_score": current_score,
                        "note": f"global_best_is_{best_attr}_but_current_is_good_enough",
                    }

            return HandoffDecision.HANDOFF_NOW, f"global_best:{best_attr}:{best_score:.0f}", {
                "target_attribute": best_attr,
                "activity": activity,
                "readiness_score": best_score,
                "current_attribute": current_attr,
                "bridge_context": f"child_previously_explored_{best_attr}_with_score_{best_score:.0f}",
            }

    # 4. Session timeout without threshold met -> EXIT_LANE
    if total_turns >= MAX_SESSION_TURNS:
        if best_score >= EXIT_LANE_INTEREST:
            return HandoffDecision.EXIT_LANE, f"timeout_with_memory:{best_attr}:{best_score:.0f}", {
                "best_attribute": best_attr,
                "best_score": best_score,
                "reason": "session_long_but_interest_detected",
            }
        else:
            return HandoffDecision.EXIT_LANE, "timeout_no_interest", {
                "reason": "session_long_no_meaningful_interest",
            }

    # 5. Default: continue
    return HandoffDecision.CONTINUE, f"building:{current_score:.0f}", {
        "current_attribute": current_attr,
        "current_score": current_score,
        "best_attribute": best_attr,
        "best_score": best_score,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cares_handoff.py -k "test_evaluate_handoff" -v`
Expected: All PASS (note: the `test_evaluate_handoff_handoff_now_current_best` test uses `unittest.mock.patch` which should work)

- [ ] **Step 5: Commit**

```bash
git add stream/cares_handoff.py tests/test_cares_handoff.py
git commit -m "feat: HandoffDecision enum and evaluate_handoff decision engine"
```

---

## Task 5: Export CARES Symbols from `stream/__init__.py`

**Files:**
- Modify: `stream/__init__.py`

**Background:** All stream submodules are re-exported from `stream/__init__.py` so `paixueji_app.py` can do `from stream import ...`.

- [ ] **Step 1: Add imports and update `__all__`**

In `stream/__init__.py`, add the new import alongside the existing Phase 0 exports:

```python
# Exploration angles (CARES Phase 0)
from .exploration_angles import (
    EXPLORATION_ANGLES,
    AngleCoverageRecord,
    select_next_angle,
)

# CARES handoff (Phase 1)
from .cares_handoff import (
    AttributeInterestRecord,
    compute_attribute_interest_score,
    on_attribute_turn,
    HandoffDecision,
    evaluate_handoff,
    MIN_INTEREST_FOR_HANDOFF,
    MAX_SESSION_TURNS,
    EXIT_LANE_INTEREST,
)
```

And in `__all__`, append:
```python
'AttributeInterestRecord',
'compute_attribute_interest_score',
'on_attribute_turn',
'HandoffDecision',
'evaluate_handoff',
'MIN_INTEREST_FOR_HANDOFF',
'MAX_SESSION_TURNS',
'EXIT_LANE_INTEREST',
```

- [ ] **Step 2: Verify import works**

Run:
```bash
python -c "from stream import AttributeInterestRecord, compute_attribute_interest_score, HandoffDecision, evaluate_handoff; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add stream/__init__.py
git commit -m "feat: export CARES Phase 1 symbols from stream package"
```

---

## Task 6: Add `attribute_interest_records` to `PaixuejiAssistant`

**Files:**
- Modify: `paixueji_assistant.py`
- Test: `tests/test_attribute_activity_pipeline.py`

**Background:** The assistant needs to persist interest records across attribute switches within a session.

- [ ] **Step 1: Add the field in `__init__`**

In `paixueji_assistant.py`, inside `PaixuejiAssistant.__init__`, after `self.attribute_matched_activity = None` (line 97), add:

```python
self.attribute_interest_records: dict[str, "AttributeInterestRecord"] = {}
```

Add the type hint import at the top if needed (or rely on string annotation). Since `AttributeInterestRecord` is in `stream/cares_handoff.py`, use a string annotation to avoid circular import:

```python
self.attribute_interest_records: dict[str, "AttributeInterestRecord"] = {}
```

- [ ] **Step 2: Verify `clear_attribute_lane` does NOT clear interest records**

Confirm `clear_attribute_lane` (around line 314) does NOT touch `attribute_interest_records`. Per design doc, records persist across lane clears. The existing method only clears:
- `attribute_lane_active`
- `attribute_state`
- `attribute_profile`
- `attribute_activity_ready`
- `attribute_matched_activity`
- `last_attribute_debug`

Do NOT add `self.attribute_interest_records = {}` here.

- [ ] **Step 3: Write test**

```python
# tests/test_attribute_activity_pipeline.py (append at end)
from stream.cares_handoff import AttributeInterestRecord


def test_assistant_initializes_empty_interest_records():
    from paixueji_assistant import PaixuejiAssistant
    assistant = PaixuejiAssistant(config_path="config.json", age_prompts_path="age_prompts.json")
    assert assistant.attribute_interest_records == {}
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_attribute_activity_pipeline.py::test_assistant_initializes_empty_interest_records -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paixueji_assistant.py tests/test_attribute_activity_pipeline.py
git commit -m "feat: add attribute_interest_records to PaixuejiAssistant"
```

---

## Task 7: Integrate CARES into `stream_attribute_activity` in `paixueji_app.py`

**Files:**
- Modify: `paixueji_app.py` (lines 1473-1715 region)

**Background:** This is the integration step. Three changes inside `stream_attribute_activity`:
1. Before angle selection: call `on_attribute_turn` to update interest record
2. Replace hardcoded `interest_score=0` with real computed score
3. After computing score: call `evaluate_handoff` and pass decision into `_build_angle_aware_guide`

- [ ] **Step 1: Add imports at top of `paixueji_app.py`**

After the existing `from stream import (...)` block (around line 143), add:

```python
from stream.cares_handoff import (
    on_attribute_turn,
    evaluate_handoff,
    compute_attribute_interest_score,
    HandoffDecision,
)
```

Also add `AngleCoverageRecord` to the `from stream import` block if not already there (it should be there from Phase 0).

- [ ] **Step 2: Modify `stream_attribute_activity` — add interest update and score computation**

Inside `async def stream_attribute_activity():`, after the `needs_followup` line and before the `messages = prepare_messages_for_streaming(...)` line, add:

```python
                        # CARES Phase 1: update interest record for this turn
                        # Build a switch result from the detector output (captured from outer scope)
                        switch_result_for_cares = SimpleNamespace(
                            should_switch=should_switch,
                            target_attribute_id=switch_target_id,
                        )
                        on_attribute_turn(
                            assistant=assistant,
                            child_input=child_input,
                            intent_type=intent_type_lower.upper(),
                            action_subtype=assistant.action_subtype,
                            switch_result=switch_result_for_cares,
                            turn_index=assistant.attribute_state.turn_count,
                        )

                        # Compute current interest score for angle unlocking
                        current_attr_id = assistant.attribute_state.profile.attribute_id
                        current_interest_record = assistant.attribute_interest_records.get(current_attr_id)
                        current_interest_score = (
                            compute_attribute_interest_score(current_interest_record)
                            if current_interest_record else 0.0
                        )

                        # Evaluate handoff decision
                        decision, decision_reason, decision_meta = evaluate_handoff(
                            assistant, switch_result_for_cares
                        )
```

Note: `SimpleNamespace` is already imported in this file (used elsewhere). If not, add `from types import SimpleNamespace` at the top.

- [ ] **Step 3: Replace hardcoded `interest_score=0`**

Change:
```python
                        selected_angle = select_next_angle(
                            explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                            dimension=dimension,
                            interest_score=0,  # Phase 0: no scoring yet; Phase 1 will pass real score
                        )
```

To:
```python
                        selected_angle = select_next_angle(
                            explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                            dimension=dimension,
                            interest_score=current_interest_score,
                        )
```

- [ ] **Step 4: Pass decision info to `_build_angle_aware_guide`**

Change the `_build_angle_aware_guide` call:
```python
                        soft_guide = _build_angle_aware_guide(
                            attribute_label=attribute_label,
                            activity_target=activity_target,
                            sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
                            selected_angle=selected_angle,
                            explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                            turn_count=assistant.attribute_state.turn_count,
                        )
```

To:
```python
                        # Build list of explored attributes for display
                        explored_attributes = list(assistant.attribute_interest_records.keys())
                        total_turns = sum(
                            r.turns_explored for r in assistant.attribute_interest_records.values()
                        )

                        soft_guide = _build_angle_aware_guide(
                            attribute_label=attribute_label,
                            activity_target=activity_target,
                            sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
                            selected_angle=selected_angle,
                            explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                            turn_count=assistant.attribute_state.turn_count,
                            current_score=current_interest_score,
                            total_turns=total_turns,
                            explored_attributes=explored_attributes,
                            decision=decision,
                            decision_meta=decision_meta,
                        )
```

- [ ] **Step 5: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: integrate CARES scoring and handoff evaluation into attribute pipeline"
```

---

## Task 8: Update `_build_angle_aware_guide` to Inject CARES State

**Files:**
- Modify: `paixueji_app.py` (lines 65-137 region)

**Background:** The guide needs a new `[SYSTEM CONTEXT]` block after `[CONVERSATION COVERAGE]` that shows the current interest score, total turns, explored attributes, and the handoff decision. This tells the model what mode it's in.

- [ ] **Step 1: Update function signature**

Change:
```python
def _build_angle_aware_guide(
    attribute_label: str,
    activity_target: str,
    sensory_safety_rules: str,
    selected_angle: dict,
    explored_angle_ids: list[str],
    turn_count: int,
) -> str:
```

To:
```python
def _build_angle_aware_guide(
    attribute_label: str,
    activity_target: str,
    sensory_safety_rules: str,
    selected_angle: dict,
    explored_angle_ids: list[str],
    turn_count: int,
    current_score: float = 0.0,
    total_turns: int = 0,
    explored_attributes: list[str] | None = None,
    decision: "HandoffDecision | None" = None,
    decision_meta: dict | None = None,
) -> str:
```

- [ ] **Step 2: Build the conditional system context block**

After the existing `used_angles_block` construction (line 102), add:

```python
    explored_attrs_str = ", ".join(explored_attributes) if explored_attributes else "(none yet)"

    # Build decision-specific instructions
    decision_block = ""
    if decision == HandoffDecision.HANDOFF_NOW:
        target_attr = (decision_meta or {}).get("target_attribute", attribute_label)
        activity = (decision_meta or {}).get("activity")
        activity_name = getattr(activity, "name", "an activity") if activity else "an activity"
        readiness = (decision_meta or {}).get("readiness_score", current_score)
        decision_block = f"""HANDOFF MODE: ACTIVE
Target attribute: {target_attr}
Activity: {activity_name}
Child interest score for this attribute: {readiness:.0f}/100

Your next message should:
1. Naturally bridge from the current conversation to the activity
2. Introduce the activity by name
3. End with [ACTIVITY_READY]"""
    elif decision == HandoffDecision.EXIT_LANE:
        decision_block = """EXIT MODE: ACTIVE
The session has been long. Wrap up naturally without pushing an activity.
Suggest free exploration or ask what the child wants to talk about next."""
    elif decision == HandoffDecision.REENGAGE:
        decision_block = """REENGAGE MODE: ACTIVE
The child is struggling. Ask a much simpler, more concrete question.
Use sensory language (look, touch, point). Avoid abstract questions."""
    else:
        decision_block = """HANDOFF MODE: INACTIVE
Continue exploring the current attribute. Do NOT output [ACTIVITY_READY]."""
```

- [ ] **Step 3: Inject the system context into the returned string**

After the existing return f-string, modify the template to include `[SYSTEM CONTEXT]` after `[CONVERSATION COVERAGE]`:

Change the return statement to:

```python
    return f"""{sensory_safety_rules}

[CONVERSATION COVERAGE]
Attribute: {attribute_label}
Turns explored: {turn_count}
Angles already used: {used_angles}

[NEXT SUGGESTED ANGLE: {angle_id}]
{description}

For this turn, try using the {angle_id} angle:
- Your RESPONSE should: {response_hint}
- Your FOLLOW-UP QUESTION should: {question_hint}
- Example of a good question: "{example}"

Already-used angles (try something different if possible):
{used_angles_block}

---

[SYSTEM CONTEXT]
Current attribute: {attribute_label}
Current interest score: {current_score:.0f}/100
Session turns: {total_turns}
Explored attributes: {explored_attrs_str}

{decision_block}

ANTI-PATTERNS -- NEVER produce these:
- "What {attribute_label} is it?" -- quiz
- "Do you know what {attribute_label} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
- "Let us look at its {attribute_label}!" -- forced redirect
- "That is nice, but..." then question about {attribute_label} -- ignoring child
- "Great! Now we can start an activity!" -- mechanical announcement
- Adding [ACTIVITY_READY] after just one shallow exchange -- premature handoff
- Switching topics on a single casual mention -- too sensitive
- Re-phrasing a question from an already-used angle
"""
```

Note: The `TRANSITION SIGNAL for [ACTIVITY_READY]` section is intentionally removed from the base template and replaced by the `decision_block`. The model now gets context-aware instructions instead of a generic transition signal.

Wait — actually, we should keep the `TRANSITION SIGNAL` in the base template for backwards compatibility, but only show it when `decision == HandoffDecision.HANDOFF_NOW`. Or better: the `decision_block` for `HANDOFF_NOW` already includes the transition instructions. For other decisions, we tell the model NOT to output `[ACTIVITY_READY]`.

But the existing code in `stream_attribute_activity` strips the `TRANSITION SIGNAL` section from the guide before passing it to `ask_followup_question_stream`:
```python
attribute_soft_guide=soft_guide.split("TRANSITION SIGNAL for [ACTIVITY_READY]:")[0].strip()
```

This split will no longer match if we restructure the template. We need to update that line too.

Change:
```python
attribute_soft_guide=soft_guide.split("TRANSITION SIGNAL for [ACTIVITY_READY]:")[0].strip() if soft_guide else soft_guide,
```

To a safer approach that strips the entire `[SYSTEM CONTEXT]` section for the follow-up generator (the follow-up generator shouldn't need the system context, only the angle hints):

```python
attribute_soft_guide=soft_guide.split("---\n\n[SYSTEM CONTEXT]")[0].strip() if soft_guide else soft_guide,
```

This preserves the angle coverage block for the follow-up generator while removing the decision context (which is more relevant for the response generator).

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/test_attribute_activity_pipeline.py tests/test_exploration_angles.py tests/test_cares_handoff.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: inject CARES decision and interest score into attribute prompt"
```

---

## Task 9: Full Test Suite Run

**Files:** All

- [ ] **Step 1: Run the complete test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass. If any fail, fix them before proceeding.

- [ ] **Step 2: Commit**

```bash
git commit -m "test: full suite passing with CARES Phase 1 integration"
```

---

## Self-Review Checklist

### Spec Coverage

| Design Doc Section | Task | Status |
|-------------------|------|--------|
| §3.1 `AttributeInterestRecord` dataclass | Task 1 | Covered |
| §3.3 `compute_attribute_interest_score` formula | Task 2 | Covered |
| §3.2 `on_attribute_turn` update logic | Task 3 | Covered |
| §4.1 Constants (`MIN_INTEREST_FOR_HANDOFF`, etc.) | Task 4 | Covered |
| §4.2 `evaluate_handoff` decision engine | Task 4 | Covered |
| §7.1 Prompt injection (SYSTEM CONTEXT + decision block) | Task 8 | Covered |
| Cross-attribute persistence | Task 6 | Covered (records NOT cleared in `clear_attribute_lane`) |
| Real interest score drives angle selection | Task 7 | Covered (`interest_score=current_interest_score`) |

### Placeholder Scan

- No "TBD", "TODO", "implement later" in any step
- All code blocks contain complete, runnable code
- All test code includes assertions
- No "similar to Task N" shortcuts

### Type Consistency

- `AttributeInterestRecord` defined once in Task 1, used consistently
- `compute_attribute_interest_score` signature: `(record) -> float`
- `on_attribute_turn` signature matches design doc with `action_subtype` default
- `evaluate_handoff` signature: `(assistant, switch_result) -> (HandoffDecision, str, dict)`
- `HandoffDecision` enum values match design doc exactly

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-cares-phase1-interest-scoring.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session, batch execution with checkpoints for review

**Which approach?**
