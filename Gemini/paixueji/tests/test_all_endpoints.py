import pytest
import json

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
    assert response.get_json()['success'] is True

def test_start_guide_direct(client):
    """Test the testing-only direct guide entry endpoint."""
    payload = {"object_name": "banana", "age": 6}
    response = client.post('/api/start-guide', json=payload)
    assert response.status_code == 200
    events = parse_sse(response.data)
    # Check if we got a guide_bridge response type
    assert any(e['data'].get('response_type') == 'guide_bridge' for e in events if e['event'] == 'chunk')
