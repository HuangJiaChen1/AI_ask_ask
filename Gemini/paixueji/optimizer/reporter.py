"""optimizer/reporter.py — human-readable console progress for the optimization loop."""
from __future__ import annotations
import difflib

_BAR = "━" * 48
_SEP = "─" * 40


class Reporter:
    """Prints formatted optimization progress to stdout. Silenced by enabled=False."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def _p(self, msg: str = "") -> None:
        if self.enabled:
            print(msg)

    def loop_start(self, culprit_name: str, prompt_name: str, n_traces: int) -> None:
        self._p()
        self._p(f"[DSPy] {_BAR}")
        self._p(f"[DSPy]  Culprit  : {culprit_name}")
        self._p(f"[DSPy]  Prompt   : {prompt_name}")
        self._p(f"[DSPy]  Traces   : {n_traces}")
        self._p(f"[DSPy] {_BAR}")

    def round_start(self, round_num: int, max_rounds: int) -> None:
        self._p()
        self._p(f"[DSPy]  ── Round {round_num}/{max_rounds} {_SEP}")

    def previews_generated(self, n: int) -> None:
        self._p(f"[DSPy]  Previews generated : {n}")

    def round_scores(
        self,
        batch_score: float,
        prev_best: float,
        per_trace: dict[str, float],
        previews: list[dict],
    ) -> None:
        arrow = "↑" if batch_score > prev_best else ("↓" if batch_score < prev_best else "→")
        note = "  (best so far)" if batch_score > prev_best else ""
        self._p(f"[DSPy]  Batch score        : {batch_score:.3f}  {arrow}{note}")
        preview_map = {p["trace_id"]: p["preview"] for p in previews}
        for trace_id, score in per_trace.items():
            snippet = preview_map.get(trace_id, "")[:50].replace("\n", " ")
            self._p(f'[DSPy]    {trace_id[:10]:10s}  score={score:.3f}  "{snippet}..."')

    def gradients_computed(self, total: int, actionable: list[dict]) -> None:
        self._p(f"[DSPy]  Gradients computed : {total}  →  actionable: {len(actionable)}")
        for g in actionable:
            conf    = g.get("confidence", "?")
            clause  = g.get("clause_id", "?")
            problem = g.get("problem", "")[:70]
            fix     = g.get("suggested_fix", "")[:70]
            self._p(f"[DSPy]    [{conf:8s}] clause={clause}")
            self._p(f"[DSPy]             Problem : {problem}")
            self._p(f"[DSPy]             Fix     : {fix}")

    def prompt_diff(self, old_prompt: str, new_prompt: str) -> None:
        lines = list(difflib.unified_diff(
            old_prompt.splitlines(),
            new_prompt.splitlines(),
            fromfile="prompt (before)",
            tofile="prompt (after)",
            lineterm="",
        ))
        if not lines:
            return
        self._p("[DSPy]  Prompt diff:")
        for line in lines[:30]:
            self._p(f"[DSPy]    {line}")
        if len(lines) > 30:
            self._p(f"[DSPy]    ... ({len(lines) - 30} more lines omitted)")

    def early_stop(self, reason: str) -> None:
        self._p(f"[DSPy]  Early stop — {reason}")

    def no_previews(self, round_num: int) -> None:
        self._p(f"[DSPy]  No previews generated in round {round_num}")

    def loop_end(self, best_score: float, outcome: str, rounds_run: int) -> None:
        self._p()
        self._p(f"[DSPy] {_BAR}")
        self._p(f"[DSPy]  Outcome  : {outcome}")
        self._p(f"[DSPy]  Score    : {best_score:.3f}")
        self._p(f"[DSPy]  Rounds   : {rounds_run}")
        self._p(f"[DSPy] {_BAR}")
        self._p()
