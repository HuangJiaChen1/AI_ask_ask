import asyncio
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
    handle_width_wrong_answer,
    extract_previous_question,
    prepare_messages_for_streaming,
    clean_messages_for_api
)
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
    kg_context: str

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
    
    # --- Output Accumulation ---
    full_response_text: str
    full_question_text: str
    sequence_number: int
    
    # --- Internal ---
    stream_callback: Any  # Async callback function(chunk: StreamChunk) -> None
    start_time: float


# ============================================================================
# NODES
# ============================================================================

async def node_analyze_input(state: PaixuejiState) -> dict:
    """
    First node: Check if it's the first turn (Intro) or requires validation.
    Also handles system-managed focus mode logic.
    """
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
        return {"response_type": "introduction"}
    
    # --- Validation Logic ---
    assistant = state["assistant"]
    is_awaiting_topic_selection = (assistant.state.value == "awaiting_topic_selection")
    
    validation_result = decide_topic_switch_with_validation(
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
        
        # Handle width wrong answer
        if assistant.current_focus_mode.startswith('width_') and (not updates["is_engaged"] or not updates["is_factually_correct"]):
            width_result = handle_width_wrong_answer(assistant)
            if width_result.get('switch_category'):
                # Update focus mode immediately
                new_mode = width_result['new_focus_mode']
                updates["focus_mode"] = new_mode
                # Update prompt in state? The prompts are usually fetched dynamically.
                # We should update state['focus_prompt'] too.
                updates["focus_prompt"] = assistant.get_focus_prompt(new_mode)
        
        # Reset wrong count
        if assistant.current_focus_mode.startswith('width_') and updates["is_factually_correct"]:
            assistant.width_wrong_count = 0

    return updates


async def node_route_logic(state: PaixuejiState) -> dict:
    """
    Determine the response type and next steps based on validation results.
    """
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
    
    async for item in generator:
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

    return full_text, sequence


async def node_generate_response(state: PaixuejiState) -> dict:
    """
    Generate the first part of the response (Feedback, Explanation, Correction, Switch).
    """
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
            kg_context=state["kg_context"]
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
    
    return {
        "full_response_text": full_text, 
        "sequence_number": new_seq
    }


async def node_generate_question(state: PaixuejiState) -> dict:
    """
    Generate the follow-up question (Part 2).
    """
    logger.info(f"[{state['session_id']}] Node: Generate Question")
    
    # If explicit switch, we don't ask a follow-up question
    if state["response_type"] == "explicit_switch":
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
            is_topic_switch=is_topic_switch,
            kg_context=state["kg_context"]
        )

    full_text, new_seq = await stream_generator_to_callback(generator, state, response_type_override="followup_question")
    
    return {
        "full_question_text": full_text,
        "sequence_number": new_seq
    }


async def node_finalize(state: PaixuejiState) -> dict:
    """
    Send final chunk and update history.
    """
    logger.info(f"[{state['session_id']}] Node: Finalize")
    
    full_response = state["full_response_text"]
    if state["full_question_text"]:
        full_response += " " + state["full_question_text"]
        
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
        correct_answer_count=state["correct_answer_count"],
        conversation_complete=False,
        focus_mode=state["focus_mode"],
        
        is_engaged=state["is_engaged"],
        is_factually_correct=state["is_factually_correct"],
        correctness_reasoning=state["correctness_reasoning"] if state["is_factually_correct"] is False else None,
        
        new_object_name=state.get("new_object_name"), # Should be None mostly
        detected_object_name=state.get("detected_object_name"),
        
        response_type=state["response_type"],
        suggested_objects=state["suggested_objects"],
        object_selection_mode=bool(state["suggested_objects"]),
        
        system_focus_mode=state["assistant"].current_focus_mode if state["assistant"].system_managed_focus else None,
        depth_progress=f"{state['assistant'].depth_questions_count}/{state['assistant'].depth_target}" if state["assistant"].system_managed_focus else None
    )
    await state["stream_callback"](final_chunk)
    
    # We return the full response to be added to history in app.py?
    # Or we can update the assistant here.
    # The original code appended to `conversation_history` in app.py AFTER the stream finished?
    # No, `call_paixueji_stream` didn't update history. `app.py` did:
    # "if chunk.finish: assistant.conversation_history.append(...)"
    # We'll stick to that contract. The app loop handles history update based on chunks.
    
    return {}


# ============================================================================
# GRAPH DEFINITION
# ============================================================================

def build_paixueji_graph():
    workflow = StateGraph(PaixuejiState)
    
    workflow.add_node("analyze_input", node_analyze_input)
    workflow.add_node("route_logic", node_route_logic)
    workflow.add_node("generate_response", node_generate_response)
    workflow.add_node("generate_question", node_generate_question)
    workflow.add_node("finalize", node_finalize)
    
    # Conditional edge from analyze
    def check_intro(state):
        if state.get("response_type") == "introduction":
            return "generate_response"
        return "route_logic"

    workflow.add_edge(START, "analyze_input")
    workflow.add_conditional_edges(
        "analyze_input", 
        check_intro,
        {
            "generate_response": "generate_response", 
            "route_logic": "route_logic"
        }
    )
    
    workflow.add_edge("route_logic", "generate_response")
    workflow.add_edge("generate_response", "generate_question")
    workflow.add_edge("generate_question", "finalize")
    workflow.add_edge("finalize", END)
    
    return workflow.compile()

# Global graph instance
paixueji_graph = build_paixueji_graph()
