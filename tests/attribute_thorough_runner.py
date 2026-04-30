#!/usr/bin/env python3
"""
Parameterized real-LLM test runner for attribute pipeline thorough testing.

Usage:
  .venv/Scripts/python.exe tests/attribute_thorough_runner.py <scenario_json>

Scenario JSON schema:
  {
    "id": str,                    # test case identifier
    "age": int,
    "object_name": str,
    "attribute_pipeline_enabled": true,
    "child_turns": [str],         # list of child inputs, one per continue turn
    "expected_intents": [str],    # optional: expected intent for each turn
    "assertions": [str]           # optional: assertion labels to verify
  }

Output:
  JSON report to stdout with keys:
    - id, status (pass/fail), transcript, final_activity_ready,
      final_response_type, attribute_debug_history, errors
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Let ADC discover credentials automatically (same as paixueji_app.py)
# Do NOT override GOOGLE_APPLICATION_CREDENTIALS with a hard-coded path.

from google import genai
from google.genai.types import HttpOptions


def parse_sse(response_data: bytes) -> list[dict]:
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


def final_chunk(events: list[dict]) -> dict:
    chunks = [e["data"] for e in events if e["event"] == "chunk"]
    if not chunks:
        raise RuntimeError("stream returned no chunks")
    return chunks[-1]


def run_scenario(flask_client, scenario: dict, config: dict) -> dict:
    transcript = []
    errors = []

    # --- START ---
    start_payload = {
        "age": scenario["age"],
        "object_name": scenario["object_name"],
        "attribute_pipeline_enabled": scenario.get("attribute_pipeline_enabled", True),
    }
    if "model_name_override" in scenario:
        start_payload["model_name_override"] = scenario["model_name_override"]

    start_response = flask_client.post("/api/start", json=start_payload)
    if start_response.status_code != 200:
        errors.append(f"start failed: HTTP {start_response.status_code}")
        return {"id": scenario["id"], "status": "fail", "errors": errors, "transcript": transcript}

    start_events = parse_sse(start_response.data)
    start_chunk = final_chunk(start_events)
    session_id = start_chunk["session_id"]
    transcript.append({
        "turn": 0,
        "role": "assistant",
        "text": start_chunk.get("response", ""),
        "response_type": start_chunk.get("response_type"),
        "attribute_debug": start_chunk.get("attribute_debug"),
    })

    # --- CONTINUE TURNS ---
    for idx, child_turn in enumerate(scenario["child_turns"]):
        time.sleep(scenario.get("turn_delay_seconds", 1))
        transcript.append({"turn": idx + 1, "role": "child", "text": child_turn})

        continue_response = flask_client.post(
            "/api/continue",
            json={"session_id": session_id, "child_input": child_turn},
        )
        if continue_response.status_code != 200:
            errors.append(f"continue turn {idx + 1} failed: HTTP {continue_response.status_code}")
            continue

        continue_events = parse_sse(continue_response.data)
        chunk = final_chunk(continue_events)
        transcript.append({
            "turn": idx + 1,
            "role": "assistant",
            "text": chunk.get("response", ""),
            "response_type": chunk.get("response_type"),
            "intent_type": chunk.get("intent_type"),
            "activity_ready": chunk.get("activity_ready"),
            "activity_target": chunk.get("activity_target"),
            "attribute_debug": chunk.get("attribute_debug"),
        })

    # --- ASSERTIONS ---
    assertion_results = {}
    for assertion in scenario.get("assertions", []):
        if assertion == "attribute_lane_active":
            assertion_results[assertion] = start_chunk.get("attribute_lane_active") is True
        elif assertion == "intro_response_type_is_attribute_intro":
            assertion_results[assertion] = start_chunk.get("response_type") == "attribute_intro"
        elif assertion == "activity_ready_true_on_final":
            final_assistant = [t for t in transcript if t["role"] == "assistant"][-1]
            assertion_results[assertion] = final_assistant.get("activity_ready") is True
        elif assertion == "activity_ready_false_on_final":
            final_assistant = [t for t in transcript if t["role"] == "assistant"][-1]
            assertion_results[assertion] = final_assistant.get("activity_ready") is False
        elif assertion == "no_reason_leaked":
            leaked = False
            for t in transcript:
                # Only check assistant responses, not child inputs
                if t.get("role") != "assistant":
                    continue
                text = t.get("text", "")
                if "REASON:" in text or "[ACTIVITY_READY]" in text:
                    leaked = True
                    break
            assertion_results[assertion] = not leaked
        else:
            assertion_results[assertion] = None

    status = "pass" if not errors and all(v for v in assertion_results.values() if v is not None) else "fail"

    return {
        "id": scenario["id"],
        "status": status,
        "session_id": session_id,
        "transcript": transcript,
        "assertions": assertion_results,
        "errors": errors,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python attribute_thorough_runner.py <scenario.json>", file=sys.stderr)
        sys.exit(1)

    scenario_path = Path(sys.argv[1])
    with open(scenario_path, encoding="utf-8") as f:
        scenario = json.load(f)

    config_path = REPO_ROOT / "config.json"
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    live_model = os.environ.get("ATTRIBUTE_ACTIVITY_REAL_MODEL", config.get("model_name"))
    config["live_eval_model"] = live_model

    from paixueji_app import app

    with app.test_client() as client:
        result = run_scenario(client, scenario, config)

    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
