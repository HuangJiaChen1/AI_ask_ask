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


def test_attribute_pipeline_start_uses_attribute_intro_and_debug(client, mock_gemini_client):
    response = client.post(
        "/api/start",
        json={"age": 6, "object_name": "apple", "attribute_pipeline_enabled": True},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "attribute_intro"
    assert chunk["attribute_pipeline_enabled"] is True
    assert chunk["attribute_lane_active"] is True
    assert "." in chunk["attribute_debug"]["profile"]["attribute_id"]  # new format: dimension.sub_attribute
    assert chunk["attribute_debug"]["state"]["profile"]["attribute_id"] == chunk["attribute_debug"]["profile"]["attribute_id"]

    prompt_text = streamed_prompt_text(mock_gemini_client)
    assert "BEAT 1" in prompt_text
    assert "EMOTIONAL OPENING" in prompt_text
    assert "BEAT 2" in prompt_text
    assert "OBJECT CONFIRMATION" in prompt_text
    assert "BEAT 3" in prompt_text
    assert "FEATURE DESCRIPTION" in prompt_text
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

    # With dynamic candidates, every object gets sub_attributes (defaults for unknown domain).
    # "plain thing" has no KB entry and mock Gemini returns non-JSON,
    # so first_candidate_fallback is used — attribute lane is still activated.
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


def test_attribute_continue_keeps_attribute_state_and_skips_bridge_activation(client):
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat food", "attribute_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "I can't smell it"},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "attribute_activity"
    assert chunk["attribute_lane_active"] is True
    assert chunk["bridge_phase"] != "activation"
    assert "." in chunk["attribute_debug"]["state"]["profile"]["attribute_id"]  # new format: dimension.sub_attribute
    assert chunk["attribute_debug"]["reply"]["reply_type"] == "constraint_avoidance"


def test_attribute_continue_activity_ready_sets_completion_and_handoff_target(client):
    start = client.post(
        "/api/start",
        json={"age": 6, "object_name": "cat food", "attribute_pipeline_enabled": True},
    )
    session_id = final_chunk(start)["session_id"]

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "Let's play a smell game"},
    )

    chunk = final_chunk(response)

    assert chunk["response_type"] == "attribute_activity"
    assert chunk["activity_ready"] is True
    assert chunk["chat_phase_complete"] is True
    assert chunk["activity_target"]["activity_source"] == "attribute"
    assert "." in chunk["activity_target"]["attribute_id"]  # new format: dimension.sub_attribute
