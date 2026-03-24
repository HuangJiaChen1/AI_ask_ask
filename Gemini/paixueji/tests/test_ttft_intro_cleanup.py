import json

from paixueji_prompts import USER_INTENT_PROMPT


def _parse_sse(response_data):
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


def test_start_intro_avoids_blocking_non_streaming_llm_calls(client, mock_gemini_client):
    response = client.post("/api/start", json={"object_name": "apple", "age": 6})

    assert response.status_code == 200
    events = _parse_sse(response.data)
    assert any(event["event"] == "chunk" for event in events)
    assert any(event["event"] == "complete" for event in events)
    assert mock_gemini_client.aio.models.generate_content.await_count == 0, (
        "Introduction TTFT path should not perform any non-streaming aio generate_content calls "
        "before the first streamed chunk."
    )


def test_user_intent_prompt_does_not_duplicate_classifier_rules():
    needle = "TASK: Classify what this child is doing, and extract a new topic if they name one."
    assert USER_INTENT_PROMPT.count(needle) == 1, (
        "USER_INTENT_PROMPT should contain the classifier task header once; duplicated rules "
        "inflate classifier latency on continuation turns."
    )
