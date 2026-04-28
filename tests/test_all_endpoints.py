import pytest
import json
from pathlib import Path

def parse_sse(response_data):
    """Parses SSE response text into a list of event/data dicts."""
    events = []
    text = response_data.decode('utf-8')
    blocks = text.split('\n\n')
    for block in blocks:
        if not block.strip():
            continue
        lines = block.split('\n')
        event_type = None
        data = None
        for line in lines:
            if line.startswith('event: '):
                event_type = line[7:].strip()
            elif line.startswith('data: '):
                try:
                    data = json.loads(line[6:].strip())
                except json.JSONDecodeError:
                    data = line[6:].strip()
        if event_type:
            events.append({'event': event_type, 'data': data})
    return events


def _install_bridge_activation_stream(monkeypatch):
    from tests.conftest import MockChunk, MockStream
    import paixueji_app

    def side_effect_stream(model, contents, config=None):
        response_text = "Your cat really likes wet food. What does your cat do when dinner is ready?"
        return MockStream([MockChunk(word + " ") for word in response_text.split()])

    monkeypatch.setattr(
        paixueji_app.GLOBAL_GEMINI_CLIENT.aio.models.generate_content_stream,
        "side_effect",
        side_effect_stream,
        raising=False,
    )

def test_static_index(client):
    """Test that the index page is served."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'Paixueji' in response.data
    assert b'Classify' not in response.data
    assert b'Level 1 Category' not in response.data
    assert b'Level 2 Category' not in response.data
    assert b'Level 3 Category' not in response.data

def test_health_check(client):
    """Test health check endpoint."""
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ok'

def test_classification_endpoint_removed(client):
    """Test that the legacy classify endpoint is no longer exposed."""
    payload = {"object_name": "banana"}
    response = client.post('/api/classify', json=payload)
    assert response.status_code == 404

def test_full_conversation_flow(client):
    """Test the main lifecycle: Start -> List -> Continue -> Reset."""
    # 1. Start session
    start_payload = {"object_name": "apple", "age": 6}
    response = client.post('/api/start', json=start_payload)
    assert response.status_code == 200
    events = parse_sse(response.data) # Consumes stream
    session_id = events[0]['data']['session_id']
    assert session_id is not None
    assert all(
        e['data'].get('ibpyp_theme_name') is None
        for e in events
        if e['event'] == 'chunk'
    )

    # 2. Verify in sessions list
    response = client.get('/api/sessions')
    assert session_id in response.get_json()['sessions']

    # 3. Continue conversation
    continue_payload = {"session_id": session_id, "child_input": "It is red"}
    response = client.post('/api/continue', json=continue_payload)
    assert response.status_code == 200
    events = parse_sse(response.data) # Consumes stream
    assert any(e['event'] == 'complete' for e in events)

    # 4. Force Switch
    switch_payload = {"session_id": session_id, "new_object": "orange"}
    response = client.post('/api/force-switch', json=switch_payload)
    assert response.status_code == 200
    assert response.get_json()['new_object'] == 'orange'

    # 5. Reset/Delete session
    response = client.post('/api/reset', json={"session_id": session_id})
    assert response.status_code == 200
    
    # Verify gone
    response = client.get('/api/sessions')
    assert session_id not in response.get_json()['sessions']

def test_critique_engine(client):
    """Test both Manual and AI critique endpoints."""
    # Setup history - MUST consume streams to update history
    start_resp = client.post('/api/start', json={"object_name": "banana"})
    events_start = parse_sse(start_resp.data)
    session_id = events_start[0]['data']['session_id']
    
    cont_resp = client.post('/api/continue', json={"session_id": session_id, "child_input": "Yellow"})
    parse_sse(cont_resp.data) # MUST consume to trigger history update

    # 1. Exchanges extraction
    response = client.get(f'/api/exchanges/{session_id}')
    assert response.status_code == 200
    data = response.get_json()
    exchanges = data['exchanges']
    assert len(exchanges) > 0, f"No exchanges found. History length: {len(exchanges)}"

    # 2. Manual Critique submission
    critique_payload = {
        "session_id": session_id,
        "exchange_critiques": [{
            "exchange_index": 1,
            "model_question_expected": "Test",
            "model_question_problem": "Test",
            "model_response_expected": "Test",
            "model_response_problem": "Test",
            "conclusion": "Test"
        }],
        "global_conclusion": "Test"
    }
    response = client.post('/api/manual-critique', json=critique_payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body['success'] is True

    report_path = Path(body["report_path"])
    report_date = report_path.parent.name
    report_name = report_path.name

    detail_response = client.get(f"/api/reports/hf/{report_date}/{report_name}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    assert detail["meta"]["object"] == "banana"
    assert detail["meta"]["key_concept"] in (None, "Change")
    assert any(turn["role"] == "model" and turn["critique"] for turn in detail["transcript"])

    raw_response = client.get(f"/api/reports/hf/{report_date}/{report_name}/raw")
    assert raw_response.status_code == 200
    assert raw_response.mimetype == "text/plain"

def test_start_guide_endpoint_removed(client):
    """Guide-only testing endpoint should no longer be exposed."""
    payload = {"object_name": "banana", "age": 6}
    response = client.post('/api/start-guide', json=payload)
    assert response.status_code == 404


def test_handoff_uses_tmp_handoff_route(client):
    """Test handoff redirect and file serving use /tmp/handoff/<file>.json."""
    start_response = client.post('/api/start', json={"object_name": "apple", "age": 6})
    events = parse_sse(start_response.data)
    session_id = events[0]['data']['session_id']

    handoff_response = client.post('/api/handoff', json={"session_id": session_id})
    assert handoff_response.status_code == 200
    handoff_data = handoff_response.get_json()

    context_path = handoff_data["context_path"]
    assert context_path.startswith("/tmp/handoff/")
    assert context_path.endswith(".json")
    assert "context=" in handoff_data["redirect_url"]
    assert f"context=http://localhost{context_path}" in handoff_data["redirect_url"]

    context_response = client.get(context_path)
    assert context_response.status_code == 200
    assert context_response.is_json

    old_route_response = client.get(context_path.replace("/tmp/handoff/", "/handoff/"))
    assert old_route_response.status_code == 404


def test_attribute_handoff_context_includes_attribute_metadata(client):
    start_response = client.post(
        '/api/start',
        json={"object_name": "cat food", "age": 6, "attribute_pipeline_enabled": True},
    )
    events = parse_sse(start_response.data)
    session_id = events[0]['data']['session_id']

    for child_input in ["It smells strong", "My lunch smells strong too"]:
        continue_response = client.post(
            '/api/continue',
            json={"session_id": session_id, "child_input": child_input},
        )
        parse_sse(continue_response.data)

    # In the LLM-driven attribute pipeline, readiness is set when the LLM emits
    # [ACTIVITY_READY]. Simulate that marker being detected so the handoff endpoint
    # returns attribute metadata.
    import paixueji_app
    assistant = paixueji_app.sessions.get(session_id)
    assert assistant is not None
    assistant.attribute_activity_ready = True
    assistant.attribute_state.activity_ready = True

    handoff_response = client.post('/api/handoff', json={"session_id": session_id})
    assert handoff_response.status_code == 200
    handoff_data = handoff_response.get_json()

    context_response = client.get(handoff_data["context_path"])
    assert context_response.status_code == 200
    context = context_response.get_json()

    assert context["activity_source"] == "attribute"
    assert "." in context["attribute_id"]  # new format: dimension.sub_attribute
    assert context["attribute_label"]  # non-empty label
    assert context["activity_target"]  # non-empty activity target
    assert context["conversation"]


def test_category_handoff_context_includes_category_metadata(client):
    start_response = client.post(
        '/api/start',
        json={"object_name": "cat", "age": 6, "category_pipeline_enabled": True},
    )
    events = parse_sse(start_response.data)
    session_id = events[0]['data']['session_id']

    for child_input in ["I like dogs too", "Why do animals have tails?"]:
        continue_response = client.post(
            '/api/continue',
            json={"session_id": session_id, "child_input": child_input},
        )
        parse_sse(continue_response.data)

    handoff_response = client.post('/api/handoff', json={"session_id": session_id})
    assert handoff_response.status_code == 200
    handoff_data = handoff_response.get_json()

    context_response = client.get(handoff_data["context_path"])
    assert context_response.status_code == 200
    context = context_response.get_json()

    assert context["activity_source"] == "category"
    assert context["category_id"] == "animals"
    assert context["category_label"] == "Animals"
    assert context["activity_target"]
    assert context["conversation"]


def test_exchanges_endpoint_exposes_attribute_debug(client):
    start_response = client.post(
        '/api/start',
        json={"object_name": "apple", "age": 6, "attribute_pipeline_enabled": True},
    )
    events = parse_sse(start_response.data)
    session_id = events[0]['data']['session_id']

    continue_response = client.post(
        '/api/continue',
        json={"session_id": session_id, "child_input": "My spoon is shiny too"},
    )
    parse_sse(continue_response.data)

    response = client.get(f'/api/exchanges/{session_id}')
    assert response.status_code == 200
    data = response.get_json()

    assert "." in data["introduction"]["attribute_debug"]["profile"]["attribute_id"]  # new format: dimension.sub_attribute
    # New debug shape uses activity_marker_detected and intent_type, not reply/readiness
    assert "activity_marker_detected" in data["exchanges"][0]["attribute_debug"]


def test_manual_critique_report_preserves_attribute_debug(client):
    start_response = client.post(
        '/api/start',
        json={"object_name": "apple", "age": 6, "attribute_pipeline_enabled": True},
    )
    events = parse_sse(start_response.data)
    session_id = events[0]['data']['session_id']

    continue_response = client.post(
        '/api/continue',
        json={"session_id": session_id, "child_input": "It is round"},
    )
    parse_sse(continue_response.data)

    response = client.post('/api/manual-critique', json={
        "session_id": session_id,
        "exchange_critiques": [{
            "exchange_index": 1,
            "model_response_problem": "Matched shape but asked about another attribute.",
        }],
        "skip_traces": True,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True

    report_path = Path(body["report_path"])
    report_text = report_path.read_text(encoding="utf-8")
    assert "Attribute ID" in report_text
    assert "Raw Attribute Debug" in report_text

    detail_response = client.get(f"/api/reports/hf/{report_path.parent.name}/{report_path.name}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    model_turn = next(
        turn for turn in detail["transcript"]
        if turn["role"] == "model" and turn.get("exchange_index") == 1
    )
    assert model_turn["attribute_debug"]["profile"]["attribute_id"].startswith("appearance.")
    assert model_turn["critique"]["attribute_debug"]["profile"]["attribute_id"].startswith("appearance.")


def test_manual_critique_report_preserves_category_debug(client):
    start_response = client.post(
        '/api/start',
        json={"object_name": "cat", "age": 6, "category_pipeline_enabled": True},
    )
    events = parse_sse(start_response.data)
    session_id = events[0]['data']['session_id']

    continue_response = client.post(
        '/api/continue',
        json={"session_id": session_id, "child_input": "Dogs are animals too"},
    )
    parse_sse(continue_response.data)

    response = client.post('/api/manual-critique', json={
        "session_id": session_id,
        "exchange_critiques": [{
            "exchange_index": 1,
            "model_response_problem": "Should invite a broader category comparison first.",
        }],
        "skip_traces": True,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True

    report_path = Path(body["report_path"])
    report_text = report_path.read_text(encoding="utf-8")
    assert "Category ID" in report_text
    assert "Raw Category Debug" in report_text

    detail_response = client.get(f"/api/reports/hf/{report_path.parent.name}/{report_path.name}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    model_turn = next(
        turn for turn in detail["transcript"]
        if turn["role"] == "model" and turn.get("exchange_index") == 1
    )
    assert model_turn["category_debug"]["profile"]["category_id"] == "animals"
    assert model_turn["critique"]["category_debug"]["profile"]["category_id"] == "animals"


def test_exchanges_endpoint_exposes_bridge_debug_for_intro_and_turns(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from unittest.mock import AsyncMock

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
            resolution_debug={
                "decision_source": "model_inference",
                "raw_model_payload_kind": "wrapped_json",
                "json_recovery_applied": True,
            },
        ),
    )
    start_response = client.post('/api/start', json={"object_name": "cat food", "age": 6})
    start_events = parse_sse(start_response.data)
    session_id = start_events[0]['data']['session_id']

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": False, "reason": "surface-only description"}),
    )
    client.post('/api/continue', json={"session_id": session_id, "child_input": "It looks like small cookies"})

    response = client.get(f'/api/exchanges/{session_id}')
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["session_resolution_debug"]["anchor_status"] == "anchored_high"
    assert payload["session_resolution_debug"]["decision_source"] == "model_inference"
    assert payload["session_resolution_debug"]["raw_model_payload_kind"] == "wrapped_json"
    assert payload["session_resolution_debug"]["json_recovery_applied"] is True
    assert payload["introduction"]["response_type"] == "introduction"
    assert payload["introduction"]["bridge_debug"]["decision"] == "intro_bridge"
    assert payload["exchanges"][0]["response_type"] == "bridge_retry"
    assert payload["exchanges"][0]["bridge_debug"]["decision"] == "bridge_retry"


def test_exchanges_endpoint_reports_bridge_activation_response_type(client, monkeypatch):
    from object_resolver import ObjectResolutionResult
    from unittest.mock import AsyncMock

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
    start_response = client.post('/api/start', json={"object_name": "cat food", "age": 6})
    start_events = parse_sse(start_response.data)
    session_id = start_events[0]['data']['session_id']
    _install_bridge_activation_stream(monkeypatch)

    monkeypatch.setattr(
        "paixueji_app.classify_bridge_follow",
        AsyncMock(return_value={"bridge_followed": True, "reason": "matched bridge follow term: smell"}),
    )
    continue_response = client.post('/api/continue', json={"session_id": session_id, "child_input": "maybe it smells nice"})
    parse_sse(continue_response.data)

    payload = client.get(f'/api/exchanges/{session_id}').get_json()
    activation_turn = payload["exchanges"][0]
    assert activation_turn["response_type"] == "bridge_activation"
    assert activation_turn["bridge_debug"]["decision"] == "bridge_activation"
