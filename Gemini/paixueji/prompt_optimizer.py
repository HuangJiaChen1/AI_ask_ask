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
import re
import uuid
from datetime import datetime
from pathlib import Path

from google.genai.types import GenerateContentConfig
from loguru import logger

import paixueji_prompts
from trace_schema import TraceObject, OptimizationResult, ConfidenceLevel, effective_culprits
from stream.utils import clean_messages_for_api, convert_messages_to_gemini_format

_ROUTER_PROMPT_NAMES = {"user_intent_prompt", "theme_navigator_rules"}


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
            culprit_names = {c.culprit_name for c in effective_culprits(trace)}
            if culprit_name in culprit_names:
                results.append(trace)
        except Exception as e:
            logger.warning(f"[Optimizer] Could not parse trace {f.name}: {e}")

    # Sort oldest-first so the LLM sees the history of failures
    results.sort(key=lambda t: t.timestamp)
    return results


def load_traces_by_ids(trace_ids: list[str]) -> list[TraceObject]:
    """Load specific TraceObjects by ID. Used for single-trace and refinement flows."""
    traces_dir = Path(__file__).parent / "traces"
    if not traces_dir.exists():
        return []
    id_set = set(trace_ids)
    results = []
    for f in sorted(traces_dir.glob("*.json")):
        try:
            trace = TraceObject.model_validate_json(f.read_text(encoding="utf-8"))
            if trace.trace_id in id_set:
                results.append(trace)
        except Exception as e:
            logger.warning(f"[Optimizer] Could not parse trace {f.name}: {e}")
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
        for c in effective_culprits(trace):
            if c.reasoning:
                lines.append(f"  Culprit reasoning ({c.culprit_phase or 'general'}): {c.reasoning}")

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


ROUTER_OPTIMIZER_PROMPT_TEMPLATE = """\
You are an expert prompt engineer for a child-educational AI system.
Improve a ROUTER RULES BLOCK to fix a GENERAL CLASS of routing/classification failure.

CRITICAL RULES:
1. Do NOT add rules about specific content from the failure examples.
   Bad: "Never classify 'I don't know' as DRIFTING"
   Good: "Reserve DRIFTING for responses where the child is engaged but veering off-topic."
2. The improved rules must handle ALL valid inputs, not just the failure cases.
3. Add guidance (what TO do), not prohibitions (what NOT to do).
4. This rules block has NO placeholder variables — it is a static block injected verbatim
   into a larger prompt. Do NOT add {{placeholders}}.
5. If the failure suggests the output SCHEMA is too narrow (a new status/strategy value
   would fix the root cause), propose it in router_patch — but ONLY if the target graph
   node already exists: guide_driver, guide_success, guide_hint, guide_exit,
   generate_intro, curiosity, clarifying, informative, play, emotional, avoidance,
   boundary, action, social.
   If a brand-new graph node would be required, set router_patch to null and explain why
   in the rationale (Mode C failure — needs engineer).

[CULPRIT NODE]: {culprit_name}
[RULES BLOCK BEING OPTIMIZED]: {prompt_name}

[CURRENT RULES BLOCK]:
{current_prompt}

[FAILURE EVIDENCE — {n} instance(s)]:
{failure_evidence}

Output JSON:
{{
  "failure_pattern": "<1-2 sentences: the general class of routing behavior that is wrong>",
  "optimized_prompt": "<full improved rules block, no {{placeholders}}>",
  "rationale": "<2-3 sentences: what changed and why it generalizes>",
  "confidence_level": "LOW" | "MODERATE" | "CONFIDENT" | "VERY_CONFIDENT",
  "router_patch": null | {{"navigator_strategy_routes": {{"NEW_STRATEGY_VALUE": "existing_node"}}}}
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

    # Use the router-specific template for semantic router prompts
    is_router_prompt = prompt_name in _ROUTER_PROMPT_NAMES
    template = ROUTER_OPTIMIZER_PROMPT_TEMPLATE if is_router_prompt else OPTIMIZER_PROMPT_TEMPLATE
    prompt = template.format(
        culprit_name=culprit_name,
        prompt_name=prompt_name,
        current_prompt=current_prompt,
        n=len(traces),
        failure_evidence=failure_evidence,
    )

    model_name = config["high_reasoning_model"]
    logger.info(f"[Optimizer] Calling {model_name} to optimize '{prompt_name}' (router={is_router_prompt})")

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
        router_patch=data.get("router_patch") if is_router_prompt else None,
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
    model_name = config["model_name"]
    response = client.models.generate_content(
        model=model_name,
        contents=grounding_prompt,
        config=GenerateContentConfig(temperature=0.3, max_output_tokens=1000),
    )
    return response.text.strip()


# ============================================================================
# Router preview helpers
# ============================================================================

def _build_input_analyzer_context(trace: TraceObject) -> dict:
    """Extract the context fields needed to re-run the Input Analyzer on the failing trace."""
    state = trace.input_state
    return {
        "age": state.get("age") or trace.age or 6,
        "object_name": state.get("object_name") or trace.object_name or "",
        "last_model_question": trace.exchange.model_question,
        "child_answer": trace.exchange.child_response,
    }


def _build_navigator_context(trace: TraceObject) -> dict:
    """Extract the context fields needed to re-run the Theme Navigator on the failing trace."""
    state = trace.input_state
    goal_description = state.get("ibpyp_theme_description") or trace.ibpyp_theme_name or ""
    theme_name = state.get("ibpyp_theme_name") or trace.ibpyp_theme_name or ""
    key_concept = state.get("key_concept") or trace.key_concept or ""
    bridge_question = state.get("bridge_question") or ""
    turn_count = state.get("guide_turn_count") or 1
    max_turns = state.get("guide_max_turns") or 6
    object_name = state.get("object_name") or trace.object_name or ""

    context_section = (
        f'[CONTEXT]\n'
        f'Object: "{object_name}"\n'
        f'Target Theme: "{theme_name}" ({goal_description})\n'
        f'Key Concept: "{key_concept}"\n'
        f'Bridge Question: "{bridge_question}"\n'
        f'Turn: {turn_count}/{max_turns}'
    )
    return {
        "age": state.get("age") or trace.age or 6,
        "object_name": object_name,
        "theme_name": theme_name,
        "key_concept": key_concept,
        "bridge_question": bridge_question,
        "user_input": trace.exchange.child_response,
        "context_section": context_section,
        "conversation_history": trace.conversation_history,   # mirror production context
    }


def _call_intent_classifier(client, config: dict, ctx: dict, prompt_template: str) -> dict:
    """Re-run the Intent Classifier (sync) with the given prompt template.

    Mirrors production classify_intent() exactly:
    gemini-2.0-flash-lite, temp=0.1, max_output_tokens=60,
    regex parsing of INTENT: / NEW_OBJECT: / REASONING: plain-text output.
    """
    prompt = prompt_template.format(
        object_name=ctx.get("object_name", ""),
        last_model_question=ctx.get("last_model_question", ""),
        child_answer=ctx.get("child_answer", ""),
        topic_selection_instructions="",
    )
    response = client.models.generate_content(
        model=config["model_name"],
        contents=prompt,
        config=GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=60,
        ),
    )
    text = response.text or ""

    def _get(pattern, default):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    valid_intents = {
        "CURIOSITY", "CLARIFYING", "INFORMATIVE", "PLAY", "EMOTIONAL",
        "AVOIDANCE", "BOUNDARY", "ACTION", "SOCIAL"
    }
    raw_intent = _get(r"INTENT:\s*(\w+)", "CLARIFYING").upper()
    intent_type = raw_intent if raw_intent in valid_intents else "CLARIFYING"

    new_object_raw = _get(r"NEW_OBJECT:\s*(.+)", "null")
    new_object = None if new_object_raw.lower() in ("null", "none", "") else new_object_raw
    if intent_type not in ("ACTION", "AVOIDANCE"):
        new_object = None

    return {
        "intent_type": intent_type,
        "new_object": new_object,
        "reasoning": _get(r"REASONING:\s*(.+)", "N/A"),
    }


# Keep legacy _call_input_analyzer for backward compatibility with old traces
def _call_input_analyzer(client, config: dict, ctx: dict, rules_block: str) -> dict:
    """Legacy: Re-run the old Input Analyzer (sync) for old traces on disk."""
    prompt = (
        f"You are an educational AI helping a {ctx['age']}-year-old child learn.\n\n"
        f"CONTEXT:\n"
        f"- Topic: {ctx['object_name']}\n"
        f"- Question: \"{ctx['last_model_question']}\"\n"
        f"- Answer: \"{ctx['child_answer']}\"\n\n"
        f"{rules_block}"
    )
    response = client.models.generate_content(
        model=config["model_name"],
        contents=prompt,
        config=GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=120,
        ),
    )
    text = response.text

    def _get(pattern, default):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    new_object_raw = _get(r"NEW_OBJECT:\s*(.+)", "null")
    engaged_raw    = _get(r"ENGAGED:\s*(true|false)", "true")
    correct_raw    = _get(r"CORRECT:\s*(true|false)", "true")

    return {
        "decision":              _get(r"DECISION:\s*(SWITCH|CONTINUE)", "CONTINUE"),
        "new_object":            None if new_object_raw.lower() in ("null", "none", "") else new_object_raw,
        "switching_reasoning":   _get(r"SWITCHING_REASONING:\s*(.+)", "N/A"),
        "is_engaged":            engaged_raw.lower() == "true",
        "is_factually_correct":  correct_raw.lower() == "true",
        "correctness_reasoning": _get(r"CORRECTNESS_REASONING:\s*(.+)", "N/A"),
    }


def _call_navigator(client, config: dict, ctx: dict, rules_block: str) -> dict:
    """Re-run the Theme Navigator (sync) with the given rules block."""
    recent_history = ""
    for msg in ctx.get("conversation_history", [])[-6:]:   # mirror production: last 3 exchanges
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role != "system":
            recent_history += f"{role.upper()}: {content}\n"
    if not recent_history:
        recent_history = "(no prior conversation available)"

    prompt = (
        f"You are the Strategy Navigator for a guided conversation with a {ctx['age']}-year-old child.\n\n"
        f"{ctx['context_section']}\n\n"
        f"[RECENT CONVERSATION]\n{recent_history}\n"
        f"User's Latest Input: \"{ctx['user_input']}\"\n\n"
        f"{rules_block}"
    )
    model_name = config["model_name"]
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    text = response.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    return json.loads(text)


def _infer_intent_prompt_name(intent_result: dict) -> str:
    """Infer which intent response prompt to use from a classify_intent result dict."""
    return f"{intent_result.get('intent_type', 'clarifying').lower()}_intent_prompt"


def _call_intent_response(
    client, config: dict, trace, intent_result: dict, prompt_name: str
) -> str:
    """Call an intent response prompt (sync) with trace context.

    Mirrors generate_intent_response_stream() production call (non-streaming sync version).
    """
    import paixueji_prompts as _pp
    state = trace.input_state
    age = state.get("age") or trace.age or 6
    object_name = state.get("object_name") or trace.object_name or ""
    prompts = _pp.get_prompts()
    prompt_template = prompts.get(prompt_name, "")
    try:
        formatted = prompt_template.format(
            child_answer=trace.exchange.child_response,
            object_name=object_name,
            age=age,
            age_prompt=_get_age_prompt(age),
            category_prompt=state.get("level1_category", ""),
            last_model_question=state.get("last_model_question", "the previous question"),
        )
    except KeyError:
        formatted = prompt_template
    model_name = config["model_name"]
    response = client.models.generate_content(
        model=model_name,
        contents=formatted,
        config=GenerateContentConfig(temperature=0.7, max_output_tokens=200),
    )
    return response.text.strip()


# Keep legacy _infer_response_type for old trace handling
def _infer_response_type(validation_result: dict) -> str:
    """Legacy: Infer which response prompt to use from old validation result dict."""
    if not validation_result.get("is_engaged", True):
        return "explanation_response_prompt"
    if validation_result.get("is_factually_correct", True):
        return "feedback_response_prompt"
    return "correction_response_prompt"


def _call_downstream_response(
    client, config: dict, trace: TraceObject, validation_result: dict, prompt_name: str
) -> str:
    """Call a response-generation prompt (feedback/correction/explanation) with trace context."""
    state = trace.input_state
    age = state.get("age") or trace.age or 6
    object_name = state.get("object_name") or trace.object_name or ""
    prompts = paixueji_prompts.get_prompts()
    prompt_template = prompts.get(prompt_name, "")
    correctness_reasoning = validation_result.get("correctness_reasoning", "")
    try:
        formatted = prompt_template.format(
            child_answer=trace.exchange.child_response,
            object_name=object_name,
            age=age,
            correctness_reasoning=correctness_reasoning,
            previous_question=trace.exchange.model_question,
        )
    except KeyError:
        formatted = prompt_template
    model_name = config["model_name"]
    response = client.models.generate_content(
        model=model_name,
        contents=formatted,
        config=GenerateContentConfig(temperature=0.7, max_output_tokens=200),
    )
    return response.text.strip()


def _call_theme_driver(client, config: dict, trace: TraceObject, nav_result: dict) -> str:
    """Call the ThemeDriver prompt synchronously with the given navigation result."""
    state = trace.input_state
    age = state.get("age") or trace.age or 6
    object_name = state.get("object_name") or trace.object_name or ""
    key_concept = state.get("key_concept") or trace.key_concept or ""
    theme_name = state.get("ibpyp_theme_name") or trace.ibpyp_theme_name or ""

    instruction = nav_result.get("instruction", "Respond naturally.")
    strategy = nav_result.get("strategy", "ADVANCE")
    scaffold_level = nav_result.get("scaffold_level", 0)

    scaffold_guidance = ""
    if strategy == "SCAFFOLD" and scaffold_level:
        scaffold_guidance = (
            f"\nSCAFFOLDING LEVEL {scaffold_level}: "
            f"Provide level-{scaffold_level} scaffolding for the child about {object_name}."
        )

    driver_instruction = (
        f"You are guiding a {age}-year-old to discover: \"{key_concept}\"\n"
        f"about \"{object_name}\" (Theme: {theme_name})\n\n"
        f"INSTRUCTION FROM NAVIGATOR:\n{instruction}\n"
        f"{scaffold_guidance}\n\n"
        f"RULES: Keep response to 1-2 sentences. Ask ONE question only. Be warm and encouraging."
    )
    model_name = config["model_name"]
    response = client.models.generate_content(
        model=model_name,
        contents=driver_instruction,
        config=GenerateContentConfig(temperature=0.7, max_output_tokens=200),
    )
    return response.text.strip()


# ============================================================================
# Preview response generation
# ============================================================================

def _get_culprit_phase(trace: TraceObject) -> str:
    """
    Return 'question' or 'response' for the primary culprit node.

    Prefers the explicitly stored culprit_phase on new traces.
    Falls back to execution_path inspection + critique-field heuristic for old traces.
    """
    primary = effective_culprits(trace)[0] if effective_culprits(trace) else None
    if primary is None:
        return "response"

    # New traces: use the value stored at critique time
    if primary.culprit_phase is not None:
        return primary.culprit_phase

    # Old traces: infer from execution path
    culprit_name = primary.culprit_name
    phases = {e.phase for e in trace.execution_path if e.node == culprit_name}
    if phases == {"question"}:
        return "question"
    if phases == {"response"}:
        return "response"

    # Ambiguous (same node in both phases): use critique fields as tiebreaker
    if trace.critique.model_response_problem:
        return "response"
    return "question"


def _build_preview_messages(
    conversation_history: list[dict],
    formatted_prompt: str,
    is_question_prompt: bool,
) -> tuple[str, list]:
    """
    Combine stored conversation history with the formatted optimized prompt.

    For response prompts: drop the last message (R_N, the bad response)
      and append the prompt as a user turn — LLM regenerates R_N.
    For question prompts: drop the last 3 messages (Q_N, A_N, R_N)
      and append the prompt as a user turn — LLM regenerates Q_N.

    Returns (system_instruction, gemini_contents) ready for generate_content().
    Falls back to a prompt-only call (no history) if history is empty.
    """
    if not conversation_history:
        # Old traces without stored history — plain string fallback
        return "", [{"role": "user", "parts": [{"text": formatted_prompt}]}]

    if is_question_prompt:
        base = conversation_history[:-3] if len(conversation_history) > 3 else []
    else:
        base = conversation_history[:-1] if len(conversation_history) > 1 else []

    messages_to_send = base + [{"role": "user", "content": formatted_prompt}]
    clean = clean_messages_for_api(messages_to_send)
    return convert_messages_to_gemini_format(clean)


def generate_preview_response(
    client,
    config: dict,
    trace: TraceObject,
    optimized_prompt: str,
    prompt_name: str,
    culprit_phase_override: str | None = None,   # explicit phase from CulpritIdentification
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
            grounded_facts_section="",
            fun_fact_instruction="Ask an opening question about this object.",
        )

    elif prompt_name == "followup_question_prompt":
        formatted = optimized_prompt.format(
            object_name=object_name,
            age=age,
            age_prompt=_get_age_prompt(age),
            category_prompt=state.get("level1_category", ""),
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

    elif prompt_name == "user_intent_prompt":
        # Two-stage preview: re-run Intent Classifier with new prompt, then run downstream intent response
        ctx = _build_input_analyzer_context(trace)
        try:
            new_intent_result = _call_intent_classifier(client, config, ctx, optimized_prompt)
        except Exception as e:
            return f"(Intent Classifier re-run failed: {e})"

        old_intent = trace.input_state.get("intent_type", "(unknown)")
        intent_prompt_name = _infer_intent_prompt_name(new_intent_result)
        try:
            downstream = _call_intent_response(client, config, trace, new_intent_result, intent_prompt_name)
        except Exception as e:
            downstream = f"(Downstream intent response failed: {e})"

        return (
            f"[Intent Classification]\n"
            f"OLD: {old_intent}\n"
            f"NEW: {json.dumps(new_intent_result, ensure_ascii=False)}\n\n"
            f"[Child-facing response after the fix]\n{downstream}"
        )

    elif prompt_name == "input_analyzer_rules":
        # Legacy: support old traces that reference input_analyzer_rules
        ctx = _build_input_analyzer_context(trace)
        try:
            new_validation = _call_input_analyzer(client, config, ctx, optimized_prompt)
        except Exception as e:
            return f"(Input Analyzer re-run failed: {e})"

        old_validation = trace.validation_result or {}
        response_prompt_name = _infer_response_type(new_validation)
        try:
            downstream = _call_downstream_response(
                client, config, trace, new_validation, response_prompt_name
            )
        except Exception as e:
            downstream = f"(Downstream response generation failed: {e})"

        return (
            f"[Router Decision]\n"
            f"OLD: {json.dumps(old_validation, ensure_ascii=False)}\n"
            f"NEW: {json.dumps(new_validation, ensure_ascii=False)}\n\n"
            f"[What the child would see after the fix]\n{downstream}"
        )

    elif prompt_name.endswith("_intent_prompt") and prompt_name != "user_intent_prompt":
        # Generic handler for any {name}_intent_prompt (e.g., curiosity_intent_prompt)
        state = trace.input_state
        age = state.get("age") or trace.age or 6
        object_name = state.get("object_name") or trace.object_name or ""
        try:
            formatted = optimized_prompt.format(
                child_answer=trace.exchange.child_response,
                object_name=object_name,
                age=age,
                age_prompt=_get_age_prompt(age),
                category_prompt=state.get("level1_category", ""),
            )
        except KeyError:
            formatted = optimized_prompt
        model_name = config["model_name"]
        response = client.models.generate_content(
            model=model_name,
            contents=formatted,
            config=GenerateContentConfig(temperature=0.7, max_output_tokens=300),
        )
        return response.text.strip()

    elif prompt_name == "theme_navigator_rules":
        # Two-stage preview: re-run Navigator with new rules, then run ThemeDriver
        ctx = _build_navigator_context(trace)
        try:
            new_nav_result = _call_navigator(client, config, ctx, optimized_prompt)
        except Exception as e:
            return f"(Navigator re-run failed: {e})"

        old_nav_result = trace.navigation_result or {}
        try:
            guide_response = _call_theme_driver(client, config, trace, new_nav_result)
        except Exception as e:
            guide_response = f"(ThemeDriver call failed: {e})"

        return (
            f"[Navigator Decision]\n"
            f"OLD: {json.dumps(old_nav_result, ensure_ascii=False)}\n"
            f"NEW: {json.dumps(new_nav_result, ensure_ascii=False)}\n\n"
            f"[Guide response after the fix]\n{guide_response}"
        )

    else:
        raise ValueError(
            f"No preview generation logic implemented for prompt: '{prompt_name}'. "
            f"Supported prompts: fun_fact_structuring_prompt, introduction_prompt, "
            f"followup_question_prompt, feedback_response_prompt, "
            f"correction_response_prompt, explanation_response_prompt, "
            f"user_intent_prompt, <intent>_intent_prompt, "
            f"input_analyzer_rules (legacy), theme_navigator_rules"
        )

    # Resolve phase: explicit override wins; fall back to trace-derived phase
    phase = culprit_phase_override if culprit_phase_override is not None else _get_culprit_phase(trace)
    if prompt_name in ("fun_fact_structuring_prompt", "introduction_prompt"):
        is_q = True
    elif prompt_name == "followup_question_prompt":
        # generate_question appears in both phases — use resolved phase to determine slice depth
        is_q = (phase == "question")
    else:
        is_q = False
    system_instruction, contents = _build_preview_messages(
        trace.conversation_history, formatted, is_question_prompt=is_q
    )
    model_name = config["model_name"]
    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=GenerateContentConfig(
            system_instruction=system_instruction if system_instruction else None,
            temperature=config.get("temperature", 0.3),
        ),
    )
    return response.text.strip()


# ============================================================================
# Multi-preview generation
# ============================================================================

def generate_previews_for_traces(
    client,
    config: dict,
    traces: list[TraceObject],
    optimized_prompt: str,
    prompt_name: str,
    culprit_name: str,
    max_previews: int = 3,
) -> list[dict]:
    """
    Generate one preview per (trace, matching-culprit-entry) pair, capped at max_previews.

    For each trace, filter culprits to those where culprit_name matches the target.
    Each matching entry drives a separate preview with its own culprit_phase, so
    Y critiqued outputs produce Y previews even when they share the same culprit node.

    Each returned dict: {trace_id, exchange_index, culprit_phase, original, preview}
    """
    results = []
    for trace in traces:
        if len(results) >= max_previews:
            break
        matching = [c for c in effective_culprits(trace) if c.culprit_name == culprit_name]
        for c in matching:
            if len(results) >= max_previews:
                break
            phase = c.culprit_phase if c.culprit_phase is not None else _get_culprit_phase(trace)
            original = (
                trace.exchange.model_question if phase == "question"
                else trace.exchange.model_response
            )
            try:
                preview = generate_preview_response(
                    client, config, trace, optimized_prompt, prompt_name,
                    culprit_phase_override=c.culprit_phase,
                )
            except Exception as e:
                preview = f"(Preview generation failed: {e})"
            results.append({
                "trace_id": trace.trace_id,
                "exchange_index": trace.exchange_index,
                "culprit_phase": phase,
                "original": original,
                "preview": preview,
            })
    return results


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

    model_name = config["high_reasoning_model"]
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
    traces = load_traces_by_ids(previous_result.trace_ids)
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

    # Generate previews with new prompt — one per (trace, matching-culprit) pair
    try:
        new_result.previews = generate_previews_for_traces(
            client, config, traces, new_result.optimized_prompt,
            new_result.prompt_name, previous_result.culprit_name
        )
        new_result.preview_response = new_result.previews[0]["preview"] if new_result.previews else ""
    except Exception as e:
        new_result.preview_response = f"(Preview generation failed: {e})"
        new_result.previews = []

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

    # If there's a router patch, merge it into router_overrides.json
    if result.router_patch:
        router_overrides_path = base_dir / "router_overrides.json"
        if router_overrides_path.exists():
            try:
                router_overrides = json.loads(router_overrides_path.read_text(encoding="utf-8"))
            except Exception:
                router_overrides = {}
        else:
            router_overrides = {}

        for key, value in result.router_patch.items():
            if isinstance(value, dict) and isinstance(router_overrides.get(key), dict):
                router_overrides[key].update(value)
            else:
                router_overrides[key] = value

        router_overrides_path.write_text(
            json.dumps(router_overrides, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(
            f"[Optimizer] Merged router_patch into router_overrides.json: {result.router_patch}"
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
    trace_id: str | None = None,
) -> OptimizationResult:
    """
    Full optimization pipeline:
      1. Load traces for the culprit (all historical, or single if trace_id given)
      2. Resolve prompt name (explicit arg > trace field > error)
      3. Call the optimizer LLM
      4. Generate a preview response with the new prompt
      5. Save to optimizations/pending/ (NOT to overrides yet)

    Args:
        trace_id: If provided, only that one trace is used (single-trace mode).
                  If omitted, all historical traces for culprit_name are used.

    Returns the complete OptimizationResult for the API to return to the UI.
    """
    if trace_id:
        traces = load_traces_by_ids([trace_id])
        logger.info(f"[Optimizer] Single-trace mode — trace_id={trace_id}")
    else:
        traces = load_traces_for_culprit(culprit_name)
    if not traces:
        raise ValueError(
            f"No traces found for culprit '{culprit_name}'. "
            f"Submit a manual critique first to generate traces."
        )

    primary_culprits = effective_culprits(traces[0])
    resolved_name = prompt_name or (primary_culprits[0].prompt_template_name if primary_culprits else None)
    if not resolved_name:
        available = [
            k for k, v in paixueji_prompts.get_prompts().items()
            if isinstance(v, str)  # exclude nested dicts
        ]
        raise ValueError(
            f"prompt_name not specified and trace has no prompt_template_name. "
            f"Pass prompt_name explicitly. Available prompt keys: {available}"
        )

    current_prompt = paixueji_prompts.get_prompts().get(resolved_name)
    if not isinstance(current_prompt, str):
        raise ValueError(
            f"'{resolved_name}' is not a string prompt (got {type(current_prompt).__name__}). "
            f"It may be a nested mapping. "
            f"Specify a leaf prompt key."
        )

    logger.info(
        f"[Optimizer] Starting optimization | culprit={culprit_name} "
        f"prompt={resolved_name} traces={len(traces)}"
    )

    result = optimize_prompt_llm(
        client, config, culprit_name, resolved_name, current_prompt, traces
    )

    # Generate previews — one per (trace, matching-culprit) pair, capped at 3
    try:
        result.previews = generate_previews_for_traces(
            client, config, traces, result.optimized_prompt, resolved_name, culprit_name
        )
        result.preview_response = result.previews[0]["preview"] if result.previews else ""
    except Exception as e:
        logger.warning(f"[Optimizer] Preview generation failed: {e}")
        result.preview_response = f"(Preview generation failed: {e})"
        result.previews = []

    save_optimization(result, approved=False)
    return result
