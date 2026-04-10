import json
from unittest.mock import AsyncMock, MagicMock


def parse_sse(response_data):
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


def _bridge_activation_text():
    return "Your cat really likes wet food. What does your cat do when dinner is ready?"


def _install_bridge_activation_stream(monkeypatch):
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    def side_effect_stream(model, contents, config=None):
        response_text = _bridge_activation_text()
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )


def test_start_with_high_confidence_anchor_stays_on_surface_object(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    assert response.status_code == 200

    events = parse_sse(response.data)
    first_chunk = next(e["data"] for e in events if e["event"] == "chunk")

    assert first_chunk["surface_object_name"] == "cat food"
    assert first_chunk["current_object_name"] == "cat food"
    assert first_chunk["anchor_object_name"] == "cat"
    assert first_chunk["anchor_status"] == "anchored_high"
    assert first_chunk["learning_anchor_active"] is False
    assert first_chunk["correct_answer_count"] == 0
    assert first_chunk["bridge_attempt_count"] == 0


def test_start_with_unresolved_object_stays_surface_and_disables_learning(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="spaceship fuel",
            visible_object_name="spaceship fuel",
            anchor_object_name=None,
            anchor_status="unresolved",
            anchor_relation=None,
            anchor_confidence_band=None,
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
            resolution_debug={"decision_reason": "no_model_client", "decision_source": "unresolved"},
        ),
    )

    response = client.post("/api/start", json={"age": 6, "object_name": "spaceship fuel"})
    assert response.status_code == 200

    events = parse_sse(response.data)
    first_chunk = next(e["data"] for e in events if e["event"] == "chunk")

    assert first_chunk["surface_object_name"] == "spaceship fuel"
    assert first_chunk["current_object_name"] == "spaceship fuel"
    assert first_chunk["anchor_object_name"] is None
    assert first_chunk["anchor_status"] == "unresolved"
    assert first_chunk["learning_anchor_active"] is False
    assert first_chunk["resolution_debug"]["decision_reason"] == "no_model_client"


def test_start_with_relation_repair_records_resolution_debug(client, monkeypatch):
    client_mock = MagicMock()
    client_mock.models.generate_content.side_effect = [
        MagicMock(text='{"anchor_object_name": null, "relation": null, "confidence_band": "low"}'),
        MagicMock(text='{"relation": "food_for", "confidence_band": "high"}'),
    ]
    monkeypatch.setattr("paixueji_app.GLOBAL_GEMINI_CLIENT", client_mock)

    response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    assert response.status_code == 200

    events = parse_sse(response.data)
    first_chunk = next(e["data"] for e in events if e["event"] == "chunk")

    assert first_chunk["anchor_status"] == "anchored_high"
    assert first_chunk["resolution_debug"]["decision_source"] == "relation_repair"


def test_cat_food_start_recovers_from_fenced_json_and_enters_anchor_bridge(client, monkeypatch):
    client_mock = MagicMock()
    client_mock.models.generate_content.return_value.text = """```json
{
  "anchor_object_name": "cat",
  "relation": "food_for",
  "confidence_band": "high"
}
```"""
    monkeypatch.setattr("paixueji_app.GLOBAL_GEMINI_CLIENT", client_mock)

    response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    assert response.status_code == 200

    events = parse_sse(response.data)
    first_chunk = next(e["data"] for e in events if e["event"] == "chunk")

    assert first_chunk["anchor_status"] == "anchored_high"
    assert first_chunk["resolution_debug"]["raw_model_payload_kind"] == "fenced_json"
    assert first_chunk["resolution_debug"]["json_recovery_applied"] is True


def test_unresolved_start_reports_bridge_not_started_reason(client, monkeypatch):
    client_mock = MagicMock()
    client_mock.models.generate_content.return_value.text = "not json"
    monkeypatch.setattr("paixueji_app.GLOBAL_GEMINI_CLIENT", client_mock)
    monkeypatch.setattr("object_resolver._candidate_anchor_shortlist", lambda *_args, **_kwargs: [])

    response = client.post("/api/start", json={"age": 6, "object_name": "spaceship fuel"})
    assert response.status_code == 200

    events = parse_sse(response.data)
    first_chunk = next(e["data"] for e in events if e["event"] == "chunk")

    assert first_chunk["anchor_status"] == "unresolved"
    assert first_chunk["bridge_debug"]["decision"] == "bridge_not_started"
    assert first_chunk["bridge_debug"]["decision_reason"] == "resolution_unresolved"
    assert first_chunk["resolution_debug"]["decision_reason"] == "invalid_json_no_candidate"


def test_medium_confidence_confirmation_accepts_anchor_and_switches(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_medium",
            anchor_relation="food_for",
            anchor_confidence_band="medium",
            anchor_confirmation_needed=True,
            learning_anchor_active=False,
        ),
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    start_events = parse_sse(start_response.data)
    session_id = next(e["data"]["session_id"] for e in start_events if e["event"] == "chunk")

    continue_response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "yes, cat"},
    )
    assert continue_response.status_code == 200

    events = parse_sse(continue_response.data)
    first_chunk = next(e["data"] for e in events if e["event"] == "chunk")

    assert first_chunk["current_object_name"] == "cat"
    assert first_chunk["surface_object_name"] == "cat food"
    assert first_chunk["anchor_object_name"] == "cat"
    assert first_chunk["learning_anchor_active"] is True
    assert first_chunk["correct_answer_count"] == 0


def test_medium_confidence_rejection_suppresses_anchor_and_stays_surface(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_medium",
            anchor_relation="food_for",
            anchor_confidence_band="medium",
            anchor_confirmation_needed=True,
            learning_anchor_active=False,
        ),
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    start_events = parse_sse(start_response.data)
    session_id = next(e["data"]["session_id"] for e in start_events if e["event"] == "chunk")

    continue_response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "no, stay with cat food"},
    )
    assert continue_response.status_code == 200

    events = parse_sse(continue_response.data)
    first_chunk = next(e["data"] for e in events if e["event"] == "chunk")

    assert first_chunk["current_object_name"] == "cat food"
    assert first_chunk["surface_object_name"] == "cat food"
    assert first_chunk["anchor_object_name"] == "cat"
    assert first_chunk["learning_anchor_active"] is False


def test_force_switch_high_confidence_enters_pre_anchor_state(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="apple",
            visible_object_name="apple",
            anchor_object_name="apple",
            anchor_status="exact_supported",
            anchor_relation="exact_match",
            anchor_confidence_band="exact",
            anchor_confirmation_needed=False,
            learning_anchor_active=True,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "apple"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
            resolution_debug={"decision_source": "model_inference"},
        ),
    )

    response = client.post(
        "/api/force-switch",
        json={"session_id": session_id, "new_object": "cat food"},
    )
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["new_object"] == "cat food"
    assert payload["learning_anchor_active"] is False


def test_bridge_follow_switches_to_anchor_on_continue(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "answered smell bridge"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "with its nose"},
    )
    assert response.status_code == 200

    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]
    assert final_chunk["current_object_name"] == "cat"
    assert final_chunk["learning_anchor_active"] is True
    assert final_chunk["correct_answer_count"] == 0


def test_first_bridge_miss_emits_retry_bridge(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": False, "reason": "stayed on food"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is crunchy"},
    )
    assert response.status_code == 200

    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]
    assert final_chunk["current_object_name"] == "cat food"
    assert final_chunk["learning_anchor_active"] is False
    assert final_chunk["bridge_attempt_count"] == 1
    assert final_chunk["response_type"] == "bridge_retry"


def test_pre_anchor_surface_reply_does_not_fall_into_correct_answer_flow(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": False, "reason": "surface-only description"}),
    )

    continue_response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "It looks like small cookies"},
    )
    assert continue_response.status_code == 200

    final_chunk = [e["data"] for e in parse_sse(continue_response.data) if e["event"] == "chunk"][-1]
    assert final_chunk["response_type"] == "bridge_retry"
    assert final_chunk["learning_anchor_active"] is False
    assert final_chunk["bridge_debug"]["pre_anchor_handler_entered"] is True
    assert final_chunk["bridge_debug"]["decision"] == "bridge_retry"


def test_third_bridge_miss_suppresses_anchor_and_falls_back_to_unresolved_chat(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    start_events = parse_sse(start_response.data)
    session_id = next(e["data"]["session_id"] for e in start_events if e["event"] == "chunk")

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": False, "reason": "first miss"}),
    )
    first_retry = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is crunchy"},
    )
    [e["data"] for e in parse_sse(first_retry.data) if e["event"] == "chunk"]

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": False, "reason": "second miss"}),
    )

    second_retry = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is brown"},
    )
    second_final = [e["data"] for e in parse_sse(second_retry.data) if e["event"] == "chunk"][-1]
    assert second_final["response_type"] == "bridge_retry"
    assert second_final["bridge_attempt_count"] == 2

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is tiny"},
    )
    assert response.status_code == 200

    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]
    assert final_chunk["current_object_name"] == "cat food"
    assert final_chunk["anchor_status"] == "unresolved"
    assert final_chunk["learning_anchor_active"] is False
    assert final_chunk["bridge_debug"]["decision"] == "unresolved_fallback"
    assert any(node["node"] == "driver:bridge_decision" for node in final_chunk["nodes_executed"])


def test_successful_bridge_follow_uses_bridge_activation_not_topic_switch(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")
    _install_bridge_activation_stream(monkeypatch)

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "maybe it smells nice, else she won't eat it"},
    )
    assert response.status_code == 200

    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]
    assert final_chunk["response_type"] == "bridge_activation"
    assert final_chunk["current_object_name"] == "cat"
    assert final_chunk["learning_anchor_active"] is True
    assert final_chunk["bridge_debug"]["decision"] == "bridge_activation"


def test_bridge_activation_preserves_pre_anchor_traces(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")
    _install_bridge_activation_stream(monkeypatch)

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "maybe it smells nice, else she won't eat it"},
    )
    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]

    assert [node["node"] for node in final_chunk["nodes_executed"]] == [
        "driver:pre_anchor_gate",
        "validator:bridge_follow",
        "driver:bridge_decision",
    ]
    assert final_chunk["nodes_executed"][-1]["changes"]["decision"] == "bridge_activation"


def test_successful_bridge_follow_final_chunk_has_evaluated_bridge_debug(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")
    _install_bridge_activation_stream(monkeypatch)

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "maybe it smells nice, else she won't eat it"},
    )
    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]

    assert final_chunk["bridge_debug"]["bridge_visible_in_response"] is True
    assert final_chunk["bridge_debug"]["bridge_visibility_reason"] != "response not evaluated yet"


def test_bridge_activation_does_not_pass_bridge_context_to_generator(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    import paixueji_app

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    captured = {}

    async def fake_generator(
        messages,
        child_answer,
        surface_object_name,
        anchor_object_name,
        age,
        age_prompt,
        bridge_context,
        config,
        client,
    ):
        captured["messages"] = messages
        captured["child_answer"] = child_answer
        captured["surface_object_name"] = surface_object_name
        captured["anchor_object_name"] = anchor_object_name
        captured["bridge_context"] = bridge_context
        full = _bridge_activation_text()
        yield ("Your ", None, "Your ")
        yield ("cat really likes wet food. What does your cat do when dinner is ready?", None, full)
        yield ("", None, full)

    monkeypatch.setattr(
        "paixueji_app.generate_bridge_activation_response_stream",
        fake_generator,
    )
    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "anchor mentioned explicitly"}),
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "my cat likes wet food a lot"},
    )
    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]

    assert captured["anchor_object_name"] == "cat"
    assert captured["surface_object_name"] == "cat food"
    assert captured["bridge_context"] == ""
    assert final_chunk["response_type"] == "bridge_activation"
    assert final_chunk["current_object_name"] == "cat"
    assert final_chunk["learning_anchor_active"] is True


def test_bridge_activation_response_can_be_anchor_focused_without_surface_link_sentence(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")
    _install_bridge_activation_stream(monkeypatch)

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "maybe it smells nice, else she won't eat it"},
    )
    text = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]["response"].lower()

    assert "your cat" in text
    assert "cat food" not in text
    assert text.count("?") == 1


def test_bridge_activation_response_does_not_use_generic_filler(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")
    _install_bridge_activation_stream(monkeypatch)

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "maybe it smells nice, else she won't eat it"},
    )
    text = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]["response"].lower()

    assert "i love cats" not in text
    assert "that is so cool" not in text
    assert "excited to learn more" not in text


def test_bridge_activation_response_does_not_drift_to_unopened_cat_dimensions(client, monkeypatch):
    from object_resolver import ObjectResolutionResult

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )
    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")
    _install_bridge_activation_stream(monkeypatch)

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "maybe it smells nice, else she won't eat it"},
    )
    text = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]["response"].lower()

    assert "paw" not in text
    assert "tail" not in text
    assert "whisker" not in text


def test_affirmative_reply_to_retry_bridge_activates_anchor_instead_of_correct_answer(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    streamed_responses = iter([
        "Cat food is interesting. What does the cat food look like inside the bag?",
        "That makes sense. When you put the food in her bowl, does she use her nose to sniff it before she starts to eat?",
        _bridge_activation_text(),
    ])

    def side_effect_stream(model, contents, config=None):
        response_text = next(streamed_responses)
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    first_continue = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "she might"},
    )
    first_final = [e["data"] for e in parse_sse(first_continue.data) if e["event"] == "chunk"][-1]
    assert first_final["response_type"] == "bridge_retry"

    second_continue = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "yep"},
    )
    second_final = [e["data"] for e in parse_sse(second_continue.data) if e["event"] == "chunk"][-1]

    assert second_final["response_type"] == "bridge_activation"
    assert second_final["current_object_name"] == "cat"
    assert second_final["learning_anchor_active"] is True
    assert second_final["bridge_debug"]["decision"] == "bridge_activation"
    assert second_final["nodes_executed"][-1]["changes"]["decision"] == "bridge_activation"
    assert not any(node["node"] == "analyze_input" for node in second_final["nodes_executed"])
    assert not any(node["node"] == "correct_answer" for node in second_final["nodes_executed"])


def test_pre_anchor_clarification_request_uses_bridge_support_without_attempt_increment(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    streamed_responses = iter([
        "Cat food is interesting. What is the most important part of cat food for a cat to eat?",
        "I mean, a cat can notice cat food in simple ways. What might its nose smell first?",
    ])

    def side_effect_stream(model, contents, config=None):
        response_text = next(streamed_responses)
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    response = client.post("/api/continue", json={"session_id": session_id, "child_input": "what do you mean?"})
    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]

    assert final_chunk["response_type"] == "bridge_support"
    assert final_chunk["bridge_attempt_count"] == 0
    assert final_chunk["pre_anchor_support_count"] == 1
    assert final_chunk["bridge_debug"]["pre_anchor_reply_type"] == "clarification_request"
    assert final_chunk["bridge_debug"]["support_action"] == "clarify"
    assert final_chunk["bridge_debug"]["bridge_visibility_reason"] != "response not evaluated yet"
    assert not any(node["node"] == "correct_answer" for node in final_chunk["nodes_executed"])


def test_pre_anchor_idk_uses_bridge_support_without_attempt_increment(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    streamed_responses = iter([
        "Cat food is interesting. Does she use her nose to sniff it?",
        "That's okay. Cats often sniff food before they eat. What might a cat do first?",
    ])

    def side_effect_stream(model, contents, config=None):
        response_text = next(streamed_responses)
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    response = client.post("/api/continue", json={"session_id": session_id, "child_input": "I don't know"})
    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]

    assert final_chunk["response_type"] == "bridge_support"
    assert final_chunk["bridge_attempt_count"] == 0
    assert final_chunk["pre_anchor_support_count"] == 1
    assert final_chunk["bridge_debug"]["pre_anchor_reply_type"] == "idk_or_stuck"
    assert final_chunk["bridge_debug"]["support_action"] == "scaffold"


def test_first_pre_anchor_idk_support_receives_intro_bridge_question(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    captured = {}

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    def side_effect_stream(model, contents, config=None):
        response_text = "Cat food is interesting. What might a cat do first when it gets near the food?"
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    async def fake_bridge_support_response_stream(**kwargs):
        captured["previous_bridge_question"] = kwargs["previous_bridge_question"]
        full = "That's okay. Cats often sniff food before they eat. What might a cat do first?"
        yield (full, None, full)

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )
    monkeypatch.setattr(
        paixueji_app,
        "generate_bridge_support_response_stream",
        fake_bridge_support_response_stream,
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    response = client.post("/api/continue", json={"session_id": session_id, "child_input": "I'm not sure, maybe?"})
    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]

    assert captured["previous_bridge_question"] == (
        "Cat food is interesting. What might a cat do first when it gets near the food?"
    )
    assert final_chunk["response_type"] == "bridge_support"
    assert final_chunk["bridge_debug"]["pre_anchor_reply_type"] == "idk_or_stuck"


def test_pre_anchor_idk_support_stays_in_same_question_family(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    streamed_responses = iter([
        "Cat food is here. What might a cat do first when it notices the food?",
        "That's okay. A cat might sniff the food first. What might it do when it notices the food?",
    ])

    def side_effect_stream(model, contents, config=None):
        response_text = next(streamed_responses)
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    response = client.post("/api/continue", json={"session_id": session_id, "child_input": "I don't know"})
    final_chunk = [e["data"] for e in parse_sse(response.data) if e["event"] == "chunk"][-1]

    assert final_chunk["response_type"] == "bridge_support"
    assert final_chunk["bridge_debug"]["pre_anchor_reply_type"] == "idk_or_stuck"


def test_valid_out_of_lane_answer_after_support_soft_activates_without_correct_answer_fallthrough(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    monkeypatch.setattr(
        "paixueji_app.resolve_object_input",
        lambda *args, **kwargs: ObjectResolutionResult(
            surface_object_name="cat food",
            visible_object_name="cat food",
            anchor_object_name="cat",
            anchor_status="anchored_high",
            anchor_relation="food_for",
            anchor_confidence_band="high",
            anchor_confirmation_needed=False,
            learning_anchor_active=False,
        ),
    )

    streamed_responses = iter([
        "Cat food is interesting. What is the most important part of cat food for a cat to eat?",
        "I mean, a cat can notice cat food in simple ways. What might its nose smell first?",
        _bridge_activation_text(),
    ])

    def side_effect_stream(model, contents, config=None):
        response_text = next(streamed_responses)
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )

    start_response = client.post("/api/start", json={"age": 6, "object_name": "cat food"})
    session_id = next(e["data"]["session_id"] for e in parse_sse(start_response.data) if e["event"] == "chunk")

    first = client.post("/api/continue", json={"session_id": session_id, "child_input": "what do you mean?"})
    first_final = [e["data"] for e in parse_sse(first.data) if e["event"] == "chunk"][-1]
    assert first_final["response_type"] == "bridge_support"

    second = client.post("/api/continue", json={"session_id": session_id, "child_input": "they can see it"})
    second_final = [e["data"] for e in parse_sse(second.data) if e["event"] == "chunk"][-1]

    assert second_final["response_type"] == "bridge_activation"
    assert second_final["current_object_name"] == "cat"
    assert second_final["learning_anchor_active"] is True
    assert second_final["bridge_debug"]["decision"] == "bridge_activation"
    assert second_final["bridge_debug"]["pre_anchor_reply_type"] == "valid_out_of_lane_anchor_related"
    assert not any(node["node"] == "analyze_input" for node in second_final["nodes_executed"])
    assert not any(node["node"] == "correct_answer" for node in second_final["nodes_executed"])
