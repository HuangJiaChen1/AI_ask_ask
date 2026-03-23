"""optimizer/backward_pass.py — TextGrad-C clause-level gradient computation."""
from __future__ import annotations
import json
import re
from collections import defaultdict
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from trace_schema import TraceObject

ClauseGradientConfidence = Literal["LOW", "MODERATE", "HIGH"]
_CONFIDENCE_WEIGHT: dict[str, int] = {"LOW": 0, "MODERATE": 1, "HIGH": 2}
_MARKER_RE = re.compile(r'^## \[CLAUSE: ([^\]]+)\]\s*$', re.MULTILINE)


def parse_clauses(prompt_text: str) -> list[dict]:
    """Parse ## [CLAUSE: id] markers. Returns [] if none found."""
    markers = list(_MARKER_RE.finditer(prompt_text))
    if not markers:
        return []
    results = []
    for i, m in enumerate(markers):
        clause_id = m.group(1).strip()
        start = m.end()
        if start < len(prompt_text) and prompt_text[start] == '\n':
            start += 1
        end = markers[i + 1].start() if i + 1 < len(markers) else len(prompt_text)
        results.append({"clause_id": clause_id, "content": prompt_text[start:end].strip()})
    return results


def compute_clause_gradient(
    clause: dict, trace: "TraceObject", score: float, config: dict, client
) -> dict:
    """LLM call: what surgical single-sentence fix to THIS CLAUSE prevents the failure?"""
    prompt = (
        f"The following prompt clause produced a low-quality response (score={score:.2f}).\n\n"
        f"CLAUSE ID: {clause['clause_id']}\nCLAUSE CONTENT:\n{clause['content']}\n\n"
        f"CHILD SAID: {trace.exchange.child_response}\n"
        f"MODEL RESPONDED: {trace.exchange.model_response}\n"
        f"CRITIQUE: {trace.critique.model_response_problem}\n\n"
        "Provide a surgical single-sentence fix to THIS CLAUSE ONLY.\n"
        'Respond as JSON: {"clause_id":"...","problem":"...","suggested_fix":"...","confidence":"LOW|MODERATE|HIGH"}'
    )
    try:
        text = client.models.generate_content(
            model=config["high_reasoning_model"], contents=[prompt]
        ).text.strip()
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.DOTALL)
        data = json.loads(text)
        data["clause_id"] = clause["clause_id"]
        if data.get("confidence") not in ("LOW", "MODERATE", "HIGH"):
            data["confidence"] = "LOW"
        return data
    except Exception:
        return {
            "clause_id": clause["clause_id"],
            "problem": "unknown",
            "suggested_fix": "",
            "confidence": "LOW",
        }


def aggregate_gradients(gradients: list[dict]) -> list[dict]:
    """Priority = sum(confidence_weight) per clause. Filters priority==0."""
    votes: dict[str, list[dict]] = defaultdict(list)
    for g in gradients:
        votes[g["clause_id"]].append(g)
    ranked = []
    for clause_id, entries in votes.items():
        priority = sum(_CONFIDENCE_WEIGHT[e.get("confidence", "LOW")] for e in entries)
        if priority == 0:
            continue
        best = max(entries, key=lambda e: _CONFIDENCE_WEIGHT[e.get("confidence", "LOW")])
        ranked.append({**best, "clause_id": clause_id, "priority": priority})
    return sorted(ranked, key=lambda x: x["priority"], reverse=True)


def apply_diffs(prompt_text: str, diffs: list[dict]) -> str:
    """Surgically replace clause contents. Preserves ## [CLAUSE: id] marker lines."""
    if not diffs:
        return prompt_text
    fix_map = {d["clause_id"]: d["suggested_fix"] for d in diffs}
    lines = prompt_text.split('\n')
    result: list[str] = []
    current_clause: str | None = None
    buffered: list[str] = []

    def flush() -> None:
        if current_clause is None:
            result.extend(buffered)
        elif current_clause in fix_map:
            result.append(f"## [CLAUSE: {current_clause}]")
            result.append(fix_map[current_clause])
        else:
            result.append(f"## [CLAUSE: {current_clause}]")
            result.extend(buffered)

    for line in lines:
        m = re.match(r'^## \[CLAUSE: ([^\]]+)\]', line)
        if m:
            flush()
            current_clause = m.group(1).strip()
            buffered = []
        else:
            buffered.append(line)
    flush()
    return '\n'.join(result)
