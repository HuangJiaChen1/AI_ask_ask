import json
from unittest.mock import AsyncMock, MagicMock, patch

from attribute_activity import AttributeProfile


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
    response = MagicMock()
    response.text = text
    mock_gemini_client.aio.models.generate_content.return_value = response


def set_intent(mock_gemini_client, intent_type, reasoning="Mock classification"):
    set_async_text(
        mock_gemini_client,
        f"INTENT: {intent_type}\nNEW_OBJECT: null\nREASONING: {reasoning}",
    )


def test_attribute_pipeline_start_passes_attribute_hook_filter(client, mock_gemini_client):
    with patch("paixueji_app.select_attribute_profile", return_value=(None, {"reason": "test bypass"})):
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

    with patch("paixueji_app.select_attribute_profile", return_value=(None, {"reason": "test bypass"})):
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
    assert "SALIENCE HIGHLIGHT" in prompt_text
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
    assert chunk["attribute_debug"]["profile"]["branch"] == "unresolved_not_in_kb"
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
    assert chunk["attribute_debug"]["profile"]["attribute_id"].startswith("appearance.")


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

    with patch("paixueji_app.select_attribute_profile", new=AsyncMock(return_value=(forced_profile, forced_debug))):
        start = client.post(
            "/api/start",
            json={"age": 6, "object_name": "cat food", "attribute_pipeline_enabled": True},
        )
    start_chunk = final_chunk(start)
    session_id = start_chunk["session_id"]
    assert start_chunk["attribute_debug"]["profile"]["attribute_id"] == "senses.smell"

    set_intent(mock_gemini_client, "CORRECT_ANSWER")
    first = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "It smells strong"},
    )
    first_chunk = final_chunk(first)
    assert first_chunk["response_type"] == "attribute_activity"
    # activity_ready is False until LLM emits [ACTIVITY_READY] marker
    assert first_chunk["activity_ready"] is False
    assert "activity_marker_detected" in first_chunk["attribute_debug"]
