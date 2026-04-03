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
    return "Yes, when a cat smells cat food, it knows food is there. Why do you think a cat's nose helps it find food?"


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
    assert first_chunk["bridge_attempt_count"] == 1


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
    assert final_chunk["bridge_attempt_count"] == 2
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


def test_second_bridge_miss_suppresses_anchor_and_falls_back_to_unresolved_chat(client, monkeypatch):
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
    client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is crunchy"},
    )

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": False, "reason": "second miss"}),
    )

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "it is brown"},
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


def test_bridge_activation_response_mentions_surface_and_anchor_and_one_question(client, monkeypatch):
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

    assert "cat food" in text
    assert "cat" in text
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


def test_bridge_activation_first_question_stays_in_food_for_lane(client, monkeypatch):
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

    assert any(term in text for term in ["smell", "nose", "eat", "food"])
    assert "paw" not in text
    assert "tail" not in text
