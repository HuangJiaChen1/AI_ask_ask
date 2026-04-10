#!/usr/bin/env python3
"""
Compare bridge activation behavior across latent grounding modes.

Usage:
  python tests/integration_scenarios/bridge_activation_grounding_compare.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


EXPERIMENT_MODES = ("none", "physical_only", "full_chat_kb")

SCENARIOS = (
    {
        "scenario_id": "cat_food_smell_follow",
        "object_name": "cat food",
        "age": 6,
        "turns": ["maybe it smells nice, else she won't eat it"],
    },
    {
        "scenario_id": "cat_food_teeth_follow",
        "object_name": "cat food",
        "age": 6,
        "turns": ["not really", "not really", "I think just with her teeth"],
    },
    {
        "scenario_id": "cat_food_out_of_lane_soft_activation",
        "object_name": "cat food",
        "age": 6,
        "turns": ["what do you mean?", "they can see it"],
    },
)


def build_run_matrix() -> list[dict]:
    return [
        {
            "scenario_id": scenario["scenario_id"],
            "mode": mode,
            "object_name": scenario["object_name"],
            "age": scenario["age"],
            "turns": list(scenario["turns"]),
        }
        for scenario in SCENARIOS
        for mode in EXPERIMENT_MODES
    ]


def parse_sse(response_data: bytes) -> list[dict]:
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


def write_summary(output_dir: Path, transcripts: list[dict]) -> None:
    lines = [
        "# Bridge Activation Grounding Comparison",
        "",
        "| Scenario | Mode | Response Type | Final Activation Text | Grounding Mode | Rubric Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for transcript in transcripts:
        final_chunk = transcript["final_chunk"]
        bridge_debug = final_chunk.get("bridge_debug") or {}
        lines.append(
            "| {scenario} | {mode} | {rtype} | {text} | {grounding_mode} | continuity: ; drift: ; coherence: ; quality: |".format(
                scenario=transcript["scenario_id"],
                mode=transcript["mode"],
                rtype=final_chunk.get("response_type"),
                text=(final_chunk.get("response", "") or "").replace("|", "\\|"),
                grounding_mode=bridge_debug.get("activation_grounding_mode", transcript["mode"]),
            )
        )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_experiment() -> Path:
    import paixueji_app

    output_dir = (
        Path("reports")
        / "experiments"
        / "bridge_activation_grounding"
        / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    transcripts = []

    paixueji_app.app.config["TESTING"] = True
    with paixueji_app.app.test_client() as client:
        for row in build_run_matrix():
            paixueji_app.sessions = {}

            start_response = client.post(
                "/api/start",
                json={"age": row["age"], "object_name": row["object_name"]},
            )
            start_events = parse_sse(start_response.data)
            session_id = next(e["data"]["session_id"] for e in start_events if e["event"] == "chunk")
            paixueji_app.sessions[session_id].config["bridge_activation_grounding_mode"] = row["mode"]

            latest_events = start_events
            for child_input in row["turns"]:
                response = client.post(
                    "/api/continue",
                    json={"session_id": session_id, "child_input": child_input},
                )
                latest_events = parse_sse(response.data)

            final_chunk = [event["data"] for event in latest_events if event["event"] == "chunk"][-1]
            payload = {
                "scenario_id": row["scenario_id"],
                "mode": row["mode"],
                "turns": row["turns"],
                "final_chunk": final_chunk,
            }
            transcripts.append(payload)
            filename = f"{row['scenario_id']}__{row['mode']}.json"
            (output_dir / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    write_summary(output_dir, transcripts)
    return output_dir


def main() -> None:
    output_dir = run_experiment()
    print(output_dir)


if __name__ == "__main__":
    main()
