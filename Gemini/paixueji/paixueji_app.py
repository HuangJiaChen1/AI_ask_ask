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

# Initialize global Gemini client to enable connection reuse
def init_global_client():
    """Initialize a global Gemini client instance to avoid cold starts."""
    try:
        config_path = "config.json"
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

    # Initialize flow tree for debugging
    assistant.init_flow_tree(session_id, age, object_name, character, focus_mode)

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
                    }
                    
                    async for chunk in stream_graph_execution(initial_state):
                        # Yield StreamChunk as SSE event (pass directly for optimized serialization)
                        # Update conversation history with final response
                        if chunk.finish:
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response
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
                                "content": chunk.response
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


@app.route('/api/debug/flow-tree/<session_id>', methods=['GET'])
def get_flow_tree(session_id):
    """
    Retrieve conversation flow tree for debugging.

    Args:
        session_id: Session ID to retrieve tree for

    Query params:
        format: 'json' (default) | 'mermaid'

    Response:
        - format=json: Raw JSON tree structure
        - format=mermaid: Mermaid diagram syntax
    """
    assistant = sessions.get(session_id)

    if not assistant:
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404

    if not assistant.flow_tree:
        return jsonify({
            "success": False,
            "error": "Flow tree not initialized for this session"
        }), 404

    output_format = request.args.get('format', 'json')

    try:
        if output_format == 'json':
            return jsonify({
                "success": True,
                "tree": assistant.flow_tree.to_json()
            })

        elif output_format == 'mermaid':
            mermaid_diagram = convert_tree_to_mermaid(assistant.flow_tree)
            return jsonify({
                "success": True,
                "diagram": mermaid_diagram
            })

        else:
            return jsonify({
                "success": False,
                "error": f"Invalid format: {output_format}"
            }), 400

    except Exception as e:
        print(f"[ERROR] Flow tree retrieval error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def escape_mermaid_text(text):
    """Escape text for Mermaid diagram labels."""
    if not text:
        return "N/A"
    # Escape quotes and handle newlines
    # 1. Replace double quotes with single quotes to avoid breaking label syntax
    # 2. Replace newlines with <br/> for formatting
    # 3. Escape special characters if necessary (keeping it simple for now)
    return str(text).replace('"', "'").replace('\n', '<br/>')


def convert_tree_to_mermaid(flow_tree):
    """Convert flow tree to Mermaid diagram syntax with comprehensive debugging info."""
    lines = ["graph TD"]
    
    # Strategy descriptions for readable intent
    FOCUS_DESCRIPTIONS = {
        "depth": "Dive Deeper (Features/Uses)",
        "width_shape": "Width: Same Shape",
        "width_color": "Width: Same Color",
        "width_category": "Width: Same Category"
    }

    # Track previous output node to connect turns
    previous_output_id = None

    for node in flow_tree.nodes:
        node_id = node.node_id
        
        # Create a subgraph for this turn to group related steps
        lines.append(f'    subgraph Turn_{node.turn_number} ["🔄 Turn {node.turn_number}: {node.type.upper()}"]')
        lines.append('    direction TB')

        # === 1. USER INPUT ===
        input_id = f"{node_id}_input"
        input_content = "Start of Conversation"
        if node.user_input:
            input_content = escape_mermaid_text(node.user_input)
        elif node.turn_number > 0:
            input_content = "(No Input / System Trigger)"
            
        lines.append(f'    {input_id}["👤 User Input:<br/>{input_content}"]')
        lines.append(f'    style {input_id} fill:#e3f2fd,stroke:#2196f3,stroke-width:2px')

        # === 2. DECISION LOGIC & CONTEXT ===
        # Gather all context and reasoning
        logic_id = f"{node_id}_logic"
        logic_lines = []
        
        # Context (Object + Character + Score)
        obj = node.state_before.get('object_name', 'N/A')
        character = node.state_before.get('character', 'Default')
        score = node.state_before.get('correct_answer_count', 0)
        logic_lines.append(f"<b>Context:</b> Object='{obj}' | Character='{character}' | Score={score}")
        
        # Active Strategy (Focus Mode)
        focus_mode = node.state_before.get('focus_mode')
        if focus_mode:
            strategy_desc = FOCUS_DESCRIPTIONS.get(focus_mode, focus_mode)
            logic_lines.append(f"<b>Strategy:</b> {strategy_desc}")

        # Validation Info
        if node.validation:
            engaged = node.validation.get('is_engaged')
            correct = node.validation.get('is_factually_correct')
            
            status_icon = "⚪"
            if engaged is False: status_icon = "❌ STUCK"
            elif correct is True: status_icon = "✅ CORRECT"
            elif correct is False: status_icon = "❌ WRONG"
            
            logic_lines.append(f"<b>Validation:</b> {status_icon}")
            
            if node.validation.get('correctness_reasoning'):
                logic_lines.append(f"<i>Reasoning:</i> {escape_mermaid_text(node.validation['correctness_reasoning'])}")
        
        # Decision Info (Switching)
        if node.decision:
            dec_type = node.decision.get('decision_type')
            detected = node.decision.get('detected_object')
            
            logic_lines.append(f"<b>Decision:</b> {dec_type}")
            if detected:
                logic_lines.append(f"<i>Detected Object:</i> {detected}")
            
            if node.decision.get('switch_reasoning'):
                logic_lines.append(f"<i>Logic:</i> {escape_mermaid_text(node.decision['switch_reasoning'])}")

        logic_content = "<br/>".join(logic_lines) if logic_lines else "No logic data"
        lines.append(f'    {logic_id}["🧠 Logic & Analysis:<br/>{logic_content}"]')
        lines.append(f'    style {logic_id} fill:#fff9c4,stroke:#fbc02d,stroke-width:2px')

        # === 3. SYSTEM ACTION ===
        action_id = f"{node_id}_action"
        action_lines = []
        
        action_lines.append(f"<b>Route:</b> {node.type}")
        
        # State Changes
        if node.state_after:
            changes = []
            for k, v in node.state_after.items():
                old_v = node.state_before.get(k)
                if v != old_v:
                    changes.append(f"{k}: {old_v} -> {v}")
            
            if changes:
                action_lines.append("<b>State Updates:</b><br/>" + "<br/>".join(changes))
        
        action_content = "<br/>".join(action_lines)
        lines.append(f'    {action_id}["⚙️ System Action:<br/>{action_content}"]')
        lines.append(f'    style {action_id} fill:#f3e5f5,stroke:#9c27b0,stroke-width:2px')

        # === 4. AI RESPONSE (Split into Parts) ===
        output_id = f"{node_id}_output"
        
        # Check if we have split parts (for dual-parallel turns)
        has_split_parts = getattr(node, 'ai_response_part1', None) or getattr(node, 'ai_response_part2', None)
        
        if has_split_parts:
            # PART 1: Feedback / Explanation / Correction
            part1_content = "(None)"
            if node.ai_response_part1:
                part1_content = escape_mermaid_text(node.ai_response_part1)
                
            part1_id = f"{node_id}_resp1"
            lines.append(f'    {part1_id}["🗣️ Feedback / Explanation:<br/>{part1_content}"]')
            lines.append(f'    style {part1_id} fill:#c8e6c9,stroke:#388e3c,stroke-width:2px')
            
            # PART 2: Follow-up Question
            part2_content = "(None)"
            if node.ai_response_part2:
                part2_content = escape_mermaid_text(node.ai_response_part2)
                
            part2_id = f"{node_id}_resp2"
            lines.append(f'    {part2_id}["❓ Follow-up Question:<br/>{part2_content}"]')
            lines.append(f'    style {part2_id} fill:#b3e5fc,stroke:#0288d1,stroke-width:2px')
            
            # Link Action -> Part 1 -> Part 2
            lines.append(f'    {action_id} --> {part1_id}')
            lines.append(f'    {part1_id} --> {part2_id}')
            
            # Set output_id to the last part for the next turn's link
            output_id = part2_id
            
        else:
            # Legacy/Introduction turns (single response)
            output_content = "(Generating...)"
            if node.ai_response:
                output_content = escape_mermaid_text(node.ai_response)
            
            lines.append(f'    {output_id}["🤖 AI Response:<br/>{output_content}"]')
            lines.append(f'    style {output_id} fill:#e8f5e9,stroke:#4caf50,stroke-width:2px')
            
            lines.append(f'    {action_id} --> {output_id}')

        # === INTERNAL SUBGRAPH LINKS ===
        lines.append(f'    {input_id} --> {logic_id}')
        lines.append(f'    {logic_id} --> {action_id}')
        
        lines.append('    end') # End subgraph

        # === LINK TO PREVIOUS TURN ===
        if previous_output_id:
            lines.append(f'    {previous_output_id} --> {input_id}')
        
        previous_output_id = output_id

    return "\n".join(lines)


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
# Bug Reproduction Helper Functions
# ============================================================================

def build_save_state(assistant, session_id):
    """
    Build complete save state from PaixuejiAssistant instance.

    IMPORTANT: Now keeps the FULL conversation including the last assistant message
    (buggy response) for bug tracking purposes. Marks the buggy response index in metadata.

    Args:
        assistant: PaixuejiAssistant instance to serialize
        session_id: Current session ID

    Returns:
        dict: Complete save state matching schema
    """
    from datetime import datetime

    # Copy conversation history - keep FULL conversation including buggy response
    conversation_history = assistant.conversation_history.copy()

    # Track buggy response index and metadata
    excluded_buggy_response = None
    last_user_message = None
    buggy_response_index = None

    if len(conversation_history) > 1 and conversation_history[-1]['role'] == 'assistant':
        # Mark the buggy response index (last assistant message)
        buggy_response_index = len(conversation_history) - 1
        excluded_buggy_response = conversation_history[-1]['content']  # Keep for reference

        # Find the last user message
        for msg in reversed(conversation_history):
            if msg['role'] == 'user':
                last_user_message = msg['content']
                break

    state = {
        "metadata": {
            "saved_at": datetime.now().isoformat(),
            "version": "1.0",
            "session_id": session_id,
            "app_version": "paixueji-v1.0",
            "excluded_buggy_response": excluded_buggy_response,
            "last_user_message": last_user_message,
            "buggy_response_index": buggy_response_index
        },
        "session_state": {
            "age": assistant.age,
            "object_name": assistant.object_name,
            "level1_category": assistant.level1_category,
            "level2_category": assistant.level2_category,
            "level3_category": assistant.level3_category,
            "character": assistant.character,
            "correct_answer_count": assistant.correct_answer_count,
            "system_managed_focus": assistant.system_managed_focus,
            "current_focus_mode": assistant.current_focus_mode,
            "depth_questions_count": assistant.depth_questions_count,
            "width_wrong_count": assistant.width_wrong_count,
            "width_categories_tried": assistant.width_categories_tried.copy(),
            "depth_target": assistant.depth_target
        },
        "conversation_history": conversation_history
    }

    # Add flow tree if available
    if assistant.flow_tree:
        try:
            state["flow_tree"] = assistant.flow_tree.to_json()
        except Exception as e:
            print(f"[WARNING] Could not serialize flow tree: {e}")
            state["flow_tree"] = None

    return state


def validate_state_schema(state):
    """
    Validate saved state schema.

    Args:
        state: State dict to validate

    Returns:
        tuple: (is_valid, error_message)
    """
    # Check top-level keys
    if not all(k in state for k in ['metadata', 'session_state', 'conversation_history']):
        return False, "Missing required top-level keys (metadata, session_state, or conversation_history)"

    # Check metadata
    if 'version' not in state['metadata']:
        return False, "Missing metadata.version"

    if state['metadata']['version'] != '1.0':
        return False, f"Unsupported schema version: {state['metadata']['version']}"

    # Check session_state required fields
    required_session_fields = ['object_name', 'correct_answer_count']
    for field in required_session_fields:
        if field not in state['session_state']:
            return False, f"Missing session_state.{field}"

    # Check conversation_history is array
    if not isinstance(state['conversation_history'], list):
        return False, "conversation_history must be an array"

    # Validate each message
    for i, msg in enumerate(state['conversation_history']):
        if 'role' not in msg or 'content' not in msg:
            return False, f"Message {i} missing role or content"
        if msg['role'] not in ['system', 'user', 'assistant']:
            return False, f"Message {i} has invalid role: {msg['role']}"

    # Validate data types and ranges
    if state['session_state'].get('age') is not None:
        age = state['session_state']['age']
        if not isinstance(age, int) or age < 3 or age > 8:
            return False, f"Invalid age: {age} (must be integer 3-8)"

    if not isinstance(state['session_state']['correct_answer_count'], int):
        return False, "correct_answer_count must be integer"

    if state['session_state']['correct_answer_count'] < 0:
        return False, "correct_answer_count must be >= 0"

    return True, None


def restore_from_state(state, client=None):
    """
    Restore PaixuejiAssistant instance from saved state.

    Args:
        state: Validated state dict
        client: Optional Gemini client to reuse

    Returns:
        PaixuejiAssistant: Restored assistant instance
    """
    session_state = state['session_state']

    # Create new assistant
    system_managed = session_state.get('system_managed_focus', False)
    assistant = PaixuejiAssistant(system_managed=system_managed, client=client)

    # Restore state fields
    assistant.age = session_state.get('age')
    assistant.object_name = session_state.get('object_name')
    assistant.level1_category = session_state.get('level1_category')
    assistant.level2_category = session_state.get('level2_category')
    assistant.level3_category = session_state.get('level3_category')
    assistant.character = session_state.get('character')
    assistant.correct_answer_count = session_state.get('correct_answer_count', 0)

    # Restore system-managed focus state
    assistant.system_managed_focus = session_state.get('system_managed_focus', False)
    assistant.current_focus_mode = session_state.get('current_focus_mode', 'depth')
    assistant.depth_questions_count = session_state.get('depth_questions_count', 0)
    assistant.width_wrong_count = session_state.get('width_wrong_count', 0)
    assistant.width_categories_tried = session_state.get('width_categories_tried', [])
    assistant.depth_target = session_state.get('depth_target', 4)

    # Restore conversation history - TRIM last user message and buggy response
    conversation_history = state['conversation_history'].copy()
    buggy_response_index = state.get('metadata', {}).get('buggy_response_index')

    # If this is a bug tracking restore (has buggy_response_index), trim the last 2 messages
    if buggy_response_index is not None and len(conversation_history) >= 2:
        # Remove last 2 messages: last user message + buggy assistant response
        # This prevents duplication when auto-replay resends the user message
        conversation_history = conversation_history[:-2]

    assistant.conversation_history = conversation_history

    # Note: Flow tree restoration is skipped for simplicity
    # A new flow tree will be initialized for the restored session

    return assistant


@app.route('/api/save-state', methods=['POST'])
def save_session_state():
    """
    Save current session state to JSON for bug reproduction.

    Excludes the last assistant message (buggy response) so saved state
    ends with the user's message that triggered the bug.

    Request body:
        {
            "session_id": "uuid-string"
        }

    Response:
        {
            "success": true,
            "state": { ... },
            "filename": "bug_2026-01-06_14-30-45.json"
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

    try:
        assistant = sessions[session_id]

        # Build save state (excludes last assistant message if present)
        state = build_save_state(assistant, session_id)

        # Generate filename
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"bug_{timestamp}.json"

        print(f"[INFO] Saved session state {session_id[:8]}... to {filename}")

        if state['metadata']['excluded_buggy_response']:
            print(f"[INFO] Excluded buggy response: {state['metadata']['excluded_buggy_response'][:100]}...")

        return jsonify({
            "success": True,
            "state": state,
            "filename": filename
        })

    except Exception as e:
        print(f"[ERROR] Error saving state: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/restore-state', methods=['POST'])
def restore_session_state():
    """
    Restore session from saved state JSON for bug reproduction.

    Creates a new session with the restored state. Conversation history
    will end with a user message, ready for auto-replay.

    Request body:
        {
            "state": { ... }
        }

    Response:
        {
            "success": true,
            "session_id": "new-uuid",
            "restored_state": {
                "object_name": "apple",
                "conversation_turns": 3,
                "correct_answer_count": 2,
                "last_user_message": "What color is the apple?"
            }
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    state = data.get('state')

    if not state:
        return jsonify({
            "success": False,
            "error": "Missing state object"
        }), 400

    try:
        # Validate schema
        is_valid, error_msg = validate_state_schema(state)
        if not is_valid:
            return jsonify({
                "success": False,
                "error": f"Invalid state format: {error_msg}"
            }), 400

        # Restore assistant
        assistant = restore_from_state(state, client=GLOBAL_GEMINI_CLIENT)

        # Create new session
        new_session_id = str(uuid.uuid4())
        sessions[new_session_id] = assistant

        # Initialize flow tree for new session
        assistant.init_flow_tree(
            session_id=new_session_id,
            age=assistant.age,
            object_name=assistant.object_name,
            character=assistant.character,
            focus_mode=assistant.current_focus_mode
        )

        # Extract last user message from metadata (correctly saved before trimming)
        last_user_message = state.get('metadata', {}).get('last_user_message')

        print(f"[INFO] Restored session {new_session_id[:8]}... from saved state | "
              f"object={assistant.object_name}, turns={len(assistant.conversation_history)}")

        return jsonify({
            "success": True,
            "session_id": new_session_id,
            "restored_state": {
                "object_name": assistant.object_name,
                "conversation_turns": len(assistant.conversation_history) - 1,  # Exclude system message
                "correct_answer_count": assistant.correct_answer_count,
                "last_user_message": last_user_message
            }
        })

    except Exception as e:
        print(f"[ERROR] Error restoring state: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def generate_comparison_html(buggy_response, new_response, context_message):
    """Generate standalone HTML file with side-by-side comparison."""
    import html
    from datetime import datetime

    # Escape content to prevent XSS
    buggy_escaped = html.escape(buggy_response)
    new_escaped = html.escape(new_response)
    context_escaped = html.escape(context_message)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Bugfix Comparison - {timestamp}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background: #10b981;
            color: white;
            padding: 20px;
            text-align: center;
        }}
        .context {{
            background: #f0f9ff;
            padding: 15px 20px;
            margin: 20px;
            border-left: 4px solid #3b82f6;
            border-radius: 4px;
        }}
        .context h3 {{
            margin: 0 0 10px 0;
            color: #1e40af;
        }}
        .comparison {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            padding: 20px;
        }}
        .column {{
            border: 2px solid;
            border-radius: 8px;
            padding: 15px;
        }}
        .before {{
            border-color: #ef4444;
            background: #fef2f2;
        }}
        .after {{
            border-color: #10b981;
            background: #f0fdf4;
        }}
        .column-header {{
            font-weight: bold;
            font-size: 18px;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid currentColor;
        }}
        .before .column-header {{
            color: #dc2626;
        }}
        .after .column-header {{
            color: #059669;
        }}
        .response-text {{
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 1.6;
            color: #333;
        }}
        @media (max-width: 768px) {{
            .comparison {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🐛 Bugfix Comparison Report</h1>
            <p>Generated: {timestamp}</p>
        </div>

        <div class="context">
            <h3>📝 Context - Last User Message:</h3>
            <p>{context_escaped}</p>
        </div>

        <div class="comparison">
            <div class="column before">
                <div class="column-header">❌ Before (Buggy Response)</div>
                <div class="response-text">{buggy_escaped}</div>
            </div>

            <div class="column after">
                <div class="column-header">✅ After (Fixed Response)</div>
                <div class="response-text">{new_escaped}</div>
            </div>
        </div>
    </div>
</body>
</html>'''


@app.route('/api/generate-bugfix-comparison', methods=['POST'])
def generate_bugfix_comparison():
    """Generate HTML comparison file for buggy vs fixed response."""
    try:
        data = request.get_json()
        buggy_response = data.get('buggy_response')
        new_response = data.get('new_response')
        context_message = data.get('context_message')

        # Validation
        if not all([buggy_response, new_response, context_message]):
            return jsonify({'error': 'Missing required fields'}), 400

        # HTML template with embedded CSS
        html_content = generate_comparison_html(
            buggy_response,
            new_response,
            context_message
        )

        # Generate filename
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f'bugfix_{timestamp}.html'

        return jsonify({
            'html': html_content,
            'filename': filename
        })

    except Exception as e:
        logger.error(f"Error generating comparison: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/logs/<session_id>', methods=['GET'])
def get_session_logs(session_id):
    """
    Retrieve debug logs for a specific session.
    
    Generates a structured text report from the conversation flow tree
    instead of reading raw server logs.

    Args:
        session_id: Session ID to retrieve logs for

    Response:
        - success: True/False
        - logs: List of log lines for this session
        - error: Error message if failed
    """
    assistant = sessions.get(session_id)

    if not assistant:
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404

    try:
        if not assistant.flow_tree:
            return jsonify({
                "success": False,
                "error": "Flow tree not initialized for this session"
            }), 404

        # Generate structured text report
        report_text = assistant.flow_tree.generate_text_report()
        report_lines = report_text.split('\n')

        print(f"[INFO] Generated debug report ({len(report_lines)} lines) for session {session_id[:8]}...")

        return jsonify({
            "success": True,
            "logs": report_lines,
            "session_id": session_id,
            "source": "flow_tree_report"
        })

    except Exception as e:
        print(f"[ERROR] Error generating logs: {e}")
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
