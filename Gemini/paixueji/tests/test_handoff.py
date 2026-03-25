import builtins
import json
from types import SimpleNamespace

import paixueji_app


def _seed_session(session_id="session-1"):
    paixueji_app.sessions[session_id] = SimpleNamespace(
        object_name="apple",
        age=6,
        conversation_history=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "It is red"},
            {"role": "assistant", "content": "Nice. Let's play."},
        ],
    )
    return session_id


def test_create_handoff_uses_configured_directory(client, monkeypatch, tmp_path):
    handoff_dir = tmp_path / "handoff-output"
    monkeypatch.setattr(
        paixueji_app,
        "_load_config",
        lambda: {
            "wonderlens_url": "https://wonderlens.example",
            "handoff_dir": str(handoff_dir),
        },
    )
    session_id = _seed_session()

    response = client.post("/api/handoff", json={"session_id": session_id})

    assert response.status_code == 200
    data = response.get_json()
    assert data["context_path"].startswith("/handoff/")

    filename = data["context_path"].split("/")[-1]
    saved_file = handoff_dir / filename
    assert saved_file.exists()

    saved_conversation = json.loads(saved_file.read_text(encoding="utf-8"))
    assert saved_conversation == [
        {"role": "child", "text": "It is red"},
        {"role": "ai", "text": "Nice. Let's play."},
    ]

    served = client.get(data["context_path"])
    assert served.status_code == 200
    assert served.get_json() == saved_conversation


def test_create_handoff_returns_500_when_write_fails(client, monkeypatch, tmp_path):
    handoff_dir = tmp_path / "handoff-output"
    monkeypatch.setattr(
        paixueji_app,
        "_load_config",
        lambda: {
            "wonderlens_url": "https://wonderlens.example",
            "handoff_dir": str(handoff_dir),
        },
    )
    session_id = _seed_session("session-2")
    original_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path).endswith(".json") and str(path).startswith(str(handoff_dir)):
            raise PermissionError("denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    response = client.post("/api/handoff", json={"session_id": session_id})

    assert response.status_code == 500
    assert response.get_json() == {"error": "handoff unavailable"}


def test_create_handoff_missing_session_returns_404(client):
    response = client.post("/api/handoff", json={"session_id": "missing"})

    assert response.status_code == 404
    assert response.get_json() == {"error": "session not found"}


def test_serve_handoff_missing_file_returns_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        paixueji_app,
        "_load_config",
        lambda: {"handoff_dir": str(tmp_path / "handoff-output")},
    )

    response = client.get("/handoff/missing.json")

    assert response.status_code == 404
    assert response.get_json() == {"error": "not found"}
