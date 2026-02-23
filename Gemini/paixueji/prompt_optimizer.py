"""
Prompt Optimization Pipeline for Paixueji self-evolution.

Reads all traces for a given culprit, synthesizes a failure pattern across
instances, rewrites the responsible prompt template, generates a real
"after-the-fix" sample response, and saves to a pending file for human review.

The optimization is NEVER saved to prompt_overrides.json automatically.
Human approval via the /api/optimize-prompt/<id>/approve endpoint is required.

Anti-hardcoding constraint: multiple traces are fed to the optimizer LLM so it
must extract a general principle, not a case-specific prohibition.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from google.genai.types import GenerateContentConfig
from loguru import logger

import paixueji_prompts
from trace_schema import TraceObject, OptimizationResult, ConfidenceLevel


# ============================================================================
# Age prompt helper (standalone, no PaixuejiAssistant dependency)
# ============================================================================

def _get_age_prompt(age: int) -> str:
    """Return the age-appropriate guidance string from age_prompts.json."""
    age_prompts_path = Path(__file__).parent / "age_prompts.json"
    if not age_prompts_path.exists():
        return ""
    try:
        data = json.loads(age_prompts_path.read_text(encoding="utf-8"))
        groups = data.get("age_groups", {})
        if 3 <= age <= 4:
            return groups.get("3-4", {}).get("prompt", "")
        elif 5 <= age <= 6:
            return groups.get("5-6", {}).get("prompt", "")
        elif 7 <= age <= 8:
            return groups.get("7-8", {}).get("prompt", "")
        else:
            return groups.get("5-6", {}).get("prompt", "")
    except Exception:
        return ""


# ============================================================================
# Trace loading
# ============================================================================

def load_traces_for_culprit(culprit_name: str) -> list[TraceObject]:
    """
    Scan traces/*.json, parse each as TraceObject, return all where
    culprit.culprit_name == culprit_name, sorted oldest-first.

    Loading all matching traces (not just the latest) forces the optimizer LLM
    to extract a pattern rather than patch a single case.
    """
    traces_dir = Path(__file__).parent / "traces"
    if not traces_dir.exists():
        return []

    results = []
    for f in sorted(traces_dir.glob("*.json")):
        try:
            trace = TraceObject.model_validate_json(f.read_text(encoding="utf-8"))
            if trace.culprit.culprit_name == culprit_name:
                results.append(trace)
        except Exception as e:
            logger.warning(f"[Optimizer] Could not parse trace {f.name}: {e}")

    # Sort oldest-first so the LLM sees the history of failures
    results.sort(key=lambda t: t.timestamp)
    return results


# ============================================================================
# Evidence builder
# ============================================================================

def build_failure_evidence(traces: list[TraceObject]) -> str:
    """
    Build numbered prose blocks from traces.

    Prose (not raw JSON) reduces noise and helps the optimizer LLM focus on
    what actually went wrong rather than getting distracted by schema fields.
    """
    blocks = []
    for i, trace in enumerate(traces, 1):
        state = trace.input_state
        age = state.get("age") or trace.age or "?"
        obj = state.get("object_name") or trace.object_name or "?"
        header = f"Instance {i} (age={age}, object={obj}):"

        lines = [header]
        if trace.exchange.model_question:
            lines.append(f"  Model question: \"{trace.exchange.model_question}\"")
        if trace.exchange.child_response:
            lines.append(f"  Child response: \"{trace.exchange.child_response}\"")
        if trace.critique.model_question_problem:
            lines.append(f"  Critique (question): {trace.critique.model_question_problem}")
        if trace.critique.model_response_problem:
            lines.append(f"  Critique (response): {trace.critique.model_response_problem}")
        if trace.critique.conclusion:
            lines.append(f"  Critique (conclusion): {trace.critique.conclusion}")
        if trace.culprit.reasoning:
            lines.append(f"  Culprit reasoning: {trace.culprit.reasoning}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


# ============================================================================
# LLM-based optimization
# ============================================================================

OPTIMIZER_PROMPT_TEMPLATE = """\
You are an expert prompt engineer for a child-educational AI system.
Improve a prompt template to fix a GENERAL CLASS of failure, without hardcoding specific cases.

CRITICAL RULES:
1. Do NOT add rules about specific content from the failure examples.
   Bad: "Never ask 'what do you think it was like for the dinosaur'"
   Good: "Prefer concrete sensory questions (what does it look like? feel like?)
          over abstract or philosophical ones."
2. All existing {{placeholder}} variables must be preserved exactly as-is.
3. The improved prompt must handle ALL valid inputs, not just the failure cases.
4. Add guidance, not prohibitions.

[CULPRIT NODE]: {culprit_name}
[PROMPT BEING OPTIMIZED]: {prompt_name}

[CURRENT PROMPT TEMPLATE]:
{current_prompt}

[FAILURE EVIDENCE — {n} instance(s)]:
{failure_evidence}

Output JSON:
{{
  "failure_pattern": "<1-2 sentences: the general class of behavior that is wrong>",
  "optimized_prompt": "<full improved prompt, all {{placeholders}} preserved>",
  "rationale": "<2-3 sentences: what changed and why it generalizes>",
  "confidence_level": "LOW" | "MODERATE" | "CONFIDENT" | "VERY_CONFIDENT"
}}
"""


def optimize_prompt_llm(
    client,
    config: dict,
    culprit_name: str,
    prompt_name: str,
    current_prompt: str,
    traces: list[TraceObject],
) -> OptimizationResult:
    """
    Call the high-reasoning model to generate an optimized prompt.

    Uses gemini-2.5-pro (high_reasoning_model) for maximum quality.
    Returns a partially-populated OptimizationResult (preview_response is
    filled by the caller via generate_preview_response).
    """
    failure_evidence = build_failure_evidence(traces)
    prompt = OPTIMIZER_PROMPT_TEMPLATE.format(
        culprit_name=culprit_name,
        prompt_name=prompt_name,
        current_prompt=current_prompt,
        n=len(traces),
        failure_evidence=failure_evidence,
    )

    model_name = config.get("high_reasoning_model", "gemini-2.5-pro")
    logger.info(f"[Optimizer] Calling {model_name} to optimize '{prompt_name}'")

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    text = response.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()

    data = json.loads(text)

    return OptimizationResult(
        optimization_id=str(uuid.uuid4()),
        timestamp=datetime.now().isoformat(),
        culprit_name=culprit_name,
        prompt_name=prompt_name,
        original_prompt=current_prompt,
        optimized_prompt=data["optimized_prompt"],
        failure_pattern=data["failure_pattern"],
        rationale=data["rationale"],
        trace_ids=[t.trace_id for t in traces],
        confidence_level=ConfidenceLevel(data["confidence_level"]),
        preview_response="",  # Filled by generate_preview_response
    )


# ============================================================================
# Synchronous grounding helper (for fun_fact preview)
# ============================================================================

def _run_grounding(client, config: dict, object_name: str, age: int) -> str:
    """
    Run the grounding step synchronously (no Google Search tool in sync API).

    Falls back to a plain generate_content call with the grounding prompt so
    the optimizer gets real factual context for structuring the preview.
    """
    prompts = paixueji_prompts.get_prompts()
    grounding_prompt = prompts["fun_fact_grounding_prompt"].format(
        object_name=object_name,
        age=age,
        category="general",
    )
    model_name = config.get("model_name", "gemini-2.5-flash-lite")
    response = client.models.generate_content(
        model=model_name,
        contents=grounding_prompt,
        config=GenerateContentConfig(temperature=0.3, max_output_tokens=1000),
    )
    return response.text.strip()


# ============================================================================
# Preview response generation
# ============================================================================

def generate_preview_response(
    client,
    config: dict,
    trace: TraceObject,
    optimized_prompt: str,
    prompt_name: str,
) -> str:
    """
    Generate a real LLM response using the new prompt against the original
    failing input. This is a direct LLM call (not a full graph run) to avoid
    side effects.

    Per-prompt input construction is explicit: each prompt has different
    required variables that must be sourced from the trace or re-generated.
    """
    state = trace.input_state
    exchange = trace.exchange
    prompts_base = paixueji_prompts.get_prompts()

    age = state.get("age") or trace.age or 6
    object_name = state.get("object_name") or trace.object_name or ""

    if prompt_name == "fun_fact_structuring_prompt":
        # Re-run grounding so the new structuring prompt is tested against real facts
        grounded_text = _run_grounding(client, config, object_name, age)
        formatted = optimized_prompt.format(
            object_name=object_name,
            age=age,
            grounded_text=grounded_text,
        )

    elif prompt_name == "introduction_prompt":
        formatted = optimized_prompt.format(
            object_name=object_name,
            age_prompt=_get_age_prompt(age),
            category_prompt=state.get("level1_category", ""),
            focus_prompt=prompts_base["focus_prompts"].get("depth", ""),
            grounded_facts_section="",
            fun_fact_instruction="Ask an opening question about this object.",
        )

    elif prompt_name == "followup_question_prompt":
        formatted = optimized_prompt.format(
            object_name=object_name,
            age=age,
            age_prompt=_get_age_prompt(age),
            category_prompt=state.get("level1_category", ""),
            character_prompt=prompts_base["character_prompts"]["teacher"],
            focus_prompt=prompts_base["focus_prompts"].get("depth", ""),
        )

    elif prompt_name in (
        "feedback_response_prompt",
        "correction_response_prompt",
        "explanation_response_prompt",
    ):
        correctness_reasoning = ""
        if trace.validation_result:
            correctness_reasoning = trace.validation_result.get(
                "correctness_reasoning", ""
            )
        formatted = optimized_prompt.format(
            child_answer=exchange.child_response,
            object_name=object_name,
            age=age,
            correctness_reasoning=correctness_reasoning,
            previous_question=exchange.model_question,
        )

    else:
        raise ValueError(
            f"No preview generation logic implemented for prompt: '{prompt_name}'. "
            f"Supported prompts: fun_fact_structuring_prompt, introduction_prompt, "
            f"followup_question_prompt, feedback_response_prompt, "
            f"correction_response_prompt, explanation_response_prompt"
        )

    model_name = config.get("model_name", "gemini-2.5-flash-lite")
    response = client.models.generate_content(
        model=model_name,
        contents=formatted,
        config=GenerateContentConfig(
            temperature=config.get("temperature", 0.3),
        ),
    )
    return response.text.strip()


# ============================================================================
# Refinement template + helpers
# ============================================================================

REFINE_PROMPT_TEMPLATE = """\
You are an expert prompt engineer for a child-educational AI system.
Improve a prompt template to fix a GENERAL CLASS of failure, without hardcoding specific cases.

CRITICAL RULES:
1. Do NOT add rules about specific content from the failure examples.
   Bad: "Never ask 'what do you think it was like for the dinosaur'"
   Good: "Prefer concrete sensory questions (what does it look like? feel like?)
          over abstract or philosophical ones."
2. All existing {{placeholder}} variables must be preserved exactly as-is.
3. The improved prompt must handle ALL valid inputs, not just the failure cases.
4. Add guidance, not prohibitions.

[CULPRIT NODE]: {culprit_name}
[PROMPT BEING OPTIMIZED]: {prompt_name}

[CURRENT PROMPT TEMPLATE]:
{current_prompt}

[FAILURE EVIDENCE — {n} instance(s)]:
{failure_evidence}

[PREVIOUS OPTIMIZATION ATTEMPT — REJECTED BY HUMAN]:
{previous_optimized_prompt}

[HUMAN'S REJECTION REASON]:
{rejection_reason}

Your task: Generate a BETTER optimization that:
1. Still fixes the general failure class described in the failure evidence.
2. Specifically addresses the human's rejection reason above.
3. Does not repeat the shortcomings of the previous attempt.

Output JSON:
{{
  "failure_pattern": "<1-2 sentences: the general class of behavior that is wrong>",
  "optimized_prompt": "<full improved prompt, all {{placeholders}} preserved>",
  "rationale": "<2-3 sentences: what changed and why it generalizes>",
  "confidence_level": "LOW" | "MODERATE" | "CONFIDENT" | "VERY_CONFIDENT"
}}
"""


def optimize_prompt_llm_refine(
    client,
    config: dict,
    culprit_name: str,
    prompt_name: str,
    current_prompt: str,
    traces: list[TraceObject],
    previous_optimized_prompt: str,
    rejection_reason: str,
) -> OptimizationResult:
    """
    Call the high-reasoning model to generate a refined optimization.

    Identical flow to optimize_prompt_llm() but uses REFINE_PROMPT_TEMPLATE,
    injecting the previous attempt and the human's rejection reason.
    """
    failure_evidence = build_failure_evidence(traces)
    prompt = REFINE_PROMPT_TEMPLATE.format(
        culprit_name=culprit_name,
        prompt_name=prompt_name,
        current_prompt=current_prompt,
        n=len(traces),
        failure_evidence=failure_evidence,
        previous_optimized_prompt=previous_optimized_prompt,
        rejection_reason=rejection_reason,
    )

    model_name = config.get("high_reasoning_model", "gemini-2.5-pro")
    logger.info(f"[Optimizer] Calling {model_name} to REFINE '{prompt_name}'")

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    text = response.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()

    data = json.loads(text)

    return OptimizationResult(
        optimization_id=str(uuid.uuid4()),
        timestamp=datetime.now().isoformat(),
        culprit_name=culprit_name,
        prompt_name=prompt_name,
        original_prompt=current_prompt,
        optimized_prompt=data["optimized_prompt"],
        failure_pattern=data["failure_pattern"],
        rationale=data["rationale"],
        trace_ids=[t.trace_id for t in traces],
        confidence_level=ConfidenceLevel(data["confidence_level"]),
        preview_response="",  # Filled by run_refinement
    )


def run_refinement(
    client,
    config: dict,
    previous_result: OptimizationResult,
    rejection_reason: str,
) -> OptimizationResult:
    """
    Full refinement pipeline:
      1. Load traces for the same culprit
      2. Call the refine LLM (previous attempt + rejection reason injected)
      3. Generate a preview response with the new prompt
      4. Delete the old pending file, save the new one

    Note: current_prompt stays as original_prompt (not the previous attempt)
    to avoid prompt drift across multiple refinement rounds.
    """
    traces = load_traces_for_culprit(previous_result.culprit_name)
    if not traces:
        raise ValueError(
            f"No traces found for culprit '{previous_result.culprit_name}'."
        )

    new_result = optimize_prompt_llm_refine(
        client, config,
        culprit_name=previous_result.culprit_name,
        prompt_name=previous_result.prompt_name,
        current_prompt=previous_result.original_prompt,   # always the original
        traces=traces,
        previous_optimized_prompt=previous_result.optimized_prompt,
        rejection_reason=rejection_reason,
    )

    # Populate audit chain fields
    new_result.refined_from_id = previous_result.optimization_id
    new_result.rejection_reason = rejection_reason

    # Generate preview with new prompt
    try:
        new_result.preview_response = generate_preview_response(
            client, config, traces[0], new_result.optimized_prompt, new_result.prompt_name
        )
    except Exception as e:
        new_result.preview_response = f"(Preview generation failed: {e})"

    # Delete the old pending file, save new one
    old_pending = (
        Path(__file__).parent / "optimizations" / "pending"
        / f"{previous_result.optimization_id}.json"
    )
    if old_pending.exists():
        old_pending.unlink()

    save_optimization(new_result, approved=False)
    return new_result


# ============================================================================
# Persistence
# ============================================================================

def save_optimization(result: OptimizationResult, approved: bool = False) -> str:
    """
    Persist an OptimizationResult.

    approved=False  → writes to optimizations/pending/{id}.json
    approved=True   → merges into prompt_overrides.json and moves the file
                       from pending/ to optimizations/{id}.json
    """
    base_dir = Path(__file__).parent
    opt_id = result.optimization_id

    if not approved:
        pending_dir = base_dir / "optimizations" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        dest = pending_dir / f"{opt_id}.json"
        dest.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        logger.info(f"[Optimizer] Saved pending optimization: {dest}")
        return str(dest)

    # ── Approved: merge into overrides and archive ──
    overrides_path = base_dir / "prompt_overrides.json"
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    else:
        overrides = {}

    overrides[result.prompt_name] = result.optimized_prompt
    overrides_path.write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        f"[Optimizer] Merged '{result.prompt_name}' into prompt_overrides.json"
    )

    # Move pending file to approved archive
    approved_dir = base_dir / "optimizations"
    approved_dir.mkdir(parents=True, exist_ok=True)
    pending_path = base_dir / "optimizations" / "pending" / f"{opt_id}.json"
    archive_path = approved_dir / f"{opt_id}.json"
    if pending_path.exists():
        pending_path.rename(archive_path)
    else:
        # Pending file missing (e.g. server restart) — write fresh archive copy
        archive_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    logger.info(f"[Optimizer] Archived approved optimization: {archive_path}")
    return str(archive_path)


# ============================================================================
# Orchestrator
# ============================================================================

def run_optimization(
    client,
    config: dict,
    culprit_name: str,
    prompt_name: str | None = None,
) -> OptimizationResult:
    """
    Full optimization pipeline:
      1. Load all traces for the culprit
      2. Resolve prompt name (explicit arg > trace field > error)
      3. Call the optimizer LLM
      4. Generate a preview response with the new prompt
      5. Save to optimizations/pending/ (NOT to overrides yet)

    Returns the complete OptimizationResult for the API to return to the UI.
    """
    traces = load_traces_for_culprit(culprit_name)
    if not traces:
        raise ValueError(
            f"No traces found for culprit '{culprit_name}'. "
            f"Submit a manual critique first to generate traces."
        )

    resolved_name = prompt_name or traces[0].culprit.prompt_template_name
    if not resolved_name:
        available = [
            k for k, v in paixueji_prompts.get_prompts().items()
            if isinstance(v, str)  # exclude nested dicts like character_prompts
        ]
        raise ValueError(
            f"prompt_name not specified and trace has no prompt_template_name. "
            f"Pass prompt_name explicitly. Available prompt keys: {available}"
        )

    current_prompt = paixueji_prompts.get_prompts().get(resolved_name)
    if not isinstance(current_prompt, str):
        raise ValueError(
            f"'{resolved_name}' is not a string prompt (got {type(current_prompt).__name__}). "
            f"It may be a nested mapping (e.g. character_prompts). "
            f"Specify a leaf prompt key."
        )

    logger.info(
        f"[Optimizer] Starting optimization | culprit={culprit_name} "
        f"prompt={resolved_name} traces={len(traces)}"
    )

    result = optimize_prompt_llm(
        client, config, culprit_name, resolved_name, current_prompt, traces
    )

    # Always generate preview — the human needs this to validate the fix
    try:
        result.preview_response = generate_preview_response(
            client, config, traces[0], result.optimized_prompt, resolved_name
        )
    except Exception as e:
        logger.warning(f"[Optimizer] Preview generation failed: {e}")
        result.preview_response = f"(Preview generation failed: {e})"

    save_optimization(result, approved=False)
    return result
