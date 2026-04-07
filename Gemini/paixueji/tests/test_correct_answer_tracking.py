"""
Tests for the correct-answer tracking feature and classify_theme node.

Covers:
1. node_correct_answer increments correct_answer_count
2. route_from_analyze_input does NOT divert to classify_theme below threshold
3. route_from_analyze_input diverts to classify_theme at threshold (count 1 → 2)
4. node_classify_theme falls back gracefully when conversation-theme classification returns None
"""
import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from paixueji_assistant import PaixuejiAssistant
from graph import (
    GUIDE_MODE_THRESHOLD,
    node_classify_theme,
    node_correct_answer,
    paixueji_graph,
    route_from_analyze_input,
)


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
                intent_type="correct_answer", content="The wheels help it move!",
                learning_anchor_active=True):
    """Return a fully-populated PaixuejiState dict for direct node or graph invocation."""
    received_chunks = []

    async def _callback(chunk):
        received_chunks.append(chunk)

    client = _make_mock_client()
    assistant.client = client  # classify_intent() uses assistant.client, not state["client"]
    assistant.learning_anchor_active = learning_anchor_active

    return {
        "messages": [],
        "content": content,
        "session_id": "test-session",
        "request_id": "req-1",
        "assistant": assistant,
        "object_name": "bike",
        "surface_object_name": "bike",
        "anchor_object_name": "bike",
        "anchor_status": "exact_supported",
        "anchor_relation": "exact_match",
        "anchor_confidence_band": "exact",
        "anchor_confirmation_needed": False,
        "learning_anchor_active": assistant.learning_anchor_active,
        "correct_answer_count": correct_answer_count,
        "age": 6,
        "config": {"model_name": "mock-model"},
        "client": client,
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
        "new_object_name": None,
        "detected_object_name": None,
        "fun_fact": None,
        "fun_fact_hook": None,
        "fun_fact_question": None,
        "real_facts": None,
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
        assistant.learning_anchor_active = True

        for expected in range(1, 4):
            state = _base_state(assistant, correct_answer_count=assistant.correct_answer_count)
            await node_correct_answer(state)
            assert assistant.correct_answer_count == expected

    @pytest.mark.asyncio
    async def test_correct_answer_does_not_increment_before_anchor_activation(self):
        assistant = PaixuejiAssistant()
        assistant.learning_anchor_active = False

        state = _base_state(assistant, correct_answer_count=0, learning_anchor_active=False)

        result = await node_correct_answer(state)

        assert assistant.correct_answer_count == 0
        assert result["correct_answer_count"] == 0


# ---------------------------------------------------------------------------
# Test 2 — routing stays on correct_answer path below threshold
# ---------------------------------------------------------------------------

class TestRoutingBelowThreshold:
    """Bug fix 2: route_from_analyze_input should NOT divert to classify_theme below threshold."""

    @pytest.mark.asyncio
    async def test_count_0_stays_on_chat_path(self):
        """
        With correct_answer_count=0 and intent=CORRECT_ANSWER, the graph should
        route to node_correct_answer (not classify_theme) and increment count to 1.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 0
        assistant.learning_anchor_active = True

        state = _base_state(assistant, correct_answer_count=0)

        # The analyze_input node uses assistant.client.aio.models.generate_content
        # which returns INTENT: CORRECT_ANSWER, so routing will check count.
        # count=0, 0+1=1 < 2 -> should NOT go to classify_theme.

        final_state = await paixueji_graph.ainvoke(state)

        assert "guide_phase" not in final_state
        assert not hasattr(assistant, "guide_phase")

        # Count must now be 1 (incremented by node_correct_answer)
        assert assistant.correct_answer_count == 1

    @pytest.mark.asyncio
    async def test_count_0_does_not_emit_guide_state(self):
        """
        count=0, intent=CORRECT_ANSWER: should be a plain correct_answer turn.
        """
        assistant = PaixuejiAssistant()
        assistant.learning_anchor_active = True
        state = _base_state(assistant, correct_answer_count=0)

        final_state = await paixueji_graph.ainvoke(state)

        assert "guide_phase" not in final_state
        assert assistant.correct_answer_count == 1

    @pytest.mark.asyncio
    async def test_threshold_boundary_count_2_minus_1_is_not_triggered(self):
        """
        count=0 -> 0+1=1, which is less than GUIDE_MODE_THRESHOLD=2, so no diversion.
        Specifically verifies the constant value matters.
        """
        assert GUIDE_MODE_THRESHOLD == 2, "Threshold changed — update this test if intentional"

        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 0
        assistant.learning_anchor_active = True
        state = _base_state(assistant, correct_answer_count=0)

        final_state = await paixueji_graph.ainvoke(state)

        assert "guide_phase" not in final_state

    def test_route_does_not_divert_to_classify_theme_when_learning_inactive(self):
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = False

        route = route_from_analyze_input({
            "classification_status": "ok",
            "intent_type": "CORRECT_ANSWER",
            "assistant": assistant,
        })

        assert route == "correct_answer"


# ---------------------------------------------------------------------------
# Test 3 — threshold triggers classify_theme → chat_complete
# ---------------------------------------------------------------------------

class TestThresholdTriggersClassifyTheme:
    """At correct_answer_count=1, the 2nd correct answer must route to classify_theme."""

    def test_threshold_route_records_completion_reason_metadata(self):
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True

        route = route_from_analyze_input({
            "classification_status": "ok",
            "intent_type": "CORRECT_ANSWER",
            "assistant": assistant,
        })

        assert route == "classify_theme"
        assert assistant._last_route_debug["route_reason"] == "correct_answer_threshold_reached"
        assert assistant._last_route_debug["correct_answer_count_before"] == 1
        assert assistant._last_route_debug["correct_answer_count_after_if_accepted"] == 2
        assert assistant._last_route_debug["guide_mode_threshold"] == GUIDE_MODE_THRESHOLD

    @pytest.mark.asyncio
    async def test_count_1_triggers_chat_complete_without_guide_state(self):
        """
        With count=1 and intent=CORRECT_ANSWER (1+1=2 >= GUIDE_MODE_THRESHOLD):
        - assistant.correct_answer_count must become 2
        - guide runtime fields must stay absent
        - assistant.ibpyp_theme_name must be set (non-empty)
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True

        state = _base_state(assistant, correct_answer_count=1)

        final_state = await paixueji_graph.ainvoke(state)

        # Count must have been incremented by node_classify_theme
        assert assistant.correct_answer_count == 2, (
            f"Expected count=2, got {assistant.correct_answer_count}"
        )

        assert "guide_phase" not in final_state
        assert not hasattr(assistant, "guide_phase")

        # Theme name must have been set (mock returns "How the World Works")
        assert assistant.ibpyp_theme_name is not None
        assert len(assistant.ibpyp_theme_name) > 0

    @pytest.mark.asyncio
    async def test_count_1_emits_theme_fields_in_completion_chunks(self):
        """
        The threshold turn should classify the theme, then emit chat completion
        chunks that include the classified theme metadata.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True

        captured_chunks = []

        async def _callback(chunk):
            captured_chunks.append(chunk)

        state = _base_state(assistant, correct_answer_count=1)
        state["stream_callback"] = _callback

        await paixueji_graph.ainvoke(state)

        assert len(captured_chunks) >= 2
        assert any(chunk.chat_phase_complete for chunk in captured_chunks)
        assert any(chunk.ibpyp_theme_name for chunk in captured_chunks)

    @pytest.mark.asyncio
    async def test_count_1_sets_theme_fields(self):
        """
        After classify_theme runs, theme fields on the assistant must be populated.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True

        state = _base_state(assistant, correct_answer_count=1)

        await paixueji_graph.ainvoke(state)

        # Both mock returns "How the World Works" (conftest default) and the
        # direct node mock return the same value — either is acceptable.
        assert assistant.ibpyp_theme_name is not None
        assert assistant.key_concept is not None
        assert assistant.bridge_question is not None

    @pytest.mark.asyncio
    async def test_count_1_uses_history_theme_result_over_yaml_theme(self):
        """
        Guide entry should take the authoritative theme from conversation history,
        while leaving the YAML-derived key concept in place.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True
        assistant.key_concept = "function"
        assistant.bridge_question = "How does the bike move?"
        assistant.category_prompt = "CONCEPT FOCUS: function"
        assistant.fallback_theme_id = "how_world_works"
        assistant.fallback_theme_name = "How the World Works"
        assistant.fallback_theme_reason = "Object-based fallback"

        state = _base_state(assistant, correct_answer_count=1)
        state["messages"] = [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "What helps the bike move?"},
            {"role": "user", "content": "The wheels help it move!"},
        ]

        with patch(
            "theme_classifier.classify_conversation_to_theme",
            new=AsyncMock(return_value={
                "theme_id": "who_we_are",
                "theme_name": "Who We Are",
                "reason": "The child focused on personal experience and body control.",
            }),
        ):
            await node_classify_theme(state)

        assert assistant.ibpyp_theme == "who_we_are"
        assert assistant.ibpyp_theme_name == "Who We Are"
        assert assistant.ibpyp_theme_reason == (
            "The child focused on personal experience and body control."
        )
        assert assistant.key_concept == "function"
        assert assistant.bridge_question == "How does the bike move?"


# ---------------------------------------------------------------------------
# Test 4 — node_classify_theme fallback when classification returns None
# ---------------------------------------------------------------------------

class TestClassifyThemeFallback:
    """node_classify_theme must use YAML-based fallback when lookup returns no match."""

    @pytest.mark.asyncio
    async def test_history_theme_failure_uses_fallback_theme_fields(self):
        """
        If the history-based theme analysis fails, guide entry should fall back to
        the assistant's stored object-derived theme.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True
        assistant.key_concept = "change"
        assistant.bridge_question = "What changes when the apple gets old?"
        assistant.category_prompt = "CONCEPT FOCUS: change"
        assistant.fallback_theme_id = "how_world_works"
        assistant.fallback_theme_name = "How the World Works"
        assistant.fallback_theme_reason = "Fallback theme"

        state = _base_state(assistant, correct_answer_count=1)
        state["messages"] = [
            {"role": "assistant", "content": "What changes when the apple gets old?"},
            {"role": "user", "content": "It turns brown."},
        ]

        with patch(
            "theme_classifier.classify_conversation_to_theme",
            new=AsyncMock(return_value=None),
        ):
            await node_classify_theme(state)

        assert assistant.ibpyp_theme == "how_world_works"
        assert assistant.ibpyp_theme_name == "How the World Works"
        assert assistant.ibpyp_theme_reason == "Fallback theme"

    @pytest.mark.asyncio
    async def test_fallback_sets_default_theme_name(self):
        """
        When YAML lookup fails, node_classify_theme must set fallback values:
        - assistant.ibpyp_theme_name == "How the World Works"
        - assistant.key_concept == "function"
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1  # will become 2 inside the node

        state = _base_state(assistant, correct_answer_count=1)

        # Patch the underlying YAML lookup to simulate a miss
        with patch("graph_lookup.lookup_top_available_concepts", return_value={"success": False, "error": "not found"}):
            result = await node_classify_theme(state)

        # Count incremented
        assert assistant.correct_answer_count == 2

        # Fallback theme values set
        assert assistant.ibpyp_theme_name == "How the World Works"
        assert assistant.key_concept == "function"

    @pytest.mark.asyncio
    async def test_fallback_bridge_question_references_object_name(self):
        """
        The fallback bridge question must mention the object_name from state.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True

        object_name = "bicycle"
        state = _base_state(assistant, correct_answer_count=1, content="It rolls!")
        state["object_name"] = object_name

        with patch("graph_lookup.lookup_top_available_concepts", return_value={"success": False, "error": "not found"}):
            await node_classify_theme(state)

        assert object_name in assistant.bridge_question, (
            f"Expected bridge_question to contain '{object_name}', "
            f"got: '{assistant.bridge_question}'"
        )

    @pytest.mark.asyncio
    async def test_fallback_count_incremented_even_when_classification_fails(self):
        """
        Even on classification failure (YAML miss), node_classify_theme must increment count.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True

        state = _base_state(assistant, correct_answer_count=1)

        with patch("graph_lookup.lookup_top_available_concepts", return_value={"success": False, "error": "not found"}):
            await node_classify_theme(state)

        assert assistant.correct_answer_count == 2

    @pytest.mark.asyncio
    async def test_fallback_result_dict_contains_correct_answer_count(self):
        """
        node_classify_theme must return a dict with 'correct_answer_count'.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1
        assistant.learning_anchor_active = True

        state = _base_state(assistant, correct_answer_count=1)

        with patch("graph_lookup.lookup_top_available_concepts", return_value={"success": False, "error": "not found"}):
            result = await node_classify_theme(state)

        assert "correct_answer_count" in result
        assert result["correct_answer_count"] == 2

    @pytest.mark.asyncio
    async def test_success_path_sets_theme_from_result(self):
        """
        When YAML lookup succeeds, the result fields must be applied to the assistant.
        """
        assistant = PaixuejiAssistant()
        assistant.correct_answer_count = 1

        # sunflower is a known object in the YAML mappings
        state = _base_state(assistant, correct_answer_count=1)
        state["object_name"] = "sunflower"

        result = await node_classify_theme(state)

        assert assistant.ibpyp_theme is not None
        assert assistant.ibpyp_theme_name is not None
        assert assistant.key_concept is not None
        assert assistant.bridge_question is not None
        assert "CONCEPT FOCUS:" in (assistant.category_prompt or "")
        assert assistant.correct_answer_count == 2
