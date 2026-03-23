"""optimizer/trigger.py — trace loading and culprit grouping for optimization triggering."""
from __future__ import annotations
from pathlib import Path

from trace_schema import TraceObject, OptimizationResult, effective_culprits

TRACES_DIR = Path(__file__).parent.parent / "traces"
OPTIMIZATIONS_DIR = Path(__file__).parent.parent / "optimizations"


def _load_all_traces() -> list[TraceObject]:
    if not TRACES_DIR.exists():
        return []
    traces = []
    for f in TRACES_DIR.glob("*.json"):
        try:
            traces.append(TraceObject.model_validate_json(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return traces


def _get_covered_trace_ids() -> set[str]:
    """Trace IDs that appear in any approved OptimizationResult (top-level, not pending/)."""
    covered: set[str] = set()
    if not OPTIMIZATIONS_DIR.exists():
        return covered
    for f in OPTIMIZATIONS_DIR.glob("*.json"):
        try:
            result = OptimizationResult.model_validate_json(f.read_text(encoding="utf-8"))
            covered.update(result.trace_ids)
        except Exception:
            continue
    return covered


def group_traces_by_culprit(include_optimized: bool = False) -> dict[str, list[TraceObject]]:
    """Group traces by culprit_name. Excludes covered traces by default."""
    covered = set() if include_optimized else _get_covered_trace_ids()
    groups: dict[str, list[TraceObject]] = {}
    for trace in _load_all_traces():
        if not include_optimized and trace.trace_id in covered:
            continue
        for c in effective_culprits(trace):
            groups.setdefault(c.culprit_name, []).append(trace)
    return groups


def get_unoptimized_traces(culprit_name: str) -> list[TraceObject]:
    """All uncovered traces for the given culprit_name."""
    covered = _get_covered_trace_ids()
    return [
        t for t in _load_all_traces()
        if t.trace_id not in covered
        and any(c.culprit_name == culprit_name for c in effective_culprits(t))
    ]


def get_traces_by_ids(trace_ids: list[str]) -> list[TraceObject]:
    """Load specific traces by ID. No coverage filtering — caller explicitly selected these."""
    target = set(trace_ids)
    return [t for t in _load_all_traces() if t.trace_id in target]
