"""optimizer/convergence_loop.py — Hybrid B+C optimization loop orchestrator."""
from __future__ import annotations
import logging
import uuid
from datetime import datetime

from trace_schema import TraceObject, OptimizationResult, ConfidenceLevel, effective_culprits

logger = logging.getLogger(__name__)

SCORE_AUTO_APPROVE    = 0.85
SCORE_HUMAN_REVIEW    = 0.70
MAX_ROUNDS            = 5
EARLY_STOP_NO_IMPROVE = 2
LOW_SCORE_THRESHOLD   = 0.80  # traces below this score trigger backward pass

_GRAD_TO_CONFIDENCE = {
    "HIGH":     ConfidenceLevel.VERY_CONFIDENT,
    "MODERATE": ConfidenceLevel.CONFIDENT,
    "LOW":      ConfidenceLevel.MODERATE,
}
_GRAD_WEIGHT = {"LOW": 0, "MODERATE": 1, "HIGH": 2}


def resolve_prompt_name(traces: list[TraceObject]) -> str | None:
    """
    Read prompt_template_name from culprits across all traces.
    Raises ValueError if traces have mixed prompt names (must all target the same prompt).
    """
    names: set[str] = set()
    for t in traces:
        for c in effective_culprits(t):
            if c.prompt_template_name:
                names.add(c.prompt_template_name)
    if len(names) > 1:
        raise ValueError(
            f"Batch has mixed prompt names: {names}. "
            "All traces in a batch must share one prompt_template_name."
        )
    return names.pop() if names else None


def run_optimization_loop(
    culprit_name: str,
    traces: list[TraceObject],
    config: dict,
    client,
    verbose: bool = True,
) -> OptimizationResult | None:
    """
    Full Hybrid B+C loop.

    Returns OptimizationResult if score >= SCORE_HUMAN_REVIEW, None otherwise.
    Auto-approves (writes to prompt_overrides.json) if score >= SCORE_AUTO_APPROVE.
    Set verbose=False to suppress console progress output.
    """
    from paixueji_prompts import get_annotated_prompt
    from prompt_optimizer import generate_previews_for_traces, save_optimization
    from optimizer.metric import compute_batch_score
    from optimizer.backward_pass import (
        parse_clauses, compute_clause_gradient, aggregate_gradients, apply_diffs,
    )
    from optimizer.bootstrap import add_golden_example, get_best_examples, inject_examples
    from optimizer.reporter import Reporter

    reporter = Reporter(enabled=verbose)

    prompt_name = resolve_prompt_name(traces)
    if not prompt_name:
        logger.error("[DSPy] Cannot resolve prompt_name for '%s'", culprit_name)
        return None

    current_prompt = get_annotated_prompt(prompt_name)
    original_prompt = current_prompt
    best_score = 0.0
    no_improve = 0
    last_previews: list[dict] = []
    confidence = ConfidenceLevel.MODERATE
    round_num = 0

    reporter.loop_start(culprit_name, prompt_name, len(traces))

    for round_num in range(1, MAX_ROUNDS + 1):
        logger.info("[DSPy] Round %d/%d for '%s'", round_num, MAX_ROUNDS, culprit_name)
        reporter.round_start(round_num, MAX_ROUNDS)

        injected = inject_examples(current_prompt, get_best_examples(prompt_name, k=3))
        previews = generate_previews_for_traces(
            client, config, traces, injected, prompt_name, culprit_name,
        )
        if not previews:
            logger.warning("[DSPy] No previews generated in round %d", round_num)
            reporter.no_previews(round_num)
            break

        reporter.previews_generated(len(previews))

        p_texts = [p["preview"] for p in previews]
        p_traces = [
            next(t for t in traces if t.trace_id == p["trace_id"])
            for p in previews
        ]
        scores = compute_batch_score(p_texts, p_traces, config, client)
        batch_score = sum(scores) / len(scores)
        logger.info("[DSPy] Round %d batch_score=%.3f", round_num, batch_score)

        per_trace = {previews[i]["trace_id"]: scores[i] for i in range(len(previews))}
        reporter.round_scores(batch_score, best_score, per_trace, previews)

        last_previews = previews

        # Bootstrap: save high-scoring previews as golden examples
        for text, trace, score in zip(p_texts, p_traces, scores):
            if score >= 0.90:
                add_golden_example(prompt_name, trace, text, score)

        # Track improvement
        if batch_score > best_score:
            best_score = batch_score
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= EARLY_STOP_NO_IMPROVE:
                logger.info("[DSPy] Early stop: no improvement for %d rounds", EARLY_STOP_NO_IMPROVE)
                reporter.early_stop(f"no improvement for {EARLY_STOP_NO_IMPROVE} consecutive rounds")
                break

        if batch_score >= SCORE_AUTO_APPROVE:
            break

        # Backward pass on low-scoring previews
        gradients: list[dict] = []
        clauses = parse_clauses(current_prompt)
        for text, trace, score in zip(p_texts, p_traces, scores):
            if score < LOW_SCORE_THRESHOLD:
                for clause in clauses:
                    gradients.append(
                        compute_clause_gradient(clause, trace, score, config, client)
                    )

        agg = aggregate_gradients(gradients)
        reporter.gradients_computed(len(gradients), agg)
        if agg:
            old_prompt = current_prompt
            current_prompt = apply_diffs(current_prompt, agg)
            reporter.prompt_diff(old_prompt, current_prompt)
            best_conf = max(agg, key=lambda d: _GRAD_WEIGHT[d.get("confidence", "LOW")])
            confidence = _GRAD_TO_CONFIDENCE[best_conf.get("confidence", "LOW")]
        else:
            logger.info("[DSPy] No actionable gradients — stopping early")
            reporter.early_stop("no actionable gradients")
            break

    if best_score >= SCORE_AUTO_APPROVE:
        _outcome = "auto-approved"
    elif best_score >= SCORE_HUMAN_REVIEW:
        _outcome = "queued_for_review"
    else:
        _outcome = "score_too_low — nothing saved"
    reporter.loop_end(best_score, _outcome, round_num)

    result = OptimizationResult(
        optimization_id=str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
        culprit_name=culprit_name,
        prompt_name=prompt_name,
        original_prompt=original_prompt,
        optimized_prompt=current_prompt,
        failure_pattern=f"Batch score after {round_num} round(s): {best_score:.3f}",
        rationale=(
            f"Hybrid B+C: backward pass applied clause diffs; "
            f"bootstrap injected {len(get_best_examples(prompt_name))} examples."
        ),
        trace_ids=[t.trace_id for t in traces],
        confidence_level=confidence,
        preview_response=last_previews[0]["preview"] if last_previews else "",
        previews=last_previews,
    )

    if best_score >= SCORE_AUTO_APPROVE:
        save_optimization(result, approved=True)
        logger.info("[DSPy] Auto-approved (score=%.3f)", best_score)
    elif best_score >= SCORE_HUMAN_REVIEW:
        save_optimization(result, approved=False)
        logger.info("[DSPy] Queued for human review (score=%.3f)", best_score)
    else:
        logger.warning("[DSPy] Score %.3f too low — nothing saved", best_score)
        return None

    return result
