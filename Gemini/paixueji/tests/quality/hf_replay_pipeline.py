"""
Orchestration for HF replay runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from google import genai

from .hf_replay_judge import HFReplayJudge
from .hf_replay_runner import HFReplayRunner
from .hf_snapshot_store import load_bundle


async def run_hf_replay(
    client: genai.Client,
    bundle_path: str | Path,
    judge_model: str = "gemini-2.5-pro",
) -> dict[str, Any]:
    bundle_path = Path(bundle_path)
    bundle = load_bundle(bundle_path)
    runner = HFReplayRunner(client)
    judge = HFReplayJudge(client, model=judge_model)

    critiqued_results: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []

    for case in bundle.get("critiqued_cases", []):
        severity = (case.get("human_feedback", {}) or {}).get("severity", "major")
        baseline_response = case.get("original_model_response") or case.get("baseline_model_response", "")

        if not baseline_response:
            critiqued_results.append({
                "exchange_index": case.get("exchange_index"),
                "severity": severity,
                "verdict": "fail",
                "reason_summary": "Missing historical baseline response.",
                "baseline_model_response": "",
                "candidate_response": "",
            })
            blocking_reasons.append(
                f"Exchange {case.get('exchange_index')} missing historical baseline response."
            )
            continue

        replay = await runner.replay_case(bundle, case)
        candidate_response = replay.get("candidate_response", "")
        if not replay.get("ok"):
            critiqued_results.append({
                "exchange_index": case.get("exchange_index"),
                "severity": severity,
                "verdict": "fail",
                "reason_summary": f"Replay error: {replay.get('error')}",
                "baseline_model_response": baseline_response,
                "candidate_response": candidate_response,
            })
            blocking_reasons.append(
                f"Exchange {case.get('exchange_index')} replay failed."
            )
            continue

        case_for_judge = {**case, "baseline_model_response": baseline_response}
        try:
            judged = await judge.judge_critiqued_case(bundle, case_for_judge, candidate_response)
        except Exception as exc:
            judged = {
                "verdict": "fail",
                "reason_summary": f"Judge error: {exc}",
                "confidence": 0.0,
                "improvement_detected": False,
                "regression_detected": True,
                "evidence_quotes": [],
                "checks": {
                    "fixes_reported_problem": False,
                    "satisfies_expected_behavior": False,
                    "introduces_new_problem": True,
                    "preserves_working_behavior": False,
                },
            }

        result_entry = {
            "exchange_index": case.get("exchange_index"),
            "severity": severity,
            "baseline_model_response": baseline_response,
            "candidate_response": candidate_response,
            **judged,
        }
        critiqued_results.append(result_entry)

        if judged.get("verdict") != "pass":
            blocking_reasons.append(
                f"Exchange {case.get('exchange_index')} did not pass."
            )

    final_verdict = "pass" if not blocking_reasons else "fail"

    return {
        "bundle_path": str(bundle_path),
        "case_bundle_id": bundle.get("case_bundle_id"),
        "critiqued_results": critiqued_results,
        "blocking_reasons": blocking_reasons,
        "final_verdict": final_verdict,
    }
