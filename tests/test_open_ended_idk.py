import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _parse_sse(response_data):
    import json

    events = []
    text = response_data.decode("utf-8")
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:].strip())
        if event_type:
            events.append({"event": event_type, "data": data})
    return events


def _make_mock_assistant(struggle_count=0):
    assistant = MagicMock()
    assistant.consecutive_struggle_count = struggle_count
    assistant.correct_answer_count = 0
    assistant.state = MagicMock()
    assistant.state.value = "awaiting_answer"
    assistant.ibpyp_theme_name = None
    assistant.ibpyp_theme_reason = None
    assistant.key_concept = None
    assistant._router_traces = []
    return assistant


def _build_state(assistant, messages=None):
    return {
        "session_id": "test-session",
        "request_id": "test-request",
        "assistant": assistant,
        "content": "I don't know",
        "object_name": "goldfish",
        "age": 6,
        "age_prompt": "",
        "config": {"model_name": "mock-model"},
        "client": MagicMock(),
        "messages": messages or [],
        "sequence_number": 0,
        "stream_callback": AsyncMock(),
        "full_response_text": "",
        "full_question_text": "",
        "start_time": 0.0,
        "ttft": None,
        "nodes_executed": [],
        "intent_type": "clarifying_idk",
        "response_type": None,
        "classification_status": None,
        "classification_failure_reason": None,
        "new_object_name": None,
        "detected_object_name": None,
        "fun_fact": None,
        "fun_fact_hook": None,
        "fun_fact_question": None,
        "real_facts": None,
        "correct_answer_count": 0,
        "status": "active",
        "used_kb_item": None,
        "kb_mapping_status": None,
        "hook_types": {},
        "selected_hook_type": None,
        "question_style": None,
        "physical_dimensions": {},
        "engagement_dimensions": {},
    }


def test_previous_question_style_falls_back_to_open_ended_question_text():
    import graph

    messages = [
        {
            "role": "assistant",
            "content": "What does she do when she wakes up from her nap?",
            "question_style": None,
            "selected_hook_type": None,
        }
    ]

    assert graph._previous_question_style(messages) == "open_ended"


def test_previous_question_style_leaves_concrete_question_untyped():
    import graph

    messages = [
        {
            "role": "assistant",
            "content": "What color is the bowl?",
            "question_style": None,
            "selected_hook_type": None,
        }
    ]

    assert graph._previous_question_style(messages) is None


class TestOpenEndedIdkFlow:
    @pytest.mark.asyncio
    async def test_node_generate_intro_marks_open_ended_question_style(self):
        import graph

        assistant = _make_mock_assistant()
        state = _build_state(assistant, messages=[{"role": "system", "content": "system"}])
        state["response_type"] = "introduction"
        state["hook_types"] = {
            "想象导向": {
                "name": "想象导向",
                "concept": "fantasy pivot",
                "examples": ["If it could talk..."],
                "age_weights": {"6": 1},
                "requires_history": False,
            }
        }

        with patch("graph.select_hook_type", return_value=("想象导向", "Hook style: 想象导向")), patch(
            "graph.ask_introduction_question_stream",
            return_value=object(),
        ), patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("intro text", 1)),
        ):
            result = await graph.node_generate_intro(state)

        assert result["selected_hook_type"] == "想象导向"
        assert result["question_style"] == "open_ended"

    @pytest.mark.asyncio
    async def test_clarifying_idk_uses_open_ended_prompt_after_open_ended_intro(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=1)
        state = _build_state(
            assistant,
            messages=[
                {
                    "role": "assistant",
                    "content": "If this little fish could talk, what do you think it would say?",
                    "question_style": "open_ended",
                    "selected_hook_type": "想象导向",
                }
            ],
        )

        with patch("graph.generate_intent_response_stream", return_value=object()) as mock_gen, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("example-based response", 1)),
        ):
            result = await graph.node_clarifying_idk(state)

        assert result["response_type"] == "clarifying_idk"
        assert mock_gen.call_args.kwargs["intent_type"] == "clarifying_open_ended_idk"

    @pytest.mark.asyncio
    async def test_give_answer_idk_uses_open_ended_example_prompt_without_followup(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=2)
        state = _build_state(
            assistant,
            messages=[
                {
                    "role": "assistant",
                    "content": "If this little fish could talk, what do you think it would say?",
                    "question_style": "open_ended",
                    "selected_hook_type": "想象导向",
                }
            ],
        )

        with patch("graph.generate_intent_response_stream", return_value=object()) as mock_gen, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("I think it might say blub blub hello.", 1)),
        ), patch("graph.ask_followup_question_stream", return_value=object()) as mock_followup:
            result = await graph.node_give_answer_idk(state)

        assert result["response_type"] == "give_answer_idk"
        assert result["full_response_text"] == "I think it might say blub blub hello."
        assert mock_gen.call_args.kwargs["intent_type"] == "give_answer_open_ended_idk"
        mock_followup.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("node_name", "intent_type", "content"),
        [
            ("node_correct_answer", "correct_answer", "she curls up"),
            ("node_give_answer_idk", "clarifying_idk", "I don't know"),
            ("node_informative", "informative", "cats sleep a lot"),
            ("node_social", "social", "are you real"),
            ("node_social_acknowledgment", "social_acknowledgment", "wow"),
        ],
    )
    async def test_followup_generating_nodes_mark_open_ended_question_style(
        self,
        node_name,
        intent_type,
        content,
    ):
        import graph

        assistant = _make_mock_assistant()
        state = _build_state(
            assistant,
            messages=[{"role": "assistant", "content": "previous question"}],
        )
        state["intent_type"] = intent_type
        state["content"] = content

        with patch("graph.generate_intent_response_stream", return_value=object()), patch(
            "graph.ask_followup_question_stream",
            return_value=object(),
        ), patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(
                side_effect=[
                    ("stub fact", 1),
                    ("What does she do when she wakes up from her nap?", 2),
                ]
            ),
        ):
            result = await getattr(graph, node_name)(state)

        assert result["question_style"] == "open_ended"

    @pytest.mark.asyncio
    async def test_clarifying_idk_uses_open_ended_prompt_after_metadata_free_followup(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=1)
        state = _build_state(
            assistant,
            messages=[
                {
                    "role": "assistant",
                    "content": "What does she do when she wakes up from her nap?",
                }
            ],
        )

        with patch("graph.generate_intent_response_stream", return_value=object()) as mock_gen, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("starter", 1)),
        ):
            await graph.node_clarifying_idk(state)

        assert mock_gen.call_args.kwargs["intent_type"] == "clarifying_open_ended_idk"

    @pytest.mark.asyncio
    async def test_give_answer_idk_uses_open_ended_prompt_after_metadata_free_followup(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=2)
        state = _build_state(
            assistant,
            messages=[
                {
                    "role": "assistant",
                    "content": "What does she do when she wakes up from her nap?",
                }
            ],
        )

        with patch("graph.generate_intent_response_stream", return_value=object()) as mock_gen, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("starter", 1)),
        ), patch("graph.ask_followup_question_stream", return_value=object()) as mock_followup:
            await graph.node_give_answer_idk(state)

        assert mock_gen.call_args.kwargs["intent_type"] == "give_answer_open_ended_idk"
        mock_followup.assert_not_called()


class TestOpenEndedPromptRegistration:
    def test_get_prompts_registers_open_ended_idk_prompts(self):
        import paixueji_prompts

        prompts = paixueji_prompts.get_prompts()

        assert "clarifying_open_ended_idk_intent_prompt" in prompts
        assert "give_answer_open_ended_idk_intent_prompt" in prompts


def test_start_persists_question_style_metadata_in_conversation_history(client):
    import time
    import paixueji_app
    from schema import StreamChunk

    async def fake_stream_graph_execution(_initial_state):
        yield StreamChunk(
            response="If this little fish could talk, what do you think it would say?",
            session_finished=False,
            duration=0.01,
            token_usage=None,
            finish=True,
            sequence_number=1,
            timestamp=time.time(),
            session_id="session-test",
            request_id="request-test",
            response_type="introduction",
            selected_hook_type="想象导向",
            question_style="open_ended",
        )

    with patch("paixueji_app.stream_graph_execution", new=fake_stream_graph_execution), patch(
        "paixueji_app.uuid.uuid4",
        side_effect=["session-test", "request-test"],
    ):
        response = client.post("/api/start", json={"object_name": "goldfish", "age": 6})

    assert response.status_code == 200
    events = _parse_sse(response.data)
    assert any(event["event"] == "chunk" for event in events)

    assistant = paixueji_app.sessions["session-test"]
    saved = assistant.conversation_history[-1]
    assert saved["selected_hook_type"] == "想象导向"
    assert saved["question_style"] == "open_ended"
