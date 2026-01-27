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

    Args:
        age: Child's age
        messages: Conversation history
        content: User content
        status: Session status
        session_id: Session ID
        request_id: Request ID
        config: Config dict
        client: Gemini client
        age_prompt: Age guidance
        object_name: Object name
        level1_category: L1 Category
        level2_category: L2 Category
        level3_category: L3 Category
        correct_answer_count: Correct answers count
        category_prompt: Category guidance
        focus_prompt: Focus strategy guidance
        focus_mode: The focus mode key (e.g., depth, width_color)
        character_prompt: Character guidance
    """
    start_time = time.time()

    # Retrieve KG context
    kg_context = assistant.get_kg_context(object_name, age or 6)
    if kg_context:
        logger.info(f"[{session_id}] KG Context: FOUND for '{object_name}'")
    else:
        logger.info(f"[{session_id}] KG Context: MISSING for '{object_name}' - using general knowledge")

    # If system-managed mode, use the actual current focus mode instead of "system_managed"
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
    # For introduction, we don't want to save the trigger message, so only add for real user inputs
    # Check if this is a real user message (not the introduction trigger)
    if content != f"Start conversation about {object_name}":
        assistant.conversation_history.append({"role": "user", "content": content})

    # Create tree node for this turn
    current_node = None
    if assistant.flow_tree:
        parent_id = assistant.flow_tree.get_latest_node().node_id if assistant.flow_tree.nodes else None
        turn_number = len(assistant.flow_tree.nodes)

        current_node = assistant.flow_tree.create_node(
            parent_id=parent_id,
            turn_number=turn_number,
            node_type="pending"  # Will be updated after routing
        )

        # Capture state BEFORE
        current_node.state_before = {
            "object_name": object_name,
            "level1_category": level1_category,
            "level2_category": level2_category,
            "correct_answer_count": correct_answer_count,
            "focus_mode": focus_mode,
            "character": assistant.character
        }
        current_node.user_input = content if turn_number > 0 else None

    # INFINITE MODE: Conversation never completes automatically
    conversation_complete = False

    logger.info(f"[{session_id}] Conversation state | correct_count={correct_answer_count}, complete={conversation_complete}")

    # Track sequence number and token usage
    sequence_number = 0
    token_usage = None
    full_response = ""
    full_response_text = None
    full_question_text = None
    buffer = ""
    new_object_name = None
    detected_object_name = None
    switch_decision_reasoning = None

    # Prepare messages with age guidance
    prepared_messages = prepare_messages_for_streaming(messages, age_prompt)

    # Determine which streaming function to use
    stream_generator = None
    response_type = None
    is_engaged = None
    is_factually_correct = None
    correctness_reasoning = None

    # Check if this is truly the first interaction (no assistant messages yet)
    has_asked_questions = any(msg.get("role") == "assistant" for msg in messages)

    if correct_answer_count == 0 and not has_asked_questions:
        # First question (introduction) - only if we haven't asked any questions yet
        stream_generator = ask_introduction_question_stream(
            prepared_messages,
            object_name,
            category_prompt,
            age_prompt,
            age or 6,  # default to 6 if age not specified
            config,
            client,
            level3_category,
            focus_prompt=focus_prompt,
            kg_context=kg_context
        )
        response_type = "introduction"
        logger.info(f"[{session_id}] Routing to introduction question")

        # Update node type for introduction (no validation)
        if current_node:
            current_node.type = response_type

    else:
        # DUAL-PARALLEL ARCHITECTURE: Separate response and question generation
        # Follow-up question or explanation - Use SINGLE AI VALIDATION for all answers
        logger.info(f"[{session_id}] Running unified AI validation for answer")

        # Check conversation state for special handling
        is_awaiting_topic_selection = (assistant.state.value == "awaiting_topic_selection")
        if is_awaiting_topic_selection:
            logger.info(f"[{session_id}] Special validation context: AWAITING_TOPIC_SELECTION")

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

        # NEW: System-managed focus tracking
        if assistant.system_managed_focus:
            # Track DEPTH questions (only for engaged answers)
            if is_engaged and assistant.current_focus_mode == 'depth':
                assistant.depth_questions_count += 1
                logger.info(f"[SYSTEM_MANAGED] Depth: {assistant.depth_questions_count}/{assistant.depth_target}")

            # Handle wrong WIDTH answers
            # Include 'not is_engaged' to handle "I don't know" as a wrong answer that triggers a switch
            if assistant.current_focus_mode.startswith('width_') and (not is_engaged or not is_factually_correct):
                width_result = handle_width_wrong_answer(assistant)
                logger.info(f"[SYSTEM_MANAGED] WIDTH wrong: {width_result}")

                # Update local variables if mode changed so response uses new strategy
                if width_result.get('switch_category'):
                    focus_mode = width_result['new_focus_mode']
                    focus_prompt = assistant.get_focus_prompt(focus_mode)
                    logger.info(f"[SYSTEM_MANAGED] Switched focus to {focus_mode} for immediate response")

            # Reset wrong count on correct WIDTH answer
            if assistant.current_focus_mode.startswith('width_') and is_factually_correct:
                assistant.width_wrong_count = 0
                logger.info(f"[SYSTEM_MANAGED] Correct WIDTH answer, reset count")

        # Capture validation in tree
        if current_node:
            current_node.validation = {
                "is_engaged": is_engaged,
                "is_factually_correct": is_factually_correct,
                "correctness_reasoning": correctness_reasoning
            }

        # Check for explicit switch decision
        should_switch = validation_result.get('decision') == 'SWITCH'

        # ROUTING: Determine response generator based on validation
        response_generator = None
        previous_question = extract_previous_question(prepared_messages)

        # Handle explicit request to switch without a specific object named
        if should_switch and not validation_result.get('new_object'):
            # Trigger object selection flow immediately
            suggested_objects = generate_object_suggestions(assistant, config, client, age or 6)

            # STATE UPDATE: We are now offering choices
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
            logger.info(f"[{session_id}] Routing to explicit switch response")

        elif should_switch and validation_result.get('new_object'):
            # PATH 2A: TOPIC SWITCH (Moved up from is_factually_correct branch)
            new_object = validation_result['new_object']
            previous_object = object_name

            # Update object in assistant and reset focus state for new object
            if assistant.system_managed_focus:
                assistant.reset_object_state(new_object)
            else:
                assistant.object_name = new_object

            object_name = new_object
            new_object_name = new_object
            switch_decision_reasoning = validation_result.get('switching_reasoning')

            # STATE UPDATE: New object, back to asking questions
            from paixueji_assistant import ConversationState
            assistant.state = ConversationState.ASKING_QUESTION

            # Classify new object (background with timeout)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(assistant.classify_object_sync, new_object)
                try:
                    future.result(timeout=1.0)
                    logger.info(f"[{session_id}] Classification completed for {new_object}")
                except concurrent.futures.TimeoutError:
                    logger.warning(f"[{session_id}] Classification timeout for {new_object}")

            # Rebuild category prompts for new object
            category_prompt = assistant.get_category_prompt(
                assistant.level1_category,
                assistant.level2_category,
                assistant.level3_category
            )
            level1_category = assistant.level1_category
            level2_category = assistant.level2_category
            level3_category = assistant.level3_category

            response_generator = generate_topic_switch_response_stream(
                messages=prepared_messages,
                previous_object=previous_object,
                new_object=new_object,
                age=age or 6,
                config=config,
                client=client
            )
            response_type = "topic_switch"
            logger.info(f"[{session_id}] Routing to topic switch | {previous_object} -> {new_object}")

        elif not is_engaged:
            # PATH 1: STUCK/UNCLEAR ("I don't know", unclear answers)
            # STATE UPDATE: Still asking questions about same object
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
            logger.info(f"[{session_id}] Routing to explanation | is_engaged=False")

        elif is_factually_correct:
            # PATH 2B: CORRECT ANSWER (no switch)
            # STATE UPDATE: Back to asking questions
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
            logger.info(f"[{session_id}] Routing to feedback | is_engaged=True, is_factually_correct=True")

        else:
            # PATH 3: WRONG + ENGAGED
            # STATE UPDATE: Back to asking questions
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
            logger.info(f"[{session_id}] Routing to gentle correction | is_engaged=True, is_factually_correct=False")

        # Update node type and capture decision
        if current_node:
            current_node.type = response_type
            if validation_result.get('decision'):
                current_node.decision = {
                    "decision_type": validation_result.get('decision'),
                    "detected_object": validation_result.get('new_object'),
                    "switch_reasoning": validation_result.get('switching_reasoning'),
                    "routing": response_type
                }

        # NEW: System-managed focus mode decision (Move BEFORE response generation)
        # This ensures the frontend gets the correct focus mode tag on the very first chunk
        skip_question_generation = False
        natural_topic_completion = False
        suggested_objects = None

        if assistant.system_managed_focus:
            focus_decision = decide_next_focus_mode(assistant)

            if focus_decision['focus_mode'] == 'object_selection':
                # Natural topic completion: congratulate and ask what they want next
                # No selection UI - let them use natural language
                natural_topic_completion = True
                response_type = "natural_topic_completion"
                logger.info(f"[{session_id}] System-managed: natural topic completion triggered")
            else:
                # Update focus mode for BOTH response and question generation
                focus_mode = focus_decision['focus_mode']
                focus_prompt = assistant.get_focus_prompt(focus_mode)
                logger.info(f"[{session_id}] System-managed: focus_mode={focus_mode}, reason={focus_decision['reason']}")

        # DUAL-PARALLEL STREAMING: Stream response first, then question
        full_response_text = ""
        full_question_text = ""

        # Stream response generator
        try:
            logger.debug(f"[{session_id}] Streaming response ({response_type})")
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
                        focus_mode=focus_mode, # Uses UPDATED focus mode
                        is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
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
            logger.error(f"[{session_id}] Response generation failed | error={str(e)}", exc_info=True)
            # Fallback response
            fallback_response = "I see!"
            full_response_text = fallback_response
            sequence_number += 1
            yield StreamChunk(
                response=fallback_response,
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
                is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
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

        # CRITICAL FIX: Update messages with the generated response BEFORE asking follow-up
        # This ensures the question generator sees the explanation/feedback we just gave
        question_messages = prepared_messages.copy()
        if full_response_text:
            question_messages.append({"role": "assistant", "content": full_response_text})

        # Check if this is an explicit switch request (no follow-up question needed)
        if response_type == "explicit_switch":
            # For explicit switches, the response already contains the object selection
            # We don't need to generate a follow-up question
            question_generator = None
            logger.info(f"[{session_id}] Skipping question generation for explicit switch")

        # Check if natural topic completion triggered (system-managed)
        elif natural_topic_completion:
            # Natural completion: congratulate and ask what they want to explore next
            question_generator = generate_natural_topic_completion_stream(
                messages=question_messages,
                current_object=object_name,
                age=age or 6,
                config=config,
                client=client
            )
            logger.info(f"[{session_id}] Using natural topic completion (no selection UI)")

        # ALWAYS generate follow-up question (for all non-introduction turns)
        # Now using the updated history including the response
        else:
            question_generator = generate_followup_question_stream(
                messages=question_messages,
                object_name=object_name,  # Updated object if switched
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

        # Stream question generator (skip if None for explicit switches)
        if question_generator is not None:
            try:
                logger.debug(f"[{session_id}] Streaming question")
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
                            is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
                            is_engaged=is_engaged,
                            is_factually_correct=is_factually_correct,
                            correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,
                            new_object_name=new_object_name,
                            detected_object_name=detected_object_name,
                            switch_decision_reasoning=switch_decision_reasoning,
                            response_type="followup_question",
                            suggested_objects=suggested_objects,
                            object_selection_mode=bool(suggested_objects),
                            system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                            depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
                        )

            except Exception as e:
                logger.error(f"[{session_id}] Question generation failed | error={str(e)}", exc_info=True)
                # Fallback question
                fallback_question = f"What else can you tell me about {object_name}?"
                full_question_text = fallback_question
                sequence_number += 1
                yield StreamChunk(
                    response=fallback_question,
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
                    is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,
                    is_engaged=is_engaged,
                    is_factually_correct=is_factually_correct,
                    correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,
                    new_object_name=new_object_name,
                    detected_object_name=detected_object_name,
                    switch_decision_reasoning=switch_decision_reasoning,
                    response_type="followup_question",
                    suggested_objects=suggested_objects,
                    object_selection_mode=bool(suggested_objects),
                    system_focus_mode=assistant.current_focus_mode if assistant.system_managed_focus else None,
                    depth_progress=f"{assistant.depth_questions_count}/{assistant.depth_target}" if assistant.system_managed_focus else None
                )

        # Combine response and question for conversation history
        # For explicit switches, there's no follow-up question, so just use the response
        if full_question_text:
            full_response = full_response_text + " " + full_question_text
        else:
            full_response = full_response_text
        prepared_messages.append({"role": "assistant", "content": full_response})

        # Set stream_generator to None to skip old streaming logic
        stream_generator = None

    # Stream chunks from the selected generator
    if stream_generator:
        async for chunked_text, chunk_token_usage, full_text, decision_info in stream_generator:
            # Capture decision info from streaming functions
            if decision_info:
                if decision_info.get('new_object_name') and not new_object_name:
                    new_object_name = decision_info['new_object_name']
                    logger.info(f"[{session_id}] TOPIC SWITCH DETECTED: {new_object_name}")
                if decision_info.get('detected_object_name') and not detected_object_name:
                    detected_object_name = decision_info['detected_object_name']
                    switch_decision_reasoning = decision_info.get('switch_decision_reasoning')
                    logger.info(f"[{session_id}] Object detected but not switching: {detected_object_name}")

            if chunk_token_usage:
                token_usage = chunk_token_usage

            # Simple buffering - no tag parsing needed (decision made in separate API call)
            buffer += chunked_text
            text_to_process = buffer
            buffer = ""

            # Yield Result
            if text_to_process:
                full_response += text_to_process # Track what we actually sent to user

                sequence_number += 1
                chunk = StreamChunk(
                    response=text_to_process,
                    session_finished=(status == "over"),
                    duration=0.0,  # Will be set in final chunk
                    token_usage=None,  # Only in final chunk
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    request_id=request_id,
                    is_stuck=False,  # Not used in Paixueji
                    correct_answer_count=correct_answer_count,
                    conversation_complete=False,  # Infinite mode: never complete
                    focus_mode=focus_mode,

                    # DEPRECATED: Keep for backward compat
                    is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,

                    # NEW unified AI validation fields:
                    is_engaged=is_engaged,
                    is_factually_correct=is_factually_correct,
                    correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,

                    # Topic switching fields:
                    new_object_name=new_object_name,
                    detected_object_name=detected_object_name,
                    switch_decision_reasoning=switch_decision_reasoning
                )
                yield chunk

                # Only send these values once (they're sent in first chunk after decision)
                if new_object_name:
                    new_object_name = None
                if detected_object_name:
                    detected_object_name = None
                    switch_decision_reasoning = None

    # Flush remaining buffer if needed
    if buffer:
        full_response += buffer

    # Calculate total duration
    end_time = time.time()
    elapsed_time = end_time - start_time

    # Validate response completeness
    if not full_response:
        logger.warning(f"[{session_id}] Empty response - possible streaming error or reasoning only")

    logger.info(
        f"[{session_id}] call_paixueji_stream completed | "
        f"response_type={response_type}, duration={elapsed_time:.3f}s, "
        f"total_chunks={sequence_number}, response_length={len(full_response)}, "
        f"correct_count={correct_answer_count}, complete={conversation_complete}, "
        f"session_finished={status == 'over'}"
    )

    logger.debug(f"Full response: {full_response}...")

    # Yield final chunk with token usage and duration
    sequence_number += 1
    final_chunk = StreamChunk(
        response=full_response,
        session_finished=(status == "over"),
        duration=elapsed_time,
        token_usage=token_usage,
        finish=True,
        sequence_number=sequence_number,
        timestamp=time.time(),
        session_id=session_id,
        request_id=request_id,
        is_stuck=False,  # Not used in Paixueji
        correct_answer_count=correct_answer_count,
        conversation_complete=conversation_complete,
        focus_mode=focus_mode,

        # DEPRECATED: Keep for backward compat
        is_correct=is_engaged and is_factually_correct if is_engaged is not None else None,

        # NEW unified AI validation fields:
        is_engaged=is_engaged,
        is_factually_correct=is_factually_correct,
        correctness_reasoning=correctness_reasoning if is_factually_correct == False else None,

        # Topic switching fields:
        new_object_name=new_object_name,
        detected_object_name=detected_object_name,
        switch_decision_reasoning=switch_decision_reasoning
    )
    yield final_chunk

    # Finalize tree node
    if current_node:
        current_node.ai_response = full_response
        current_node.ai_response_part1 = full_response_text
        current_node.ai_response_part2 = full_question_text
        current_node.response_duration = elapsed_time

        # Capture state changes
        state_after = {}
        if assistant.object_name != current_node.state_before.get("object_name"):
            state_after["object_name"] = assistant.object_name
            state_after["level1_category"] = assistant.level1_category
            state_after["level2_category"] = assistant.level2_category
        if assistant.correct_answer_count != current_node.state_before.get("correct_answer_count"):
            state_after["correct_answer_count"] = assistant.correct_answer_count

        current_node.state_after = state_after
        current_node.metadata = {
            "chunk_count": sequence_number,
            "token_usage": token_usage.model_dump() if token_usage else None
        }

        # [DEBUG LOG] Structured output matching Debug Panel
        state_b = current_node.state_before
        val = current_node.validation or {}
        dec = current_node.decision or {}

        log_msg = (
            f"\n\n[DEBUG TREE NODE] Turn {current_node.turn_number} ({current_node.type.upper()})\n"
            f"--------------------------------------------------\n"
            f"USER INPUT: {current_node.user_input or '(None)'}\n"
            f"CONTEXT: Object='{state_b.get('object_name')}' | Character='{state_b.get('character')}' | Focus='{state_b.get('focus_mode')}'\n"
            f"VALIDATION: Engaged={val.get('is_engaged')} | Correct={val.get('is_factually_correct')}\n"
            f"REASONING: {val.get('correctness_reasoning') or 'N/A'}\n"
            f"DECISION: {dec.get('decision_type') or 'N/A'} (Reason: {dec.get('switch_reasoning') or 'N/A'})\n"
            f"RESPONSE PART 1: {current_node.ai_response_part1 or '(None)'}\n"
            f"RESPONSE PART 2: {current_node.ai_response_part2 or '(None)'}\n"
            f"--------------------------------------------------\n"
        )
        logger.debug(log_msg)
