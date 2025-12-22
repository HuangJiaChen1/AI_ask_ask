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
from ask_ask_stream import call_ask_ask_stream
from schema import StreamChunk
import ask_ask_prompts

app = Flask(__name__, static_folder='static')
CORS(app)

# In-memory session storage
# NOTE: Sessions will be lost on server restart
# For production, consider using Redis or database storage
sessions = {}

# Track active streams with cancellation flags
# Structure: {session_id: {"cancel": False, "timestamp": float}}
active_streams = {}
active_streams_lock = threading.Lock()

# Global event loop for async operations (reused across requests)
_global_event_loop = None
_loop_lock = threading.Lock()


def get_event_loop():
    """
    Get or create the global event loop for async operations.

    This reuses a single event loop across all requests instead of creating
    a new one each time, saving ~5-10ms per request.

    Returns:
        asyncio.AbstractEventLoop: The global event loop
    """
    global _global_event_loop
    with _loop_lock:
        if _global_event_loop is None or _global_event_loop.is_closed():
            _global_event_loop = asyncio.new_event_loop()
        return _global_event_loop


def start_stream_tracking(session_id):
    """Mark a session as actively streaming."""
    import time
    with active_streams_lock:
        active_streams[session_id] = {
            "cancel": False,
            "timestamp": time.time()
        }
    print(f"[INFO] Started tracking stream for session {session_id[:8]}...")


def stop_stream_tracking(session_id):
    """Remove stream tracking for a session."""
    with active_streams_lock:
        if session_id in active_streams:
            del active_streams[session_id]
    print(f"[INFO] Stopped tracking stream for session {session_id[:8]}...")


def is_stream_cancelled(session_id):
    """Check if stream should be cancelled."""
    with active_streams_lock:
        return active_streams.get(session_id, {}).get("cancel", False)


def cancel_stream(session_id):
    """Set cancellation flag for a session."""
    with active_streams_lock:
        if session_id in active_streams:
            active_streams[session_id]["cancel"] = True
            print(f"[INFO] Cancellation requested for session {session_id[:8]}...")
            return True
        else:
            print(f"[WARNING] Cannot cancel - session {session_id[:8]}... not streaming")
            return False


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
    Start a new conversation with streaming introduction.

    Request body:
        {
            "age": 6 (optional, 3-8)
        }

    SSE Events:
        - chunk: StreamChunk object (serialized as JSON)
        - complete: Final completion marker
        - error: Error information
    """
    data = request.get_json() or {}
    age = data.get('age')

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
    assistant = AskAskAssistant()
    sessions[session_id] = assistant

    # Store age in session
    assistant.age = age

    print(f"[INFO] Created session {session_id[:8]}... with age={age}")

    def generate():
        """Generator for SSE stream."""
        try:
            # Start stream tracking
            start_stream_tracking(session_id)

            # Build system prompt with age guidance (use cached prompts)
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

            # Introduction content (use cached prompts)
            introduction_content = assistant.prompts['introduction_prompt']

            # Get reused event loop (saves ~5-10ms per request)
            loop = get_event_loop()

            async def stream_introduction():
                async for chunk in call_ask_ask_stream(
                    age=age,
                    messages=assistant.conversation_history.copy(),
                    content=introduction_content,
                    status="normal",
                    session_id=session_id,
                    config=assistant.config,
                    client=assistant.client,
                    age_prompt=age_prompt,
                    cancel_checker=lambda: is_stream_cancelled(session_id)
                ):
                    # Check for cancellation
                    if is_stream_cancelled(session_id):
                        print(f"[INFO] Session {session_id[:8]}... interrupted by user")
                        yield sse_event("interrupted", {"message": "Stream stopped by user"})
                        return

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

        except GeneratorExit:
            # Client disconnected - stream was interrupted
            print(f"[INFO] Session {session_id[:8]}... client disconnected")
        except Exception as e:
            print(f"[ERROR] Error in start_conversation: {e}")
            import traceback
            traceback.print_exc()
            yield sse_event("error", {"message": str(e)})
        finally:
            # Always clean up stream tracking
            stop_stream_tracking(session_id)

    return Response(generate(), mimetype='text/event-stream')


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

    print(f"[INFO] Session {session_id[:8]}... continuing: '{child_input[:50]}...'")

    def generate():
        """Generator for SSE stream."""
        try:
            # Start stream tracking
            start_stream_tracking(session_id)

            # Get age prompt if age is set
            age_prompt = ""
            if assistant.age is not None:
                age_prompt = assistant.get_age_prompt(assistant.age)

            # Get reused event loop (saves ~5-10ms per request)
            loop = get_event_loop()

            async def stream_response():
                async for chunk in call_ask_ask_stream(
                    age=assistant.age,
                    messages=assistant.conversation_history.copy(),
                    content=child_input,
                    status="normal",
                    session_id=session_id,
                    config=assistant.config,
                    client=assistant.client,
                    age_prompt=age_prompt,
                    cancel_checker=lambda: is_stream_cancelled(session_id)
                ):
                    # Check for cancellation
                    if is_stream_cancelled(session_id):
                        print(f"[INFO] Session {session_id[:8]}... interrupted by user")
                        yield sse_event("interrupted", {"message": "Stream stopped by user"})
                        return

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

            # Stream the response
            gen = stream_response()
            for event in async_gen_to_sync(gen, loop):
                yield event

            print(f"[INFO] Session {session_id[:8]}... response streamed successfully")

        except GeneratorExit:
            # Client disconnected
            print(f"[INFO] Session {session_id[:8]}... client disconnected")
        except Exception as e:
            print(f"[ERROR] Error in continue_conversation: {e}")
            import traceback
            traceback.print_exc()
            yield sse_event("error", {"message": str(e)})
        finally:
            # Always clean up stream tracking
            stop_stream_tracking(session_id)

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


@app.route('/api/stop', methods=['POST'])
def stop_streaming():
    """
    Stop an active streaming response.

    Request body:
        {
            "session_id": "..."
        }

    Response:
        {
            "success": true/false,
            "message": "..." (if successful),
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

    # Check if session exists
    if session_id not in sessions:
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404

    # Cancel the stream
    if cancel_stream(session_id):
        return jsonify({
            "success": True,
            "message": "Stream cancellation requested"
        })
    else:
        return jsonify({
            "success": False,
            "error": "Session is not currently streaming"
        }), 400


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
    print("URL: http://localhost:5001")
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
