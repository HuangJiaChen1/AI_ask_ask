import asyncio
import functools
import json
import random
from pathlib import Path
from typing import TypedDict, Annotated, List, Optional, Any
from langgraph.graph import StateGraph, END, START

from google import genai
from loguru import logger
import time

from stream import (
    ask_introduction_question_stream,
    ask_followup_question_stream,
    classify_intent,
    classify_dimension,
    generate_intent_response_stream,
    generate_topic_switch_response_stream,
    extract_previous_response,
    prepare_messages_for_streaming,
    generate_guide_hint
)
from stream.theme_guide import ThemeNavigator, ThemeDriver
from schema import StreamChunk

GUIDE_MODE_THRESHOLD = 4  # Correct answers required to enter guide mode


def _load_router_overrides() -> dict:
    """Load router_overrides.json for data-driven strategy→node routing."""
    p = Path(__file__).parent / "router_overrides.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _build_generic_bridge_question(object_name: str) -> str:
    """Create a guide-opening question without using mapping-derived copy."""
    return f"What is one thing about {object_name} that makes you curious right now?"


class PaixuejiState(TypedDict):
    # --- Inputs ---
    age: int
    messages: List[dict]
    content: str
    status: str
    session_id: str
    request_id: str
    config: dict
    client: Any  # genai.Client
    assistant: Any  # PaixuejiAssistant instance

    # --- Context ---
    object_name: str
    correct_answer_count: int

    # --- Dimension Coverage ---
    physical_dimensions: dict      # {dim: {attr: value}}, loaded at session start
    engagement_dimensions: dict    # {dim: [topic_examples]}, loaded at session start
    dimensions_covered: list       # dimension names explored so far
    current_dimension: Optional[str]  # dimension classified for this turn

    # --- Prompts ---
    age_prompt: str

    # --- Flow Control & Computed State ---
    intent_type: Optional[str]   # one of 9 intent categories (chat mode)

    new_object_name: Optional[str]
    detected_object_name: Optional[str]

    response_type: Optional[str]

    # --- Guide State (Multi-turn Navigator/Driver) ---
    guide_phase: Optional[str]   # "active", "hint", "success", "exit"
    guide_status: Optional[str]  # ON_TRACK, DRIFTING, STUCK, COMPLETED
    guide_strategy: Optional[str]  # ADVANCE, PIVOT, SCAFFOLD, COMPLETE
    guide_turn_count: Optional[int]
    scaffold_level: Optional[int]  # 1-4, progressive hint levels (only if SCAFFOLD)
    last_navigation_state: Optional[dict]  # Full Navigator result

    # --- Fun Fact (Grounded) ---
    fun_fact: Optional[str]
    fun_fact_hook: Optional[str]
    fun_fact_question: Optional[str]
    real_facts: Optional[str]

    # --- Output Accumulation ---
    full_response_text: str
    full_question_text: str
    sequence_number: int

    # --- Internal ---
    stream_callback: Any   # Async callback function(chunk: StreamChunk) -> None
    start_time: float
    ttft: Optional[float]  # Time to First Token (seconds)

    # --- Execution Tracing ---
    nodes_executed: List[dict]  # [{"node": str, "time_ms": float, "changes": dict}]


# ============================================================================
# NODE EXECUTION TRACING
# ============================================================================

KEY_STATE_FIELDS = [
    "intent_type", "response_type",
    "guide_phase", "guide_status", "guide_strategy",
    "new_object_name", "scaffold_level", "guide_turn_count",
    "current_dimension",
]


def trace_node(func):
    """
    Decorator to trace node execution for critique reports.

    Captures:
    - Node name (derived from function name)
    - Execution time in milliseconds
    - Key state changes (before vs after)
    - state_before: key fields snapshot before the node ran
    - navigation_result: if returned by the node (e.g. node_guide_navigator)
    """
    @functools.wraps(func)
    async def wrapper(state: PaixuejiState) -> dict:
        start_time = time.time()
        node_name = func.__name__.replace('node_', '')

        # Capture key state before execution (filtered to non-None)
        state_before_raw = {k: state.get(k) for k in KEY_STATE_FIELDS}
        state_before = {k: v for k, v in state_before_raw.items() if v is not None}

        # Execute the actual node function
        result = await func(state)

        # Compute state changes
        state_after = {k: result.get(k, state.get(k)) for k in KEY_STATE_FIELDS}
        changes = {
            k: v for k, v in state_after.items()
            if v != state_before_raw.get(k) and v is not None
        }

        # Build trace entry with enriched fields
        trace_entry = {
            "node": node_name,
            "time_ms": round((time.time() - start_time) * 1000, 1),
            "changes": changes,
            "state_before": state_before,
        }

        # Capture navigation_result if present (from node_guide_navigator)
        if "last_navigation_state" in result and result["last_navigation_state"]:
            trace_entry["navigation_result"] = result["last_navigation_state"]

        # Append to existing traces (immutable merge)
        current_traces = state.get("nodes_executed", []) or []
        result["nodes_executed"] = current_traces + [trace_entry]

        return result

    return wrapper


def trace_router(capture_fields):
    """
    Decorator to trace router (conditional edge) decisions.

    Since routers are not graph nodes, they can't append to state["nodes_executed"]
    directly. Instead, traces are stored on the assistant object (passed by reference)
    and merged into nodes_executed by node_finalize.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(state):
            start_time = time.time()

            # Capture relevant state the router inspects
            state_before = {k: state.get(k) for k in capture_fields if state.get(k) is not None}

            # Also check assistant attributes for fields not in state dict
            assistant = state.get("assistant")
            if assistant:
                for field in capture_fields:
                    if field not in state_before and hasattr(assistant, field):
                        val = getattr(assistant, field)
                        if val is not None:
                            state_before[field] = val

            # Execute the router function
            destination = func(state)

            # Build router trace entry
            trace_entry = {
                "node": f"router:{func.__name__}",
                "time_ms": round((time.time() - start_time) * 1000, 1),
                "changes": {"destination": destination},
                "state_before": state_before,
            }

            # Store on assistant object for later merging in node_finalize
            if assistant:
                if not hasattr(assistant, '_router_traces'):
                    assistant._router_traces = []
                assistant._router_traces.append(trace_entry)

            return destination
        return wrapper
    return decorator


# ============================================================================
# DIMENSION HINT HELPER
# ============================================================================

def _build_dimension_hint(state: "PaixuejiState") -> str:
    """
    Pick one random unexplored dimension and format a soft hint for the
    follow-up question prompt.  Returns "" when no dimensions are available
    (entity not in DB, or all dimensions already covered).
    """
    physical = state.get("physical_dimensions") or {}
    engagement = state.get("engagement_dimensions") or {}
    covered = set(state.get("dimensions_covered") or [])

    remaining_physical = {k: v for k, v in physical.items() if k not in covered}
    remaining_engagement = {k: v for k, v in engagement.items() if k not in covered}

    if not remaining_physical and not remaining_engagement:
        return ""

    all_remaining = list(remaining_physical.keys()) + list(remaining_engagement.keys())
    chosen = random.choice(all_remaining)

    object_name = state.get("object_name", "this object")

    if chosen in remaining_physical:
        attrs = remaining_physical[chosen]
        if not attrs:
            return ""
        lines = [f'[Dimension suggestion: "{chosen}"]']
        lines.append(f"Known facts about {object_name}'s {chosen}:")
        for attr, val in list(attrs.items())[:3]:
            lines.append(f'  - {attr.replace("_", " ")}: "{val}"')
        lines.append("Use these as grounding — ask a question that lets the child discover one naturally.")
        return "\n".join(lines)
    else:
        examples = remaining_engagement[chosen]
        if not examples:
            return ""
        lines = [f'[Dimension suggestion: "{chosen}"]']
        lines.append("Example questions in this style (do not repeat verbatim — generalize a fresh one):")
        for ex in examples[:3]:
            lines.append(f'  - "{ex}"')
        return "\n".join(lines)


# ============================================================================
# TOPIC SWITCH HELPER
# ============================================================================

async def _apply_topic_switch(state: PaixuejiState, new_obj: str) -> dict:
    """
    Update assistant state for a named-object topic switch and return state updates.
    Uses YAML lookup (in-memory, no LLM call needed).
    """
    from paixueji_assistant import ConversationState

    assistant = state["assistant"]
    assistant.object_name = new_obj
    assistant.state = ConversationState.ASKING_QUESTION

    assistant.load_object_context_from_yaml(new_obj)
    assistant.clear_active_theme()

    return {
        "object_name": new_obj,
        "new_object_name": new_obj,
        "response_type": "topic_switch",
    }


# ============================================================================
# NODES
# ============================================================================

@trace_node
async def node_analyze_input(state: PaixuejiState) -> dict:
    """
    Classify child utterance into one of 9 communicative intents.
    Runs dimension classification in parallel for coverage tracking.
    Routes to a dedicated intent node for response generation.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Analyze Input")

    # Build list of dimensions not yet explored (for parallel dim classification)
    all_dims = (
        list((state.get("physical_dimensions") or {}).keys())
        + list((state.get("engagement_dimensions") or {}).keys())
    )
    remaining_dims = [d for d in all_dims if d not in (state.get("dimensions_covered") or [])]

    # Run intent + dimension classification in parallel
    intent_result, current_dim = await asyncio.gather(
        classify_intent(
            assistant=state["assistant"],
            child_answer=state["content"],
            object_name=state["object_name"],
            age=state["age"],
        ),
        classify_dimension(
            assistant=state["assistant"],
            child_answer=state["content"],
            last_assistant_message=state.get("full_response_text", ""),
            object_name=state["object_name"],
            available_dimensions=remaining_dims,
        ),
    )

    intent_type = intent_result["intent_type"]

    # Reset IDK streak when child gives any non-IDK response
    if intent_type != "CLARIFYING_IDK":
        state["assistant"].consecutive_idk_count = 0

    # Update dimension coverage (mutate assistant so next turn sees it)
    new_covered = list(state.get("dimensions_covered") or [])
    if current_dim and current_dim not in new_covered:
        new_covered.append(current_dim)
    state["assistant"].dimensions_covered = new_covered

    logger.info(
        f"[{state['session_id']}] Node: Analyze Input finished in {time.time() - start_time:.3f}s "
        f"| intent={intent_type} | dim={current_dim}"
    )
    return {
        "intent_type": intent_type,
        "new_object_name": intent_result.get("new_object"),
        "current_dimension": current_dim,
        "dimensions_covered": new_covered,
    }


@trace_node
async def node_generate_fun_fact(state: PaixuejiState) -> dict:
    """
    Generate grounded fun facts for the introduction using Google Search.
    Only called on the introduction path.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Generate Fun Fact for '{state['object_name']}'")

    from stream.fun_fact import generate_fun_fact

    fact_data = await generate_fun_fact(
        object_name=state["object_name"],
        age=state["age"] or 6,
        config=state["config"],
        client=state["client"],
    )

    logger.info(f"[{state['session_id']}] Node: Generate Fun Fact finished in {time.time() - start_time:.3f}s")
    return {
        "fun_fact": fact_data.get("fun_fact", ""),
        "fun_fact_hook": fact_data.get("hook", ""),
        "fun_fact_question": fact_data.get("question", ""),
        "real_facts": fact_data.get("real_facts", "")
    }


@trace_node
async def node_generate_intro(state: PaixuejiState) -> dict:
    """
    Stream the introduction response using ask_introduction_question_stream.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Generate Intro for '{state['object_name']}'")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])

    generator = ask_introduction_question_stream(
        messages=messages,
        object_name=state["object_name"],
        age_prompt=state["age_prompt"],
        age=state["age"],
        config=state["config"],
        client=state["client"],
        fun_fact=state.get("fun_fact", ""),
        fun_fact_hook=state.get("fun_fact_hook", ""),
        fun_fact_question=state.get("fun_fact_question", ""),
        real_facts=state.get("real_facts", "")
    )

    full_text, new_seq = await stream_generator_to_callback(
        generator, state, response_type_override="introduction"
    )

    logger.info(f"[{state['session_id']}] Node: Generate Intro finished in {time.time() - start_time:.3f}s")
    return {
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "response_type": "introduction",
        "ttft": state.get("ttft"),
    }


# --- Streaming Helper ---

async def stream_generator_to_callback(generator, state: PaixuejiState, response_type_override=None):
    """
    Helper to consume a generator, emit chunks via callback, and return full text.
    """
    full_text = ""
    token_usage = None

    sequence = state["sequence_number"]
    start_time = time.time()
    first_token_received = False
    first_text_chunk_sent = False

    async for item in generator:
        if not first_token_received:
            ttft = time.time() - state["start_time"]
            logger.info(f"[{state['session_id']}] TTFT: {ttft:.3f}s for {response_type_override or state.get('response_type', 'unknown')}")
            first_token_received = True
            if "ttft" not in state:
                state["ttft"] = ttft

        # Normalize item format
        text_chunk = item[0]
        usage = item[1]
        full_so_far = item[2]

        if usage:
            token_usage = usage

        full_text = full_so_far

        if text_chunk:
            sequence += 1
            if not first_text_chunk_sent:
                chunk_duration = state.get("ttft") or 0.0
                first_text_chunk_sent = True
            else:
                chunk_duration = 0.0
            chunk = StreamChunk(
                response=text_chunk,
                session_finished=(state["status"] == "over"),
                duration=chunk_duration,
                token_usage=None,
                finish=False,
                sequence_number=sequence,
                timestamp=time.time(),
                session_id=state["session_id"],
                request_id=state["request_id"],
                is_stuck=False,
                correct_answer_count=state["correct_answer_count"],
                conversation_complete=False,

                intent_type=state.get("intent_type"),
                new_object_name=state["new_object_name"],
                detected_object_name=state["detected_object_name"],

                response_type=response_type_override or state["response_type"],
            )
            await state["stream_callback"](chunk)

            # Clear one-time fields after first chunk sent
            if state["new_object_name"]:
                state["new_object_name"] = None
            if state["detected_object_name"]:
                state["detected_object_name"] = None

    logger.info(f"[{state['session_id']}] Stream finished in {time.time() - start_time:.3f}s for {response_type_override or state.get('response_type', 'unknown')}")
    return full_text, sequence


# --- Intent Nodes (9 total) ---

@trace_node
async def node_curiosity(state: PaixuejiState) -> dict:
    """Child asks why/what/how — expand gently + suggest one concrete action."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Curiosity")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type="curiosity",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Curiosity finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "curiosity",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_concept_confusion(state: PaixuejiState) -> dict:
    """Child is confused about or disputes a concept the model just introduced — explain, bridge, re-ask."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Concept Confusion")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type="concept_confusion",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Concept Confusion finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "concept_confusion",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_clarifying_idk(state: PaixuejiState) -> dict:
    """Child said IDK. On 1st IDK increment counter; on 2nd+ IDK reveal the answer and reset."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Clarifying IDK")

    if state["assistant"].consecutive_idk_count >= 1:
        # Second IDK — give the answer directly and reset the counter
        state["assistant"].consecutive_idk_count = 0
        intent_type = "give_answer_idk"
    else:
        # First IDK — scaffold hint and increment counter
        state["assistant"].consecutive_idk_count += 1
        intent_type = "clarifying_idk"

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type=intent_type,
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Clarifying IDK finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": intent_type,
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_give_answer_idk(state: PaixuejiState) -> dict:
    """Child said IDK twice — reveal the answer directly and reset the IDK counter."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Give Answer IDK")

    state["assistant"].consecutive_idk_count = 0
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])

    # First call: acceptance + direct answer (no question)
    generator = generate_intent_response_stream(
        intent_type="give_answer_idk",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)

    # Update sequence so second generator picks up where first left off
    state["sequence_number"] = new_seq
    messages_with_response = messages + [{"role": "assistant", "content": full_text_intent}]

    # Second call: follow-up question
    followup_gen = ask_followup_question_stream(
        messages=messages_with_response,
        object_name=state["object_name"],
        age_prompt=state["age_prompt"],
        age=state["age"],
        config=state["config"],
        client=state["client"],
        dimension_hint=_build_dimension_hint(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Give Answer IDK finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "give_answer_idk",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_clarifying_wrong(state: PaixuejiState) -> dict:
    """Child gave wrong/incomplete answer — affirm effort + gently correct."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Clarifying Wrong")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type="clarifying_wrong",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Clarifying Wrong finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "clarifying_wrong",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_clarifying_constraint(state: PaixuejiState) -> dict:
    """Child described a real-world constraint — validate + object-anchored redirect."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Clarifying Constraint")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type="clarifying_constraint",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Clarifying Constraint finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "clarifying_constraint",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_correct_answer(state: PaixuejiState) -> dict:
    """Child directly answered the model's question — confirm + extend with one wow fact."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Correct Answer")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])

    # First call: confirm + wow fact (no question)
    generator = generate_intent_response_stream(
        intent_type="correct_answer",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)
    state["assistant"].increment_correct_answers()

    # Update sequence so second generator picks up where first left off
    state["sequence_number"] = new_seq
    messages_with_response = messages + [{"role": "assistant", "content": full_text_intent}]

    # Second call: followup question
    followup_gen = ask_followup_question_stream(
        messages=messages_with_response,
        object_name=state["object_name"],
        age_prompt=state["age_prompt"],
        age=state["age"],
        config=state["config"],
        client=state["client"],
        dimension_hint=_build_dimension_hint(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Correct Answer finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "correct_answer",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "correct_answer_count": state["assistant"].correct_answer_count,
    }


@trace_node
async def node_informative(state: PaixuejiState) -> dict:
    """Child shares knowledge — give space + social reaction."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Informative")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])

    # First call: genuine celebration reaction (no question)
    generator = generate_intent_response_stream(
        intent_type="informative",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)

    # Update sequence so second generator picks up where first left off
    state["sequence_number"] = new_seq
    messages_with_response = messages + [{"role": "assistant", "content": full_text_intent}]

    # Second call: follow-up question
    followup_gen = ask_followup_question_stream(
        messages=messages_with_response,
        object_name=state["object_name"],
        age_prompt=state["age_prompt"],
        age=state["age"],
        config=state["config"],
        client=state["client"],
        dimension_hint=_build_dimension_hint(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Informative finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "informative",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_play(state: PaixuejiState) -> dict:
    """Child being silly/imaginative — play along + gamify + suggest one action."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Play")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type="play",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Play finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "play",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_emotional(state: PaixuejiState) -> dict:
    """Child expresses feeling — empathize first + gently redirect."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Emotional")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type="emotional",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Emotional finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "emotional",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_avoidance(state: PaixuejiState) -> dict:
    """
    Child refuses or wants to stop.
    - If new_object named → topic switch via generate_topic_switch_response_stream
    - If no new_object → intent response offering to explore something else
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Avoidance")

    new_obj = state.get("new_object_name")
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    extra_updates = {}

    if new_obj:
        switch_updates = await _apply_topic_switch(state, new_obj)
        extra_updates.update(switch_updates)
        generator = generate_topic_switch_response_stream(
            messages=messages,
            previous_object=state["object_name"],
            new_object=new_obj,
            age=state["age"],
            config=state["config"],
            client=state["client"],
        )
    else:
        generator = generate_intent_response_stream(
            intent_type="avoidance",
            messages=messages,
            child_answer=state["content"],
            object_name=state["object_name"],
            age=state["age"],
            age_prompt=state["age_prompt"],
            last_model_response=extract_previous_response(state["messages"]),
            config=state["config"],
            client=state["client"],
        )

    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Avoidance finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "avoidance",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        **extra_updates,
    }


@trace_node
async def node_boundary(state: PaixuejiState) -> dict:
    """Child asks risky action — empathize + deny danger + safe alternative."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Boundary")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type="boundary",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Boundary finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "boundary",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_action(state: PaixuejiState) -> dict:
    """
    Child issues a command or requests a change.
    - If new_object named → topic switch via generate_topic_switch_response_stream
    - If no new_object → intent response executing or redirecting the command
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Action")

    new_obj = state.get("new_object_name")
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    extra_updates = {}

    if new_obj:
        switch_updates = await _apply_topic_switch(state, new_obj)
        extra_updates.update(switch_updates)
        generator = generate_topic_switch_response_stream(
            messages=messages,
            previous_object=state["object_name"],
            new_object=new_obj,
            age=state["age"],
            config=state["config"],
            client=state["client"],
        )
    else:
        generator = generate_intent_response_stream(
            intent_type="action",
            messages=messages,
            child_answer=state["content"],
            object_name=state["object_name"],
            age=state["age"],
            age_prompt=state["age_prompt"],
            last_model_response=extract_previous_response(state["messages"]),
            config=state["config"],
            client=state["client"],
        )

    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Action finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "action",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        **extra_updates,
    }


@trace_node
async def node_social(state: PaixuejiState) -> dict:
    """Child asks about the AI — warm direct answer."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Social")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])

    # First call: warm direct answer (no question — prompt already prohibits it)
    generator = generate_intent_response_stream(
        intent_type="social",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)

    # Update sequence so second generator picks up where first left off
    state["sequence_number"] = new_seq
    messages_with_response = messages + [{"role": "assistant", "content": full_text_intent}]

    # Second call: follow-up question
    followup_gen = ask_followup_question_stream(
        messages=messages_with_response,
        object_name=state["object_name"],
        age_prompt=state["age_prompt"],
        age=state["age"],
        config=state["config"],
        client=state["client"],
        dimension_hint=_build_dimension_hint(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Social finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "social",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


@trace_node
async def node_social_acknowledgment(state: PaixuejiState) -> dict:
    """Child reacts socially ("wow", "oh yeah", "i didn't know that") — brief reaction + pivot forward."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Social Acknowledgment")

    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])

    # First call: brief natural reaction (no question)
    generator = generate_intent_response_stream(
        intent_type="social_acknowledgment",
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)

    # Update sequence so second generator picks up where first left off
    state["sequence_number"] = new_seq
    messages_with_response = messages + [{"role": "assistant", "content": full_text_intent}]

    # Second call: follow-up question
    followup_gen = ask_followup_question_stream(
        messages=messages_with_response,
        object_name=state["object_name"],
        age_prompt=state["age_prompt"],
        age=state["age"],
        config=state["config"],
        client=state["client"],
        dimension_hint=_build_dimension_hint(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Social Acknowledgment finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "social_acknowledgment",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
    }


# --- Guide Nodes (unchanged) ---

@trace_node
async def node_start_guide(state: PaixuejiState):
    """
    Start the IB PYP Guide Phase.
    Present the Bridge Question and initialize multi-turn guide state.
    """
    logger.info(f"[{state['session_id']}] Node: Start Guide")

    assistant = state["assistant"]

    # Initialize multi-turn guide state
    assistant.enter_guide_mode()

    bridge_question = _build_generic_bridge_question(state["object_name"])
    assistant.bridge_question = bridge_question
    key_concept = assistant.key_concept
    theme_name = assistant.ibpyp_theme_name
    object_name = state["object_name"]

    # 3-part combined response (zero extra LLM call — template only for TTFT-optimal delivery)
    confirmation = "Yes, that's right! Great job! 🌟 "
    inquiry_invitation = (
        f"Ooh wait — I just thought of a mystery! "
        f"Let's be explorers together and find out a secret about {object_name}... "
    )
    full_response = confirmation + inquiry_invitation + bridge_question

    # Stream it
    callback = state.get("stream_callback")
    new_seq = state["sequence_number"] + 1
    if callback:
        chunk = StreamChunk(
            response=full_response,
            session_finished=(state["status"] == "over"),
            duration=time.time() - state["start_time"],
            finish=False,
            sequence_number=new_seq,
            timestamp=time.time(),
            session_id=state["session_id"],
            request_id=state["request_id"],
            response_type="question",
            guide_phase="active",
            key_concept=key_concept,
            ibpyp_theme_name=theme_name,
            bridge_question=bridge_question,
            guide_turn_count=0,
            guide_max_turns=assistant.guide_max_turns
        )
        await callback(chunk)

    return {
        "guide_phase": "active",
        "full_question_text": full_response,
        "sequence_number": new_seq
    }


@trace_node
async def node_guide_navigator(state: PaixuejiState):
    """
    Navigator node: Analyze child's response using the Navigator pattern.
    Determines status (ON_TRACK, DRIFTING, RESISTANCE, COMPLETED) and strategy.
    """
    logger.info(f"[{state['session_id']}] Node: Guide Navigator")

    assistant = state["assistant"]
    child_input = state["content"]

    target_theme = {
        "name": assistant.ibpyp_theme_name or "Unknown Theme",
        "description": assistant.ibpyp_theme_reason or ""
    }

    navigator = ThemeNavigator(
        client=state["client"],
        config=state["config"]
    )

    nav_result = await navigator.analyze_turn(
        history=state["messages"],
        user_input=child_input,
        current_topic=state["object_name"],
        target_theme=target_theme,
        age=state["age"],
        key_concept="",
        bridge_question=assistant.bridge_question or "",
        turn_count=assistant.guide_turn_count,
        max_turns=assistant.guide_max_turns,
    )

    # Update assistant state (handles turn count, scaffold level, last_navigation_state)
    assistant.update_navigation_state(nav_result)

    return {
        "guide_status": nav_result.get("status"),
        "guide_strategy": nav_result.get("strategy"),
        "guide_turn_count": assistant.guide_turn_count,
        "last_navigation_state": nav_result
    }


@trace_node
async def node_guide_driver(state: PaixuejiState):
    """
    Driver node: Generate response following the Navigator's instruction.
    Streams the natural language response to the child.
    """
    logger.info(f"[{state['session_id']}] Node: Guide Driver")

    assistant = state["assistant"]
    nav_state = assistant.last_navigation_state

    if not nav_state:
        return {
            "full_response_text": "That's interesting! Tell me more about what you're thinking.",
            "sequence_number": state["sequence_number"] + 1
        }

    driver = ThemeDriver(
        client=state["client"],
        config=state["config"]
    )

    object_name = state["object_name"]
    theme_name = assistant.ibpyp_theme_name or ""

    full_text = ""
    new_seq = state["sequence_number"]

    async for text_chunk, usage, full_so_far in driver.generate_response_stream(
        history=state["messages"],
        nav_plan=nav_state,
        age=state["age"],
        object_name=object_name,
        key_concept="",
        theme_name=theme_name
    ):
        if text_chunk:
            full_text = full_so_far
            new_seq += 1

            callback = state.get("stream_callback")
            if callback:
                chunk = StreamChunk(
                    response=text_chunk,
                    session_finished=(state["status"] == "over"),
                    duration=time.time() - state["start_time"],
                    finish=False,
                    sequence_number=new_seq,
                    timestamp=time.time(),
                    session_id=state["session_id"],
                    request_id=state["request_id"],
                    response_type="guide_response",
                    guide_phase="active",
                    guide_turn_count=assistant.guide_turn_count,
                    guide_max_turns=assistant.guide_max_turns,
                    guide_status=nav_state.get("status"),
                    guide_strategy=nav_state.get("strategy"),
                    scaffold_level=assistant.scaffold_level if nav_state.get("strategy") == "SCAFFOLD" else None,
                    key_concept=assistant.key_concept,
                    ibpyp_theme_name=assistant.ibpyp_theme_name
                )
                await callback(chunk)

    return {
        "full_response_text": full_text,
        "sequence_number": new_seq
    }


@trace_node
async def node_guide_hint(state: PaixuejiState):
    """
    Give the child a helpful hint when max turns are reached.
    Uses LLM to generate a concrete, age-appropriate explanation.
    """
    logger.info(f"[{state['session_id']}] Node: Guide Hint")

    assistant = state["assistant"]
    assistant.give_hint()

    hint_message = await generate_guide_hint(
        object_name=state["object_name"],
        key_concept="",
        key_concept_reason="",
        bridge_question=assistant.bridge_question or "",
        theme_name=assistant.ibpyp_theme_name or "",
        age=state["age"],
        messages=state["messages"],
        config=state["config"],
        client=state["client"]
    )

    callback = state.get("stream_callback")
    new_seq = state["sequence_number"] + 1

    if callback:
        chunk = StreamChunk(
            response=hint_message,
            session_finished=(state["status"] == "over"),
            duration=time.time() - state["start_time"],
            finish=False,
            sequence_number=new_seq,
            timestamp=time.time(),
            session_id=state["session_id"],
            request_id=state["request_id"],
            response_type="guide_hint",
            guide_phase="hint",
            guide_turn_count=assistant.guide_turn_count,
            guide_max_turns=assistant.guide_max_turns,
            key_concept=assistant.key_concept,
            ibpyp_theme_name=assistant.ibpyp_theme_name
        )
        await callback(chunk)

    return {
        "full_response_text": hint_message,
        "sequence_number": new_seq,
        "guide_phase": "hint"
    }


@trace_node
async def node_guide_exit(state: PaixuejiState):
    """
    Graceful exit from guide mode.
    Triggered after 2 consecutive RESISTANCE or after hint with no success.
    """
    logger.info(f"[{state['session_id']}] Node: Guide Exit")

    assistant = state["assistant"]
    assistant.exit_guide_mode()

    exit_message = "That's okay! Let's explore something else. What would you like to learn about next?"

    callback = state.get("stream_callback")
    new_seq = state["sequence_number"] + 1

    if callback:
        chunk = StreamChunk(
            response=exit_message,
            session_finished=(state["status"] == "over"),
            duration=time.time() - state["start_time"],
            finish=False,
            sequence_number=new_seq,
            timestamp=time.time(),
            session_id=state["session_id"],
            request_id=state["request_id"],
            response_type="guide_exit",
            guide_phase="exit"
        )
        await callback(chunk)

    return {
        "full_response_text": exit_message,
        "sequence_number": new_seq,
        "guide_phase": "exit"
    }


@trace_node
async def node_guide_success(state: PaixuejiState):
    """
    Guide Success! Child has articulated understanding of the concept.
    Celebrate their discovery and reset guide state.
    """
    logger.info(f"[{state['session_id']}] Node: Guide Success")

    assistant = state["assistant"]
    object_name = state["object_name"]
    theme_name = assistant.ibpyp_theme_name or "this big idea"

    msg = (
        f"That's wonderful! You found a really interesting idea about {object_name} in {theme_name}! "
        f"You're thinking like a real explorer now!"
    )

    assistant.guide_phase = "success"

    callback = state.get("stream_callback")
    new_seq = state["sequence_number"] + 1
    if callback:
        chunk = StreamChunk(
            response=msg,
            session_finished=(state["status"] == "over"),
            duration=time.time() - state["start_time"],
            finish=False,
            sequence_number=new_seq,
            timestamp=time.time(),
            session_id=state["session_id"],
            request_id=state["request_id"],
            response_type="guide_success",
            guide_phase="success",
            is_guide_success=True,
            key_concept=assistant.key_concept,
            ibpyp_theme_name=assistant.ibpyp_theme_name,
            guide_turn_count=assistant.guide_turn_count
        )
        await callback(chunk)

    return {
        "is_guide_success": True,
        "full_response_text": msg,
        "sequence_number": new_seq,
        "guide_phase": "success"
    }


@trace_node
async def node_finalize(state: PaixuejiState) -> dict:
    """
    Send final chunk and update history.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Finalize")

    full_response = state.get("full_response_text", "")
    if state.get("full_question_text"):
        full_response += " " + state["full_question_text"]

    # Merge router traces into nodes_executed
    assistant = state["assistant"]
    if hasattr(assistant, '_router_traces') and assistant._router_traces:
        node_traces = state.get("nodes_executed", []) or []
        merged = assistant._router_traces + node_traces
        state["nodes_executed"] = merged
        assistant._router_traces = []

    # Theme should stay unset during ordinary chat, but once classification has
    # happened we expose it even if guide mode is not entered.
    guide_phase = state.get("guide_phase") or state["assistant"].guide_phase
    include_theme = bool(guide_phase or state["assistant"].ibpyp_theme_name)

    # Send final chunk
    final_chunk = StreamChunk(
        response=full_response,
        session_finished=(state["status"] == "over"),
        duration=state.get("ttft") or 0.0,
        token_usage=None,
        finish=True,
        sequence_number=state["sequence_number"] + 1,
        timestamp=time.time(),
        session_id=state["session_id"],
        request_id=state["request_id"],
        is_stuck=False,
        correct_answer_count=state.get("correct_answer_count", 0),
        conversation_complete=False,

        intent_type=state.get("intent_type"),
        new_object_name=state.get("new_object_name"),
        detected_object_name=state.get("detected_object_name"),

        response_type=state.get("response_type"),

        # Theme classification fields
        key_concept=state["assistant"].key_concept or None,
        ibpyp_theme_name=state["assistant"].ibpyp_theme_name if include_theme else None,
        theme_classification_reason=state["assistant"].ibpyp_theme_reason if include_theme else None,

        # Guide Phase specific fields
        guide_phase=guide_phase,
        bridge_question=state["assistant"].bridge_question if include_theme else None,
        is_guide_success=state.get("is_guide_success", False),

        # Node execution trace (for critique reports)
        nodes_executed=state.get("nodes_executed", [])
    )
    await state["stream_callback"](final_chunk)

    logger.info(f"[{state['session_id']}] Node: Finalize finished in {time.time() - start_time:.3f}s")
    return {}


@trace_node
@trace_node
async def node_classify_theme(state: PaixuejiState) -> dict:
    """
    4th correct answer threshold reached: classify guide theme from conversation history.
    Guide theme is classified from conversation history, while response text
    stays free of mapping-derived prompt content.
    """
    from theme_classifier import classify_conversation_to_theme

    assistant = state["assistant"]
    logger.info(f"[{state['session_id']}] Node: Classify Theme (guide mode entry)")

    assistant.increment_correct_answers()

    if (
        not assistant.fallback_theme_id
        or not assistant.fallback_theme_name
    ):
        assistant.load_object_context_from_yaml(state["object_name"])

    result = await classify_conversation_to_theme(
        history=state["messages"],
        object_name=state["object_name"],
        age=state["age"] or 6,
        client=state["client"],
        config=state["config"],
    )

    if result:
        assistant.ibpyp_theme = result["theme_id"]
        assistant.ibpyp_theme_name = result["theme_name"]
        assistant.ibpyp_theme_reason = result["reason"]
        logger.info(
            f"[{state['session_id']}] Theme: {result['theme_name']} | "
            f"Concept: {assistant.key_concept}"
        )
    else:
        assistant.apply_fallback_theme()
        logger.warning(
            f"[{state['session_id']}] Conversation theme analysis failed for "
            f"'{state['object_name']}', using fallback theme"
        )

    return {"correct_answer_count": assistant.correct_answer_count}


@trace_node
async def node_chat_complete(state: PaixuejiState) -> dict:
    """
    Chat phase completion: acknowledge and signal that the chat phase is complete.
    Template-based — no LLM call. Assumes the threshold turn already updated the
    correct-answer count and sets chat_phase_complete=True for the frontend modal.
    """
    logger.info(f"[{state['session_id']}] Node: Chat Complete")

    assistant = state["assistant"]

    celebration = (
        "Yes, that's right! Wonderful work — you've been such a great explorer today! 🎉 "
        "You've answered all the questions so well. Now it's time to switch to activities!"
    )

    callback = state.get("stream_callback")
    new_seq = state["sequence_number"] + 1
    if callback:
        chunk = StreamChunk(
            response=celebration,
            session_finished=(state["status"] == "over"),
            duration=time.time() - state["start_time"],
            finish=False,
            sequence_number=new_seq,
            timestamp=time.time(),
            session_id=state["session_id"],
            request_id=state["request_id"],
            response_type="correct_answer",
            correct_answer_count=assistant.correct_answer_count,
            key_concept=assistant.key_concept or None,
            ibpyp_theme_name=assistant.ibpyp_theme_name or None,
            theme_classification_reason=assistant.ibpyp_theme_reason or None,
            chat_phase_complete=True,
        )
        await callback(chunk)

    return {
        "response_type": "correct_answer",
        "full_response_text": celebration,
        "sequence_number": new_seq,
        "correct_answer_count": assistant.correct_answer_count,
    }


# ============================================================================
# GRAPH DEFINITION
# ============================================================================

def build_paixueji_graph():
    workflow = StateGraph(PaixuejiState)

    # --- Core nodes ---
    workflow.add_node("analyze_input", node_analyze_input)
    workflow.add_node("generate_fun_fact", node_generate_fun_fact)
    workflow.add_node("generate_intro", node_generate_intro)

    # --- 13 Intent nodes ---
    workflow.add_node("curiosity", node_curiosity)
    workflow.add_node("concept_confusion", node_concept_confusion)
    workflow.add_node("clarifying_idk", node_clarifying_idk)
    workflow.add_node("give_answer_idk", node_give_answer_idk)
    workflow.add_node("clarifying_wrong", node_clarifying_wrong)
    workflow.add_node("clarifying_constraint", node_clarifying_constraint)
    workflow.add_node("correct_answer", node_correct_answer)
    workflow.add_node("informative", node_informative)
    workflow.add_node("play", node_play)
    workflow.add_node("emotional", node_emotional)
    workflow.add_node("avoidance", node_avoidance)
    workflow.add_node("boundary", node_boundary)
    workflow.add_node("action", node_action)
    workflow.add_node("social", node_social)
    workflow.add_node("social_acknowledgment", node_social_acknowledgment)

    # --- Guide nodes ---
    workflow.add_node("classify_theme", node_classify_theme)
    workflow.add_node("start_guide", node_start_guide)
    workflow.add_node("guide_navigator", node_guide_navigator)
    workflow.add_node("guide_driver", node_guide_driver)
    workflow.add_node("guide_success", node_guide_success)
    workflow.add_node("guide_hint", node_guide_hint)
    workflow.add_node("guide_exit", node_guide_exit)

    workflow.add_node("finalize", node_finalize)

    # --- START router ---
    # Guide phase active/hint → guide_navigator
    # Introduction (response_type == "introduction") → generate_fun_fact
    # Everything else → analyze_input
    @trace_router(["guide_phase", "response_type"])
    def route_from_start(state):
        guide_phase = state.get("guide_phase") or state["assistant"].guide_phase

        if guide_phase == "active":
            return "guide_navigator"

        if guide_phase == "hint":
            return "guide_navigator"

        if state.get("response_type") == "introduction":
            return "generate_fun_fact"

        return "analyze_input"

    workflow.add_conditional_edges(
        START,
        route_from_start,
        {
            "analyze_input": "analyze_input",
            "generate_fun_fact": "generate_fun_fact",
            "guide_navigator": "guide_navigator"
        }
    )

    # Introduction path: fun fact → intro → finalize
    workflow.add_edge("generate_fun_fact", "generate_intro")
    workflow.add_edge("generate_intro", "finalize")

    # Chat path: analyze_input → route_from_analyze_input → one of 9 intent nodes
    @trace_router(["intent_type"])
    def route_from_analyze_input(state):
        intent = state.get("intent_type", "clarifying_idk").lower()
        # Intercept the Nth correct answer to run theme classification
        if (intent == "correct_answer" and
                state["assistant"].correct_answer_count + 1 >= GUIDE_MODE_THRESHOLD):
            return "classify_theme"
        # Intercept repeated IDK — route to dedicated answer-reveal node
        if intent == "clarifying_idk" and state["assistant"].consecutive_idk_count > 0:
            return "give_answer_idk"
        return intent

    workflow.add_conditional_edges(
        "analyze_input",
        route_from_analyze_input,
        {
            "curiosity": "curiosity",
            "concept_confusion": "concept_confusion",
            "clarifying_idk": "clarifying_idk",
            "give_answer_idk": "give_answer_idk",
            "clarifying_wrong": "clarifying_wrong",
            "clarifying_constraint": "clarifying_constraint",
            "correct_answer": "correct_answer",
            "informative": "informative",
            "play": "play",
            "emotional": "emotional",
            "avoidance": "avoidance",
            "boundary": "boundary",
            "action": "action",
            "social": "social",
            "social_acknowledgment": "social_acknowledgment",
            "classify_theme": "classify_theme",
            "chat_complete": "chat_complete",
        }
    )

    workflow.add_node("chat_complete", node_chat_complete)
    workflow.add_edge("chat_complete", "finalize")

    # All 15 intent nodes → finalize
    for intent_node in ["curiosity", "concept_confusion", "clarifying_idk", "give_answer_idk",
                        "clarifying_wrong", "clarifying_constraint", "correct_answer",
                        "informative", "play", "emotional", "avoidance", "boundary",
                        "action", "social", "social_acknowledgment"]:
        workflow.add_edge(intent_node, "finalize")

    # Guide edges
    workflow.add_edge("classify_theme", "chat_complete")
    workflow.add_edge("start_guide", "finalize")  # First turn — present bridge question

    @trace_router(["guide_strategy", "guide_status"])
    def route_after_navigator(state):
        """
        Route based on Navigator's analysis result.

        Routes to:
        - guide_success: Child articulated understanding (COMPLETED)
        - guide_hint: Max turns reached, no hint given yet
        - guide_exit: 2 consecutive RESISTANCE or hint already given at max turns
        - guide_driver: Continue conversation (default)
        """
        assistant = state["assistant"]
        guide_strategy = state.get("guide_strategy")
        guide_status = state.get("guide_status")

        if guide_strategy == "COMPLETE" or guide_status == "COMPLETED":
            logger.info(f"[{state['session_id']}] Guide: Child completed! Routing to success.")
            return "guide_success"

        if assistant.should_give_hint():
            logger.info(f"[{state['session_id']}] Guide: Max turns reached, giving hint.")
            return "guide_hint"

        if assistant.should_exit_guide():
            logger.info(f"[{state['session_id']}] Guide: Exiting (resistance or post-hint timeout).")
            return "guide_exit"

        # Data-driven strategy → node lookup (from router_overrides.json)
        overrides = _load_router_overrides()
        strategy_routes = overrides.get("navigator_strategy_routes", {})
        if guide_strategy in strategy_routes:
            target = strategy_routes[guide_strategy]
            logger.info(f"[{state['session_id']}] Guide: Routing '{guide_strategy}' → '{target}' (from router_overrides.json).")
            return target

        return "guide_driver"

    workflow.add_conditional_edges(
        "guide_navigator",
        route_after_navigator,
        {
            "guide_success": "guide_success",
            "guide_driver": "guide_driver",
            "guide_hint": "guide_hint",
            "guide_exit": "guide_exit"
        }
    )

    workflow.add_edge("guide_driver", "finalize")
    workflow.add_edge("guide_success", "finalize")
    workflow.add_edge("guide_hint", "finalize")
    workflow.add_edge("guide_exit", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()


# Global graph instance
paixueji_graph = build_paixueji_graph()
