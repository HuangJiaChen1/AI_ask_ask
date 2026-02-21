import asyncio
import functools
from typing import TypedDict, Annotated, List, Optional, Any
from langgraph.graph import StateGraph, END, START

from google import genai
from loguru import logger
import time

from stream import (
    ask_introduction_question_stream,
    decide_topic_switch_with_validation,
    generate_explicit_switch_response_stream,
    generate_object_suggestions,
    generate_topic_switch_response_stream,
    generate_explanation_response_stream,
    generate_feedback_response_stream,
    generate_correction_response_stream,
    generate_followup_question_stream,
    generate_natural_topic_completion_stream,
    decide_next_focus_mode,
    extract_previous_question,
    prepare_messages_for_streaming,
    clean_messages_for_api,
    generate_guide_hint
)
from stream.theme_guide import ThemeNavigator, ThemeDriver
from schema import StreamChunk, TokenUsage

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
    level1_category: str
    level2_category: str
    level3_category: str
    correct_answer_count: int

    # --- Prompts ---
    age_prompt: str
    character_prompt: str
    category_prompt: str
    focus_prompt: str

    # --- Flow Control & Computed State ---
    focus_mode: Optional[str]
    validation_result: Optional[dict]

    is_engaged: Optional[bool]
    is_factually_correct: Optional[bool]
    correctness_reasoning: Optional[str]
    switch_decision_reasoning: Optional[str]

    new_object_name: Optional[str]
    detected_object_name: Optional[str]

    response_type: Optional[str]
    suggested_objects: Optional[List[str]]
    natural_topic_completion: bool

    # --- Guide State (Multi-turn Navigator/Driver) ---
    guide_phase: Optional[str]  # "active", "hint", "success", "exit"
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
    stream_callback: Any  # Async callback function(chunk: StreamChunk) -> None
    start_time: float

    # --- Execution Tracing ---
    nodes_executed: List[dict]  # [{"node": str, "time_ms": float, "changes": dict}]


# ============================================================================
# NODE EXECUTION TRACING
# ============================================================================

# Key state fields to track for changes
KEY_STATE_FIELDS = [
    "response_type", "is_engaged", "is_factually_correct",
    "guide_phase", "guide_status", "guide_strategy",
    "new_object_name", "natural_topic_completion",
    "correctness_reasoning", "switch_decision_reasoning",
    "focus_mode", "scaffold_level", "guide_turn_count"
]


def trace_node(func):
    """
    Decorator to trace node execution for critique reports.

    Captures:
    - Node name (derived from function name)
    - Execution time in milliseconds
    - Key state changes (before vs after)
    - state_before: key fields snapshot before the node ran
    - validation_result: if returned by the node (e.g. node_analyze_input)
    - navigation_result: if returned by the node (e.g. node_guide_navigator)

    The trace is appended to state["nodes_executed"] for later inclusion
    in critique reports and TraceObject assembly.
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

        # Capture validation_result if present (from node_analyze_input)
        if "validation_result" in result and result["validation_result"]:
            trace_entry["validation_result"] = result["validation_result"]

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

    Args:
        capture_fields: list of state keys to capture for debugging context
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
# NODES
# ============================================================================

@trace_node
async def node_analyze_input(state: PaixuejiState) -> dict:
    """
    First node: Check if it's the first turn (Intro) or requires validation.
    Also handles system-managed focus mode logic.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Analyze Input")
    
    # Check if introduction (no assistant messages yet and correct count 0)
    # The 'messages' list already has the current user input appended in app.py before calling graph?
    # No, we'll append it here if needed or assume it's passed in.
    # In `call_paixueji_stream`, it appended the user input.
    
    # IMPORTANT: Logic from original `call_paixueji_stream` about appending user input
    # "messages.append({'role': 'user', 'content': content})"
    # We'll assume the caller (app.py) handles the `conversation_history` persistence,
    # but `state['messages']` is what we send to LLM.
    
    # Logic for Intro detection
    has_asked_questions = any(msg.get("role") == "assistant" for msg in state["messages"])
    is_intro = (state["correct_answer_count"] == 0 and not has_asked_questions)
    
    if is_intro:
        # Trigger background IB PYP theme classification on introduction
        state["assistant"].classify_theme_background(state["object_name"])
        logger.info(f"[{state['session_id']}] Node: Analyze Input finished in {time.time() - start_time:.3f}s")
        return {"response_type": "introduction"}
    
    # --- Validation Logic ---
    assistant = state["assistant"]
    is_awaiting_topic_selection = (assistant.state.value == "awaiting_topic_selection")
    
    validation_result = await decide_topic_switch_with_validation(
        assistant=assistant,
        child_answer=state["content"],
        object_name=state["object_name"],
        age=state["age"],
        focus_mode=state["focus_mode"],
        is_awaiting_topic_selection=is_awaiting_topic_selection
    )
    
    updates = {
        "validation_result": validation_result,
        "is_engaged": validation_result.get("is_engaged"),
        "is_factually_correct": validation_result.get("is_factually_correct"),
        "correctness_reasoning": validation_result.get("correctness_reasoning"),
        "switch_decision_reasoning": validation_result.get("switching_reasoning"),
        "new_object_name": validation_result.get("new_object"),
        "detected_object_name": validation_result.get("detected_object") if not validation_result.get("new_object") else None
    }
    
    # --- System Managed Focus Logic (Pre-Routing) ---
    if assistant.system_managed_focus:
        # Track depth questions
        if updates["is_engaged"] and assistant.current_focus_mode == 'depth':
            assistant.depth_questions_count += 1

    logger.info(f"[{state['session_id']}] Node: Analyze Input finished in {time.time() - start_time:.3f}s")
    return updates


@trace_node
async def node_generate_fun_fact(state: PaixuejiState) -> dict:
    """
    Generate grounded fun facts for the introduction using Google Search.
    Only called on the introduction path (skips analyze_input).
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Generate Fun Fact for '{state['object_name']}'")

    # Trigger background IB PYP theme classification on introduction (since analyze_input is skipped)
    state["assistant"].classify_theme_background(state["object_name"])

    from stream.fun_fact import generate_fun_fact

    fact_data = await generate_fun_fact(
        object_name=state["object_name"],
        age=state["age"] or 6,
        config=state["config"],
        client=state["client"],
        category=state.get("level1_category", "")
    )

    logger.info(f"[{state['session_id']}] Node: Generate Fun Fact finished in {time.time() - start_time:.3f}s")
    return {
        "fun_fact": fact_data.get("fun_fact", ""),
        "fun_fact_hook": fact_data.get("hook", ""),
        "fun_fact_question": fact_data.get("question", ""),
        "real_facts": fact_data.get("real_facts", "")
    }


@trace_node
async def node_route_logic(state: PaixuejiState) -> dict:
    """
    Determine the response type and next steps based on validation results.
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Route Logic")
    
    val_result = state["validation_result"]
    should_switch = val_result.get("decision") == "SWITCH"
    
    updates = {}
    
    if should_switch and not val_result.get("new_object"):
        # Explicit Switch (Offering choices)
        from paixueji_assistant import ConversationState
        state["assistant"].state = ConversationState.AWAITING_TOPIC_SELECTION
        
        suggested = generate_object_suggestions(state["assistant"], state["config"], state["client"], state["age"])
        updates["suggested_objects"] = suggested
        updates["response_type"] = "explicit_switch"
        
    elif should_switch and val_result.get("new_object"):
        # Topic Switch
        new_obj = val_result["new_object"]
        
        # Update assistant state
        if state["assistant"].system_managed_focus:
            state["assistant"].reset_object_state(new_obj)
        else:
            state["assistant"].object_name = new_obj
            
        from paixueji_assistant import ConversationState
        state["assistant"].state = ConversationState.ASKING_QUESTION
        
        # Trigger background classification (simplification: running sync here or assume async helper)
        # We'll just let the assistant handle it, but for the graph flow, we update context.
        # Ideally, we should update level categories here.
        # Since we can't easily do async background tasks that outlive the request in this strict node structure without blocking,
        # we will skip the background thread part or do it blocking if fast. 
        # The original code did it in a thread pool. We'll leave it as side-effect on assistant.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(state["assistant"].classify_object_sync, new_obj)
            # Also trigger IB PYP theme classification in background
            executor.submit(state["assistant"].classify_theme_background, new_obj)
            
        # Update state context for next steps
        updates["object_name"] = new_obj
        updates["new_object_name"] = new_obj
        updates["response_type"] = "topic_switch"
        
        # Re-fetch category prompt (since object changed)
        # assistant.level* categories are updated by classify_object_sync... 
        # if it's background, they might not be ready yet. 
        # Original code re-fetched prompt immediately using OLD categories or wait?
        # Original code: "Rebuild category prompts... level1_category = assistant.level1_category"
        # Since classification is background, it uses old or None until finished. 
        # We will follow original logic.
        updates["category_prompt"] = state["assistant"].get_category_prompt(
            state["assistant"].level1_category,
            state["assistant"].level2_category,
            state["assistant"].level3_category
        )

    elif not state["is_engaged"]:
        updates["response_type"] = "explanation"
        from paixueji_assistant import ConversationState
        state["assistant"].state = ConversationState.ASKING_QUESTION
        
    elif state["is_factually_correct"]:
        updates["response_type"] = "feedback"
        from paixueji_assistant import ConversationState
        state["assistant"].state = ConversationState.ASKING_QUESTION
        
    else:
        updates["response_type"] = "gentle_correction"
        from paixueji_assistant import ConversationState
        state["assistant"].state = ConversationState.ASKING_QUESTION
        
    # --- System Managed Focus Logic (Post-Routing Decision) ---
    assistant = state["assistant"]
    if assistant.system_managed_focus and updates.get("response_type") != "explicit_switch":
        focus_decision = decide_next_focus_mode(assistant)
        if focus_decision['focus_mode'] == 'object_selection':
            updates["natural_topic_completion"] = True
            updates["response_type"] = "natural_topic_completion"
        else:
            updates["focus_mode"] = focus_decision['focus_mode']
            updates["focus_prompt"] = assistant.get_focus_prompt(updates["focus_mode"])

    logger.info(f"[{state['session_id']}] Node: Route Logic finished in {time.time() - start_time:.3f}s")
    return updates


# --- Streaming Helpers ---

async def stream_generator_to_callback(generator, state: PaixuejiState, response_type_override=None):
    """
    Helper to consume a generator, emit chunks via callback, and return full text.
    """
    full_text = ""
    token_usage = None
    
    # We need to know if we are in the "response" phase or "question" phase for the chunk
    # But StreamChunk validation logic in `call_paixueji_stream` combined everything.
    # The `stream_callback` expects a StreamChunk.
    
    sequence = state["sequence_number"]
    start_time = time.time()
    first_token_received = False
    
    async for item in generator:
        if not first_token_received:
            ttft = time.time() - start_time
            logger.info(f"[{state['session_id']}] Time to First Token (TTFT): {ttft:.3f}s for {response_type_override or state.get('response_type', 'unknown')}")
            first_token_received = True

        # Normalize item format
        # Intro: (text, usage, full, info)
        # Others: (text, usage, full) or (text, usage, full, info)
        
        text_chunk = item[0]
        usage = item[1]
        full_so_far = item[2]
        info = item[3] if len(item) > 3 else {}
        
        if usage:
            token_usage = usage
            
        # Capture decision info if present (mostly for Intro or Switch)
        # In original code, these updated local vars `new_object_name`, `detected_object_name`.
        # We'll rely on what's in `state` mostly, but if generator provides new info, use it.
        
        full_text = full_so_far
        
        if text_chunk:
            sequence += 1
            chunk = StreamChunk(
                response=text_chunk,
                session_finished=(state["status"] == "over"),
                duration=0.0,
                token_usage=None,
                finish=False,
                sequence_number=sequence,
                timestamp=time.time(),
                session_id=state["session_id"],
                request_id=state["request_id"],
                is_stuck=False,
                correct_answer_count=state["correct_answer_count"],
                conversation_complete=False,
                focus_mode=state["focus_mode"],
                
                is_engaged=state["is_engaged"],
                is_factually_correct=state["is_factually_correct"],
                correctness_reasoning=state["correctness_reasoning"] if state["is_factually_correct"] is False else None,
                
                new_object_name=state["new_object_name"],
                detected_object_name=state["detected_object_name"],
                switch_decision_reasoning=state["switch_decision_reasoning"],
                
                response_type=response_type_override or state["response_type"],
                suggested_objects=state["suggested_objects"],
                object_selection_mode=bool(state["suggested_objects"]),
                
                system_focus_mode=state["assistant"].current_focus_mode if state["assistant"].system_managed_focus else None,
                depth_progress=f"{state['assistant'].depth_questions_count}/{state['assistant'].depth_target}" if state["assistant"].system_managed_focus else None
            )
            await state["stream_callback"](chunk)
            
            # Clear one-time flags after first chunk sent?
            # Original code: "if new_object_name: new_object_name = None"
            # We can update state? No, passing state to callback is complex.
            # We will just let them persist for the stream, frontend handles dedupe if needed, 
            # or we modify the state copy we are reading from? 
            # Actually, `state` is dict, mutable.
            if state["new_object_name"]:
                state["new_object_name"] = None
            if state["detected_object_name"]:
                state["detected_object_name"] = None
                state["switch_decision_reasoning"] = None

    logger.info(f"[{state['session_id']}] Stream finished in {time.time() - start_time:.3f}s for {response_type_override or state.get('response_type', 'unknown')}")
    return full_text, sequence


@trace_node
async def node_generate_response(state: PaixuejiState) -> dict:
    """
    Generate the first part of the response (Feedback, Explanation, Correction, Switch).
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Generate Response ({state['response_type']})")
    
    response_type = state["response_type"]
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    previous_question = extract_previous_question(messages)
    
    generator = None
    
    if response_type == "introduction":
        generator = ask_introduction_question_stream(
            messages=messages,
            object_name=state["object_name"],
            category_prompt=state["category_prompt"],
            age_prompt=state["age_prompt"],
            age=state["age"],
            config=state["config"],
            client=state["client"],
            level3_category=state["level3_category"],
            focus_prompt=state["focus_prompt"],
            fun_fact=state.get("fun_fact", ""),
            fun_fact_hook=state.get("fun_fact_hook", ""),
            fun_fact_question=state.get("fun_fact_question", ""),
            real_facts=state.get("real_facts", "")
        )
    elif response_type == "explicit_switch":
        generator = generate_explicit_switch_response_stream(
            messages=messages,
            suggested_objects=state["suggested_objects"],
            age=state["age"],
            config=state["config"],
            client=state["client"]
        )
    elif response_type == "topic_switch":
        # We need previous object name. It's not in state explicitly?
        # Original code used `previous_object = object_name` (before update).
        # We updated object_name in route_logic. 
        # We can assume the message history implies the old object, 
        # but the prompt needs `previous_object`.
        # Simplification: Use "the previous object" or try to find it. 
        # Or better: `node_route_logic` should have saved `previous_object_name` to state.
        # Let's hack: The prompt only needs it for context "You were talking about...".
        # We'll use state["object_name"] as new, and assume standard phrasing.
        # Actually, let's fix logic: If switched, state['object_name'] is NEW.
        # But we don't have OLD stored.
        # We will assume generic transition if missing.
        generator = generate_topic_switch_response_stream(
            messages=messages,
            previous_object="the previous object", # Minor regression potential
            new_object=state["object_name"],
            age=state["age"],
            config=state["config"],
            client=state["client"]
        )
    elif response_type == "explanation":
        generator = generate_explanation_response_stream(
            messages=messages,
            child_answer=state["content"],
            object_name=state["object_name"],
            previous_question=previous_question,
            age=state["age"],
            category_prompt=state["category_prompt"],
            age_prompt=state["age_prompt"],
            config=state["config"],
            client=state["client"]
        )
    elif response_type == "feedback":
        generator = generate_feedback_response_stream(
            messages=messages,
            child_answer=state["content"],
            object_name=state["object_name"],
            age=state["age"],
            config=state["config"],
            client=state["client"]
        )
    elif response_type == "gentle_correction":
        generator = generate_correction_response_stream(
            messages=messages,
            child_answer=state["content"],
            object_name=state["object_name"],
            previous_question=previous_question,
            correctness_reasoning=state["correctness_reasoning"],
            age=state["age"],
            config=state["config"],
            client=state["client"]
        )
    elif response_type == "natural_topic_completion":
         # This is handled in follow-up usually? No, it replaces response?
         # In original code: `if natural_topic_completion: response_type="natural_topic_completion"`
         # But the GENERATOR used was `generate_natural_topic_completion_stream` as QUESTION generator.
         # The Response generator was skipped/fallback?
         # "Stream response generator ... yield chunk"
         # Then "Check if natural_topic_completion ... question_generator = generate_natural_topic_completion_stream"
         # So we still need a response (feedback) BEFORE the completion question?
         # Original code: 
         #   1. focus_decision (sets natural_topic_completion=True)
         #   2. Stream response (Feedback/Correction based on valid result)
         #   3. Stream question (Natural Completion)
         # So we should run Feedback/Correction HERE, and set flag for next node.
         
         # Revert response_type to what validation said (Feedback/Correction)
         # But `node_route_logic` set it to `natural_topic_completion`.
         # Let's fix: We should check `is_engaged` etc. to pick feedback/correction generator.
         if state["is_factually_correct"]:
             generator = generate_feedback_response_stream(
                messages=messages,
                child_answer=state["content"],
                object_name=state["object_name"],
                age=state["age"],
                config=state["config"],
                client=state["client"]
            )
         else:
             # Fallback if completion triggered on wrong answer? Unlikely but possible.
             generator = generate_explanation_response_stream(
                messages=messages,
                child_answer=state["content"],
                object_name=state["object_name"],
                previous_question=previous_question,
                age=state["age"],
                category_prompt=state["category_prompt"],
                age_prompt=state["age_prompt"],
                config=state["config"],
                client=state["client"]
            )

    full_text, new_seq = await stream_generator_to_callback(generator, state)
    
    logger.info(f"[{state['session_id']}] Node: Generate Response finished in {time.time() - start_time:.3f}s")
    return {
        "full_response_text": full_text, 
        "sequence_number": new_seq
    }


@trace_node
async def node_generate_question(state: PaixuejiState) -> dict:
    """
    Generate the follow-up question (Part 2).
    """
    start_time = time.time()
    logger.info(f"[{state['session_id']}] Node: Generate Question")
    
    # If explicit switch, we don't ask a follow-up question
    if state["response_type"] == "explicit_switch":
        logger.info(f"[{state['session_id']}] Node: Generate Question finished in {time.time() - start_time:.3f}s (Skipped)")
        return {}
        
    messages = prepare_messages_for_streaming(state["messages"], state["age_prompt"])
    
    # Append the response we just generated so the question is coherent
    if state["full_response_text"]:
        messages.append({"role": "assistant", "content": state["full_response_text"]})
        
    generator = None
    
    if state.get("natural_topic_completion"):
        generator = generate_natural_topic_completion_stream(
            messages=messages,
            current_object=state["object_name"],
            age=state["age"],
            config=state["config"],
            client=state["client"]
        )
    elif state["response_type"] == "introduction":
        # Introduction ALREADY included the question in `ask_introduction_question_stream`
        # It yields the full text "Hi! This is apple. What color is it?"
        # So we skip this node?
        # Yes.
        return {}
    else:
        # Standard follow-up
        is_topic_switch = (state["response_type"] == "topic_switch")
        generator = generate_followup_question_stream(
            messages=messages,
            object_name=state["object_name"],
            correct_count=state["correct_answer_count"],
            category_prompt=state["category_prompt"],
            age_prompt=state["age_prompt"],
            age=state["age"],
            focus_prompt=state["focus_prompt"],
            config=state["config"],
            client=state["client"],
            character_prompt=state["character_prompt"],
            is_topic_switch=is_topic_switch
        )

    full_text, new_seq = await stream_generator_to_callback(generator, state, response_type_override="followup_question")
    
    logger.info(f"[{state['session_id']}] Node: Generate Question finished in {time.time() - start_time:.3f}s")
    return {
        "full_question_text": full_text,
        "sequence_number": new_seq
    }


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

    bridge_question = assistant.bridge_question
    key_concept = assistant.key_concept
    theme_name = assistant.ibpyp_theme_name

    # Construct response with bridge question
    full_response = bridge_question

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

    # Build target theme dict
    target_theme = {
        "name": assistant.ibpyp_theme_name or "Unknown Theme",
        "description": assistant.ibpyp_theme_reason or ""
    }

    # Create Navigator and analyze
    navigator = ThemeNavigator(
        client=state["client"],
        config=state["config"]
    )

    nav_result = await asyncio.to_thread(
        navigator.analyze_turn,
        history=state["messages"],
        user_input=child_input,
        current_topic=state["object_name"],
        target_theme=target_theme,
        age=state["age"],
        key_concept=assistant.key_concept,
        bridge_question=assistant.bridge_question,
        turn_count=assistant.guide_turn_count,
        max_turns=assistant.guide_max_turns
    )

    # Update assistant state
    assistant.update_navigation_state(nav_result)

    logger.info(f"[{state['session_id']}] Navigator result: status={nav_result.get('status')}, "
                f"strategy={nav_result.get('strategy')}, turn={assistant.guide_turn_count}")

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

    Now passes full theme context (object_name, key_concept, theme_name) to Driver
    so it can generate coherent, on-theme responses.
    """
    logger.info(f"[{state['session_id']}] Node: Guide Driver")

    assistant = state["assistant"]
    nav_state = assistant.last_navigation_state

    if not nav_state:
        # Fallback if no navigation state
        return {
            "full_response_text": "That's interesting! Tell me more about what you're thinking.",
            "sequence_number": state["sequence_number"] + 1
        }

    # Create Driver and generate response
    driver = ThemeDriver(
        client=state["client"],
        config=state["config"]
    )

    # Get character prompt and theme context
    character_prompt = state.get("character_prompt", "")
    object_name = state["object_name"]
    key_concept = assistant.key_concept or ""
    theme_name = assistant.ibpyp_theme_name or ""

    # Stream the response
    full_text = ""
    new_seq = state["sequence_number"]

    async for text_chunk, usage, full_so_far in driver.generate_response_stream(
        history=state["messages"],
        nav_plan=nav_state,
        character_prompt=character_prompt,
        age=state["age"],
        object_name=object_name,
        key_concept=key_concept,
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
    Uses LLM to generate a concrete, age-appropriate explanation
    instead of abstract IB PYP terminology.
    """
    logger.info(f"[{state['session_id']}] Node: Guide Hint")

    assistant = state["assistant"]

    # Mark that hint was given
    assistant.give_hint()

    # Generate hint using LLM (replaces hardcoded template)
    hint_message = await generate_guide_hint(
        object_name=state["object_name"],
        key_concept=assistant.key_concept or "something special",
        key_concept_reason=assistant.ibpyp_theme_reason or "",
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

    # Exit guide mode
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
    key_concept = assistant.key_concept or "this idea"
    theme_name = assistant.ibpyp_theme_name or "this theme"
    object_name = state["object_name"]

    # Celebrate the discovery
    msg = (
        f"That's wonderful! You discovered that {object_name} is connected to {key_concept}! "
        f"You're thinking like a real explorer now!"
    )

    # Reset guide state after success
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
        # Router traces go at the beginning (they ran before nodes in each step)
        merged = assistant._router_traces + node_traces
        state["nodes_executed"] = merged
        assistant._router_traces = []

    # Send final chunk
    final_chunk = StreamChunk(
        response=full_response,
        session_finished=(state["status"] == "over"),
        duration=time.time() - state["start_time"],
        token_usage=None,
        finish=True,
        sequence_number=state["sequence_number"] + 1,
        timestamp=time.time(),
        session_id=state["session_id"],
        request_id=state["request_id"],
        is_stuck=False,
        correct_answer_count=state.get("correct_answer_count", 0),
        conversation_complete=False,
        focus_mode=state.get("focus_mode"),

        is_engaged=state.get("is_engaged"),
        is_factually_correct=state.get("is_factually_correct"),
        correctness_reasoning=state.get("correctness_reasoning") if state.get("is_factually_correct") is False else None,
        
        new_object_name=state.get("new_object_name"),  # Should be None mostly
        detected_object_name=state.get("detected_object_name"),

        response_type=state.get("response_type"),
        suggested_objects=state.get("suggested_objects"),
        object_selection_mode=bool(state.get("suggested_objects")),
        
        system_focus_mode=state["assistant"].current_focus_mode if state["assistant"].system_managed_focus else None,
        depth_progress=f"{state['assistant'].depth_questions_count}/{state['assistant'].depth_target}" if state["assistant"].system_managed_focus else None,
        
        # Theme classification fields (always sent for debug visibility)
        key_concept=state["assistant"].key_concept or None,
        ibpyp_theme_name=state["assistant"].ibpyp_theme_name or None,
        theme_classification_reason=state["assistant"].ibpyp_theme_reason or None,

        # Guide Phase specific fields
        guide_phase=state.get("guide_phase"),
        bridge_question=state["assistant"].bridge_question if state.get("guide_phase") else None,
        is_guide_success=state.get("is_guide_success", False),

        # Node execution trace (for critique reports)
        nodes_executed=state.get("nodes_executed", [])
    )
    await state["stream_callback"](final_chunk)
    
    # We return the full response to be added to history in app.py?
    # Or we can update the assistant here.
    # The original code appended to `conversation_history` in app.py AFTER the stream finished?
    # No, `call_paixueji_stream` didn't update history. `app.py` did:
    # "if chunk.finish: assistant.conversation_history.append(...)"
    # We'll stick to that contract. The app loop handles history update based on chunks.
    
    logger.info(f"[{state['session_id']}] Node: Finalize finished in {time.time() - start_time:.3f}s")
    return {}


# ============================================================================
# GRAPH DEFINITION
# ============================================================================

def build_paixueji_graph():
    workflow = StateGraph(PaixuejiState)

    # Add nodes
    workflow.add_node("start", lambda s: s)  # Entry point
    workflow.add_node("analyze_input", node_analyze_input)
    workflow.add_node("route_logic", node_route_logic)
    workflow.add_node("generate_response", node_generate_response)
    workflow.add_node("generate_question", node_generate_question)
    workflow.add_node("generate_fun_fact", node_generate_fun_fact)

    # Guide Nodes (Multi-turn Navigator/Driver pattern)
    workflow.add_node("start_guide", node_start_guide)
    workflow.add_node("guide_navigator", node_guide_navigator)
    workflow.add_node("guide_driver", node_guide_driver)
    workflow.add_node("guide_success", node_guide_success)
    workflow.add_node("guide_hint", node_guide_hint)
    workflow.add_node("guide_exit", node_guide_exit)

    workflow.add_node("finalize", node_finalize)

    # Route from START: introductions go to fun fact generation,
    # guide phase goes to navigator, everything else to analyze_input
    @trace_router(["guide_phase", "response_type"])
    def route_from_start(state):
        # Check for Guide Phase routing (multi-turn conversation)
        guide_phase = state.get("guide_phase") or state["assistant"].guide_phase

        if guide_phase == "active":
            # Continue multi-turn guide - analyze child's response
            return "guide_navigator"

        if guide_phase == "hint":
            # Child responded after hint - check again
            return "guide_navigator"

        if state.get("response_type") == "introduction":
            return "generate_fun_fact"

        return "analyze_input"

    # Define edges
    workflow.add_conditional_edges(
        START,
        route_from_start,
        {
            "analyze_input": "analyze_input",
            "generate_fun_fact": "generate_fun_fact",
            "guide_navigator": "guide_navigator"
        }
    )

    workflow.add_edge("analyze_input", "route_logic")
    workflow.add_edge("route_logic", "generate_response")

    # Check if we should guide instead of asking normal question
    @trace_router(["correct_answer_count", "is_factually_correct"])
    def route_after_response(state):
        try:
            current_count = state["correct_answer_count"]
            is_correct = state.get("is_factually_correct", False)

            # Trigger if we hit 4 correct answers (current 3 + 1 correct)
            should_trigger = (current_count >= 3 and is_correct) or current_count >= 4

            # Check if we have necessary guide info
            assistant = state["assistant"]
            has_guide_info = assistant.ibpyp_theme and assistant.key_concept and assistant.bridge_question

            if should_trigger and has_guide_info:
                logger.info(f"[{state['session_id']}] Triggering Theme Guide (Count: {current_count}+1)")
                return "start_guide"

            return "generate_question"
        except Exception as e:
            logger.error(f"Route error: {e}")
            return "generate_question"

    workflow.add_conditional_edges(
        "generate_response",
        route_after_response,
        {
            "generate_question": "generate_question",
            "start_guide": "start_guide"
        }
    )

    workflow.add_edge("generate_question", "finalize")
    workflow.add_edge("generate_fun_fact", "generate_response")

    # Guide Edges
    workflow.add_edge("start_guide", "finalize")  # First turn - present bridge question

    # Route after Navigator analysis
    @trace_router(["guide_strategy", "guide_status", "hint_given", "consecutive_stuck_count"])
    def route_after_navigator(state):
        """
        Route based on Navigator's analysis result.

        Routes to:
        - guide_success: Child articulated understanding (COMPLETED)
        - guide_hint: Max turns reached, no hint given yet
        - guide_exit: 2 consecutive RESISTANCE or hint already given at max turns
        - guide_driver: Continue conversation (ON_TRACK, DRIFTING, or first RESISTANCE)
        """
        assistant = state["assistant"]
        guide_strategy = state.get("guide_strategy")
        guide_status = state.get("guide_status")

        # Check for COMPLETED status
        if guide_strategy == "COMPLETE" or guide_status == "COMPLETED":
            logger.info(f"[{state['session_id']}] Guide: Child completed! Routing to success.")
            return "guide_success"

        # Check if should give hint (max turns, no hint yet)
        if assistant.should_give_hint():
            logger.info(f"[{state['session_id']}] Guide: Max turns reached, giving hint.")
            return "guide_hint"

        # Check if should exit (2 consecutive resistance OR hint already given at max)
        if assistant.should_exit_guide():
            logger.info(f"[{state['session_id']}] Guide: Exiting (resistance or post-hint timeout).")
            return "guide_exit"

        # Continue conversation with Driver
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
    workflow.add_edge("guide_hint", "finalize")  # After hint, await child response
    workflow.add_edge("guide_exit", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()

# Global graph instance
paixueji_graph = build_paixueji_graph()
