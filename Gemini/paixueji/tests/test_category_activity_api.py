import json


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


def test_category_pipeline_start_uses_category_intro_and_debug(client, mock_gemini_client):
    response = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat", "category_pipeline_enabled": True},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "category_intro"
    assert chunk["category_pipeline_enabled"] is True
    assert chunk["category_lane_active"] is True
    assert chunk["category_debug"]["profile"]["category_id"] == "animals"
    assert chunk["activity_target"]["activity_source"] == "category"
    assert chunk["activity_target"]["category_id"] == "animals"

    prompt_text = streamed_prompt_text(mock_gemini_client)
    assert "Animals" in prompt_text
    assert "different animals" in prompt_text


def test_category_pipeline_supports_unknown_domain_fallback(client, mock_gemini_client):
    mock_response = mock_gemini_client.aio.models.generate_content.return_value
    mock_response.text = '{"domain":"not_a_real_domain"}'

    response = client.post(
        "/api/start",
        json={"age": 6, "object_name": "plain thing", "category_pipeline_enabled": True},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "category_intro"
    assert chunk["category_pipeline_enabled"] is True
    assert chunk["category_lane_active"] is True
    assert chunk["category_debug"]["profile"]["category_id"] is None
    assert chunk["category_debug"]["profile"]["activity_target"] == "exploring different kinds of things in our world"


def test_category_continue_keeps_category_state_and_skips_bridge_activation(client):
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat", "category_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "Cars race fast"},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "category_chat"
    assert chunk["category_lane_active"] is True
    assert chunk["bridge_phase"] != "activation"
    assert chunk["category_debug"]["reply"]["reply_type"] == "category_drift"
    assert chunk["activity_ready"] is False


def test_category_continue_activity_ready_after_two_engaged_turns(client):
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat", "category_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    first = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "I like dogs too"},
    )
    first_chunk = final_chunk(first)
    assert first_chunk["activity_ready"] is False
    assert first_chunk["chat_phase_complete"] is None
    assert first_chunk["category_debug"]["readiness"]["engaged_turn_count"] == 1

    second = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "Why do animals have tails?"},
    )
    second_chunk = final_chunk(second)

    assert second_chunk["response_type"] == "category_activity"
    assert second_chunk["activity_ready"] is True
    assert second_chunk["chat_phase_complete"] is True
    assert second_chunk["category_debug"]["readiness"]["readiness_source"] == "backend_engagement_policy"
    assert second_chunk["activity_target"]["activity_source"] == "category"
    assert second_chunk["activity_target"]["category_label"] == "Animals"
