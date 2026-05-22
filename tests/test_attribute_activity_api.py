import json
from unittest.mock import AsyncMock, MagicMock, patch

import paixueji_app
from attribute_activity import AttributeProfile, DiscoverySessionState
from activities import ActivityDefinition
from stream.cares_handoff import HandoffDecision


def parse_sse(response_data):
    events = []
    for block in response_data.decode("utf-8").split("\n\n"):
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


def final_chunk(response):
    chunks = [event["data"] for event in parse_sse(response.data) if event["event"] == "chunk"]
    assert chunks
    return chunks[-1]


def streamed_prompt_text(mock_gemini_client):
    call = mock_gemini_client.aio.models.generate_content_stream.call_args
    assert call is not None
    contents = call.kwargs["contents"]
    parts = []
    for content in contents:
        for part in content.get("parts", []):
            parts.append(part.get("text", ""))
    return "\n".join(parts)


def set_async_text(mock_gemini_client, text):
    async def _side_effect(*args, **kwargs):
        response = MagicMock()
        response.text = text
        return response
    mock_gemini_client.aio.models.generate_content.side_effect = _side_effect


def set_intent(mock_gemini_client, intent_type, reasoning="Mock classification"):
    set_async_text(
        mock_gemini_client,
        f"INTENT: {intent_type}\nNEW_OBJECT: null\nREASONING: {reasoning}",
    )


def test_attribute_pipeline_start_passes_attribute_hook_filter(client, mock_gemini_client):
    with patch("paixueji_app.select_activities_for_object", new=AsyncMock(return_value=(None, {"reason": "test bypass"}))):
        with patch("graph.select_hook_type", return_value=("细节发现", "Hook style: 细节发现")) as mock_select:
            response = client.post(
                "/api/start",
                json={"age": 6, "object_name": "apple", "attribute_pipeline_enabled": True},
            )

    assert response.status_code == 200
    _, kwargs = mock_select.call_args
    assert kwargs["attribute_pipeline_enabled"] is True


def test_attribute_pipeline_start_reports_only_observable_hook_types(client, mock_gemini_client, monkeypatch):
    import paixueji_app
    monkeypatch.setattr(
        paixueji_app,
        "HOOK_TYPES",
        {
            "想象导向": {
                "name": "想象导向",
                "concept": "fantasy prompt",
                "examples": ["If it were magic?"],
                "age_weights": {"6": 1},
                "requires_history": False,
            },
            "细节发现": {
                "name": "细节发现",
                "concept": "observable prompt",
                "examples": ["What shape do you notice?"],
                "age_weights": {"6": 1},
                "requires_history": False,
                "attribute_mode": "observable",
            },
        },
    )

    with patch("paixueji_app.select_activities_for_object", new=AsyncMock(return_value=(None, {"reason": "test bypass"}))):
        response = client.post(
            "/api/start",
            json={"age": 6, "object_name": "apple", "attribute_pipeline_enabled": True},
        )

    assert response.status_code == 200
    chunks = [event["data"] for event in parse_sse(response.data) if event["event"] == "chunk"]
    final_chunk = chunks[-1]
    assert final_chunk["selected_hook_type"] == "细节发现"


def test_attribute_pipeline_start_uses_attribute_intro_and_debug(client, mock_gemini_client):
    response = client.post(
        "/api/start",
        json={"age": 6, "object_name": "apple", "attribute_pipeline_enabled": True},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "attribute_intro"
    assert chunk["attribute_pipeline_enabled"] is True
    assert chunk["attribute_lane_active"] is True
    assert "." in chunk["attribute_debug"]["profile"]["attribute_id"]
    assert chunk["attribute_debug"]["state"]["profile"]["attribute_id"] == chunk["attribute_debug"]["profile"]["attribute_id"]

    prompt_text = streamed_prompt_text(mock_gemini_client)
    assert "BEAT 1" in prompt_text
    assert "EMOTIONAL OPENING" in prompt_text
    assert "BEAT 2" in prompt_text
    assert "OBJECT CONFIRMATION" in prompt_text
    assert "BEAT 3" in prompt_text
    assert "OBSERVATION INVITATION" in prompt_text
    assert "BEAT 4" in prompt_text
    assert "ENGAGEMENT HOOK" in prompt_text


def test_attribute_pipeline_supports_unresolved_not_in_kb_without_anchor_fields(client):
    response = client.post(
        "/api/start",
        json={"age": 6, "object_name": "spaceship fuel", "attribute_pipeline_enabled": True},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "attribute_intro"
    assert chunk["attribute_lane_active"] is True
    # New activity-driven flow: branch reflects LLM selection outcome, not resolution path
    assert chunk["attribute_debug"]["profile"]["branch"] in ("in_kb", "unresolved_not_in_kb")
    assert chunk["attribute_debug"]["state"]["surface_object_name"] is None
    assert chunk["attribute_debug"]["state"]["anchor_object_name"] is None
    assert chunk["bridge_debug"] is None


def test_attribute_pipeline_no_match_preserves_existing_fallback_pipeline(client):
    response = client.post(
        "/api/start",
        json={"age": 6, "object_name": "plain thing", "attribute_pipeline_enabled": True},
    )

    chunk = final_chunk(response)

    assert chunk["attribute_pipeline_enabled"] is True
    assert chunk["attribute_debug"] is not None
    # Activity-driven flow returns activity.* ids; legacy returns appearance.* ids
    assert "." in chunk["attribute_debug"]["profile"]["attribute_id"]


def test_attribute_pipeline_off_preserves_bridge_pipeline_for_anchorable_object(client):
    response = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat food", "attribute_pipeline_enabled": False},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "introduction"
    assert chunk["attribute_pipeline_enabled"] is False
    assert chunk["attribute_lane_active"] is False
    assert chunk["attribute_debug"] is None


def test_attribute_continue_keeps_attribute_state(client, mock_gemini_client):
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat food", "attribute_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    set_intent(mock_gemini_client, "CLARIFYING_CONSTRAINT")
    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "I can't smell it"},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "attribute_activity"
    assert chunk["attribute_lane_active"] is True
    assert chunk["bridge_phase"] != "activation"
    assert "." in chunk["attribute_debug"]["state"]["profile"]["attribute_id"]
    # New debug shape has intent_type and activity_marker_detected, not reply/readiness
    assert "activity_marker_detected" in chunk["attribute_debug"]


def test_attribute_continue_tracks_turns_without_heuristic_readiness(client, mock_gemini_client):
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat food", "attribute_pipeline_enabled": True},
    )
    forced_profile = AttributeProfile(
        attribute_id="senses.smell",
        label="smell",
        activity_target="noticing and describing what cat food smells like",
        branch="anchored_not_in_kb",
        object_examples=("cat food",),
    )
    forced_debug = {
        "decision": "attribute_selected",
        "source": "test_patch",
        "attribute_id": "senses.smell",
        "confidence": "high",
        "reason": "selected by test patch",
    }

    forced_state = DiscoverySessionState(
        object_name="cat food",
        age=6,
        profile=forced_profile,
        primary_activity=ActivityDefinition(activity_id="test_smell", name="Test Smell Activity"),
    )
    with patch("paixueji_app.select_activities_for_object", new=AsyncMock(return_value=(forced_state, forced_debug))):
        start = client.post(
            "/api/start",
            json={"age": 6, "object_name": "cat food", "attribute_pipeline_enabled": True},
        )
    start_chunk = final_chunk(start)
    session_id = start_chunk["session_id"]
    assert start_chunk["attribute_debug"]["profile"]["attribute_id"] == "senses.smell"

    set_intent(mock_gemini_client, "CORRECT_ANSWER")
    with patch("paixueji_app.evaluate_handoff", return_value=(HandoffDecision.CONTINUE, "building", {})):
        first = client.post(
            "/api/continue",
            json={"session_id": session_id, "child_input": "It smells strong"},
        )
    first_chunk = final_chunk(first)
    assert first_chunk["response_type"] == "attribute_activity"
    assert first_chunk["activity_ready"] is False
    assert "activity_marker_detected" in first_chunk["attribute_debug"]


def _make_stream(text):
    """Helper to build a mock async stream that yields the given text word-by-word."""
    class _Chunk:
        def __init__(self, text):
            self.text = text

    class _Stream:
        def __init__(self, chunks):
            self.chunks = chunks

        async def __aiter__(self):
            for chunk in self.chunks:
                yield chunk

    chunks = [_Chunk(word + " ") for word in text.split()]
    return _Stream(chunks)


# Removed: test_activity_marker_rejected_without_evidence_quote
# Removed: test_activity_marker_rejected_with_fabricated_quote
# Removed: test_activity_marker_accepted_with_current_turn_quote
# These tests validated the [ACTIVITY_READY] marker system which has been
# removed. Handoff readiness is now determined entirely by evaluate_handoff.


def test_marker_and_reason_preserved_in_response(client, mock_gemini_client):
    """[ACTIVITY_READY] and REASON are no longer stripped from LLM output.

    Since the marker system has been removed and prompts no longer instruct
    the LLM to emit these tokens, any that do appear are passed through.
    """
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat", "attribute_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    set_intent(mock_gemini_client, "CURIOSITY")

    stream_call = 0
    def _side_effect(model, contents, config=None):
        nonlocal stream_call
        stream_call += 1
        if stream_call == 1:
            return _make_stream(
                'Cats have amazing fur. What do you notice? [ACTIVITY_READY]\nREASON: Child said "it is orange".'
            )
        return _make_stream("What else do you notice about the cat?")

    mock_gemini_client.aio.models.generate_content_stream.side_effect = _side_effect

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is fat"},
    )

    chunks = [event["data"] for event in parse_sse(response.data) if event["event"] == "chunk"]
    # Verify markers are preserved (stripping was removed along with the marker system)
    assert any("[ACTIVITY_READY]" in (c.get("response") or "") for c in chunks)
    assert any("REASON:" in (c.get("response") or "") for c in chunks)


def test_response_marker_preserved_when_generator_emits_it(client, mock_gemini_client):
    """[ACTIVITY_READY] emitted by the response generator is no longer stripped.

    The marker system has been removed; prompts no longer instruct the LLM
    to emit these tokens. Any that appear are passed through unchanged.
    """
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat", "attribute_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    set_intent(mock_gemini_client, "CURIOSITY")

    stream_call = 0
    def _side_effect(model, contents, config=None):
        nonlocal stream_call
        stream_call += 1
        if stream_call == 1:
            return _make_stream('That cat is definitely a big one! [ACTIVITY_READY]\nREASON: child said "it is big"')
        return _make_stream("What else do you notice about the cat?")

    mock_gemini_client.aio.models.generate_content_stream.side_effect = _side_effect

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is big"},
    )

    chunks = [event["data"] for event in parse_sse(response.data) if event["event"] == "chunk"]
    # Verify marker and REASON are preserved (stripping was removed)
    assert any("[ACTIVITY_READY]" in (c.get("response") or "") for c in chunks)
    assert any("REASON:" in (c.get("response") or "") for c in chunks)


def test_reason_preserved_when_marker_absent(client, mock_gemini_client):
    """REASON line is no longer stripped from LLM output.

    The marker system has been removed; _strip_activity_markers no longer
    exists, so any REASON lines the LLM emits are passed through.
    """
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat", "attribute_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    set_intent(mock_gemini_client, "CURIOSITY")

    stream_call = 0
    def _side_effect(model, contents, config=None):
        nonlocal stream_call
        stream_call += 1
        if stream_call == 1:
            return _make_stream("Cats have amazing fur. REASON: child seemed ready")
        return _make_stream("What else do you notice about the cat?")

    mock_gemini_client.aio.models.generate_content_stream.side_effect = _side_effect

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is fat"},
    )

    chunks = [event["data"] for event in parse_sse(response.data) if event["event"] == "chunk"]
    # REASON is preserved since stripping was removed
    assert any("REASON:" in (c.get("response") or "") for c in chunks)


def test_followup_question_preserved_on_continue(client, mock_gemini_client):
    """When evaluate_handoff returns CONTINUE, the follow-up question is still
    yielded so the conversation can continue normally."""
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat", "attribute_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    # Use INFORMATIVE (not CURIOSITY) so needs_followup=True and the
    # follow-up question block actually executes.
    set_intent(mock_gemini_client, "INFORMATIVE")

    stream_call = 0
    def _side_effect(model, contents, config=None):
        nonlocal stream_call
        stream_call += 1
        if stream_call == 1:
            return _make_stream("Cats have amazing fur. What do you notice about this one?")
        return _make_stream("Can you spot anything orange nearby?")

    mock_gemini_client.aio.models.generate_content_stream.side_effect = _side_effect

    with patch("paixueji_app.evaluate_handoff", return_value=(HandoffDecision.CONTINUE, "building", {})):
        response = client.post(
            "/api/continue",
            json={"session_id": session_id, "child_input": "it is fat"},
        )

    chunks = [event["data"] for event in parse_sse(response.data) if event["event"] == "chunk"]
    final = chunks[-1]
    assert "Can you spot anything orange nearby?" in final["response"], (
        f"Follow-up question missing from final response: {final['response']}"
    )
    # activity_ready is False because evaluate_handoff returns CONTINUE
    # (insufficient turns / interest score not high enough)
    assert final["attribute_lane_active"] is True


def test_attribute_continue_topic_switch_rematches_activity(client, mock_gemini_client):
    """When topic switch detector fires during attribute lane, activity re-match must not crash on undefined age."""
    forced_profile = AttributeProfile(
        attribute_id="appearance.color",
        label="color",
        activity_target="noticing colors",
        branch="in_kb",
        object_examples=("apple",),
        fallback_attributes=(
            AttributeProfile(
                attribute_id="appearance.shape",
                label="shape",
                activity_target="noticing shapes",
                branch="in_kb",
                object_examples=("apple",),
            ),
        ),
    )
    forced_debug = {
        "decision": "attribute_selected",
        "source": "test_patch",
        "attribute_id": "appearance.color",
        "confidence": "high",
        "reason": "selected by test patch",
    }

    forced_state = DiscoverySessionState(
        object_name="apple",
        age=6,
        profile=forced_profile,
        primary_activity=ActivityDefinition(activity_id="test_color", name="Test Color Activity"),
    )
    with patch("paixueji_app.select_activities_for_object", new=AsyncMock(return_value=(forced_state, forced_debug))):
        start = client.post(
            "/api/start",
            json={"age": 6, "object_name": "apple", "attribute_pipeline_enabled": True},
        )
    start_chunk = final_chunk(start)
    session_id = start_chunk["session_id"]

    set_intent(mock_gemini_client, "CURIOSITY")

    with patch("paixueji_app.detect_topic_switch", new=AsyncMock(return_value=(True, "appearance.shape", "child asked about shape"))):
        response = client.post(
            "/api/continue",
            json={"session_id": session_id, "child_input": "what shape is it"},
        )

    assert response.status_code == 200
    chunk = final_chunk(response)
    assert chunk["attribute_lane_active"] is True
