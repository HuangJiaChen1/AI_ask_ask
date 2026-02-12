"""
Formatting helpers for HF replay outputs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def build_markdown_report(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# HF Replay Regression Report")
    lines.append("")
    lines.append(f"- Generated: {datetime.now().isoformat()}")
    lines.append(f"- Bundle: `{result.get('bundle_path')}`")
    lines.append(f"- Final Verdict: **{result.get('final_verdict', 'fail').upper()}**")
    lines.append("")

    blocking = result.get("blocking_reasons", [])
    if blocking:
        lines.append("## Blocking Reasons")
        lines.append("")
        for reason in blocking:
            lines.append(f"- {reason}")
        lines.append("")

    lines.append("## Critiqued Cases")
    lines.append("")
    critiqued = result.get("critiqued_results", [])
    if not critiqued:
        lines.append("- None")
    for entry in critiqued:
        status = "PASS" if entry.get("verdict") == "pass" else "FAIL"
        lines.append(f"### Exchange {entry.get('exchange_index')} - {status}")
        lines.append(f"- Severity: {entry.get('severity', 'major')}")
        lines.append(f"- Reason: {entry.get('reason_summary', '')}")
        lines.append(f"- Baseline: {entry.get('baseline_model_response', '')}")
        lines.append(f"- Candidate: {entry.get('candidate_response', '')}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_report_files(
    result: dict[str, Any],
    output_md: str | Path | None = None,
    output_json: str | Path | None = None,
) -> tuple[Path | None, Path | None]:
    md_path = Path(output_md) if output_md else None
    json_path = Path(output_json) if output_json else None

    if md_path:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(build_markdown_report(result), encoding="utf-8")

    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path, json_path
