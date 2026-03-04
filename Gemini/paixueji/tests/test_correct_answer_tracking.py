"""
Tests for the correct-answer tracking feature and classify_theme node.

Covers:
1. node_correct_answer increments correct_answer_count
2. route_from_analyze_input does NOT divert to classify_theme below threshold
3. route_from_analyze_input diverts to classify_theme at threshold (count 3 → 4)
4. node_classify_theme falls back gracefully when classify_object_to_theme returns None
"""
import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from paixueji_assistant import PaixuejiAssistant
from graph import node_correct_answer, node_classify_theme, paixueji_graph, GUIDE_MODE_THRESHOLD


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_mock_client(*, stream_text="Nice work! You got it right.", theme_json=None):
    """
    Build a lightweight mock client suitable for direct node calls.

    - models.generate_content: returns valid theme JSON (sync)
    - models.generate_content_stream: yields word-by-word chunks (sync iterator)
    - aio.models.generate_content: returns intent JSON (async)
    - aio.models.generate_content_stream: yields word-by-word chunks (async iterator)
    """
    class _Chunk:
        def __init__(self, text):
            self.text = text

    class _SyncStream:
        def __init__(self, chunks):
            self._chunks = chunks

        def __iter__(self):
            yield from self._chunks

    if theme_json is None:
        theme_json = json.dumps({
            "theme_id": "Category_Nature_And_Physics",
            "theme_name": "How the World Works",
            "reason": "Test reason",
            "key_concept": "Function",
            "bridge_question": "How does the bike move?",
            "thinking": "test",
        })

    # Sync models
    sync_models = MagicMock()
    mock_sync_response = MagicMock()
    mock_sync_response.text = theme_json
    sync_models.generate_content.return_value = mock_sync_response

    def _stream_side_effect(model, contents, config=None):
        words = stream_text.split()
        chunks = [_Chunk(w + " ") for w in words]
        return _SyncStream(chunks)

    sync_models.generate_content_stream.side_effect = _stream_side_effect

    # Async models (aio)
    async_models = MagicMock()
    mock_async_response = MagicMock()
    mock_async_response.text = (
        "INTENT: CORRECT_ANSWER\nNEW_OBJECT: null\nREASONING: Child answered correctly"
    )
    async_models.generate_content = AsyncMock(return_value=mock_async_response)

    async def _async_stream_side_effect(model, contents, config=None):
        words = stream_text.split()
        for w in words:
            yield _Chunk(w + " ")

    async_models.generate_content_stream.side_effect = _async_stream_side_effect

    client = MagicMock()
    client.models = sync_models
    client.aio = MagicMock()
    client.aio.models = async_models

    return client


def _base_state(assistant, *, correct_answer_count=0, guide_phase=None,
                intent_type="correct_answer", content="The wheels help it move!"):
    """Return a fully-populated PaixuejiState dict for direct node or graph invocation."""
    received_chunks = []

    async def _callback(chunk):
        received_chunks.append(chunk)

    client = _make_mock_client()

    return {
        "messages": [],
        "content": content,
        "session_id": "test-session",
        "request_id": "req-1",
        "assistant": assistant,
        "object_name": "bike",
        "correct_answer_count": correct_answer_count,
        "is_factually_correct": True,
        "age": 6,
        "config": {"model_name": "mock-model"},
        "client": client,
        "validation_result": {"is_factually_correct": True},
        "age_prompt": "",
        "category_prompt": "",
        "level1_category": "transport",
        "level2_category": "",
        "level3_category": "",
        "status": "normal",
        "start_time": 0.0,
        "sequence_number": 0,
        "full_response_text": "",
        "full_question_text": "",
        "stream_callback": _callback,
        "is_engaged": True,
        "new_object_name": None,
        "detected_object_name": None,
        "switch_decision_reasoning": None,
        "suggested_objects": None,
        "natural_topic_completion": False,
        "fun_fact": None,
        "fun_fact_hook": None,
        "fun_fact_question": None,
        "real_facts": None,
        "correctness_reasoning": None,
        "guide_phase": guide_phase,
        "guide_status": None,
        "guide_strategy": None,
        "guide_turn_count": None,
        "scaffold_level": None,
        "last_navigation_state": None,
        "intent_type": intent_type,
        "response_type": None,
        "nodes_executed": [],
        "ttft": None,
    }


# ---------------------------------------------------------------------------
# Test 1 — node_correct_answer increments correct_answer_count
# ---------------------------------------------------------------------------

class TestNodeCorrectAnswerIncrementsCount:
    """Bug fix 1: node_correct_answer must call assistant.increment_correct_answers()."""

    @pytest.mark.asyncio
    async def test_correct_answer_increments_count_from_zero(self):
        """Calling node_correct_answer with count=0 should leave count=1."""
        assistant = PaixuejiAssistant()
        assert assistant.correct_answer_count == 0

        state = _base_state(assistant, correct_answer_count=0)

        result = await node_correct_answer(state)

        # The assistant's count must have been incremented
        assert assistant.correct_answer_count == 1

    @pytest.mark.asyncio
    async def test_correct_answer_returns_updated_count_in_dict(self):
        """node_correct_answer return dict must contain 'correct_answer_count'."""
        assistant = PaixuejiAssistant()
        state = _base_state(assistant, correct_answer_count=0)

        result = await node_correct_answer(state)

        assert "correct_answer_count" in result
        assert result["correct_answer_count"] == 1

    @pytest.mark.asyncio
    async def test_correct_answer_accumulates_across_sequential_calls(self):
        """Three sequential node calls should result in count=3."""
        assistant = PaixuejiAssistant()

        for expected in range(1, 4):
            state = _base_state(assistant, correct_answer_count=assistant.correct_answer_count)
            await node_correct_answer(state)
            assert assistant.correct_answer_count == expected


# ---------------------------------------------------------------------------
# Test 2 — routing stays on correct_answer path below threshold
# ---------------------------------------------------------------------------

class TestRoutingBelowThreshold:
    """Bug fix 2: route_from_analyze_input should NOT divert to classify_theme below threshold."""

    @pytest.mark.asyncio
    async def test_count_2_does_not_trigger_guide_mode(self):
        """
        With correct_answer_count=2 and intent=CORRECT_ANSWER, the graph should
        route to node_correct_answer (not classify_theme), leaving guide_phase
        not 'active' and incrementing count to 3.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 2

        state = _base_state(assistant, correct_answer_count=2)

        # The analyze_input node uses assistant.client.aio.models.generate_content
        # which returns INTENT: CORRECT_ANSWER, so routing will check count.
        # count=2, 2+1=3 < 4 → should NOT go to classify_theme.

        final_state = await paixueji_graph.ainvoke(state)

        # guide_phase must NOT become "active"
        guide_phase = final_state.get("guide_phase") or assistant.guide_phase
        assert guide_phase != "active", (
            f"Expected guide_phase != 'active' with count=2, got: {guide_phase}"
        )

        # Count must now be 3 (incremented by node_correct_answer)
        assert assistant.correct_answer_count == 3

    @pytest.mark.asyncio
    async def test_count_0_does_not_trigger_guide_mode(self):
        """
        count=0, intent=CORRECT_ANSWER: should be a plain correct_answer turn.
        """
        assistant = PaixuejiAssistant()
        state = _base_state(assistant, correct_answer_count=0)

        final_state = await paixueji_graph.ainvoke(state)

        guide_phase = final_state.get("guide_phase") or assistant.guide_phase
        assert guide_phase != "active"
        assert assistant.correct_answer_count == 1

    @pytest.mark.asyncio
    async def test_threshold_boundary_count_3_minus_1_is_not_triggered(self):
        """
        count=2 → 2+1=3, which is less than GUIDE_MODE_THRESHOLD=4, so no diversion.
        Specifically verifies the constant value matters.
        """
        assert GUIDE_MODE_THRESHOLD == 4, "Threshold changed — update this test if intentional"

        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 2
        state = _base_state(assistant, correct_answer_count=2)

        final_state = await paixueji_graph.ainvoke(state)

        guide_phase = final_state.get("guide_phase") or assistant.guide_phase
        assert guide_phase != "active"


# ---------------------------------------------------------------------------
# Test 3 — threshold triggers classify_theme → start_guide
# ---------------------------------------------------------------------------

class TestThresholdTriggersClassifyTheme:
    """At correct_answer_count=3, the 4th correct answer must route to classify_theme."""

    @pytest.mark.asyncio
    async def test_count_3_triggers_guide_phase_active(self):
        """
        With count=3 and intent=CORRECT_ANSWER (3+1=4 >= GUIDE_MODE_THRESHOLD):
        - assistant.correct_answer_count must become 4
        - assistant.guide_phase must become 'active'
        - assistant.ibpyp_theme_name must be set (non-empty)
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 3

        state = _base_state(assistant, correct_answer_count=3)

        final_state = await paixueji_graph.ainvoke(state)

        # Count must have been incremented by node_classify_theme
        assert assistant.correct_answer_count == 4, (
            f"Expected count=4, got {assistant.correct_answer_count}"
        )

        # Guide phase must be active (set by node_start_guide → enter_guide_mode())
        guide_phase = final_state.get("guide_phase") or assistant.guide_phase
        assert guide_phase == "active", (
            f"Expected guide_phase='active', got: {guide_phase}"
        )

        # Theme name must have been set (mock returns "How the World Works")
        assert assistant.ibpyp_theme_name is not None
        assert len(assistant.ibpyp_theme_name) > 0

    @pytest.mark.asyncio
    async def test_count_3_sets_theme_fields(self):
        """
        After classify_theme runs, theme fields on the assistant must be populated.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 3

        state = _base_state(assistant, correct_answer_count=3)

        await paixueji_graph.ainvoke(state)

        # Both mock returns "How the World Works" (conftest default) and the
        # direct node mock return the same value — either is acceptable.
        assert assistant.ibpyp_theme_name is not None
        assert assistant.key_concept is not None
        assert assistant.bridge_question is not None


# ---------------------------------------------------------------------------
# Test 4 — node_classify_theme fallback when classification returns None
# ---------------------------------------------------------------------------

class TestClassifyThemeFallback:
    """node_classify_theme must use hardcoded fallback when classify_object_to_theme returns None."""

    @pytest.mark.asyncio
    async def test_fallback_sets_default_theme_name(self):
        """
        When classify_object_to_theme returns None, node_classify_theme must set:
        - assistant.ibpyp_theme_name == "How the World Works"
        - assistant.key_concept == "Function"
        - assistant.bridge_question contains object_name
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 3  # will become 4 inside the node

        state = _base_state(assistant, correct_answer_count=3)

        # Patch classify_object_to_theme to return None at the module level used by graph.py
        with patch("graph.classify_object_to_theme", return_value=None):
            result = await node_classify_theme(state)

        # Count incremented
        assert assistant.correct_answer_count == 4

        # Fallback theme values set
        assert assistant.ibpyp_theme_name == "How the World Works"
        assert assistant.key_concept == "Function"

    @pytest.mark.asyncio
    async def test_fallback_bridge_question_references_object_name(self):
        """
        The fallback bridge question must mention the object_name from state.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 3

        object_name = "bicycle"
        state = _base_state(assistant, correct_answer_count=3, content="It rolls!")
        state["object_name"] = object_name

        with patch("graph.classify_object_to_theme", return_value=None):
            await node_classify_theme(state)

        assert object_name in assistant.bridge_question, (
            f"Expected bridge_question to contain '{object_name}', "
            f"got: '{assistant.bridge_question}'"
        )

    @pytest.mark.asyncio
    async def test_fallback_count_incremented_even_when_classification_fails(self):
        """
        Even on classification failure, node_classify_theme must increment count.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 3

        state = _base_state(assistant, correct_answer_count=3)

        with patch("graph.classify_object_to_theme", return_value=None):
            await node_classify_theme(state)

        assert assistant.correct_answer_count == 4

    @pytest.mark.asyncio
    async def test_fallback_result_dict_contains_correct_answer_count(self):
        """
        node_classify_theme must return a dict with 'correct_answer_count'.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 3

        state = _base_state(assistant, correct_answer_count=3)

        with patch("graph.classify_object_to_theme", return_value=None):
            result = await node_classify_theme(state)

        assert "correct_answer_count" in result
        assert result["correct_answer_count"] == 4

    @pytest.mark.asyncio
    async def test_success_path_sets_theme_from_result(self):
        """
        When classify_object_to_theme succeeds, the result fields must be applied
        to the assistant, overriding any defaults.
        """
        from theme_classifier import ThemeClassificationResult

        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 3

        mock_result = ThemeClassificationResult(
            theme_id="Category_Society",
            theme_name="How We Organise Ourselves",
            reason="Society reason",
            key_concept="System",
            bridge_question="How do communities work together?",
            thinking="test",
        )

        state = _base_state(assistant, correct_answer_count=3)

        with patch("graph.classify_object_to_theme", return_value=mock_result):
            await node_classify_theme(state)

        assert assistant.ibpyp_theme == "Category_Society"
        assert assistant.ibpyp_theme_name == "How We Organise Ourselves"
        assert assistant.key_concept == "System"
        assert assistant.bridge_question == "How do communities work together?"
        assert assistant.correct_answer_count == 4
