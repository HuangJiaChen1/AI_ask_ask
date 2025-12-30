"""
Flask API for Ask Ask Assistant with Server-Sent Events (SSE) streaming.

This provides real-time streaming responses using the new StreamChunk architecture.
"""

from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import json
import uuid
import asyncio
import threading

from ask_ask_assistant import AskAskAssistant
from ask_ask_stream import call_ask_ask_stream, sanitize_text
from schema import StreamChunk
import ask_ask_prompts

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
    Start a new conversation and get introduction.
    Returns a standard JSON response (non-streaming).
    Warms up the LLM by generating the first response.

    Request body:
        {
            "session_id": "...",
            "age": 6 (optional, 3-8)
        }
    """
    data = request.get_json() or {}
    session_id = data.get('session_id')
    age = data.get('age')

    if not session_id:
        return jsonify({
            "success": False,
            "error": "Missing required field: session_id"
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

    # Check if session already exists - silently ignore duplicate /start calls
    if session_id in sessions:
        print(f"[INFO] Session {session_id[:8]}... already exists - ignoring duplicate /start call (doing nothing)")
        # Return success without doing any LLM generation or session modification
        return jsonify({
            "success": True,
            "session_id": session_id,
            "introduction": "",  # Empty - client should ignore this
            "request_id": str(uuid.uuid4()),
            "duplicate": True  # Flag indicating this was a no-op duplicate call
        }), 200

    # Create session
    assistant = AskAskAssistant()
    sessions[session_id] = assistant
    assistant.age = age

    # Generate unique request ID
    request_id = str(uuid.uuid4())

    print(f"\n{'='*80}")
    print(f"[/api/start] NEW SESSION STARTED")
    print(f"  Session ID: {session_id}")
    print(f"  Age: {age}")
    print(f"  Request ID: {request_id}")
    print(f"{'='*80}")

    try:
        # Build system prompt with age guidance
        system_prompt = assistant.prompts['system_prompt']
        age_prompt = ""
        if age is not None:
            age_prompt = assistant.get_age_prompt(age)
            if age_prompt:
                system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"

        # Initialize conversation history with system prompt
        assistant.conversation_history = [
            {"role": "system", "content": system_prompt}
        ]
        introduction_content = assistant.prompts['introduction_prompt']

        # Call the stream but consume it fully to return a single response
        loop = get_event_loop()
        
        async def get_full_response():
            full_text = ""
            async for chunk in call_ask_ask_stream(
                age=age,
                messages=assistant.conversation_history.copy(),
                content=introduction_content,
                status="normal",
                session_id=session_id,
                request_id=request_id,
                config=assistant.config,
                client=assistant.client,
                age_prompt=age_prompt
            ):
                if chunk.finish:
                    full_text = chunk.response
            return full_text

        introduction = loop.run_until_complete(get_full_response())
        loop.close()

        # Sanitize introduction to remove emojis and newlines
        introduction = sanitize_text(introduction)

        # Update conversation history with final response
        assistant.conversation_history.append({
            "role": "assistant",
            "content": introduction
        })

        print(f"[/api/start] Introduction generated (length: {len(introduction)})")
        print(f"[/api/start] Conversation history now has {len(assistant.conversation_history)} messages")
        print(f"{'='*80}\n")

        return jsonify({
            "success": True,
            "session_id": session_id,
            "introduction": introduction,
            "request_id": request_id
        })

    except Exception as e:
        print(f"[ERROR] Error in start_conversation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/continue', methods=['POST'])
def continue_conversation():
    """
    Continue conversation with streaming response.

    Request body:
        {
            "session_id": "...",
            "child_input": "Why is the sky blue?"
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

    print(f"\n{'='*80}")
    print(f"[/api/continue] CONTINUE REQUEST RECEIVED")
    print(f"  Session ID: {session_id}")
    print(f"  User Input: {repr(child_input[:100] if child_input else None)}...")
    print(f"{'='*80}")

    if not session_id or not child_input:
        return jsonify({
            "success": False,
            "error": "Missing required fields: session_id and child_input"
        }), 400

    assistant = sessions.get(session_id)

    if not assistant:
        print(f"[/api/continue] ERROR: Session {session_id} NOT FOUND")
        print(f"[/api/continue] Available sessions: {list(sessions.keys())}")
        print(f"{'='*80}\n")
        return jsonify({
            "success": False,
            "error": "Session not found. Please start a new conversation."
        }), 404

    # Generate unique request ID for this stream
    request_id = str(uuid.uuid4())

    print(f"[/api/continue] Session found - current history has {len(assistant.conversation_history)} messages")

    def generate():
        """Generator for SSE stream."""
        try:

            # Get age prompt if age is set
            age_prompt = ""
            if assistant.age is not None:
                age_prompt = assistant.get_age_prompt(assistant.age)

            # Get new event loop for this request (avoids race conditions)
            loop = get_event_loop()

            print(f"[/api/continue] Starting streaming response...")
            print(f"[/api/continue] Message history being sent to model:")
            for i, msg in enumerate(assistant.conversation_history):
                role = msg.get('role', 'unknown')
                content_preview = msg.get('content', '')[:80]
                print(f"    [{i}] {role}: {content_preview}...")

            try:
                async def stream_response():
                    async for chunk in call_ask_ask_stream(
                        age=assistant.age,
                        messages=assistant.conversation_history.copy(),
                        content=child_input,
                        status="normal",
                        session_id=session_id,
                        request_id=request_id,
                        config=assistant.config,
                        client=assistant.client,
                        age_prompt=age_prompt
                    ):
                        # Yield StreamChunk as SSE event (pass directly for optimized serialization)
                        # Update conversation history with both user input and final response
                        if chunk.finish:
                            # Save user input first
                            assistant.conversation_history.append({
                                "role": "user",
                                "content": child_input
                            })
                            # Then save assistant response
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response
                            })

                            print(f"[/api/continue] Streaming completed")
                            print(f"[/api/continue] Final response length: {len(chunk.response)}")
                            print(f"[/api/continue] Conversation history now has {len(assistant.conversation_history)} messages")
                            print(f"{'='*80}\n")

                        yield sse_event("chunk", chunk)

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
    print("Ask Ask Assistant - Streaming API Server")
    print("=" * 60)
    print("\nServer starting...")
    print("URL: http://localhost:5000")
    print("\nEndpoints:")
    print("  GET  /api/health          - Health check")
    print("  POST /api/start           - Start conversation (SSE)")
    print("  POST /api/continue        - Continue conversation (SSE)")
    print("  POST /api/reset           - Delete session")
    print("  GET  /api/sessions        - List active sessions")
    print("  GET  /                    - Web interface")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
