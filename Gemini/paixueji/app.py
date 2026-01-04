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

from paixueji_assistant import PaixuejiAssistant
from paixueji_stream import call_paixueji_stream
from schema import StreamChunk
import paixueji_prompts

app = Flask(__name__, static_folder='static')
CORS(app)

# In-memory session storage
# NOTE: Sessions will be lost on server restart
# For production, consider using Redis or database storage
sessions = {}


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
    tone = data.get('tone')
    focus_mode = data.get('focus_mode', 'depth')  # Default to depth if not provided

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
    assistant = PaixuejiAssistant()
    sessions[session_id] = assistant

    # Initialize flow tree for debugging
    assistant.init_flow_tree(session_id, age, object_name, tone, focus_mode)

    # Store session state
    assistant.age = age
    assistant.object_name = object_name
    assistant.level1_category = level1_category
    assistant.level2_category = level2_category
    assistant.level3_category = level3_category
    assistant.tone = tone
    assistant.correct_answer_count = 0

    # Generate unique request ID for this stream
    request_id = str(uuid.uuid4())

    print(f"[INFO] Created Paixueji session {session_id[:8]}... | age={age}, object={object_name}, "
          f"level1={level1_category}, level2={level2_category}, level3={level3_category}, tone={tone}, focus={focus_mode}, request_id={request_id[:8]}...")

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

            # Get tone prompt
            tone_prompt = assistant.get_tone_prompt(tone)
            if tone_prompt:
                system_prompt += f"\n\nTONE GUIDANCE:\n{tone_prompt}"

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
                    async for chunk in call_paixueji_stream(
                        age=age,
                        messages=assistant.conversation_history.copy(),
                        content=introduction_content,
                        status="normal",
                        session_id=session_id,
                        request_id=request_id,
                        config=assistant.config,
                        client=assistant.client,
                        assistant=assistant,
                        age_prompt=age_prompt,
                        object_name=object_name,
                        level1_category=level1_category,
                        level2_category=level2_category,
                        level3_category=level3_category,
                        correct_answer_count=0,
                        category_prompt=category_prompt,
                        focus_prompt=focus_prompt,
                        focus_mode=focus_mode
                    ):
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

            # Get category prompt
            category_prompt = assistant.get_category_prompt(
                assistant.level1_category,
                assistant.level2_category,
                assistant.level3_category
            )
            
            # Get focus prompt
            focus_prompt = assistant.get_focus_prompt(focus_mode)

            # NOTE: Validation now happens inside call_paixueji_stream() using unified AI validation
            # Increment logic moved to stream handler below based on chunk.is_factually_correct

            # Get new event loop for this request (avoids race conditions)
            loop = get_event_loop()

            try:
                async def stream_response():
                    should_increment = False

                    async for chunk in call_paixueji_stream(
                        age=assistant.age,
                        messages=assistant.conversation_history.copy(),
                        content=child_input,
                        status="normal",
                        session_id=session_id,
                        request_id=request_id,
                        config=assistant.config,
                        client=assistant.client,
                        assistant=assistant,
                        age_prompt=age_prompt,
                        object_name=assistant.object_name,
                        level1_category=assistant.level1_category,
                        level2_category=assistant.level2_category,
                        level3_category=assistant.level3_category,
                        correct_answer_count=assistant.correct_answer_count,
                        category_prompt=category_prompt,
                        focus_prompt=focus_prompt,
                        focus_mode=focus_mode
                    ):
                        # NEW: Topic switching and classification now handled in ask_followup_question_stream()
                        # The decision step happens BEFORE response generation
                        # Object name and categories are already updated if switch occurred

                        # Check if we should increment based on factual correctness
                        if chunk.finish and chunk.is_factually_correct:
                            should_increment = True

                        # Update conversation history with final response
                        if chunk.finish:
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response
                            })

                            # NEW: Increment only if factually correct
                            if should_increment:
                                assistant.increment_correct_answers()
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


def convert_tree_to_mermaid(flow_tree):
    """Convert flow tree to Mermaid diagram syntax with comprehensive debugging info."""
    lines = ["graph TD"]

    for node in flow_tree.nodes:
        # Helper function to truncate text safely
        def truncate(text, max_len=35):
            if not text:
                return "N/A"
            text = str(text).replace('"', "'").replace("\n", " ")
            return text[:max_len] + "..." if len(text) > max_len else text

        # === HEADER: Turn number and type ===
        obj = node.state_after.get('object_name') or node.state_before.get('object_name')
        label_parts = [f"🔄 T{node.turn_number}: {node.type.upper()}"]
        label_parts.append(f"📦 Object: {obj}")

        # === USER INPUT ===
        if node.user_input:
            label_parts.append(f"👦 Child: {truncate(node.user_input, 40)}")

        # === VALIDATION STATUS ===
        if node.validation:
            engaged = node.validation.get('is_engaged')
            correct = node.validation.get('is_factually_correct')

            # Build validation line with emojis
            val_line = "🔍 "
            if engaged is False:
                val_line += "❌ NOT ENGAGED"
            elif engaged is True:
                if correct is True:
                    val_line += "✅ CORRECT"
                elif correct is False:
                    val_line += "❌ INCORRECT"
                else:
                    val_line += "⚠️ ENGAGED (no correctness)"
            else:
                val_line += "⚪ No validation"

            label_parts.append(val_line)

            # Add correctness reasoning if available
            reasoning = node.validation.get('correctness_reasoning')
            if reasoning:
                label_parts.append(f"💭 Why: {truncate(reasoning, 50)}")

        # === AI RESPONSE PREVIEW ===
        if node.ai_response:
            label_parts.append(f"🤖 AI: {truncate(node.ai_response, 45)}")

        # === STATE CHANGES ===
        state_changes = []
        if node.state_after:
            if 'correct_answer_count' in node.state_after:
                old_count = node.state_before.get('correct_answer_count', 0)
                new_count = node.state_after['correct_answer_count']
                state_changes.append(f"✨ Correct: {old_count}→{new_count}")

            if 'object_name' in node.state_after:
                old_obj = node.state_before.get('object_name', 'None')
                new_obj = node.state_after['object_name']
                state_changes.append(f"🔀 Topic: {old_obj}→{new_obj}")

            if 'level2_category' in node.state_after:
                old_cat = node.state_before.get('level2_category', 'None')
                new_cat = node.state_after['level2_category']
                state_changes.append(f"📂 Cat: {old_cat}→{new_cat}")

        if state_changes:
            label_parts.extend(state_changes)

        # === DECISION INFO (Topic Switching) ===
        if node.decision:
            decision_type = node.decision.get('decision_type')
            if decision_type == 'SWITCH':
                detected_obj = node.decision.get('detected_object', 'unknown')
                label_parts.append(f"⚡ SWITCH DETECTED → {detected_obj}")
            elif decision_type == 'STAY':
                label_parts.append("⚡ STAY on current topic")

        # === PERFORMANCE METRICS ===
        perf_parts = []
        if node.response_duration:
            perf_parts.append(f"⏱️ {node.response_duration:.2f}s")

        if node.metadata and node.metadata.get('token_usage'):
            tokens = node.metadata['token_usage']
            if 'total_tokens' in tokens:
                perf_parts.append(f"🎫 {tokens['total_tokens']} tokens")

        if perf_parts:
            label_parts.append(" | ".join(perf_parts))

        # === BUILD FINAL LABEL ===
        label = "<br/>".join(label_parts)

        # === NODE STYLING ===
        # Color code based on validation result for easy visual debugging
        if node.validation:
            engaged = node.validation.get('is_engaged')
            correct = node.validation.get('is_factually_correct')

            if engaged is False:
                # Not engaged - yellow/orange
                style = "fill:#fff3e0,stroke:#ff9800,stroke-width:3px"
            elif correct is True:
                # Correct answer - green
                style = "fill:#e8f5e9,stroke:#4caf50,stroke-width:3px"
            elif correct is False:
                # Incorrect answer - red
                style = "fill:#ffebee,stroke:#f44336,stroke-width:3px"
            else:
                # Engaged but no correctness - blue
                style = "fill:#e3f2fd,stroke:#2196f3,stroke-width:2px"
        else:
            # No validation (e.g., introduction) - light gray
            style = "fill:#f5f5f5,stroke:#9e9e9e,stroke-width:2px"

        # Add node
        lines.append(f'    {node.node_id}["{label}"]')
        lines.append(f'    style {node.node_id} {style}')

        # === EDGE WITH LABEL ===
        if node.parent_id:
            # Add edge label showing the flow logic
            edge_label = ""
            if node.validation:
                engaged = node.validation.get('is_engaged')
                correct = node.validation.get('is_factually_correct')

                if engaged is False:
                    edge_label = "Not engaged"
                elif correct is True:
                    edge_label = "Correct ✓"
                elif correct is False:
                    edge_label = "Wrong ✗"

            if edge_label:
                lines.append(f'    {node.parent_id} -->|{edge_label}| {node.node_id}')
            else:
                lines.append(f'    {node.parent_id} --> {node.node_id}')

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
    assistant = PaixuejiAssistant()

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
