"""
TraceObject assembly and storage logic.

Assembles structured TraceObjects from conversation history, node traces,
and human critique data. Saves them as JSON files for the optimization pipeline.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from google.genai.types import GenerateContentConfig
from loguru import logger

from trace_schema import (
    TraceObject, NodeTrace, HumanCritique, ExchangeContext,
    CulpritIdentification, CulpritType, ConfidenceLevel,
    effective_culprits,
)


_NODE_GLOSSARY = """Graph node roles:
- router:route_from_start: Decides generate_intro (intro) or analyze_input (chat)
- analyze_input: Classifies child's utterance into 1 of 9 intents; uses prompt 'user_intent_prompt'
- router:route_from_analyze_input: Routes to one of 9 intent nodes based on intent_type
- generate_intro: Streams the introduction response using ask_introduction_question_stream
- curiosity: Child asks why/what/how — expand gently + suggest action; uses 'curiosity_intent_prompt'
- clarifying_idk: Child says "I don't know" — affirm + give partial answer; uses 'clarifying_idk_intent_prompt'
- clarifying_wrong: Child gives incorrect answer — affirm effort + gently correct; uses 'clarifying_wrong_intent_prompt'
- clarifying_constraint: Child gives partial answer — add constraint/refine; uses 'clarifying_constraint_intent_prompt'
- give_answer_idk: Child deeply confused — give full answer directly; uses 'give_answer_idk_intent_prompt'
- correct_answer: Child answers correctly — celebrate + deepen; uses 'correct_answer_intent_prompt'
- informative: Child shares knowledge — give space + social reaction; uses 'informative_intent_prompt'
- play: Child being silly/imaginative — play along + gamify; uses 'play_intent_prompt'
- emotional: Child expresses feeling — empathize first + redirect; uses 'emotional_intent_prompt'
- avoidance: Child refuses/exits — acknowledge + re-hook or topic switch; uses 'avoidance_intent_prompt'
- boundary: Child asks risky action — empathize + deny danger + safe alt; uses 'boundary_intent_prompt'
- action: Child issues command — execute or redirect; uses 'action_intent_prompt'
- social: Child asks about AI — warm direct answer; uses 'social_intent_prompt'
- social_acknowledgment: Child asks about AI/social — warm acknowledgment; uses 'social_acknowledgment_intent_prompt'
- chat_complete: Ends chat phase after the threshold correct answer; signals frontend to disable input
- finalize: Sends final StreamChunk and closes the turn"""


def identify_culprit_llm(
    client,
    config: dict,
    critique: HumanCritique,
    execution_path: list[NodeTrace],
    exchange: ExchangeContext,
    validation_result: dict | None = None,
    navigation_result: dict | None = None,
    focus_aspect: str | None = None,   # "question" | "response" | None
) -> CulpritIdentification:
    """
    Use a Gemini LLM to holistically identify the component responsible for the failure.

    Reads the full exchange context, execution path, validation/navigation results,
    and human critique to reason about which graph component most likely caused
    the problem — including subtle failures like wrong tone or age-inappropriate language.

    When focus_aspect is set, the LLM is directed to focus only on the relevant
    execution phase and critique text, enabling independent per-aspect identification.
    """
    # Serialize execution path for the prompt
    def _fmt_entry(entry: NodeTrace) -> str:
        return (
            f"  - {entry.node} ({entry.time_ms}ms)"
            f" | changes={entry.changes}"
            f" | state_before={entry.state_before}"
        )

    response_lines = [_fmt_entry(e) for e in execution_path if e.phase == "response"]
    response_path_text = "\n".join(response_lines) if response_lines else "  (none)"

    # Serialize validation / navigation results
    val_text = json.dumps(validation_result, ensure_ascii=False) if validation_result else "null"
    nav_text = json.dumps(navigation_result, ensure_ascii=False) if navigation_result else "null"

    # When focus_aspect is set, show only the relevant critique field
    if focus_aspect == "response":
        response_problem_text = critique.model_response_problem or "(none)"
    else:
        response_problem_text = critique.model_response_problem or "(none)"

    # Build focus directive line when narrowing scope
    if focus_aspect == "response":
        focus_directive = (
            "\nFocus exclusively on identifying the culprit responsible for the "
            "MODEL RESPONSE problem.\n"
        )
    else:
        focus_directive = ""

    prompt = f"""You are an expert AI system debugger reviewing a failed educational exchange with a child.

{_NODE_GLOSSARY}

---

[EXCHANGE]
Mode: {exchange.mode}
Child response: {exchange.child_response}
Model response: {exchange.model_response}

[EXECUTION PATH — RESPONSE PHASE]
(nodes that ran to process the child response and produce model_response)
{response_path_text}

[VALIDATION RESULT]
{val_text}

[NAVIGATION RESULT]
{nav_text}

[HUMAN CRITIQUE]
Response problem: {response_problem_text}
Conclusion: {critique.conclusion or "(none)"}

---
{focus_directive}
Your task: Identify which graph component is MOST RESPONSIBLE for the failure described in the human critique.
Reason holistically — consider tone, vocabulary, age-appropriateness, strategic direction, and factual accuracy.

- Set culprit_phase to "question" if the culprit ran to produce model_question,
  "response" if it ran to produce model_response.
  Use null for pure classifiers (routers, validators) that produce a decision, not text.

Output a single JSON object with EXACTLY these fields:
{{
  "culprit_type": "NODE" | "ROUTER" | "VALIDATOR" | "NAVIGATOR" | "DRIVER" | "PROMPT" | "UNKNOWN",
  "culprit_name": "<exact node or component name from the glossary above>",
  "confidence_level": "LOW" | "MODERATE" | "CONFIDENT" | "VERY_CONFIDENT",
  "reasoning": "<2-4 sentences referencing the actual exchange content and why this component is responsible>",
  "prompt_template_name": "<exact key — pick from: fun_fact_structuring_prompt, fun_fact_grounding_prompt, introduction_prompt, user_intent_prompt (analyze_input), curiosity_intent_prompt, clarifying_idk_intent_prompt, clarifying_wrong_intent_prompt, clarifying_constraint_intent_prompt, give_answer_idk_intent_prompt, correct_answer_intent_prompt, informative_intent_prompt, play_intent_prompt, emotional_intent_prompt, avoidance_intent_prompt, boundary_intent_prompt, action_intent_prompt, social_intent_prompt, social_acknowledgment_intent_prompt, topic_switch_response_prompt, followup_question_prompt, completion_prompt, classification_prompt. Use null ONLY for pure routers (router:*), finalize, generate_intro, chat_complete.>",
  "culprit_phase": "question" | "response" | null
}}
"""

    try:
        model_name = config["high_reasoning_model"]
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

        data = json.loads(text)
        return CulpritIdentification(
            culprit_type=CulpritType(data["culprit_type"]),
            culprit_name=data["culprit_name"],
            confidence_level=ConfidenceLevel(data["confidence_level"]),
            reasoning=data["reasoning"],
            prompt_template_name=data.get("prompt_template_name"),
            culprit_phase=data.get("culprit_phase"),
        )

    except Exception as e:
        logger.error(f"[TraceAssembler] LLM culprit identification failed: {e}")
        return CulpritIdentification(
            culprit_type=CulpritType.UNKNOWN,
            culprit_name="unknown",
            confidence_level=ConfidenceLevel.LOW,
            reasoning=f"LLM identification failed: {e}",
        )


def _extract_clean_history(assistant, exchange_index: int) -> list[dict]:
    """
    Return conversation history up through the exchange_index-th child→model pair,
    stripping all internal metadata fields (only role + content kept).
    exchange_index is 1-based. The introduction (first assistant message) is
    included but not counted as an exchange.
    """
    raw = assistant.conversation_history
    clean = []
    exchanges_found = 0
    i = 0
    intro_found = False
    while i < len(raw):
        msg = raw[i]
        if msg.get("role") == "system":
            clean.append({"role": "system", "content": msg.get("content", "")})
            i += 1
            continue
        # Introduction: first assistant message
        if not intro_found and msg.get("role") == "assistant":
            clean.append({"role": "assistant", "content": msg.get("content", "")})
            intro_found = True
            i += 1
            continue
        # Pairs: user → assistant
        if (intro_found
                and msg.get("role") == "user"
                and i + 1 < len(raw)
                and raw[i + 1].get("role") == "assistant"):
            exchanges_found += 1
            clean.append({"role": "user",      "content": msg.get("content", "")})
            clean.append({"role": "assistant", "content": raw[i + 1].get("content", "")})
            if exchanges_found >= exchange_index:
                break
            i += 2
        else:
            i += 1
    return clean


def extract_input_state_for_exchange(assistant, exchange_index: int) -> dict:
    """
    Walk conversation_history to find the Nth child→model pair
    and return the _input_state_snapshot from the model message.

    exchange_index is 1-based (matching the critique UI).
    The introduction (first assistant message) is skipped and not counted.
    """
    exchanges_found = 0
    i = 0
    history = assistant.conversation_history
    intro_found = False

    while i < len(history):
        msg = history[i]
        if msg.get("role") == "system":
            i += 1
            continue

        # Skip introduction: first assistant message
        if not intro_found and msg.get("role") == "assistant":
            intro_found = True
            i += 1
            continue

        # Look for child→model pair
        if (intro_found
                and msg.get("role") == "user"
                and i + 1 < len(history)
                and history[i + 1].get("role") == "assistant"):
            exchanges_found += 1
            if exchanges_found == exchange_index:
                return history[i + 1].get("_input_state_snapshot", {})
            i += 2
        else:
            i += 1

    return {}


def assemble_trace_object(
    session_id: str,
    assistant,
    exchange_index: int,
    exchange_data: dict,
    critique_data: dict,
) -> TraceObject:
    """
    Assemble a complete TraceObject from exchange and critique data.

    Args:
        session_id: The session UUID
        assistant: PaixuejiAssistant instance
        exchange_index: 1-based index of the exchange in the conversation
        exchange_data: Dict with model_question, child_response, model_response,
                       nodes_executed, mode
        critique_data: Dict with human critique fields
    """
    # Build execution path from both question and response phases
    def _build_node_traces(raw_nodes: list, phase: str) -> tuple[list[NodeTrace], float]:
        traces, total = [], 0.0
        for entry in raw_nodes:
            traces.append(NodeTrace(
                node=entry.get("node", "unknown"),
                time_ms=entry.get("time_ms", 0),
                changes=entry.get("changes", {}),
                state_before=entry.get("state_before", {}),
                validation_result=entry.get("validation_result"),
                navigation_result=entry.get("navigation_result"),
                phase=phase,
            ))
            total += entry.get("time_ms", 0)
        return traces, total

    question_traces, q_time = _build_node_traces(
        exchange_data.get("question_nodes_executed", []), phase="question"
    )
    response_traces, r_time = _build_node_traces(
        exchange_data.get("nodes_executed", []), phase="response"
    )
    execution_path = question_traces + response_traces
    total_time = q_time + r_time

    # Extract input state from conversation history
    input_state = extract_input_state_for_exchange(assistant, exchange_index)

    # Build exchange context (model_question="" — deprecated field, kept for backward compat)
    exchange = ExchangeContext(
        model_question="",
        child_response=exchange_data.get("child_response", ""),
        model_response=exchange_data.get("model_response", ""),
        mode=exchange_data.get("mode", "chat"),
    )

    # Build human critique
    critique = HumanCritique(
        exchange_index=exchange_index,
        model_response_expected=critique_data.get("model_response_expected", ""),
        model_response_problem=critique_data.get("model_response_problem", ""),
        conclusion=critique_data.get("conclusion", ""),
    )

    # Extract validation and navigation results from the execution path
    validation_result = None
    navigation_result = None
    for entry in execution_path:
        if entry.validation_result and not validation_result:
            validation_result = entry.validation_result
        if entry.navigation_result and not navigation_result:
            navigation_result = entry.navigation_result

    # Identify culprit(s) via LLM — one focused call per critiqued aspect
    _llm_kwargs = dict(
        client=assistant.client,
        config=assistant.config,
        critique=critique,
        execution_path=execution_path,
        exchange=exchange,
        validation_result=validation_result,
        navigation_result=navigation_result,
    )
    culprits = []
    if critique.model_response_problem:
        c = identify_culprit_llm(**_llm_kwargs, focus_aspect="response")
        culprits.append(c)
    if not culprits:
        # No specific problem field filled — run unfocused to still get a culprit
        culprits.append(identify_culprit_llm(**_llm_kwargs, focus_aspect=None))

    primary = culprits[0]   # legacy field gets the first (or only) culprit

    # Count conversation length (non-system messages)
    conversation_length = sum(
        1 for msg in assistant.conversation_history
        if msg.get("role") != "system"
    )

    # Extract clean conversation history up to the critiqued exchange
    conversation_history = _extract_clean_history(assistant, exchange_index)

    return TraceObject(
        trace_id=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=datetime.now().isoformat(),
        object_name=assistant.object_name or "unknown",
        age=assistant.age,
        key_concept=assistant.key_concept,
        ibpyp_theme_name=assistant.ibpyp_theme_name,
        input_state=input_state,
        execution_path=execution_path,
        culprit=primary,    # legacy field — kept for backward compat
        culprits=culprits,  # new list: one entry per critiqued aspect
        critique=critique,
        exchange=exchange,
        validation_result=validation_result,
        navigation_result=navigation_result,
        exchange_index=exchange_index,
        conversation_length=conversation_length,
        total_execution_time_ms=round(total_time, 1),
        conversation_history=conversation_history,
    )


def save_trace_object(trace: TraceObject) -> str:
    """
    Save a TraceObject as JSON to the traces/ directory.

    Naming: {object_name}_{session_prefix}_ex{index}_{timestamp}.json
    Returns the file path as a string.
    """
    traces_dir = Path(__file__).parent / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (trace.object_name or "unknown")
    )
    session_prefix = trace.session_id[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_name}_{session_prefix}_ex{trace.exchange_index}_{timestamp}.json"

    file_path = traces_dir / filename
    file_path.write_text(
        trace.model_dump_json(indent=2),
        encoding="utf-8",
    )

    logger.info(f"[TRACE] Saved trace object: {file_path}")
    return str(file_path)
