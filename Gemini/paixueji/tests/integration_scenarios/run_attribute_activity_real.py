from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai.types import HttpOptions


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
    chunks = [event["data"] for event in events if event["event"] == "chunk"]
    if not chunks:
        raise RuntimeError("stream returned no chunks")
    return chunks[-1]


def build_evaluator_prompt(scenario: dict, transcript: list[dict]) -> str:
    return f"""Evaluate this child-chat transcript for an attribute-bound activity pipeline.

SCENARIO:
{json.dumps(scenario, ensure_ascii=False, indent=2)}

TRANSCRIPT:
{json.dumps(transcript, ensure_ascii=False, indent=2)}

Return JSON only:
{{
  "attribute_adherence": 1-5,
  "naturalness": 1-5,
  "activity_transition_smoothness": 1-5,
  "multi_turn_continuity": 1-5,
  "object_drift_tolerance": 1-5,
  "hard_failures": ["zero or more: system_wording, fake_observation, knowledge_test_intro, multiple_questions"],
  "reason": "short explanation"
}}

Scoring guidance:
- Reward staying naturally attached to the selected attribute.
- Do not penalize object drift when the same attribute remains coherent.
- Penalize fragmented jumps from object-bound facts to activity.
- Penalize mentioning pipelines, modes, databases, or tests.
"""


def evaluate_transcript(client: genai.Client, config: dict, scenario: dict, transcript: list[dict]) -> dict:
    response = client.models.generate_content(
        model=config["model_name"],
        contents=build_evaluator_prompt(scenario, transcript),
        config={"temperature": 0.0, "max_output_tokens": 400},
    )
    raw = response.text or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def run_scenario(flask_client, scenario: dict) -> dict:
    transcript = []
    start_response = flask_client.post(
        "/api/start",
        json={
            "age": scenario["age"],
            "object_name": scenario["object_name"],
            "attribute_pipeline_enabled": True,
        },
    )
    start_events = parse_sse(start_response.data)
    start_chunk = final_chunk(start_events)
    session_id = start_chunk["session_id"]
    transcript.append({
        "role": "assistant",
        "text": start_chunk["response"],
        "response_type": start_chunk.get("response_type"),
        "attribute_debug": start_chunk.get("attribute_debug"),
    })

    for child_turn in scenario["child_turns"]:
        transcript.append({"role": "child", "text": child_turn})
        continue_response = flask_client.post(
            "/api/continue",
            json={"session_id": session_id, "child_input": child_turn},
        )
        continue_events = parse_sse(continue_response.data)
        chunk = final_chunk(continue_events)
        transcript.append({
            "role": "assistant",
            "text": chunk["response"],
            "response_type": chunk.get("response_type"),
            "activity_ready": chunk.get("activity_ready"),
            "activity_target": chunk.get("activity_target"),
            "attribute_debug": chunk.get("attribute_debug"),
        })

    return {"session_id": session_id, "transcript": transcript}


def assert_evaluator_pass(evaluation: dict):
    scores = [
        evaluation.get("attribute_adherence", 0),
        evaluation.get("naturalness", 0),
        evaluation.get("activity_transition_smoothness", 0),
        evaluation.get("multi_turn_continuity", 0),
        evaluation.get("object_drift_tolerance", 0),
    ]
    average = sum(float(score) for score in scores) / len(scores)
    hard_failures = evaluation.get("hard_failures") or []
    if average < 4.0 or hard_failures:
        raise AssertionError(f"Evaluator failed: average={average:.2f}, hard_failures={hard_failures}")


def main():
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("GOOGLE_APPLICATION_CREDENTIALS is not set; live Gemini run cannot start.", file=sys.stderr)
        return 2

    config_path = REPO_ROOT / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    evaluator_client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1"),
    )

    from paixueji_app import app

    scenarios = [
        {
            "id": "in_kb_same_attribute_drift",
            "age": 6,
            "object_name": "apple",
            "expected_attribute": "surface_shiny_smooth",
            "child_turns": [
                "It is shiny and smooth.",
                "My spoon is shiny too.",
                "Let's play a shiny game.",
            ],
        },
        {
            "id": "unresolved_not_in_kb_attribute_lane",
            "age": 6,
            "object_name": "spaceship fuel",
            "expected_attribute": "sparkle_glow",
            "child_turns": [
                "It glows blue.",
                "A flashlight glows too.",
                "Let's do the light activity.",
            ],
        },
    ]

    results = []
    with app.test_client() as flask_client:
        for scenario in scenarios:
            run = run_scenario(flask_client, scenario)
            evaluation = evaluate_transcript(evaluator_client, config, scenario, run["transcript"])
            assert_evaluator_pass(evaluation)
            results.append({**scenario, **run, "evaluation": evaluation})

    output_dir = REPO_ROOT / "tests" / "integration_scenarios" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"attribute_activity_{int(time.time())}.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved live attribute activity transcripts to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
