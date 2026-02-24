"""
Flask API for Paixueji Assistant with Server-Sent Events (SSE) streaming.

This provides real-time streaming responses where the LLM asks questions about objects.
"""

from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import json
import uuid
import asyncio
import threading
import os

from google import genai
from google.genai.types import HttpOptions
from loguru import logger

from paixueji_assistant import PaixuejiAssistant
from graph import paixueji_graph
from schema import StreamChunk
import paixueji_prompts
import time

app = Flask(__name__, static_folder='static')
CORS(app)

# In-memory session storage
# NOTE: Sessions will be lost on server restart
# For production, consider using Redis or database storage
sessions = {}

# Background critique task tracking
# {task_id: {"status": "pending"|"running"|"completed"|"failed",
#            "session_id": str, "report_path": str|None,
#            "error": str|None, "started_at": float}}
critique_tasks = {}

# Initialize global Gemini client to enable connection reuse
def init_global_client():
    """Initialize a global Gemini client instance to avoid cold starts."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "config.json")
        if not os.path.exists(config_path):
            print(f"[WARNING] Config file not found: {config_path}")
            return None

        with open(config_path, 'r') as f:
            config = json.load(f)

        # Set up authentication if credentials file is specified in environment
        credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if credentials_path and not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_SET'):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
            os.environ['GOOGLE_APPLICATION_CREDENTIALS_SET'] = '1'

        print("[INFO] Initializing global Gemini client...")
        client = genai.Client(
            vertexai=True,
            project=config["project"],
            location=config["location"],
            http_options=HttpOptions(api_version="v1")
        )
        print("[INFO] Global Gemini client initialized successfully")
        return client
    except Exception as e:
        print(f"[ERROR] Failed to initialize global Gemini client: {e}")
        return None

GLOBAL_GEMINI_CLIENT = init_global_client()


def get_event_loop():
    """
    Create a new event loop for async operations.

    Each request gets its own event loop to avoid race conditions when
    multiple requests are processed concurrently (e.g., user sends new
    message while previous one is still streaming).

    Returns:
        asyncio.AbstractEventLoop: A new event loop for this request
    """
    # Create a new event loop for each request to avoid:
    # "RuntimeError: This event loop is already running"
    # when concurrent requests try to use the same loop
    loop = asyncio.new_event_loop()
    return loop


def sse_event(event_type, data):
    """
    Format data as Server-Sent Event.

    Args:
        event_type: Event type (chunk, complete, error)
        data: Data to send (will be JSON-encoded). Can be a dict or Pydantic model.

    Returns:
        Formatted SSE string with event type and data
    """
    # Optimize Pydantic model serialization - use model_dump_json() directly
    # which is faster than model_dump() + json.dumps()
    if hasattr(data, 'model_dump_json'):
        json_data = data.model_dump_json()
    else:
        json_data = json.dumps(data)

    return f"event: {event_type}\ndata: {json_data}\n\n"

# Helper to bridge Graph execution to SSE stream
async def stream_graph_execution(initial_state):
    """
    Executes the LangGraph workflow and yields StreamChunks as they are produced.
    """
    import asyncio
    
    # Queue for passing chunks from graph nodes to this generator
    queue = asyncio.Queue()
    
    # Callback injected into state
    async def stream_callback(chunk):
        await queue.put(chunk)
        
    initial_state["stream_callback"] = stream_callback
    initial_state["start_time"] = time.time()
    
    # Start graph execution in background task
    task = asyncio.create_task(paixueji_graph.ainvoke(initial_state))
    
    while True:
        # Wait for next chunk or completion
        get_chunk = asyncio.create_task(queue.get())
        done, pending = await asyncio.wait(
            [get_chunk, task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Check for new chunk
        if get_chunk in done:
            chunk = get_chunk.result()
            yield chunk
            
        # Check for graph completion (or error)
        if task in done:
            # If we have a pending get_chunk, cancel it to avoid "Task was destroyed but it is pending"
            # and "Event loop is closed" errors. This happens on both success and failure because
            # a waiting get_chunk task is always active when the graph finishes.
            if not get_chunk.done():
                get_chunk.cancel()
                try:
                    await get_chunk
                except asyncio.CancelledError:
                    pass

            # Check for exceptions
            if task.exception():
                # If we have a pending get_chunk, cancel it
                if not get_chunk.done():
                    get_chunk.cancel()
                raise task.exception()
            
            # Flush any remaining chunks in queue
            while not queue.empty():
                yield await queue.get()
                
            break


@app.route('/')
def index():
    """Serve the web interface."""
    return app.send_static_file('index.html')


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "streaming": True,
        "active_sessions": len(sessions)
    })


@app.route('/api/start', methods=['POST'])
def start_conversation():
    """
    Start a new Paixueji conversation with first question about object.

    Request body:
        {
            "age": 6 (optional, 3-8),
            "object_name": "apple" (required),
            "level1_category": "foods" (optional),
            "level2_category": "fresh_ingredients" (optional),
            "level3_category": "some_level3" (optional)
        }

    SSE Events:
        - chunk: StreamChunk object (serialized as JSON)
        - complete: Final completion marker
        - error: Error information
    """
    data = request.get_json() or {}
    age = data.get('age')
    object_name = data.get('object_name')
    level1_category = data.get('level1_category')
    level2_category = data.get('level2_category')
    level3_category = data.get('level3_category')
    character = data.get('character')
    focus_mode = data.get('focus_mode', 'depth')  # Default to depth if not provided
    system_managed = data.get('system_managed', False)  # System-managed focus mode

    # Validate required fields
    if not object_name:
        return jsonify({
            "success": False,
            "error": "object_name is required"
        }), 400

    # Validate age
    if age is not None:
        try:
            age = int(age)
            if age < 3 or age > 8:
                print(f"[WARNING] Invalid age {age}, using None")
                age = None
        except (ValueError, TypeError):
            print(f"[WARNING] Invalid age format {age}, using None")
            age = None

    # Create session
    session_id = str(uuid.uuid4())
    assistant = PaixuejiAssistant(system_managed=system_managed, client=GLOBAL_GEMINI_CLIENT)
    sessions[session_id] = assistant

    # Store session state
    assistant.age = age
    assistant.object_name = object_name
    assistant.level1_category = level1_category
    assistant.level2_category = level2_category
    assistant.level3_category = level3_category
    assistant.character = character
    assistant.correct_answer_count = 0

    # Generate unique request ID for this stream
    request_id = str(uuid.uuid4())

    print(f"[INFO] Created Paixueji session {session_id[:8]}... | age={age}, object={object_name}, "
          f"level1={level1_category}, level2={level2_category}, level3={level3_category}, character={character}, focus={focus_mode}, request_id={request_id[:8]}...")

    def generate():
        """Generator for SSE stream."""
        try:

            # Build system prompt with age guidance (use cached prompts)
            system_prompt = assistant.prompts['system_prompt']

            age_prompt = ""
            if age is not None:
                age_prompt = assistant.get_age_prompt(age)
                if age_prompt:
                    system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"

            # Get character prompt
            character_prompt = assistant.get_character_prompt(character)
            if character_prompt:
                system_prompt += f"\n\nCHARACTER GUIDANCE:\n{character_prompt}"

            # Get category prompt
            category_prompt = assistant.get_category_prompt(level1_category, level2_category, level3_category)
            if category_prompt:
                system_prompt += f"\n\nCATEGORY GUIDANCE:\n{category_prompt}"

            # Get focus prompt for first question
            focus_prompt = assistant.get_focus_prompt(focus_mode)

            # Initialize conversation history with system prompt
            assistant.conversation_history = [
                {"role": "system", "content": system_prompt}
            ]

            # Introduction content (trigger first question)
            introduction_content = f"Start conversation about {object_name}"

            # Get new event loop for this request (avoids race conditions)
            loop = get_event_loop()

            try:
                async def stream_introduction():
                    # Construct Initial State for Graph
                    initial_state = {
                        "age": age,
                        "messages": assistant.conversation_history.copy(),
                        "content": introduction_content,
                        "status": "normal",
                        "session_id": session_id,
                        "request_id": request_id,
                        "config": assistant.config,
                        "client": assistant.client,
                        "assistant": assistant,
                        "age_prompt": age_prompt,
                        "character_prompt": character_prompt,
                        "object_name": object_name,
                        "level1_category": level1_category,
                        "level2_category": level2_category,
                        "level3_category": level3_category,
                        "correct_answer_count": 0,
                        "category_prompt": category_prompt,
                        "focus_prompt": focus_prompt,
                        "focus_mode": focus_mode,

                        # Initialize outputs
                        "full_response_text": "",
                        "full_question_text": "",
                        "sequence_number": 0,

                        # Initialize flags
                        "is_engaged": None,
                        "is_factually_correct": None,
                        "correctness_reasoning": None,
                        "switch_decision_reasoning": None,
                        "new_object_name": None,
                        "detected_object_name": None,
                        "response_type": "introduction",
                        "suggested_objects": None,
                        "natural_topic_completion": False,
                        "validation_result": {},

                        # Fun fact (grounded)
                        "fun_fact": "",
                        "fun_fact_hook": "",
                        "fun_fact_question": "",
                        "real_facts": "",

                        # Node execution tracing
                        "nodes_executed": [],

                        # Input state snapshot for TraceObject assembly
                        "_input_state_snapshot": {
                            "object_name": assistant.object_name,
                            "age": assistant.age,
                            "correct_answer_count": assistant.correct_answer_count,
                            "content": introduction_content,
                            "conversation_state": assistant.state.value,
                            "guide_phase": assistant.guide_phase,
                            "guide_turn_count": assistant.guide_turn_count,
                            "scaffold_level": assistant.scaffold_level,
                            "hint_given": assistant.hint_given,
                            "focus_mode": focus_mode,
                            "depth_questions_count": assistant.depth_questions_count,
                            "depth_target": assistant.depth_target,
                            "ibpyp_theme_name": assistant.ibpyp_theme_name,
                            "key_concept": assistant.key_concept,
                            "level1_category": assistant.level1_category,
                            "level2_category": assistant.level2_category,
                            "level3_category": assistant.level3_category,
                        },
                    }

                    async for chunk in stream_graph_execution(initial_state):
                        # Yield StreamChunk as SSE event (pass directly for optimized serialization)
                        # Update conversation history with final response
                        if chunk.finish:
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response,
                                "nodes_executed": chunk.nodes_executed or [],
                                "mode": "guide" if chunk.guide_phase else "chat",
                                "_input_state_snapshot": initial_state.get("_input_state_snapshot", {}),
                            })

                        yield sse_event("chunk", chunk)

                    # Send completion event
                    yield sse_event("complete", {"success": True})

                # Stream the introduction
                gen = stream_introduction()
                for event in async_gen_to_sync(gen, loop):
                    yield event

                print(f"[INFO] Session {session_id[:8]}... started successfully")
            finally:
                # Let garbage collection handle loop cleanup (faster and avoids RuntimeError)
                pass

        except GeneratorExit:
            # Client disconnected - stream was interrupted
            print(f"[INFO] Session {session_id[:8]}... client disconnected")
        except Exception as e:
            print(f"[ERROR] Error in start_conversation: {e}")
            import traceback
            traceback.print_exc()
            yield sse_event("error", {"message": str(e)})

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/start-guide', methods=['POST'])
def start_guide_test():
    """
    Start a direct guide mode test - skips introduction, runs theme classification,
    and immediately enters guide phase.

    This endpoint is for testing the Navigator/Driver guide flow without going
    through the normal conversation flow.

    Request body:
        {
            "age": 6 (optional, 3-8),
            "object_name": "banana" (required),
            "character": "teacher" (optional)
        }

    SSE Events:
        - chunk: StreamChunk object (serialized as JSON)
        - complete: Final completion marker
        - error: Error information
    """
    from theme_classifier import classify_object_to_theme
    from google.genai.types import GenerateContentConfig

    data = request.get_json() or {}
    age = data.get('age')
    object_name = data.get('object_name')
    character = data.get('character', 'teacher')

    # Validate required fields
    if not object_name:
        return jsonify({
            "success": False,
            "error": "object_name is required"
        }), 400

    # Validate age
    if age is not None:
        try:
            age = int(age)
            if age < 3 or age > 8:
                print(f"[WARNING] Invalid age {age}, using 6")
                age = 6
        except (ValueError, TypeError):
            print(f"[WARNING] Invalid age format {age}, using 6")
            age = 6
    else:
        age = 6  # Default age for guide testing

    # Create session
    session_id = str(uuid.uuid4())
    assistant = PaixuejiAssistant(client=GLOBAL_GEMINI_CLIENT)
    sessions[session_id] = assistant

    # Store session state
    assistant.age = age
    assistant.object_name = object_name
    assistant.character = character
    assistant.correct_answer_count = 4  # Simulate 4 correct answers

    # Generate unique request ID for this stream
    request_id = str(uuid.uuid4())

    print(f"[INFO] Starting GUIDE TEST session {session_id[:8]}... | age={age}, object={object_name}, character={character}, request_id={request_id[:8]}...")

    def generate():
        """Generator for SSE stream."""
        try:
            # Step 1: Run theme classification SYNCHRONOUSLY
            print(f"[GUIDE-TEST] Running theme classification for '{object_name}'...")

            result = classify_object_to_theme(object_name, assistant.client, assistant.config)

            if result:
                assistant.ibpyp_theme = result.theme_id
                assistant.ibpyp_theme_name = result.theme_name
                assistant.key_concept = result.key_concept
                assistant.bridge_question = result.bridge_question
                print(f"[GUIDE-TEST] Classification complete: theme={result.theme_name}, concept={result.key_concept}")
            else:
                print(f"[GUIDE-TEST] Classification failed, using fallback")
                assistant.ibpyp_theme = "how_the_world_works"
                assistant.ibpyp_theme_name = "How the World Works"
                assistant.key_concept = "Change"
                assistant.bridge_question = f"What happens to {object_name} over time?"

            # Step 2: Enter guide mode
            assistant.enter_guide_mode()
            print(f"[GUIDE-TEST] Entered guide mode, phase={assistant.guide_phase}")

            # Step 3: Build system prompt and initialize conversation
            system_prompt = assistant.prompts['system_prompt']

            age_prompt = assistant.get_age_prompt(age)
            if age_prompt:
                system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"

            character_prompt = assistant.get_character_prompt(character)
            if character_prompt:
                system_prompt += f"\n\nCHARACTER GUIDANCE:\n{character_prompt}"

            # Initialize conversation history with system prompt
            assistant.conversation_history = [
                {"role": "system", "content": system_prompt}
            ]

            # Get new event loop for this request
            loop = get_event_loop()

            try:
                async def stream_bridge():
                    """Stream the bridge question as the first guide turn."""
                    # Build prompt for introducing the bridge question naturally
                    bridge_prompt = f"""You are a friendly teacher guiding a {age}-year-old child.

The child has been learning about "{object_name}" and you want to help them discover something deeper.

Your task: Introduce this question naturally and engagingly:
"{assistant.bridge_question}"

RULES:
- Make it feel like a natural conversation transition
- Be warm and encouraging
- Keep it short (2-3 sentences max)
- End with the question
- Do NOT mention "themes" or "concepts" - just ask naturally
"""

                    # Stream the bridge question
                    full_response = ""
                    seq = 0
                    start_time = time.time()

                    stream = assistant.client.models.generate_content_stream(
                        model=assistant.config["model_name"],
                        contents=bridge_prompt,
                        config=GenerateContentConfig(
                            temperature=0.7,
                            max_output_tokens=200
                        )
                    )

                    for chunk in stream:
                        if chunk.text:
                            full_response += chunk.text
                            seq += 1
                            yield StreamChunk(
                                session_id=session_id,
                                request_id=request_id,
                                sequence_number=seq,
                                response=chunk.text,
                                finish=False,
                                session_finished=False,
                                duration=0.0,
                                timestamp=time.time(),
                                correct_answer_count=4,
                                response_type="guide_bridge",
                                guide_phase=assistant.guide_phase,
                                guide_turn_count=assistant.guide_turn_count,
                                current_object_name=object_name
                            )

                    # Yield final chunk
                    duration = time.time() - start_time
                    yield StreamChunk(
                        session_id=session_id,
                        request_id=request_id,
                        sequence_number=seq + 1,
                        response=full_response,
                        finish=True,
                        session_finished=False,
                        duration=duration,
                        timestamp=time.time(),
                        correct_answer_count=4,
                        response_type="guide_bridge",
                        guide_phase=assistant.guide_phase,
                        guide_turn_count=assistant.guide_turn_count,
                        current_object_name=object_name
                    )

                async def run_stream():
                    async for chunk in stream_bridge():
                        # Update conversation history with final response
                        if chunk.finish:
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response,
                                "mode": "guide",
                            })
                            # Increment guide turn count
                            assistant.guide_turn_count = 1

                        yield sse_event("chunk", chunk)

                    # Send completion event
                    yield sse_event("complete", {"success": True})

                # Stream the response
                gen = run_stream()
                for event in async_gen_to_sync(gen, loop):
                    yield event

                print(f"[GUIDE-TEST] Session {session_id[:8]}... bridge question streamed")
            finally:
                pass

        except GeneratorExit:
            print(f"[INFO] Session {session_id[:8]}... client disconnected")
        except Exception as e:
            print(f"[ERROR] Error in start_guide_test: {e}")
            import traceback
            traceback.print_exc()
            yield sse_event("error", {"message": str(e)})

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/continue', methods=['POST'])
def continue_conversation():
    """
    Continue Paixueji conversation with child's answer and next question.

    Request body:
        {
            "session_id": "...",
            "child_input": "It's red"
        }

    SSE Events:
        - chunk: StreamChunk object (serialized as JSON)
        - complete: Final completion marker
        - error: Error information
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    session_id = data.get('session_id')
    child_input = data.get('child_input')
    focus_mode = data.get('focus_mode', 'depth')  # Default to depth

    if not session_id or not child_input:
        return jsonify({
            "success": False,
            "error": "Missing required fields: session_id and child_input"
        }), 400

    assistant = sessions.get(session_id)

    if not assistant:
        return jsonify({
            "success": False,
            "error": "Session not found. Please start a new conversation."
        }), 404

    # Generate unique request ID for this stream
    request_id = str(uuid.uuid4())

    print(f"[INFO] Session {session_id[:8]}... continuing | answer: '{child_input[:50]}...', "
          f"correct_count: {assistant.correct_answer_count}, focus={focus_mode}, request_id={request_id[:8]}...")

    def generate():
        """Generator for SSE stream."""
        try:

            # Get age prompt if age is set
            age_prompt = ""
            if assistant.age is not None:
                age_prompt = assistant.get_age_prompt(assistant.age)

            # Get character prompt
            character_prompt = assistant.get_character_prompt(assistant.character)

            # Get category prompt
            category_prompt = assistant.get_category_prompt(
                assistant.level1_category,
                assistant.level2_category,
                assistant.level3_category
            )
            
            # Get focus prompt
            focus_prompt = assistant.get_focus_prompt(focus_mode)

            # NOTE: Validation now happens inside graph logic using unified AI validation
            # Increment logic moved to stream handler below based on chunk.is_factually_correct
            # NOTE: User message is added to conversation_history inside call_paixueji_stream()

            # Get new event loop for this request (avoids race conditions)
            loop = get_event_loop()

            try:
                async def stream_response():
                    should_increment = False
                    
                    # Prepare messages (append current user input)
                    # Note: We append here for the Graph execution context, but ONLY append to 
                    # assistant.conversation_history after successful completion/streaming.
                    current_messages = assistant.conversation_history.copy()
                    current_messages.append({"role": "user", "content": child_input})
                    
                    # Construct Initial State
                    initial_state = {
                        "age": assistant.age,
                        "messages": current_messages,
                        "content": child_input,
                        "status": "normal",
                        "session_id": session_id,
                        "request_id": request_id,
                        "config": assistant.config,
                        "client": assistant.client,
                        "assistant": assistant,
                        "age_prompt": age_prompt,
                        "character_prompt": character_prompt,
                        "object_name": assistant.object_name,
                        "level1_category": assistant.level1_category,
                        "level2_category": assistant.level2_category,
                        "level3_category": assistant.level3_category,
                        "correct_answer_count": assistant.correct_answer_count,
                        "category_prompt": category_prompt,
                        "focus_prompt": focus_prompt,
                        "focus_mode": focus_mode,

                        # Initialize outputs
                        "full_response_text": "",
                        "full_question_text": "",
                        "sequence_number": 0,

                        # Initialize flags
                        "is_engaged": None,
                        "is_factually_correct": None,
                        "correctness_reasoning": None,
                        "switch_decision_reasoning": None,
                        "new_object_name": None,
                        "detected_object_name": None,
                        "response_type": None,
                        "suggested_objects": None,
                        "natural_topic_completion": False,
                        "validation_result": {},

                        # Fun fact (not used in continue, but required by state schema)
                        "fun_fact": "",
                        "fun_fact_hook": "",
                        "fun_fact_question": "",
                        "real_facts": "",

                        # Node execution tracing
                        "nodes_executed": [],

                        # Input state snapshot for TraceObject assembly
                        "_input_state_snapshot": {
                            "object_name": assistant.object_name,
                            "age": assistant.age,
                            "correct_answer_count": assistant.correct_answer_count,
                            "content": child_input,
                            "conversation_state": assistant.state.value,
                            "guide_phase": assistant.guide_phase,
                            "guide_turn_count": assistant.guide_turn_count,
                            "scaffold_level": assistant.scaffold_level,
                            "hint_given": assistant.hint_given,
                            "focus_mode": focus_mode,
                            "depth_questions_count": assistant.depth_questions_count,
                            "depth_target": assistant.depth_target,
                            "ibpyp_theme_name": assistant.ibpyp_theme_name,
                            "key_concept": assistant.key_concept,
                            "level1_category": assistant.level1_category,
                            "level2_category": assistant.level2_category,
                            "level3_category": assistant.level3_category,
                        },
                    }

                    async for chunk in stream_graph_execution(initial_state):
                        # NEW: Topic switching and classification now handled in graph nodes
                        # The decision step happens BEFORE response generation
                        # Object name and categories are already updated if switch occurred

                        # Check if we should increment based on factual correctness
                        if chunk.finish and chunk.is_factually_correct:
                            should_increment = True

                        # Update conversation history with final response
                        if chunk.finish:
                            # Also append the USER message to history now that turn is complete
                            # (matches logic in original call_paixueji_stream which did it early,
                            # but safer to do here or assuming app.py handles it?)
                            # Original: "messages.append... assistant.conversation_history.append"
                            # inside stream meant it was added early.
                            # In `continue_conversation` (app.py), we only see:
                            # "if chunk.finish: assistant.conversation_history.append(... response ...)"
                            # WHERE is the user message added to assistant.conversation_history?
                            # In original `call_paixueji_stream`:
                            # "assistant.conversation_history.append({'role': 'user', 'content': content})"
                            # So I MUST do it here too if the graph doesn't mutate assistant history.
                            assistant.conversation_history.append({"role": "user", "content": child_input})

                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response,
                                "nodes_executed": chunk.nodes_executed or [],
                                "mode": "guide" if chunk.guide_phase else "chat",
                                "_input_state_snapshot": initial_state.get("_input_state_snapshot", {}),
                            })

                            # NEW: Increment only if factually correct
                            if should_increment:
                                assistant.increment_correct_answers()
                                # Update chunk with new count so frontend sees it immediately
                                chunk.correct_answer_count = assistant.correct_answer_count
                                print(f"[INFO] Session {session_id[:8]}... factually correct answer | new count: {assistant.correct_answer_count}")
                            elif chunk.is_factually_correct == False:
                                print(f"[INFO] Session {session_id[:8]}... factually incorrect answer | count unchanged: {assistant.correct_answer_count}")
                            elif not chunk.is_engaged:
                                print(f"[INFO] Session {session_id[:8]}... child stuck (not engaged) | count unchanged: {assistant.correct_answer_count}")

                            # Log completion if conversation complete (won't happen now but kept for safety)
                            if chunk.conversation_complete:
                                print(f"[INFO] Session {session_id[:8]}... CONVERSATION COMPLETE!")

                        yield sse_event("chunk", chunk)

                    # Send completion event
                    yield sse_event("complete", {"success": True})

                # Stream the response
                gen = stream_response()
                for event in async_gen_to_sync(gen, loop):
                    yield event

                print(f"[INFO] Session {session_id[:8]}... response streamed successfully")
            finally:
                # Let garbage collection handle loop cleanup (faster and avoids RuntimeError)
                pass

        except GeneratorExit:
            # Client disconnected
            print(f"[INFO] Session {session_id[:8]}... client disconnected")
        except Exception as e:
            print(f"[ERROR] Error in continue_conversation: {e}")
            import traceback
            traceback.print_exc()
            yield sse_event("error", {"message": str(e)})

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/reset', methods=['POST'])
def reset_session():
    """
    Delete a session.

    Request body:
        {
            "session_id": "..."
        }

    Response:
        {
            "success": true/false,
            "error": "..." (if failed)
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    session_id = data.get('session_id')

    if not session_id:
        return jsonify({
            "success": False,
            "error": "Missing session_id"
        }), 400

    if session_id in sessions:
        del sessions[session_id]
        print(f"[INFO] Deleted session {session_id[:8]}...")
        return jsonify({"success": True})

    return jsonify({
        "success": False,
        "error": "Session not found"
    }), 404


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """
    List all active sessions.

    Response:
        {
            "success": true,
            "sessions": ["uuid1", "uuid2"],
            "count": 2
        }
    """
    return jsonify({
        "success": True,
        "sessions": list(sessions.keys()),
        "count": len(sessions)
    })


@app.route('/api/classify', methods=['POST'])
def classify_object():
    """
    Classify an object into level2 category.

    Request body:
        {
            "object_name": "apple"
        }

    Response:
        {
            "success": true,
            "object_name": "apple",
            "level2_category": "fresh_ingredients",
            "level1_category": "foods"
        }
        OR
        {
            "success": true,
            "object_name": "apple",
            "level2_category": "none",
            "level1_category": "none"
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    object_name = data.get('object_name')

    if not object_name:
        return jsonify({
            "success": False,
            "error": "Missing object_name"
        }), 400

    # Create a temporary assistant for classification
    assistant = PaixuejiAssistant(client=GLOBAL_GEMINI_CLIENT)

    try:
        # Run classification synchronously
        assistant.classify_object_sync(object_name)

        # Get results
        level2_category = assistant.level2_category or "none"
        level1_category = assistant.level1_category or "none"

        print(f"[INFO] Classified '{object_name}' -> level2={level2_category}, level1={level1_category}")

        return jsonify({
            "success": True,
            "object_name": object_name,
            "level2_category": level2_category,
            "level1_category": level1_category
        })

    except Exception as e:
        print(f"[ERROR] Classification error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/force-switch', methods=['POST'])
def force_switch():
    """
    Manually force a topic switch when user disagrees with AI decision.

    Request body:
        {
            "session_id": "uuid-string",
            "new_object": "ObjectName"
        }

    Response:
        {
            "success": true,
            "previous_object": "apple",
            "new_object": "banana",
            "message": "Switched to banana"
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    session_id = data.get('session_id')
    new_object = data.get('new_object')

    if not session_id:
        return jsonify({
            "success": False,
            "error": "Missing session_id"
        }), 400

    if not new_object:
        return jsonify({
            "success": False,
            "error": "Missing new_object"
        }), 400

    if session_id not in sessions:
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404

    try:
        assistant = sessions[session_id]

        # Save previous object
        previous_object = assistant.object_name

        # Update object name
        assistant.object_name = new_object

        # Classify new object with timeout
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(assistant.classify_object_sync, new_object)
            try:
                future.result(timeout=1.0)
                print(f"[FORCE-SWITCH] Classification completed for {new_object}")
            except concurrent.futures.TimeoutError:
                print(f"[FORCE-SWITCH] Classification timeout for {new_object}, continuing anyway")

        print(f"[FORCE-SWITCH] User forced switch from {previous_object} to {new_object}")

        return jsonify({
            "success": True,
            "previous_object": previous_object,
            "new_object": new_object,
            "message": f"Switched to {new_object}"
        })

    except Exception as e:
        print(f"[ERROR] Force switch error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================================
# REMOVED: /api/select-object endpoint
# ============================================================================
# Object selection now uses natural language instead of API endpoint:
# - AI suggests objects in response text through /api/continue
# - User types their choice as a regular message
# - Validation detects the SWITCH and processes it through normal flow
# ============================================================================


# ============================================================================
# Background Critique Worker
# ============================================================================

def run_critique_background(task_id: str, session_id: str, transcript: list,
                            object_name: str, key_concept: str, age: int,
                            ibpyp_theme_name: str = None):
    """
    Background worker for critique generation.

    Splits the transcript by mode (chat vs guide), runs the critique pipeline
    separately for each phase, then combines into a single 2-in-1 report.

    Args:
        task_id: Unique identifier for this critique task
        session_id: Session ID being critiqued
        transcript: Conversation transcript [{role, content, mode?, nodes_executed?}, ...]
        object_name: Object being discussed
        key_concept: Key learning concept
        age: Child's age
        ibpyp_theme_name: IB PYP theme name (optional)
    """
    from datetime import datetime
    from pathlib import Path
    from tests.quality.pipeline import PedagogicalCritiquePipeline
    from tests.quality.critique_report import CritiqueReportGenerator

    try:
        critique_tasks[task_id]["status"] = "running"
        logger.info(f"[CRITIQUE] Task {task_id[:8]}... started for session {session_id[:8]}...")

        # Split transcript into chat and guide sub-transcripts by mode
        chat_transcript = []
        guide_transcript = []
        i = 0
        while i < len(transcript) - 2:
            if (transcript[i].get("role") == "model" and
                transcript[i + 1].get("role") == "child" and
                transcript[i + 2].get("role") == "model"):

                mode = transcript[i + 2].get("mode", "chat")
                triplet = [transcript[i], transcript[i + 1], transcript[i + 2]]
                if mode == "guide":
                    guide_transcript.extend(triplet)
                else:
                    chat_transcript.extend(triplet)
                i += 2
            else:
                i += 1

        # Create event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            pipeline = PedagogicalCritiquePipeline(GLOBAL_GEMINI_CLIENT)

            # Run chat pipeline (if chat exchanges exist)
            chat_critique = None
            if chat_transcript:
                logger.info(f"[CRITIQUE] Task {task_id[:8]}... running chat phase ({len(chat_transcript) // 3} exchanges)")
                chat_critique = loop.run_until_complete(
                    pipeline.critique_transcript(
                        transcript=chat_transcript,
                        object_name=object_name,
                        key_concept=f"general knowledge about {object_name}",
                        age=age,
                        mode="chat",
                    )
                )

            # Run guide pipeline (if guide exchanges exist)
            guide_critique = None
            if guide_transcript:
                logger.info(f"[CRITIQUE] Task {task_id[:8]}... running guide phase ({len(guide_transcript) // 3} exchanges)")
                guide_critique = loop.run_until_complete(
                    pipeline.critique_transcript(
                        transcript=guide_transcript,
                        object_name=object_name,
                        key_concept=key_concept,
                        age=age,
                        mode="guide",
                    )
                )
        finally:
            loop.close()

        # Generate combined markdown report
        report_md = CritiqueReportGenerator.to_combined_markdown(
            chat_critique, guide_critique, key_concept=key_concept
        )

        # Save to reports folder
        reports_dir = Path(__file__).parent / "reports" / "AIF"
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_object_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (object_name or "unknown"))
        filename = f"{safe_object_name}_{timestamp}.md"
        report_path = reports_dir / filename

        # Build full report with conversation transcript (with mode labels)
        full_report = f"# Critique Report: {object_name}\n\n"
        full_report += f"**Session:** {session_id}\n"
        full_report += f"**Age:** {age}\n"
        if ibpyp_theme_name:
            full_report += f"**IB PYP Theme:** {ibpyp_theme_name}\n"
        if key_concept:
            full_report += f"**Key Concept:** {key_concept}\n"
        full_report += f"**Date:** {datetime.now().isoformat()}\n\n"
        full_report += "---\n\n"
        full_report += "## Conversation Transcript\n\n"
        for msg in transcript:
            if msg["role"] == "model":
                mode_label = msg.get("mode", "chat").upper()
                nodes_executed = msg.get("nodes_executed", [])
                if nodes_executed:
                    node_names = [n["node"] for n in nodes_executed]
                    total_time = sum(n.get("time_ms", 0) for n in nodes_executed)
                    trace_summary = f"[{' → '.join(node_names)}] ({total_time:.0f}ms)"
                    full_report += f"**Model** `[{mode_label}]`**:** {trace_summary}\n{msg['content']}\n\n"
                else:
                    full_report += f"**Model** `[{mode_label}]`**:** {msg['content']}\n\n"
            else:
                full_report += f"**Child:** {msg['content']}\n\n"
        full_report += "---\n\n"
        full_report += report_md

        report_path.write_text(full_report, encoding='utf-8')

        # Calculate combined effectiveness (weighted average)
        chat_eff = chat_critique.overall_effectiveness if chat_critique else 0
        guide_eff = guide_critique.overall_effectiveness if guide_critique else 0
        chat_n = chat_critique.total_exchanges if chat_critique else 0
        guide_n = guide_critique.total_exchanges if guide_critique else 0
        total_n = chat_n + guide_n
        combined_effectiveness = ((chat_eff * chat_n + guide_eff * guide_n) / total_n) if total_n > 0 else 0

        # Update task status
        critique_tasks[task_id]["status"] = "completed"
        critique_tasks[task_id]["report_path"] = str(report_path)
        critique_tasks[task_id]["overall_effectiveness"] = combined_effectiveness

        logger.info(f"[CRITIQUE] Task {task_id[:8]}... completed | report: {report_path} | "
                     f"chat: {chat_eff:.1f}% ({chat_n}ex) | guide: {guide_eff:.1f}% ({guide_n}ex) | "
                     f"combined: {combined_effectiveness:.1f}%")

    except Exception as e:
        critique_tasks[task_id]["status"] = "failed"
        critique_tasks[task_id]["error"] = str(e)
        logger.error(f"[CRITIQUE] Task {task_id[:8]}... failed: {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# Critique Endpoints for Engineer Review
# ============================================================================

@app.route('/api/critique', methods=['POST'])
def critique_conversation():
    """
    Start a background critique of the current conversation.

    Returns immediately with a task_id. Poll /api/critique/status/<task_id>
    to check progress, then GET /api/critique/report/<task_id> to retrieve.

    Request body:
        {
            "session_id": "uuid-string"
        }

    Response:
        {
            "success": true,
            "task_id": "uuid-string",
            "message": "Critique started. Poll /api/critique/status/<task_id> for progress."
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    session_id = data.get('session_id')

    if not session_id:
        return jsonify({
            "success": False,
            "error": "Missing session_id"
        }), 400

    if session_id not in sessions:
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404

    assistant = sessions[session_id]

    # Build transcript from conversation history (with node execution traces + mode)
    transcript = []
    for msg in assistant.conversation_history:
        if msg["role"] == "system":
            continue
        role = "model" if msg["role"] == "assistant" else "child"
        entry = {"role": role, "content": msg["content"]}
        if role == "model":
            if "nodes_executed" in msg:
                entry["nodes_executed"] = msg["nodes_executed"]
            entry["mode"] = msg.get("mode", "chat")
        transcript.append(entry)

    if len(transcript) < 3:
        return jsonify({
            "success": False,
            "error": "Need at least one complete exchange (model→child→model) to critique"
        }), 400

    # Create task entry
    task_id = str(uuid.uuid4())
    critique_tasks[task_id] = {
        "status": "pending",
        "session_id": session_id,
        "report_path": None,
        "error": None,
        "overall_effectiveness": None,
        "started_at": time.time()
    }

    # Capture session state for background worker (session may be deleted while critique runs)
    object_name = assistant.object_name
    key_concept = assistant.key_concept or "learning objective"
    ibpyp_theme_name = assistant.ibpyp_theme_name
    age = assistant.age or 6

    # Spawn background worker
    thread = threading.Thread(
        target=run_critique_background,
        args=(task_id, session_id, transcript, object_name, key_concept, age, ibpyp_theme_name),
        daemon=True
    )
    thread.start()

    logger.info(f"[CRITIQUE] Task {task_id[:8]}... spawned for session {session_id[:8]}...")

    return jsonify({
        "success": True,
        "task_id": task_id,
        "message": "Critique started. Poll /api/critique/status/<task_id> for progress."
    })


@app.route('/api/critique/status/<task_id>', methods=['GET'])
def critique_status(task_id):
    """
    Check status of a background critique task.

    Response:
        {
            "success": true,
            "task_id": "uuid-string",
            "status": "pending" | "running" | "completed" | "failed",
            "report_path": "reports/banana_20260207.md" (if completed),
            "overall_effectiveness": 75.5 (if completed),
            "error": "..." (if failed),
            "elapsed_seconds": 15.2
        }
    """
    if task_id not in critique_tasks:
        return jsonify({
            "success": False,
            "error": "Task not found"
        }), 404

    task = critique_tasks[task_id]
    return jsonify({
        "success": True,
        "task_id": task_id,
        "status": task["status"],
        "session_id": task["session_id"],
        "report_path": task["report_path"],
        "overall_effectiveness": task["overall_effectiveness"],
        "error": task["error"],
        "elapsed_seconds": round(time.time() - task["started_at"], 1)
    })


@app.route('/api/exchanges/<session_id>', methods=['GET'])
def get_exchanges(session_id):
    """
    Extract exchange triplets (model→child→model) from conversation history.

    Returns structured exchanges for the manual critique form.

    Response:
        {
            "success": true,
            "exchanges": [
                {
                    "index": 1,
                    "model_question": "...",
                    "child_response": "...",
                    "model_response": "...",
                    "nodes_executed": [...]
                }
            ],
            "object_name": "apple",
            "age": 6
        }
    """
    assistant = sessions.get(session_id)

    if not assistant:
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404

    # Build transcript from conversation history (skip system message)
    transcript = []
    for msg in assistant.conversation_history:
        if msg["role"] == "system":
            continue
        role = "model" if msg["role"] == "assistant" else "child"
        entry = {"role": role, "content": msg["content"]}
        if role == "model":
            if "nodes_executed" in msg:
                entry["nodes_executed"] = msg["nodes_executed"]
            entry["mode"] = msg.get("mode", "chat")
        transcript.append(entry)

    # Extract triplets: model → child → model
    exchanges = []
    exchange_index = 0
    i = 0
    while i < len(transcript) - 2:
        if (transcript[i].get("role") == "model" and
            transcript[i + 1].get("role") == "child" and
            transcript[i + 2].get("role") == "model"):

            exchange_index += 1
            exchanges.append({
                "index": exchange_index,
                "model_question": transcript[i]["content"],
                "child_response": transcript[i + 1]["content"],
                "model_response": transcript[i + 2]["content"],
                "nodes_executed": transcript[i + 2].get("nodes_executed", []),
                "mode": transcript[i + 2].get("mode", "chat"),
            })
            i += 2  # Move past child response, next iteration checks from model response
        else:
            i += 1

    return jsonify({
        "success": True,
        "exchanges": exchanges,
        "object_name": assistant.object_name,
        "age": assistant.age,
        "key_concept": assistant.key_concept,
        "ibpyp_theme_name": assistant.ibpyp_theme_name
    })


@app.route('/api/manual-critique', methods=['POST'])
def manual_critique():
    """
    Save a manual (human feedback) critique report.

    Request body:
        {
            "session_id": "uuid",
            "exchange_critiques": [
                {
                    "exchange_index": 1,
                    "model_question_expected": "...",
                    "model_question_problem": "...",
                    "model_response_expected": "...",
                    "model_response_problem": "...",
                    "conclusion": "..."
                }
            ],
            "global_conclusion": "..."
        }

    Response:
        {
            "success": true,
            "report_path": "reports/HF/apple_20260209_143045.md",
            "exchanges_critiqued": 2
        }
    """
    from datetime import datetime
    from pathlib import Path

    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    session_id = data.get('session_id')
    exchange_critiques = data.get('exchange_critiques', [])
    global_conclusion = data.get('global_conclusion', '')

    if not session_id:
        return jsonify({
            "success": False,
            "error": "Missing session_id"
        }), 400

    if not exchange_critiques:
        return jsonify({
            "success": False,
            "error": "At least one exchange must be critiqued"
        }), 400

    assistant = sessions.get(session_id)

    if not assistant:
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404

    # Build transcript from conversation history (with node traces + mode)
    transcript = []
    for msg in assistant.conversation_history:
        if msg["role"] == "system":
            continue
        role = "model" if msg["role"] == "assistant" else "child"
        entry = {"role": role, "content": msg["content"]}
        if role == "model":
            if "nodes_executed" in msg:
                entry["nodes_executed"] = msg["nodes_executed"]
            entry["mode"] = msg.get("mode", "chat")
        transcript.append(entry)

    # Re-extract all exchanges to match indices
    all_exchanges = []
    i = 0
    while i < len(transcript) - 2:
        if (transcript[i].get("role") == "model" and
            transcript[i + 1].get("role") == "child" and
            transcript[i + 2].get("role") == "model"):
            all_exchanges.append({
                "model_question": transcript[i]["content"],
                "child_response": transcript[i + 1]["content"],
                "model_response": transcript[i + 2]["content"],
                "question_nodes_executed": transcript[i].get("nodes_executed", []),
                "nodes_executed": transcript[i + 2].get("nodes_executed", []),
                "mode": transcript[i + 2].get("mode", "chat"),
            })
            i += 2
        else:
            i += 1

    try:
        report_md = build_human_feedback_report(
            object_name=assistant.object_name,
            age=assistant.age,
            session_id=session_id,
            transcript=transcript,
            all_exchanges=all_exchanges,
            exchange_critiques=exchange_critiques,
            global_conclusion=global_conclusion,
            key_concept=assistant.key_concept,
        )

        # Save to reports/HF/
        reports_dir = Path(__file__).parent / "reports" / "HF"
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_object_name = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in (assistant.object_name or "unknown")
        )
        filename = f"{safe_object_name}_{timestamp}.md"
        report_path = reports_dir / filename

        report_path.write_text(report_md, encoding='utf-8')

        logger.info(f"[MANUAL-CRITIQUE] Report saved: {report_path} | "
                     f"exchanges critiqued: {len(exchange_critiques)}")

        # Assemble TraceObjects for each critiqued exchange
        from trace_assembler import assemble_trace_object, save_trace_object
        trace_paths = []
        saved_traces = []
        for ec in exchange_critiques:
            idx = ec.get("exchange_index")
            if idx is None or idx < 1 or idx > len(all_exchanges):
                continue
            try:
                trace_obj = assemble_trace_object(
                    session_id, assistant, idx, all_exchanges[idx - 1], ec
                )
                trace_path = save_trace_object(trace_obj)
                trace_paths.append(trace_path)
                saved_traces.append(trace_obj)
            except Exception as trace_err:
                logger.warning(f"[MANUAL-CRITIQUE] Failed to assemble trace for exchange {idx}: {trace_err}")

        # Build one item per distinct (trace_id, culprit_name) pair so the UI
        # renders one optimization button per culprit, not per exchange.
        from trace_schema import effective_culprits as _effective_culprits
        seen = set()
        trace_items = []
        for t in saved_traces:
            for c in _effective_culprits(t):
                if not c.culprit_name or c.culprit_name == "unknown":
                    continue
                key = (t.trace_id, c.culprit_name)
                if key not in seen:
                    seen.add(key)
                    trace_items.append({
                        "exchange_index": t.exchange_index,
                        "trace_id": t.trace_id,
                        "culprit_name": c.culprit_name,
                        "prompt_template_name": c.prompt_template_name,
                    })

        return jsonify({
            "success": True,
            "report_path": str(report_path),
            "exchanges_critiqued": len(exchange_critiques),
            "trace_paths": trace_paths,
            "traces_assembled": len(trace_paths),
            "traces": trace_items,
        })

    except Exception as e:
        logger.error(f"[MANUAL-CRITIQUE] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================================
# Prompt Optimization Endpoints
# ============================================================================

@app.route('/api/optimize-prompt', methods=['POST'])
def optimize_prompt():
    """
    Run prompt optimization for a given culprit.

    Request body:
        {
            "culprit_name": "generate_fun_fact",
            "prompt_name": null,   # optional explicit override
            "trace_id": null       # optional; if provided, only that trace is used
        }

    When trace_id is provided the optimizer runs in single-trace mode, which
    prevents stale historical traces from diluting or reverting recent fixes.
    Omit trace_id (or pass null) to use all historical traces for the culprit.

    Response: full OptimizationResult JSON (optimization_id, failure_pattern,
              rationale, original_prompt, optimized_prompt, preview_response, ...)
    """
    from prompt_optimizer import run_optimization

    data = request.get_json() or {}
    culprit_name = data.get("culprit_name")
    prompt_name = data.get("prompt_name")  # optional
    trace_id = data.get("trace_id")        # optional; enables single-trace mode

    if not culprit_name:
        return jsonify({"success": False, "error": "culprit_name is required"}), 400

    try:
        result = run_optimization(
            client=GLOBAL_GEMINI_CLIENT,
            config=_load_config(),
            culprit_name=culprit_name,
            prompt_name=prompt_name or None,
            trace_id=trace_id or None,
        )
        return jsonify(result.model_dump())
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"[OPTIMIZE] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/optimize-prompt/<optimization_id>/approve', methods=['POST'])
def approve_optimization(optimization_id):
    """
    Approve a pending optimization: merge into prompt_overrides.json and archive.

    Response: {"status": "approved", "prompt_name": ..., "optimization_id": ...}
    """
    from pathlib import Path
    from trace_schema import OptimizationResult
    from prompt_optimizer import save_optimization

    pending_path = Path(__file__).parent / "optimizations" / "pending" / f"{optimization_id}.json"

    if not pending_path.exists():
        return jsonify({"success": False, "error": "Pending optimization not found"}), 404

    try:
        result = OptimizationResult.model_validate_json(
            pending_path.read_text(encoding="utf-8")
        )
        save_optimization(result, approved=True)
        logger.info(f"[OPTIMIZE] Approved optimization {optimization_id} for '{result.prompt_name}'")
        return jsonify({
            "status": "approved",
            "prompt_name": result.prompt_name,
            "optimization_id": optimization_id,
        })
    except Exception as e:
        logger.error(f"[OPTIMIZE] Approval error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/optimize-prompt/<optimization_id>/refine', methods=['POST'])
def refine_optimization(optimization_id):
    """
    Re-run optimization with human rejection feedback.

    Body: {"rejection_reason": "The suggested fix is still too abstract..."}
    Response: new full OptimizationResult JSON
    """
    from pathlib import Path
    from trace_schema import OptimizationResult
    from prompt_optimizer import run_refinement

    data = request.get_json() or {}
    rejection_reason = data.get("rejection_reason", "").strip()
    if not rejection_reason:
        return jsonify({"success": False, "error": "rejection_reason is required"}), 400

    pending_path = Path(__file__).parent / "optimizations" / "pending" / f"{optimization_id}.json"
    if not pending_path.exists():
        return jsonify({"success": False, "error": "Pending optimization not found"}), 404

    try:
        previous_result = OptimizationResult.model_validate_json(
            pending_path.read_text(encoding="utf-8")
        )
        new_result = run_refinement(
            client=GLOBAL_GEMINI_CLIENT,
            config=_load_config(),
            previous_result=previous_result,
            rejection_reason=rejection_reason,
        )
        return jsonify(new_result.model_dump())
    except Exception as e:
        logger.error(f"[OPTIMIZE] Refine error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/optimize-prompt/<optimization_id>/reject', methods=['POST'])
def reject_optimization(optimization_id):
    """
    Reject a pending optimization: delete the pending file.

    Response: {"status": "rejected"}
    """
    from pathlib import Path

    pending_path = Path(__file__).parent / "optimizations" / "pending" / f"{optimization_id}.json"

    if pending_path.exists():
        pending_path.unlink()
        logger.info(f"[OPTIMIZE] Rejected and deleted pending optimization {optimization_id}")

    return jsonify({"status": "rejected"})


def _load_config() -> dict:
    """Load config.json (used by optimization endpoints that run outside request context)."""
    import os
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, "r") as f:
        return json.load(f)


def build_human_feedback_report(object_name, age, session_id, transcript,
                                 all_exchanges, exchange_critiques,
                                 global_conclusion, key_concept=None):
    """
    Generate a markdown report for human feedback critique.

    Structures the report into Chat Phase and Guide Phase sections,
    mirroring the two-phase structure of the AI critique report.

    Args:
        object_name: Object being discussed
        age: Child's age
        session_id: Session ID
        transcript: Full conversation transcript [{role, content, nodes_executed?, mode?}]
        all_exchanges: All extracted exchanges (list of dicts with mode)
        exchange_critiques: User-submitted critiques (list of dicts)
        global_conclusion: Overall conclusion text
        key_concept: Key concept being taught in guide phase

    Returns:
        str: Markdown report content
    """
    from datetime import datetime

    total_exchanges = len(all_exchanges)
    critiqued_count = len(exchange_critiques)

    report = f"# Human Feedback Critique Report: {object_name}\n\n"
    report += f"**Session:** {session_id}\n"
    report += f"**Age:** {age}\n"
    if key_concept:
        report += f"**Key Concept:** {key_concept}\n"
    report += f"**Date:** {datetime.now().isoformat()}\n"
    report += f"**Feedback Type:** Manual (Human)\n"
    report += f"**Exchanges Critiqued:** {critiqued_count} / {total_exchanges}\n\n"
    report += "---\n\n"

    # Conversation transcript (with mode labels)
    report += "## Conversation Transcript\n\n"
    for msg in transcript:
        if msg["role"] == "model":
            mode_label = msg.get("mode", "chat").upper()
            nodes_executed = msg.get("nodes_executed", [])
            if nodes_executed:
                node_names = [n["node"] for n in nodes_executed]
                total_time = sum(n.get("time_ms", 0) for n in nodes_executed)
                trace_summary = f"[{' → '.join(node_names)}] ({total_time:.0f}ms)"
                report += f"**Model** `[{mode_label}]`**:** {trace_summary}\n{msg['content']}\n\n"
            else:
                report += f"**Model** `[{mode_label}]`**:** {msg['content']}\n\n"
        else:
            report += f"**Child:** {msg['content']}\n\n"

    report += "---\n\n"

    # Build critiqued exchange lookup: index → critique data
    critique_by_index = {ec["exchange_index"]: ec for ec in exchange_critiques}

    # Classify exchanges by mode
    chat_critiqued = []
    guide_critiqued = []
    for ec in exchange_critiques:
        idx = ec["exchange_index"]
        if idx < 1 or idx > total_exchanges:
            continue
        exchange = all_exchanges[idx - 1]
        mode = exchange.get("mode", "chat")
        if mode == "guide":
            guide_critiqued.append((idx, exchange, ec))
        else:
            chat_critiqued.append((idx, exchange, ec))

    # Chat Phase section
    if chat_critiqued:
        report += "## Chat Phase — Human Critique\n\n"
        report += "> Exploratory Q&A. NOT evaluated for key concept guidance.\n\n"
        for idx, exchange, ec in chat_critiqued:
            report += _render_hf_exchange(idx, exchange, ec)
        report += "\n"

    # Separator between phases
    if chat_critiqued and guide_critiqued:
        report += "---\n\n"

    # Guide Phase section
    if guide_critiqued:
        report += "## Guide Phase — Human Critique\n\n"
        concept_display = key_concept or "unknown"
        report += f"> Key Concept: **{concept_display}**. Evaluated for concept advancement.\n\n"
        for idx, exchange, ec in guide_critiqued:
            report += _render_hf_exchange(idx, exchange, ec)
        report += "\n"

    # Fallback: if no exchanges were critiqued in either phase, show empty section
    if not chat_critiqued and not guide_critiqued:
        report += "## Detailed Exchange Analysis\n\n"
        report += "*No exchanges were critiqued.*\n\n"

    # Global conclusion
    if global_conclusion and global_conclusion.strip():
        report += f"## Global Conclusion\n\n{global_conclusion.strip()}\n"

    return report


def _render_hf_exchange(idx, exchange, ec):
    """Render a single HF exchange critique as markdown."""
    report = f"### Exchange {idx}\n\n"
    report += f"**Model asked:** \"{exchange['model_question']}\"\n\n"
    report += f"**Child said:** \"{exchange['child_response']}\"\n\n"
    report += f"**Model responded:** \"{exchange['model_response']}\"\n\n"

    # Node execution trace
    nodes_executed = exchange.get("nodes_executed", [])
    if nodes_executed:
        report += "#### Node Execution Trace\n\n"
        report += "| Node | Time | State Changes |\n"
        report += "|------|------|---------------|\n"
        for node in nodes_executed:
            node_name = node.get("node", "?")
            time_ms = node.get("time_ms", 0)
            changes = node.get("state_changes", {})
            changes_str = ", ".join(
                f"{k}: {v}" for k, v in changes.items()
            ) if changes else "-"
            report += f"| {node_name} | {time_ms:.0f}ms | {changes_str} |\n"
        report += "\n"

    # Human critique sections
    report += "#### Human Critique\n\n"

    mq_expected = ec.get("model_question_expected", "").strip()
    mq_problem = ec.get("model_question_problem", "").strip()
    if mq_expected or mq_problem:
        report += "**Model Question:**\n"
        if mq_expected:
            report += f"- *What is expected:* {mq_expected}\n"
        if mq_problem:
            report += f"- *Why is it problematic:* {mq_problem}\n"
        report += "\n"

    mr_expected = ec.get("model_response_expected", "").strip()
    mr_problem = ec.get("model_response_problem", "").strip()
    if mr_expected or mr_problem:
        report += "**Model Response:**\n"
        if mr_expected:
            report += f"- *What is expected:* {mr_expected}\n"
        if mr_problem:
            report += f"- *Why is it problematic:* {mr_problem}\n"
        report += "\n"

    conclusion = ec.get("conclusion", "").strip()
    if conclusion:
        report += f"#### Conclusion\n\n{conclusion}\n\n"

    report += "---\n\n"
    return report


@app.route('/api/critique/report/<task_id>', methods=['GET'])
def get_critique_report(task_id):
    """
    Retrieve the generated critique report content.

    Response:
        {
            "success": true,
            "report_content": "# Critique Report...",
            "report_path": "reports/banana_20260207.md",
            "overall_effectiveness": 75.5
        }
    """
    from pathlib import Path

    if task_id not in critique_tasks:
        return jsonify({
            "success": False,
            "error": "Task not found"
        }), 404

    task = critique_tasks[task_id]

    if task["status"] == "pending":
        return jsonify({
            "success": False,
            "error": "Task is pending, not yet started"
        }), 400

    if task["status"] == "running":
        return jsonify({
            "success": False,
            "error": f"Task is still running ({round(time.time() - task['started_at'], 1)}s elapsed)"
        }), 400

    if task["status"] == "failed":
        return jsonify({
            "success": False,
            "error": f"Task failed: {task['error']}"
        }), 400

    # Status is "completed"
    report_path = Path(task["report_path"])
    if not report_path.exists():
        return jsonify({
            "success": False,
            "error": "Report file not found on disk"
        }), 404

    return jsonify({
        "success": True,
        "report_content": report_path.read_text(encoding='utf-8'),
        "report_path": str(report_path),
        "overall_effectiveness": task["overall_effectiveness"]
    })


def async_gen_to_sync(async_gen, loop):
    """
    Bridge async generator to sync generator WITHOUT buffering.

    This uses a queue and background thread to immediately yield chunks
    as they arrive from the async generator, enabling real streaming.

    Args:
        async_gen: Async generator to bridge
        loop: Event loop to run async generator in

    Yields:
        Items from async generator in real-time
    """
    import queue
    import threading

    chunk_queue = queue.Queue()
    exception_holder = [None]

    def run_async():
        """Runs in background thread to consume async generator."""
        try:
            async def consume():
                async for item in async_gen:
                    chunk_queue.put(('chunk', item))
                chunk_queue.put(('done', None))
            loop.run_until_complete(consume())
        except Exception as e:
            exception_holder[0] = e
            chunk_queue.put(('error', e))

    # Start background thread
    thread = threading.Thread(target=run_async, daemon=True)
    thread.start()

    # Yield chunks as they arrive
    while True:
        msg_type, data = chunk_queue.get()  # Blocks until chunk available
        if msg_type == 'chunk':
            yield data
        elif msg_type == 'done':
            break
        elif msg_type == 'error':
            raise exception_holder[0]


if __name__ == '__main__':
    print("=" * 60)
    print("Paixueji Assistant - Question-Asking System")
    print("=" * 60)
    print("\nServer starting...")
    print("URL: http://localhost:5000")
    print("\nEndpoints:")
    print("  GET  /api/health          - Health check")
    print("  POST /api/start           - Start conversation (SSE)")
    print("                              Requires: age, object_name, level1_category")
    print("  POST /api/continue        - Continue conversation (SSE)")
    print("                              Requires: session_id, child_input")
    print("  POST /api/classify        - Classify object into categories")
    print("                              Requires: object_name")
    print("  POST /api/reset           - Delete session")
    print("  GET  /api/sessions        - List active sessions")
    print("  GET  /                    - Web interface")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
