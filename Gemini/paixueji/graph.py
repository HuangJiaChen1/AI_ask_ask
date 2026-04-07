import asyncio
import functools
from typing import TypedDict, Annotated, List, Optional, Any
from langgraph.graph import StateGraph, END, START

from google import genai
from loguru import logger
import time

from stream import (
    ask_introduction_question_stream,
    ask_followup_question_stream,
    classify_intent,
    generate_classification_fallback_stream,
    generate_intent_response_stream,
    generate_topic_switch_response_stream,
    extract_previous_response,
    map_response_to_kb_item,
    prepare_messages_for_streaming,
    select_hook_type
)
from schema import StreamChunk
from bridge_context import build_bridge_context
from bridge_debug import build_bridge_debug

GUIDE_MODE_THRESHOLD = 2  # Correct answers required to complete chat mode
_STRUGGLING_INTENTS = {"CLARIFYING_IDK", "CLARIFYING_WRONG"}  # Intents that share the struggle counter
GROUNDED_INTENTS = {
    "curiosity",
    "give_answer_idk",
    "clarifying_wrong",
    "correct_answer",
    "informative",
    "play",
}
OPEN_ENDED_QUESTION_HOOKS = {
    "想象导向",
    "情绪投射",
    "角色代入",
    "选择偏好",
    "创意改造",
    "意图好奇",
}
CONCRETE_QUESTION_HOOKS = {
    "细节发现",
    "经验、生活链接",
}


def route_from_analyze_input(state) -> str:
    """
    Routing logic for analyze_input conditional edges.

    Extracted to module level for testability (LangGraph requires nested decorated
    functions for wiring, but the pure logic should be testable without building the graph).
    """
    if state.get("classification_status") == "failed":
        return "fallback_freeform"

    intent = (state.get("intent_type") or "clarifying_idk").lower()
    # Intercept the Nth correct answer to run theme classification
    if (intent == "correct_answer" and
            state["assistant"].learning_anchor_active and
            state["assistant"].correct_answer_count + 1 >= GUIDE_MODE_THRESHOLD):
        return "classify_theme"
    # Intercept 2nd+ struggle (IDK or wrong) — route to dedicated answer-reveal node
    if intent in ("clarifying_idk", "clarifying_wrong") and state["assistant"].consecutive_struggle_count >= 2:
        return "give_answer_idk"
    return intent

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
    surface_object_name: Optional[str]
    anchor_object_name: Optional[str]
    anchor_status: Optional[str]
    anchor_relation: Optional[str]
    anchor_confidence_band: Optional[str]
    anchor_confirmation_needed: bool
    learning_anchor_active: bool
    bridge_attempt_count: int
    bridge_debug: Optional[dict]
    resolution_debug: Optional[dict]
    correct_answer_count: int
    intro_mode: Optional[str]

    # --- Dimension Coverage ---
    physical_dimensions: dict      # {dim: {attr: value}}, loaded at session start
    engagement_dimensions: dict    # {dim: [seed_text]}, loaded at session start
    used_kb_item: Optional[dict]   # debug-only top-1 KB item mapped from the main response
    kb_mapping_status: Optional[str]  # mapped, none_matched, not_applicable

    # --- Prompts ---
    age_prompt: str

    # --- Flow Control & Computed State ---
    intent_type: Optional[str]   # one of 9 intent categories (chat mode)
    classification_status: Optional[str]
    classification_failure_reason: Optional[str]

    new_object_name: Optional[str]
    detected_object_name: Optional[str]

    response_type: Optional[str]

    # --- Fun Fact (Grounded) ---
    fun_fact: Optional[str]
    fun_fact_hook: Optional[str]
    fun_fact_question: Optional[str]
    real_facts: Optional[str]

    # --- Hook Type Selection ---
    hook_types: dict                       # Loaded from hook_types.json at startup
    selected_hook_type: Optional[str]      # e.g. "情绪投射", "创意改造"
    question_style: Optional[str]          # "open_ended" | "concrete"

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
    "classification_status", "classification_failure_reason",
    "new_object_name",
    "question_style",
    "object_name",
    "surface_object_name",
    "anchor_object_name",
    "anchor_status",
    "anchor_relation",
    "anchor_confidence_band",
    "anchor_confirmation_needed",
    "learning_anchor_active",
    "bridge_attempt_count",
    "resolution_debug",
    "intro_mode",
    "correct_answer_count",
]


def _question_style_for_hook_type(hook_type_name: Optional[str]) -> Optional[str]:
    if hook_type_name in OPEN_ENDED_QUESTION_HOOKS:
        return "open_ended"
    if hook_type_name in CONCRETE_QUESTION_HOOKS:
        return "concrete"
    return None


def _latest_assistant_message(messages: list[dict]) -> Optional[dict]:
    for message in reversed(messages or []):
        if message.get("role") == "assistant":
            return message
    return None


def _previous_question_style(messages: list[dict]) -> Optional[str]:
    latest = _latest_assistant_message(messages)
    if not latest:
        return None

    explicit_style = latest.get("question_style")
    if explicit_style in {"open_ended", "concrete"}:
        return explicit_style

    return _question_style_for_hook_type(latest.get("selected_hook_type"))


def trace_node(func):
    """
    Decorator to trace node execution for critique reports.

    Captures:
    - Node name (derived from function name)
    - Execution time in milliseconds
    - Key state changes (before vs after)
    - state_before: key fields snapshot before the node ran
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
# CHAT KB HELPERS
# ============================================================================

def _build_chat_kb_context(state: "PaixuejiState") -> str:
    """
    Format the full current-object dimension KB for ordinary chat.

    This includes physical attribute/value facts plus engagement seed strings,
    and excludes themes, concepts, and physical topics.
    """
    if state.get("learning_anchor_active") is False:
        return ""

    physical = state.get("physical_dimensions") or {}
    engagement = state.get("engagement_dimensions") or {}

    if not physical and not engagement:
        return ""

    object_name = state.get("object_name", "this object")
    lines = [f"Current-object KB for {object_name}:"]

    for dimension, attrs in physical.items():
        if not attrs:
            continue
        lines.append(f"[physical.{dimension}]")
        for attribute, value in attrs.items():
            lines.append(f"  - {attribute.replace('_', ' ')}: {value}")

    for dimension, seeds in engagement.items():
        if not seeds:
            continue
        lines.append(f"[engagement.{dimension}]")
        for seed_text in seeds:
            lines.append(f"  - {seed_text}")

    return "\n".join(lines)


def _build_intro_kb_context(state: "PaixuejiState") -> str:
    """
    Format only concrete physical facts for the introduction turn.

    Intro should stay close to observable details and avoid imaginative engagement
    seeds that can pull the opening away from the object too early.
    """
    if state.get("learning_anchor_active") is False:
        return ""

    physical = state.get("physical_dimensions") or {}
    if not physical:
        return ""

    object_name = state.get("object_name", "this object")
    lines = [f"Intro grounding for {object_name}:"]

    for dimension, attrs in physical.items():
        if not attrs:
            continue
        lines.append(f"[physical.{dimension}]")
        for attribute, value in attrs.items():
            lines.append(f"  - {attribute.replace('_', ' ')}: {value}")

    return "\n".join(lines)


def _build_bridge_prompt_context(state: "PaixuejiState", attempt_number: int) -> str:
    bridge_context = build_bridge_context(
        surface_object_name=state.get("surface_object_name") or state.get("object_name", ""),
        anchor_object_name=state.get("anchor_object_name") or "",
        relation=state.get("anchor_relation"),
        attempt_number=attempt_number,
    )
    return bridge_context.prompt_context if bridge_context else ""


def _build_post_intro_bridge_context_preview(state: "PaixuejiState", attempt_number: int) -> str:
    context = _build_bridge_prompt_context(state, attempt_number)
    if not context:
        return ""
    lines = context.splitlines()
    lines[0] = "Post-intro bridge context preview."
    return "\n".join(lines)


def _intent_uses_grounding(intent_type: str | None) -> bool:
    """Return whether this ordinary-chat intent explicitly consumes KB context."""
    return (intent_type or "").lower() in GROUNDED_INTENTS


def _grounding_context_for_intent(state: "PaixuejiState", intent_type: str | None) -> str:
    """Only grounded intents should receive KB context in their prompt."""
    if not _intent_uses_grounding(intent_type):
        return ""
    return _build_chat_kb_context(state)


def _resolution_guardrails_for_state(state: "PaixuejiState") -> str:
    if state.get("learning_anchor_active"):
        return ""
    if state.get("anchor_status") != "unresolved":
        return ""
    surface = state.get("surface_object_name") or state.get("object_name", "this object")
    return "\n".join(
        [
            "No supported anchor is active for this turn.",
            f"Stay on the surface object only: {surface}.",
            "Do not introduce facts about related objects implied by the name.",
            "Do not turn words inside the object name into teaching facts.",
            "Prefer observable, use-based, texture, smell, feeling, and preference questions only.",
        ]
    )


def _surface_only_mode_for_state(state: "PaixuejiState") -> bool:
    return bool(state.get("anchor_status") == "unresolved" and not state.get("learning_anchor_active"))


def _surface_object_name_for_state(state: "PaixuejiState") -> str:
    return state.get("surface_object_name") or state.get("object_name", "")


def _mark_kb_mapping_not_applicable(state: "PaixuejiState") -> None:
    """Clear stale mapping data for turns that intentionally skip KB mapping."""
    state["used_kb_item"] = None
    state["kb_mapping_status"] = "not_applicable"


async def _set_used_kb_item(state: "PaixuejiState", response_text: str) -> dict | None:
    """Map a finished ordinary-chat response to one KB item for debug display."""
    used_kb_item = await map_response_to_kb_item(
        assistant=state["assistant"],
        response_text=response_text,
        object_name=state["object_name"],
        physical_dimensions=state.get("physical_dimensions") or {},
        engagement_dimensions=state.get("engagement_dimensions") or {},
    )
    state["used_kb_item"] = used_kb_item
    state["kb_mapping_status"] = "mapped" if used_kb_item else "none_matched"
    return used_kb_item


async def _maybe_set_used_kb_item(
    state: "PaixuejiState",
    intent_type: str | None,
    response_text: str,
) -> dict | None:
    """Run the KB mapper only for intents that explicitly use grounded context."""
    if not _intent_uses_grounding(intent_type):
        _mark_kb_mapping_not_applicable(state)
        return None
    return await _set_used_kb_item(state, response_text)


# ============================================================================
# TOPIC SWITCH HELPER
# ============================================================================

async def _apply_topic_switch(state: PaixuejiState, new_obj: str) -> dict:
    """
    Update assistant state for a named-object topic switch and return state updates.
    Uses YAML lookup (in-memory, no LLM call needed).
    """
    from paixueji_assistant import ConversationState
    from object_resolver import resolve_object_input

    assistant = state["assistant"]
    resolution = resolve_object_input(
        raw_object_name=new_obj,
        age=state["age"] or 6,
        client=state["client"],
        config=state["config"],
    )
    assistant.apply_resolution(resolution)
    if resolution.anchor_status == "anchored_high" and resolution.anchor_object_name:
        assistant.activate_anchor_topic(resolution.anchor_object_name)
        assistant.anchor_status = "anchored_high"

    assistant.state = ConversationState.ASKING_QUESTION
    if assistant.learning_anchor_active:
        assistant.load_dimension_data(assistant.object_name)
    else:
        assistant.physical_dimensions = {}
        assistant.engagement_dimensions = {}

    return {
        "object_name": assistant.object_name,
        "surface_object_name": assistant.surface_object_name,
        "anchor_object_name": assistant.anchor_object_name,
        "anchor_status": assistant.anchor_status,
        "anchor_relation": assistant.anchor_relation,
        "anchor_confidence_band": assistant.anchor_confidence_band,
        "anchor_confirmation_needed": assistant.anchor_confirmation_needed,
        "learning_anchor_active": assistant.learning_anchor_active,
        "new_object_name": new_obj,
        "response_type": "topic_switch",
        "physical_dimensions": assistant.physical_dimensions,
        "engagement_dimensions": assistant.engagement_dimensions,
        "used_kb_item": None,
        "kb_mapping_status": "not_applicable",
    }


# ============================================================================
# NODES
# ============================================================================

@trace_node
async def node_analyze_input(state: PaixuejiState) -> dict:
    """
    Classify child utterance into one of 9 communicative intents.
    Ordinary chat no longer classifies or retires dimensions on the TTFT path.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Analyze Input")

    intent_result = await classify_intent(
        assistant=state["assistant"],
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
    )

    intent_type = intent_result["intent_type"]
    classification_status = intent_result.get("classification_status")
    classification_failure_reason = intent_result.get("classification_failure_reason")

    # Update unified struggle counter (IDK or wrong answer)
    if classification_status == "failed":
        state["assistant"].consecutive_struggle_count = 0
    elif intent_type in _STRUGGLING_INTENTS:
        state["assistant"].consecutive_struggle_count += 1
    else:
        state["assistant"].consecutive_struggle_count = 0

    logger.info(
        f"[{state['session_id']}] Node: Analyze Input finished in {time.time() - start_time:.3f}s "
        f"| intent={intent_type}"
    )
    return {
        "intent_type": intent_type,
        "new_object_name": intent_result.get("new_object"),
        "classification_status": classification_status,
        "classification_failure_reason": classification_failure_reason,
        "used_kb_item": None,
        "kb_mapping_status": None,
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
    bridge_attempt_count = state.get("bridge_attempt_count", 0) or 0
    bridge_context_attempt = max(bridge_attempt_count, 1)

    # Select a hook type for this session using age-weighted sampling
    hook_types = state.get("hook_types") or {}
    if hook_types:
        hook_type_name, hook_type_section = select_hook_type(
            state["age"], state["messages"], hook_types
        )
        logger.info(f"[{state['session_id']}] Hook type selected: {hook_type_name}")
    else:
        hook_type_name = None
        hook_type_section = ""
    question_style = _question_style_for_hook_type(hook_type_name)
    intro_mode = state.get("intro_mode") or "supported"
    intro_bridge_context = "" if intro_mode == "anchor_bridge" else _build_bridge_prompt_context(state, bridge_context_attempt)
    intro_knowledge_context = "" if intro_mode == "anchor_bridge" else _build_intro_kb_context(state)

    generator = ask_introduction_question_stream(
        messages=messages,
        object_name=state["object_name"],
        surface_object_name=state.get("surface_object_name"),
        anchor_object_name=state.get("anchor_object_name"),
        intro_mode=intro_mode,
        age_prompt=state["age_prompt"],
        age=state["age"],
        config=state["config"],
        client=state["client"],
        hook_type_section=hook_type_section,
        knowledge_context=intro_knowledge_context,
        bridge_context=intro_bridge_context,
    )

    full_text, new_seq = await stream_generator_to_callback(
        generator, state, response_type_override="introduction"
    )
    bridge_debug = None
    if state.get("intro_mode") == "anchor_bridge":
        bridge_debug = build_bridge_debug(
            surface_object_name=state.get("surface_object_name"),
            anchor_object_name=state.get("anchor_object_name"),
            anchor_status=state.get("anchor_status"),
            anchor_relation=state.get("anchor_relation"),
            anchor_confidence_band=state.get("anchor_confidence_band"),
            intro_mode=state.get("intro_mode"),
            learning_anchor_active_before=False,
            learning_anchor_active_after=state.get("learning_anchor_active", False),
            bridge_attempt_count_before=bridge_attempt_count,
            bridge_attempt_count_after=bridge_attempt_count,
            decision="intro_bridge",
            decision_reason="pre-anchor intro; bridge attempt budget not consumed",
            response_text=full_text,
            response_type="introduction",
            pre_anchor_handler_entered=False,
            kb_mode="bridge_context_only",
            bridge_context_summary=_build_post_intro_bridge_context_preview(state, bridge_context_attempt),
        )
        state["bridge_debug"] = bridge_debug
    elif state.get("intro_mode") == "unknown_object":
        bridge_debug = build_bridge_debug(
            surface_object_name=state.get("surface_object_name"),
            anchor_object_name=state.get("anchor_object_name"),
            anchor_status=state.get("anchor_status"),
            anchor_relation=state.get("anchor_relation"),
            anchor_confidence_band=state.get("anchor_confidence_band"),
            intro_mode=state.get("intro_mode"),
            learning_anchor_active_before=False,
            learning_anchor_active_after=False,
            bridge_attempt_count_before=0,
            bridge_attempt_count_after=0,
            decision="bridge_not_started",
            decision_reason="resolution_unresolved",
            response_text=full_text,
            response_type="introduction",
            pre_anchor_handler_entered=False,
            kb_mode="surface_only_unresolved",
        )
        state["bridge_debug"] = bridge_debug

    logger.info(f"[{state['session_id']}] Node: Generate Intro finished in {time.time() - start_time:.3f}s")
    return {
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "response_type": "introduction",
        "ttft": state.get("ttft"),
        "selected_hook_type": hook_type_name,
        "question_style": question_style,
        "intro_mode": state.get("intro_mode"),
        "bridge_debug": bridge_debug,
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
                classification_status=state.get("classification_status"),
                classification_failure_reason=state.get("classification_failure_reason"),
                new_object_name=state["new_object_name"],
                detected_object_name=state["detected_object_name"],
                current_object_name=state["object_name"],
                surface_object_name=state.get("surface_object_name"),
                anchor_object_name=state.get("anchor_object_name"),
                anchor_status=state.get("anchor_status"),
                anchor_relation=state.get("anchor_relation"),
                anchor_confidence_band=state.get("anchor_confidence_band"),
                anchor_confirmation_needed=state.get("anchor_confirmation_needed", False),
                learning_anchor_active=state.get("learning_anchor_active", False),
                bridge_attempt_count=state.get("bridge_attempt_count", 0),
                bridge_debug=state.get("bridge_debug"),
                resolution_debug=state.get("resolution_debug"),

                response_type=response_type_override or state["response_type"],
                selected_hook_type=state.get("selected_hook_type"),
                question_style=state.get("question_style"),
                used_kb_item=state.get("used_kb_item"),
                kb_mapping_status=state.get("kb_mapping_status"),
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
        knowledge_context=_grounding_context_for_intent(state, "curiosity"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    await _maybe_set_used_kb_item(state, "curiosity", full_text)
    logger.info(f"[{state['session_id']}] Node: Curiosity finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "curiosity",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
    }


@trace_node
async def node_concept_confusion(state: PaixuejiState) -> dict:
    """Child is confused about or disputes a concept the model just introduced — explain, bridge, re-ask."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Concept Confusion")

    _mark_kb_mapping_not_applicable(state)
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
        knowledge_context=_grounding_context_for_intent(state, "concept_confusion"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Concept Confusion finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "concept_confusion",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
    }


@trace_node
async def node_clarifying_idk(state: PaixuejiState) -> dict:
    """Child said IDK — give a scaffold hint (router guarantees struggle_count < 2)."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Clarifying IDK")

    # No counter mutation here — node_analyze_input handles it upstream.
    _mark_kb_mapping_not_applicable(state)
    question_style = _previous_question_style(state["messages"])
    prompt_intent = "clarifying_open_ended_idk" if question_style == "open_ended" else "clarifying_idk"
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_intent_response_stream(
        intent_type=prompt_intent,
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
        knowledge_context=_grounding_context_for_intent(state, "clarifying_idk"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Clarifying IDK finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "clarifying_idk",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "question_style": question_style if question_style == "open_ended" else None,
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
    }


@trace_node
async def node_fallback_freeform(state: PaixuejiState) -> dict:
    """Classifier failed — respond naturally without intent-specific prompting."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Fallback Freeform")

    _mark_kb_mapping_not_applicable(state)
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    generator = generate_classification_fallback_stream(
        messages=messages,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        age_prompt=state["age_prompt"],
        last_model_response=extract_previous_response(state["messages"]),
        config=state["config"],
        client=state["client"],
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Fallback Freeform finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "fallback_freeform",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
    }


@trace_node
async def node_give_answer_idk(state: PaixuejiState) -> dict:
    """Child said IDK/wrong twice — reveal the answer directly and reset the struggle counter."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Give Answer IDK")

    state["assistant"].consecutive_struggle_count = 0
    question_style = _previous_question_style(state["messages"])
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])

    if question_style == "open_ended":
        _mark_kb_mapping_not_applicable(state)
        generator = generate_intent_response_stream(
            intent_type="give_answer_open_ended_idk",
            messages=messages,
            child_answer=state["content"],
            object_name=state["object_name"],
            age=state["age"],
            age_prompt=state["age_prompt"],
            last_model_response=extract_previous_response(state["messages"]),
            config=state["config"],
            client=state["client"],
            knowledge_context="",
            resolution_guardrails=_resolution_guardrails_for_state(state),
        )
        full_text_intent, new_seq = await stream_generator_to_callback(generator, state)
        logger.info(f"[{state['session_id']}] Node: Give Answer IDK finished in {time.time() - start_time:.3f}s")
        return {
            "response_type": "give_answer_idk",
            "full_response_text": full_text_intent,
            "sequence_number": new_seq,
            "ttft": state.get("ttft"),
            "question_style": "open_ended",
            "used_kb_item": state.get("used_kb_item"),
            "kb_mapping_status": state.get("kb_mapping_status"),
        }

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
        knowledge_context=_grounding_context_for_intent(state, "give_answer_idk"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)
    await _maybe_set_used_kb_item(state, "give_answer_idk", full_text_intent)

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
        knowledge_context=_build_chat_kb_context(state),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Give Answer IDK finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "give_answer_idk",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "question_style": None,
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
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
        knowledge_context=_grounding_context_for_intent(state, "clarifying_wrong"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    await _maybe_set_used_kb_item(state, "clarifying_wrong", full_text)
    logger.info(f"[{state['session_id']}] Node: Clarifying Wrong finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "clarifying_wrong",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
    }


@trace_node
async def node_clarifying_constraint(state: PaixuejiState) -> dict:
    """Child described a real-world constraint — validate + object-anchored redirect."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Clarifying Constraint")

    _mark_kb_mapping_not_applicable(state)
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
        knowledge_context=_grounding_context_for_intent(state, "clarifying_constraint"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Clarifying Constraint finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "clarifying_constraint",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
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
        knowledge_context=_grounding_context_for_intent(state, "correct_answer"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
        surface_only_mode=_surface_only_mode_for_state(state),
        surface_object_name=_surface_object_name_for_state(state),
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)
    await _maybe_set_used_kb_item(state, "correct_answer", full_text_intent)
    if state["assistant"].learning_anchor_active:
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
        knowledge_context=_build_chat_kb_context(state),
        resolution_guardrails=_resolution_guardrails_for_state(state),
        surface_only_mode=_surface_only_mode_for_state(state),
        surface_object_name=_surface_object_name_for_state(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Correct Answer finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "correct_answer",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "correct_answer_count": state["assistant"].correct_answer_count,
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
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
        knowledge_context=_grounding_context_for_intent(state, "informative"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text_intent, new_seq = await stream_generator_to_callback(generator, state)
    await _maybe_set_used_kb_item(state, "informative", full_text_intent)

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
        knowledge_context=_build_chat_kb_context(state),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Informative finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "informative",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
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
        knowledge_context=_grounding_context_for_intent(state, "play"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    await _maybe_set_used_kb_item(state, "play", full_text)
    logger.info(f"[{state['session_id']}] Node: Play finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "play",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
    }


@trace_node
async def node_emotional(state: PaixuejiState) -> dict:
    """Child expresses feeling — empathize first + gently redirect."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Emotional")

    _mark_kb_mapping_not_applicable(state)
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
        knowledge_context=_grounding_context_for_intent(state, "emotional"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Emotional finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "emotional",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
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
        _mark_kb_mapping_not_applicable(state)
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
            knowledge_context=_grounding_context_for_intent(state, "avoidance"),
            resolution_guardrails=_resolution_guardrails_for_state(state),
        )

    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Avoidance finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "avoidance",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
        **extra_updates,
    }


@trace_node
async def node_boundary(state: PaixuejiState) -> dict:
    """Child asks risky action — empathize + deny danger + safe alternative."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Boundary")

    _mark_kb_mapping_not_applicable(state)
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
        knowledge_context=_grounding_context_for_intent(state, "boundary"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Boundary finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "boundary",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
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
        _mark_kb_mapping_not_applicable(state)
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
            knowledge_context=_grounding_context_for_intent(state, "action"),
            resolution_guardrails=_resolution_guardrails_for_state(state),
        )

    full_text, new_seq = await stream_generator_to_callback(generator, state)
    logger.info(f"[{state['session_id']}] Node: Action finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "action",
        "full_response_text": full_text,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
        **extra_updates,
    }


@trace_node
async def node_social(state: PaixuejiState) -> dict:
    """Child asks about the AI — warm direct answer."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Social")

    _mark_kb_mapping_not_applicable(state)
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
        knowledge_context=_grounding_context_for_intent(state, "social"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
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
        knowledge_context=_build_chat_kb_context(state),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Social finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "social",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
    }


@trace_node
async def node_social_acknowledgment(state: PaixuejiState) -> dict:
    """Child reacts socially ("wow", "oh yeah", "i didn't know that") — brief reaction + pivot forward."""
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Social Acknowledgment")

    _mark_kb_mapping_not_applicable(state)
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
        knowledge_context=_grounding_context_for_intent(state, "social_acknowledgment"),
        resolution_guardrails=_resolution_guardrails_for_state(state),
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
        knowledge_context=_build_chat_kb_context(state),
        resolution_guardrails=_resolution_guardrails_for_state(state),
    )
    full_text_question, new_seq = await stream_generator_to_callback(followup_gen, state)

    logger.info(f"[{state['session_id']}] Node: Social Acknowledgment finished in {time.time() - start_time:.3f}s")
    return {
        "response_type": "social_acknowledgment",
        "full_response_text": full_text_intent + " " + full_text_question,
        "sequence_number": new_seq,
        "ttft": state.get("ttft"),
        "used_kb_item": state.get("used_kb_item"),
        "kb_mapping_status": state.get("kb_mapping_status"),
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
    # happened we expose it on later completion/final chunks.
    include_theme = bool(state["assistant"].ibpyp_theme_name)

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
        classification_status=state.get("classification_status"),
        classification_failure_reason=state.get("classification_failure_reason"),
        new_object_name=state.get("new_object_name"),
        detected_object_name=state.get("detected_object_name"),
        current_object_name=state.get("object_name"),
        surface_object_name=state.get("surface_object_name"),
        anchor_object_name=state.get("anchor_object_name"),
        anchor_status=state.get("anchor_status"),
        anchor_relation=state.get("anchor_relation"),
        anchor_confidence_band=state.get("anchor_confidence_band"),
        anchor_confirmation_needed=state.get("anchor_confirmation_needed", False),
        learning_anchor_active=state.get("learning_anchor_active", False),
        bridge_attempt_count=state.get("bridge_attempt_count", 0),
        bridge_debug=state.get("bridge_debug"),
        resolution_debug=state.get("resolution_debug"),

        response_type=state.get("response_type"),

        # Theme classification fields
        key_concept=state["assistant"].key_concept or None,
        ibpyp_theme_name=state["assistant"].ibpyp_theme_name if include_theme else None,
        theme_classification_reason=state["assistant"].ibpyp_theme_reason if include_theme else None,

        # Node execution trace (for critique reports)
        nodes_executed=state.get("nodes_executed", []),

        # Hook type (set on introduction turns only)
        selected_hook_type=state.get("selected_hook_type"),
        question_style=state.get("question_style"),
        used_kb_item=state.get("used_kb_item"),
        kb_mapping_status=state.get("kb_mapping_status"),
    )
    await state["stream_callback"](final_chunk)

    logger.info(f"[{state['session_id']}] Node: Finalize finished in {time.time() - start_time:.3f}s")
    return {}


@trace_node
@trace_node
async def node_classify_theme(state: PaixuejiState) -> dict:
    """
    Threshold correct answer reached: classify guide theme from conversation history.
    Guide theme is classified from conversation history, while response text
    stays free of mapping-derived prompt content.
    """
    from theme_classifier import classify_conversation_to_theme

    assistant = state["assistant"]
    logger.info(f"[{state['session_id']}] Node: Classify Theme (guide mode entry)")

    if assistant.learning_anchor_active:
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
            current_object_name=state.get("object_name"),
            surface_object_name=state.get("surface_object_name"),
            anchor_object_name=state.get("anchor_object_name"),
            anchor_status=state.get("anchor_status"),
            anchor_relation=state.get("anchor_relation"),
            anchor_confidence_band=state.get("anchor_confidence_band"),
            anchor_confirmation_needed=state.get("anchor_confirmation_needed", False),
            learning_anchor_active=state.get("learning_anchor_active", False),
            bridge_attempt_count=state.get("bridge_attempt_count", 0),
            resolution_debug=state.get("resolution_debug"),
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
    workflow.add_node("generate_intro", node_generate_intro)

    # --- 13 Intent nodes ---
    workflow.add_node("curiosity", node_curiosity)
    workflow.add_node("concept_confusion", node_concept_confusion)
    workflow.add_node("clarifying_idk", node_clarifying_idk)
    workflow.add_node("fallback_freeform", node_fallback_freeform)
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

    workflow.add_node("classify_theme", node_classify_theme)

    workflow.add_node("finalize", node_finalize)

    # --- START router ---
    # Introduction (response_type == "introduction") → generate_intro
    # Everything else → analyze_input
    @trace_router(["response_type"])
    def route_from_start(state):
        if state.get("response_type") == "introduction":
            return "generate_intro"

        return "analyze_input"

    workflow.add_conditional_edges(
        START,
        route_from_start,
        {
            "analyze_input": "analyze_input",
            "generate_intro": "generate_intro",
        }
    )

    # Introduction path: intro → finalize
    workflow.add_edge("generate_intro", "finalize")

    # Chat path: analyze_input → route_from_analyze_input → one of 9 intent nodes
    # The module-level route_from_analyze_input holds the pure logic; wrap it with
    # trace_router here so the graph can observe routing decisions.
    _traced_route_from_analyze_input = trace_router(["intent_type", "classification_status"])(route_from_analyze_input)

    workflow.add_conditional_edges(
        "analyze_input",
        _traced_route_from_analyze_input,
        {
            "curiosity": "curiosity",
            "concept_confusion": "concept_confusion",
            "clarifying_idk": "clarifying_idk",
            "fallback_freeform": "fallback_freeform",
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
    for intent_node in ["curiosity", "concept_confusion", "clarifying_idk", "fallback_freeform", "give_answer_idk",
                        "clarifying_wrong", "clarifying_constraint", "correct_answer",
                        "informative", "play", "emotional", "avoidance", "boundary",
                        "action", "social", "social_acknowledgment"]:
        workflow.add_edge(intent_node, "finalize")

    workflow.add_edge("classify_theme", "chat_complete")
    workflow.add_edge("finalize", END)

    return workflow.compile()


# Global graph instance
paixueji_graph = build_paixueji_graph()
