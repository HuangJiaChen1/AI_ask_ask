"""
test_split_critique_buttons.py

Verifies the "Split Manual Critique Submit into Two Buttons" implementation.

Contracts validated:
  1. index.html has exactly two submit buttons: submitReportDbBtn and submitEvolvingAgentBtn
  2. The old submitManualCritiqueBtn ID and submitManualCritique() bare function are gone
  3. app.js has collectExchangeCritiques() shared helper
  4. submitManualCritiqueToDatabase() sends skip_traces: true
  5. submitManualCritiqueWithEvolution() does NOT send skip_traces (defaults to false server-side)
  6. /api/manual-critique reads skip_traces from request JSON (server-side)
  7. When skip_traces=True the endpoint returns immediately with {"success": True, "traces": []}
  8. When skip_traces=False (or absent) the full trace-assembly path is reached
  9. submitReportDbBtn disables itself and restores label in finally block
  10. submitEvolvingAgentBtn disables itself and restores label in finally block
"""

import pytest
import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_HTML   = PROJECT_ROOT / "static" / "index.html"
APP_JS       = PROJECT_ROOT / "static" / "app.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
                try:
                    data = json.loads(line[6:].strip())
                except json.JSONDecodeError:
                    data = line[6:].strip()
        if event_type:
            events.append({"event": event_type, "data": data})
    return events


def _setup_session(client):
    """Start a session, do one exchange, and return the session_id."""
    start_resp = client.post("/api/start", json={"object_name": "apple", "age": 6})
    events = parse_sse(start_resp.data)
    session_id = events[0]["data"]["session_id"]
    cont_resp = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": "It is red"},
    )
    parse_sse(cont_resp.data)  # consume stream so history is updated
    return session_id


def _base_critique_payload(session_id):
    return {
        "session_id": session_id,
        "exchange_critiques": [
            {
                "exchange_index": 1,
                "model_question_expected": "Good open question",
                "model_question_problem": "None",
                "model_response_expected": "Positive reinforcement",
                "model_response_problem": "None",
                "conclusion": "Solid exchange",
            }
        ],
        "global_conclusion": "Looks good",
    }


# ===========================================================================
# Static-analysis tests — index.html
# ===========================================================================

class TestIndexHtmlButtons:
    """HTML structure: exactly two submit buttons, old button gone."""

    def test_submitReportDbBtn_exists_in_html(self):
        html = _read(INDEX_HTML)
        assert 'id="submitReportDbBtn"' in html, \
            "submitReportDbBtn id not found in index.html"

    def test_submitEvolvingAgentBtn_exists_in_html(self):
        html = _read(INDEX_HTML)
        assert 'id="submitEvolvingAgentBtn"' in html, \
            "submitEvolvingAgentBtn id not found in index.html"

    def test_exactly_two_critique_submit_buttons(self):
        html = _read(INDEX_HTML)
        db_count     = html.count('id="submitReportDbBtn"')
        evo_count    = html.count('id="submitEvolvingAgentBtn"')
        assert db_count == 1,  f"Expected 1 submitReportDbBtn, found {db_count}"
        assert evo_count == 1, f"Expected 1 submitEvolvingAgentBtn, found {evo_count}"

    def test_old_submitManualCritiqueBtn_gone_from_html(self):
        html = _read(INDEX_HTML)
        assert 'submitManualCritiqueBtn' not in html, \
            "Old submitManualCritiqueBtn id still present in index.html"

    def test_submitReportDbBtn_calls_correct_onclick(self):
        html = _read(INDEX_HTML)
        # The button must invoke the database function, not the evolution one
        assert 'submitManualCritiqueToDatabase()' in html, \
            "submitManualCritiqueToDatabase() not found as onclick in index.html"

    def test_submitEvolvingAgentBtn_calls_correct_onclick(self):
        html = _read(INDEX_HTML)
        assert 'submitManualCritiqueWithEvolution()' in html, \
            "submitManualCritiqueWithEvolution() not found as onclick in index.html"

    def test_submitReportDbBtn_sky_blue_color(self):
        html = _read(INDEX_HTML)
        # Find the button line and assert sky-blue colour
        assert '#0ea5e9' in html, \
            "Sky-blue colour #0ea5e9 not found in index.html (expected on submitReportDbBtn)"

    def test_submitEvolvingAgentBtn_purple_color(self):
        html = _read(INDEX_HTML)
        assert '#7c3aed' in html, \
            "Purple colour #7c3aed not found in index.html (expected on submitEvolvingAgentBtn)"


# ===========================================================================
# Static-analysis tests — app.js
# ===========================================================================

class TestAppJsStructure:
    """JS functions: shared helper + two submit functions, old function gone."""

    def test_collectExchangeCritiques_helper_exists(self):
        js = _read(APP_JS)
        assert 'function collectExchangeCritiques()' in js, \
            "collectExchangeCritiques() function not found in app.js"

    def test_submitManualCritiqueToDatabase_exists(self):
        js = _read(APP_JS)
        assert 'function submitManualCritiqueToDatabase()' in js, \
            "submitManualCritiqueToDatabase() not found in app.js"

    def test_submitManualCritiqueWithEvolution_exists(self):
        js = _read(APP_JS)
        assert 'function submitManualCritiqueWithEvolution()' in js, \
            "submitManualCritiqueWithEvolution() not found in app.js"

    def test_old_bare_submitManualCritique_function_gone(self):
        js = _read(APP_JS)
        # The old function was exactly named 'submitManualCritique' — it must not
        # appear as a function declaration (the two new names both extend it).
        # We allow 'submitManualCritiqueToDatabase' and 'submitManualCritiqueWithEvolution'
        # but the bare name must not be declared as a function.
        assert 'function submitManualCritique()' not in js, \
            "Old bare submitManualCritique() function declaration still exists in app.js"

    def test_submitManualCritiqueToDatabase_sends_skip_traces_true(self):
        js = _read(APP_JS)
        # Find the function body
        start = js.find('function submitManualCritiqueToDatabase()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end]
        assert 'skip_traces: true' in func_body, \
            "submitManualCritiqueToDatabase() does not send skip_traces: true"

    def test_submitManualCritiqueWithEvolution_does_not_send_skip_traces(self):
        js = _read(APP_JS)
        start = js.find('function submitManualCritiqueWithEvolution()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end] if end != -1 else js[start:]
        # The evolution path must NOT include skip_traces at all
        assert 'skip_traces' not in func_body, \
            "submitManualCritiqueWithEvolution() should NOT send skip_traces"

    def test_submitManualCritiqueToDatabase_references_submitReportDbBtn(self):
        js = _read(APP_JS)
        start = js.find('function submitManualCritiqueToDatabase()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end]
        assert 'submitReportDbBtn' in func_body, \
            "submitManualCritiqueToDatabase() does not reference submitReportDbBtn"

    def test_submitManualCritiqueWithEvolution_references_submitEvolvingAgentBtn(self):
        js = _read(APP_JS)
        start = js.find('function submitManualCritiqueWithEvolution()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end] if end != -1 else js[start:]
        assert 'submitEvolvingAgentBtn' in func_body, \
            "submitManualCritiqueWithEvolution() does not reference submitEvolvingAgentBtn"

    def test_submitManualCritiqueToDatabase_disables_button(self):
        js = _read(APP_JS)
        start = js.find('function submitManualCritiqueToDatabase()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end]
        assert 'submitBtn.disabled = true' in func_body, \
            "submitManualCritiqueToDatabase() does not disable the button during request"

    def test_submitManualCritiqueToDatabase_restores_label_in_finally(self):
        js = _read(APP_JS)
        start = js.find('function submitManualCritiqueToDatabase()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end]
        # finally block must re-enable and restore label
        assert 'finally' in func_body, \
            "submitManualCritiqueToDatabase() has no finally block"
        assert 'submitBtn.disabled = false' in func_body, \
            "submitManualCritiqueToDatabase() does not re-enable button in finally"
        assert "'Submit to Report Database'" in func_body or \
               '"Submit to Report Database"' in func_body, \
            "submitManualCritiqueToDatabase() does not restore original label in finally"

    def test_submitManualCritiqueWithEvolution_disables_button(self):
        js = _read(APP_JS)
        start = js.find('function submitManualCritiqueWithEvolution()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end] if end != -1 else js[start:]
        assert 'submitBtn.disabled = true' in func_body, \
            "submitManualCritiqueWithEvolution() does not disable the button during request"

    def test_submitManualCritiqueWithEvolution_restores_label_in_finally(self):
        js = _read(APP_JS)
        start = js.find('function submitManualCritiqueWithEvolution()')
        end   = js.find('\nasync function ', start + 1)
        if end == -1:
            end = js.find('\nfunction ', start + 1)
        func_body = js[start:end] if end != -1 else js[start:]
        assert 'finally' in func_body, \
            "submitManualCritiqueWithEvolution() has no finally block"
        assert 'submitBtn.disabled = false' in func_body, \
            "submitManualCritiqueWithEvolution() does not re-enable button in finally"
        assert "'Submit for Evolving Agent'" in func_body or \
               '"Submit for Evolving Agent"' in func_body, \
            "submitManualCritiqueWithEvolution() does not restore original label in finally"

    def test_both_functions_call_collectExchangeCritiques(self):
        js = _read(APP_JS)
        # DB function
        db_start = js.find('function submitManualCritiqueToDatabase()')
        db_end   = js.find('\nasync function ', db_start + 1)
        if db_end == -1:
            db_end = js.find('\nfunction ', db_start + 1)
        db_body = js[db_start:db_end]
        assert 'collectExchangeCritiques()' in db_body, \
            "submitManualCritiqueToDatabase() does not call collectExchangeCritiques()"

        # Evolution function
        evo_start = js.find('function submitManualCritiqueWithEvolution()')
        evo_end   = js.find('\nasync function ', evo_start + 1)
        if evo_end == -1:
            evo_end = js.find('\nfunction ', evo_start + 1)
        evo_body = js[evo_start:evo_end] if evo_end != -1 else js[evo_start:]
        assert 'collectExchangeCritiques()' in evo_body, \
            "submitManualCritiqueWithEvolution() does not call collectExchangeCritiques()"


# ===========================================================================
# Server-side tests — /api/manual-critique endpoint
# ===========================================================================

class TestManualCritiqueEndpointSkipTracesTrue:
    """When skip_traces=true the endpoint returns immediately with traces=[]."""

    def test_skip_traces_true_returns_200(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = True
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 200

    def test_skip_traces_true_returns_success(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = True
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert data["success"] is True

    def test_skip_traces_true_returns_empty_traces_list(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = True
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert "traces" in data, "Response missing 'traces' key"
        assert data["traces"] == [], \
            f"Expected traces=[] when skip_traces=True, got {data['traces']}"

    def test_skip_traces_true_returns_report_path(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = True
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert "report_path" in data, "Response missing 'report_path'"
        assert data["report_path"]  # non-empty string

    def test_skip_traces_true_returns_exchanges_critiqued(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = True
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert "exchanges_critiqued" in data
        assert data["exchanges_critiqued"] == 1

    def test_skip_traces_true_does_not_return_trace_paths_key(self, client):
        """The early-return branch should NOT include trace_paths (that's the full path)."""
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = True
        data = client.post("/api/manual-critique", json=payload).get_json()
        # The early-return omits trace_paths and traces_assembled
        assert "trace_paths" not in data, \
            "Early-return (skip_traces=True) should not include 'trace_paths'"
        assert "traces_assembled" not in data, \
            "Early-return (skip_traces=True) should not include 'traces_assembled'"


class TestManualCritiqueEndpointSkipTracesFalse:
    """When skip_traces is absent (defaults False) the full response is returned."""

    def test_no_skip_traces_returns_200(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        # skip_traces NOT included — defaults to False on server
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 200

    def test_no_skip_traces_returns_success(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert data["success"] is True

    def test_no_skip_traces_returns_traces_key(self, client):
        """Full path must include 'traces' key (may be empty list if no culprits)."""
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert "traces" in data, \
            "Full response (skip_traces=False) must include 'traces' key"

    def test_no_skip_traces_returns_trace_paths_key(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert "trace_paths" in data, \
            "Full response (skip_traces=False) must include 'trace_paths' key"

    def test_no_skip_traces_returns_traces_assembled_key(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert "traces_assembled" in data, \
            "Full response (skip_traces=False) must include 'traces_assembled' key"

    def test_explicit_skip_traces_false_behaves_same_as_absent(self, client):
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = False
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert data["success"] is True
        assert "trace_paths" in data


class TestManualCritiqueEndpointErrorCases:
    """Existing error paths must still work after the refactor."""

    def test_missing_session_id_returns_400(self, client):
        payload = {
            "exchange_critiques": [{"exchange_index": 1}],
            "global_conclusion": "test",
        }
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 400
        assert response.get_json()["success"] is False

    def test_missing_exchange_critiques_returns_400(self, client):
        # Both empty → 400
        session_id = _setup_session(client)
        payload = {
            "session_id": session_id,
            "exchange_critiques": [],
            "global_conclusion": "",
        }
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False

    def test_global_conclusion_only_succeeds(self, client):
        # No exchange critiques but a global conclusion is enough
        session_id = _setup_session(client)
        payload = {
            "session_id": session_id,
            "exchange_critiques": [],
            "global_conclusion": "The model uses too many high-level terms overall.",
            "skip_traces": True,
        }
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["exchanges_critiqued"] == 0

    def test_unknown_session_returns_404(self, client):
        payload = _base_critique_payload("nonexistent-session-id")
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 404
        assert response.get_json()["success"] is False

    def test_skip_traces_missing_session_still_returns_400(self, client):
        """skip_traces=True must not bypass session validation."""
        payload = {
            "exchange_critiques": [{"exchange_index": 1}],
            "global_conclusion": "test",
            "skip_traces": True,
        }
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 400

    def test_skip_traces_true_unknown_session_still_returns_404(self, client):
        """skip_traces=True must not bypass session existence check."""
        payload = _base_critique_payload("ghost-session")
        payload["skip_traces"] = True
        response = client.post("/api/manual-critique", json=payload)
        assert response.status_code == 404


class TestServerSideSkipTracesReading:
    """Confirm paixueji_app.py reads skip_traces from request data."""

    def test_skip_traces_defaults_to_false_when_absent(self, client):
        """Verify the default is False: full response keys are present when omitted."""
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        # Explicitly do NOT include skip_traces
        assert "skip_traces" not in payload
        data = client.post("/api/manual-critique", json=payload).get_json()
        # Full path returns trace_paths (may be []) — proves the default is False
        assert "trace_paths" in data

    def test_skip_traces_true_short_circuits_before_trace_assembly(self, client):
        """
        Regression: with skip_traces=True the response must NOT include
        'traces_assembled' (that key is only set by the trace-assembly block).
        """
        session_id = _setup_session(client)
        payload = _base_critique_payload(session_id)
        payload["skip_traces"] = True
        data = client.post("/api/manual-critique", json=payload).get_json()
        assert "traces_assembled" not in data, \
            "skip_traces=True must short-circuit before trace assembly"
