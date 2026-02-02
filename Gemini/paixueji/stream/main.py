"""
Main entry point for Paixueji streaming.

This module contains the core call_paixueji_stream function that orchestrates
the entire conversation flow, routing to appropriate generators based on
validation results.
"""
import time
from typing import AsyncGenerator

from google import genai
from loguru import logger

from schema import StreamChunk, TokenUsage

from .utils import prepare_messages_for_streaming, extract_previous_question
from .question_generators import (
    ask_introduction_question_stream,
    generate_followup_question_stream,
    generate_completion_message_stream
)
from .response_generators import (
    generate_feedback_response_stream,
    generate_explanation_response_stream,
    generate_correction_response_stream,
    generate_topic_switch_response_stream,
    generate_natural_topic_completion_stream,
    generate_explicit_switch_response_stream
)
from .validation import decide_topic_switch_with_validation
from .focus_mode import (
    decide_next_focus_mode,
    handle_width_wrong_answer,
    generate_object_suggestions
)
# Import new Theme Guide classes
from .theme_guide import ThemeNavigator, ThemeDriver


async def call_paixueji_stream(
    age: int | None,
    messages: list[dict],
    content: str,
    status: str,
    session_id: str,
    request_id: str,
    config: dict,
    client: genai.Client,
    assistant,  # PaixuejiAssistant instance for topic switching
    age_prompt: str = "",
    object_name: str = "",
    level1_category: str = "",
    level2_category: str = "",
    level3_category: str = "",
    correct_answer_count: int = 0,
    category_prompt: str = "",
    focus_prompt: str = "",
    focus_mode: str | None = None,
    character_prompt: str = ""
) -> AsyncGenerator[StreamChunk, None]:
    """
    Main streaming function for Paixueji assistant.
    """
    start_time = time.time()

    # Retrieve KG context
    kg_context = assistant.get_kg_context(object_name, age or 6)
    if kg_context:
        logger.info(f"[{session_id}] KG Context: FOUND for '{object_name}'")
    else:
        logger.info(f"[{session_id}] KG Context: MISSING for '{object_name}' - using general knowledge")

    # If system-managed mode, use the actual current focus mode
    if assistant.system_managed_focus:
        focus_mode = assistant.current_focus_mode
        focus_prompt = assistant.get_focus_prompt(focus_mode)
        logger.info(f"[{session_id}] System-managed mode: using focus_mode={focus_mode}")

    logger.info(
        f"[{session_id}] call_paixueji_stream started | "
        f"session_id={session_id}, age={age}, object={object_name}, "
        f"level1={level1_category}, level2={level2_category}, level3={level3_category}, "
        f"correct_count={correct_answer_count}, status={status}, "
        f"content_length={len(content)}, message_history={len(messages)}"
    )

    # Add user input to messages for Gemini API
    messages.append({"role": "user", "content": content})

    # IMPORTANT: Also add to actual conversation_history so it's saved
    if content != f"Start conversation about {object_name}":
        assistant.conversation_history.append({"role": "user", "content": content})

    # Create tree node for this turn (Debugging)
    current_node = None
    if assistant.flow_tree:
        parent_id = assistant.flow_tree.get_latest_node().node_id if assistant.flow_tree.nodes else None
        turn_number = len(assistant.flow_tree.nodes)
        current_node = assistant.flow_tree.create_node(
            parent_id=parent_id,
            turn_number=turn_number,
            node_type="pending"
        )
        current_node.state_before = {
            "object_name": object_name,
            "level1_category": level1_category,
            "level2_category": level2_category,
            "correct_answer_count": correct_answer_count,
            "focus_mode": focus_mode,
            "character": assistant.character
        }
        current_node.user_input = content if turn_number > 0 else None

    # Track sequence number and token usage
    sequence_number = 0
    token_usage = None
    full_response = ""
    buffer = ""
    new_object_name = None
    detected_object_name = None
    switch_decision_reasoning = None
    conversation_complete = False

    # Prepare messages with age guidance
    prepared_messages = prepare_messages_for_streaming(messages, age_prompt)

    # Determine which streaming function to use
    stream_generator = None
    response_type = None
    is_engaged = None
    is_factually_correct = None
    correctness_reasoning = None
    suggested_objects = None

    # =========================================================================
    # THEME GUIDE LOGIC (Navigator & Driver Architecture)
    # =========================================================================
    if assistant.guide_mode and assistant.target_theme:
        logger.info(f"[{session_id}] THEME GUIDE ACTIVE: {assistant.target_theme['name']}")
        
        # 1. Initialize Agents
        # Optimization: Use 'gemini-1.5-flash-8b' for the Navigator if it exists, as it's faster for logic.
        # Otherwise, it defaults to the main model.
        navigator = ThemeNavigator(client, config)
        driver = ThemeDriver(client, config)
        
        # 2. NAVIGATOR STEP (Plan)
        # Detect if this is the start trigger
        is_intro = (content == f"Start conversation about {object_name}")
        
        if is_intro:
             # Special plan for intro
             nav_plan = {
                 "status": "ON_TRACK",
                 "strategy": "ADVANCE",
                 "instruction": f"Introduce {object_name} enthusiastically and ask a simple question that bridges towards {assistant.target_theme['name']}."
             }
        else:
             nav_plan = navigator.analyze_turn(
                history=prepared_messages,
                user_input=content,
                current_topic=object_name,
                target_theme=assistant.target_theme,
                age=age or 6
             )
        
        # Store plan for debugging/visualization
        assistant.last_navigation_state = nav_plan
        
        # Check completion
        if nav_plan.get("status") == "COMPLETED" or nav_plan.get("strategy") == "COMPLETE":
            logger.info(f"[{session_id}] Theme Guide COMPLETED via Navigator.")
            assistant.stop_theme_guide()
            # We can let the driver generate one last wrap-up message here or fall through.
            # Let's let the driver do the wrap up based on the "COMPLETE" instruction.
            # But we must update assistant state so next turn is normal.
        
        # 3. DRIVER STEP (Act)
        stream_generator = driver.generate_response_stream(
            history=prepared_messages,
            nav_plan=nav_plan,
            character_prompt=character_prompt,
            age=age or 6
        )
        response_type = "theme_guidance"

        # Wrap the generator to match standard format
        async def wrapped_theme_stream():
            async for text, usage, full in stream_generator:
                yield text, usage, full, None

        # Execute stream
        async for chunk_data in wrapped_theme_stream():
            text_chunk, chunk_token_usage, full_text, _ = chunk_data
            
            if chunk_token_usage:
                token_usage = chunk_token_usage
            
            if text_chunk:
                full_response += text_chunk
                sequence_number += 1
                yield StreamChunk(
                    response=text_chunk,
                    session_finished=False,
                    duration=0.0,
                    token_usage=None,
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    request_id=request_id,
                    is_stuck=False,
                    correct_answer_count=correct_answer_count,
                    conversation_complete=False,
                    focus_mode="theme_guide",
                    response_type=response_type,
                    switch_decision_reasoning=nav_plan.get("reasoning") # Expose reasoning
                )
        
        # Final Chunk
        end_time = time.time()
        yield StreamChunk(
            response="",
            session_finished=False,
            duration=end_time - start_time,
            token_usage=token_usage,
            finish=True,
            sequence_number=sequence_number + 1,
            timestamp=time.time(),
            session_id=session_id,
            request_id=request_id,
            is_stuck=False,
            correct_answer_count=correct_answer_count,
            conversation_complete=False,
            focus_mode="theme_guide",
            response_type=response_type,
            switch_decision_reasoning=nav_plan.get("reasoning")
        )
        
        # Add to history
        assistant.conversation_history.append({"role": "assistant", "content": full_response})
        return # Exit, turn handled

    # =========================================================================
    # STANDARD LOGIC (Non-Theme Guide)
    # =========================================================================

    # Check if this is truly the first interaction (no assistant messages yet)
    has_asked_questions = any(msg.get("role") == "assistant" for msg in messages)

    if correct_answer_count == 0 and not has_asked_questions:
        # First question (introduction)
        stream_generator = ask_introduction_question_stream(
            prepared_messages,
            object_name,
            category_prompt,
            age_prompt,
            age or 6,
            config,
            client,
            level3_category,
            focus_prompt=focus_prompt,
            kg_context=kg_context
        )
        response_type = "introduction"
        logger.info(f"[{session_id}] Routing to introduction question")

        if current_node:
            current_node.type = response_type

    else:
        # Standard Turn Logic (Validation -> Response -> Question)
        logger.info(f"[{session_id}] Running unified AI validation for answer")

        is_awaiting_topic_selection = (assistant.state.value == "awaiting_topic_selection")
        
        validation_result = decide_topic_switch_with_validation(
            assistant=assistant,
            child_answer=content,
            object_name=object_name,
            age=age or 6,
            focus_mode=focus_mode,
            is_awaiting_topic_selection=is_awaiting_topic_selection
        )

        is_engaged = validation_result.get('is_engaged')
        is_factually_correct = validation_result.get('is_factually_correct')
        correctness_reasoning = validation_result.get('correctness_reasoning')
        switch_decision_reasoning = validation_result.get('switching_reasoning')

        # System-managed focus tracking
        if assistant.system_managed_focus:
            if is_engaged and assistant.current_focus_mode == 'depth':
                assistant.depth_questions_count += 1
            
            if assistant.current_focus_mode.startswith('width_') and (not is_engaged or not is_factually_correct):
                width_result = handle_width_wrong_answer(assistant)
                if width_result.get('switch_category'):
                    focus_mode = width_result['new_focus_mode']
                    focus_prompt = assistant.get_focus_prompt(focus_mode)

            if assistant.current_focus_mode.startswith('width_') and is_factually_correct:
                assistant.width_wrong_count = 0

        if current_node:
            current_node.validation = {
                "is_engaged": is_engaged,
                "is_factually_correct": is_factually_correct,
                "correctness_reasoning": correctness_reasoning
            }

        should_switch = validation_result.get('decision') == 'SWITCH'

        # ROUTING
        response_generator = None
        previous_question = extract_previous_question(prepared_messages)

        if should_switch and not validation_result.get('new_object'):
            # Explicit switch request (Object Selection)
            suggested_objects = generate_object_suggestions(assistant, config, client, age or 6)
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.AWAITING_TOPIC_SELECTION

            response_generator = generate_explicit_switch_response_stream(
                messages=prepared_messages,
                suggested_objects=suggested_objects,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "explicit_switch"

        elif should_switch and validation_result.get('new_object'):
            # Topic Switch
            new_object = validation_result['new_object']
            previous_object = object_name

            if assistant.system_managed_focus:
                assistant.reset_object_state(new_object)
            else:
                assistant.object_name = new_object

            object_name = new_object
            new_object_name = new_object
            switch_decision_reasoning = validation_result.get('switching_reasoning')

            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.ASKING_QUESTION

            # Background classification
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.submit(assistant.classify_object_sync, new_object)

            category_prompt = assistant.get_category_prompt(
                assistant.level1_category, assistant.level2_category, assistant.level3_category
            )

            response_generator = generate_topic_switch_response_stream(
                messages=prepared_messages,
                previous_object=previous_object,
                new_object=new_object,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "topic_switch"

        elif not is_engaged:
            # Explanation
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.ASKING_QUESTION

            response_generator = generate_explanation_response_stream(
                messages=prepared_messages,
                child_answer=content,
                object_name=object_name,
                previous_question=previous_question,
                age=age or 6,
                category_prompt=category_prompt,
                age_prompt=age_prompt,
                config=config,
                client=client
            )
            response_type = "explanation"

        elif is_factually_correct:
            # Feedback
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.ASKING_QUESTION

            response_generator = generate_feedback_response_stream(
                messages=prepared_messages,
                child_answer=content,
                object_name=object_name,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "feedback"

        else:
            # Correction
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.ASKING_QUESTION

            response_generator = generate_correction_response_stream(
                messages=prepared_messages,
                child_answer=content,
                object_name=object_name,
                previous_question=previous_question,
                correctness_reasoning=correctness_reasoning,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "gentle_correction"

        if current_node:
            current_node.type = response_type
            if validation_result.get('decision'):
                current_node.decision = {
                    "decision_type": validation_result.get('decision'),
                    "detected_object": validation_result.get('new_object'),
                    "switch_reasoning": validation_result.get('switching_reasoning'),
                    "routing": response_type
                }

        # System-managed focus decision
        natural_topic_completion = False
        if assistant.system_managed_focus:
            focus_decision = decide_next_focus_mode(assistant)
            if focus_decision['focus_mode'] == 'object_selection':
                natural_topic_completion = True
                response_type = "natural_topic_completion"
            else:
                focus_mode = focus_decision['focus_mode']
                focus_prompt = assistant.get_focus_prompt(focus_mode)

        # Stream Response
        full_response_text = ""
        full_question_text = ""

        try:
            async for chunk_data in response_generator:
                text_chunk, usage, response_so_far = chunk_data
                full_response_text = response_so_far
                if text_chunk:
                    sequence_number += 1
                    yield StreamChunk(
                        response=text_chunk,
                        session_finished=False,
                        duration=0.0,
                        token_usage=None,
                        finish=False,
                        sequence_number=sequence_number,
                        timestamp=time.time(),
                        session_id=session_id,
                        request_id=request_id,
                        is_stuck=False,
                        correct_answer_count=correct_answer_count,
                        conversation_complete=False,
                        focus_mode=focus_mode,
                        is_engaged=is_engaged,
                        is_factually_correct=is_factually_correct,
                        correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,
                        new_object_name=new_object_name,
                        detected_object_name=detected_object_name,
                        switch_decision_reasoning=switch_decision_reasoning,
                        response_type=response_type,
                        suggested_objects=suggested_objects,
                        object_selection_mode=bool(suggested_objects),
                        system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                        depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
                    )

        except Exception as e:
            logger.error(f"[{session_id}] Response generation failed: {e}")
            full_response_text = "I see!"
            sequence_number += 1
            yield StreamChunk(
                response=full_response_text,
                session_finished=False,
                duration=0.0,
                token_usage=None,
                finish=False,
                sequence_number=sequence_number,
                timestamp=time.time(),
                session_id=session_id,
                request_id=request_id,
                is_stuck=False,
                correct_answer_count=correct_answer_count,
                conversation_complete=False,
                focus_mode=focus_mode,
                response_type=response_type
            )

        # Prepare for Question Generation
        question_messages = prepared_messages.copy()
        if full_response_text:
            question_messages.append({"role": "assistant", "content": full_response_text})

        if response_type == "explicit_switch":
            question_generator = None
        elif natural_topic_completion:
            question_generator = generate_natural_topic_completion_stream(
                messages=question_messages,
                current_object=object_name,
                age=age or 6,
                config=config,
                client=client
            )
        else:
            question_generator = generate_followup_question_stream(
                messages=question_messages,
                object_name=object_name,
                correct_count=correct_answer_count,
                category_prompt=category_prompt,
                age_prompt=age_prompt,
                age=age or 6,
                focus_prompt=focus_prompt,
                config=config,
                client=client,
                character_prompt=character_prompt,
                is_topic_switch=should_switch,
                kg_context=kg_context
            )

        # Stream Question
        if question_generator is not None:
            try:
                async for chunk_data in question_generator:
                    text_chunk, usage, question_so_far = chunk_data
                    full_question_text = question_so_far
                    if text_chunk:
                        sequence_number += 1
                        yield StreamChunk(
                            response=text_chunk,
                            session_finished=False,
                            duration=0.0,
                            token_usage=None,
                            finish=False,
                            sequence_number=sequence_number,
                            timestamp=time.time(),
                            session_id=session_id,
                            request_id=request_id,
                            is_stuck=False,
                            correct_answer_count=correct_answer_count,
                            conversation_complete=False,
                            focus_mode=focus_mode,
                            response_type="followup_question",
                            system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                            depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
                        )
            except Exception as e:
                logger.error(f"[{session_id}] Question generation failed: {e}")
                full_question_text = f"What else about {object_name}?"
                sequence_number += 1
                yield StreamChunk(
                    response=full_question_text,
                    session_finished=False,
                    duration=0.0,
                    token_usage=None,
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    request_id=request_id,
                    is_stuck=False,
                    correct_answer_count=correct_answer_count,
                    conversation_complete=False,
                    focus_mode=focus_mode,
                    response_type="followup_question"
                )

        # Combine logic
        full_response = (full_response_text + " " + full_question_text).strip()
        assistant.conversation_history.append({"role": "assistant", "content": full_response})

        # Set stream_generator to None to prevent double execution below
        stream_generator = None

    # Handle Standard Stream Results (from above if not stream_generator is None)
    if stream_generator:
        async for chunked_text, chunk_token_usage, full_text, decision_info in stream_generator:
            if chunk_token_usage:
                token_usage = chunk_token_usage
            
            buffer += chunked_text
            text_to_process = buffer
            buffer = ""
            
            if text_to_process:
                full_response += text_to_process
                sequence_number += 1
                yield StreamChunk(
                    response=text_to_process,
                    session_finished=(status == "over"),
                    duration=0.0,
                    token_usage=None,
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    request_id=request_id,
                    is_stuck=False,
                    correct_answer_count=correct_answer_count,
                    conversation_complete=False,
                    focus_mode=focus_mode
                )

    if buffer:
        full_response += buffer

    # Final Chunk
    end_time = time.time()
    elapsed_time = end_time - start_time

    sequence_number += 1
    yield StreamChunk(
        response=full_response, # Ensure this is the full response
        session_finished=(status == "over"),
        duration=elapsed_time,
        token_usage=token_usage,
        finish=True,
        sequence_number=sequence_number,
        timestamp=time.time(),
        session_id=session_id,
        request_id=request_id,
        is_stuck=False,
        correct_answer_count=correct_answer_count,
        conversation_complete=conversation_complete,
        focus_mode=focus_mode,
        is_engaged=is_engaged,
        is_factually_correct=is_factually_correct,
        correctness_reasoning=correctness_reasoning,
        new_object_name=new_object_name,
        detected_object_name=detected_object_name,
        switch_decision_reasoning=switch_decision_reasoning,
        response_type=response_type if response_type else "unknown"
    )

    # Update Tree Node
    if current_node:
        current_node.ai_response = full_response
        current_node.ai_response_part1 = full_response_text
        current_node.ai_response_part2 = full_question_text
        current_node.response_duration = elapsed_time