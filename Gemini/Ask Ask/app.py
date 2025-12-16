"""
Flask API for Ask Ask Assistant with Server-Sent Events (SSE) streaming.

This provides real-time streaming responses for a better user experience.
"""

from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import json
import uuid

from ask_ask_assistant import AskAskAssistant

app = Flask(__name__, static_folder='static')
CORS(app)

# In-memory session storage
# NOTE: Sessions will be lost on server restart
# For production, consider using Redis or database storage
sessions = {}


def sse_event(event_type, data):
    """
    Format data as Server-Sent Event.

    Args:
        event_type: Event type (metadata, text_chunk, complete, error)
        data: Data to send (will be JSON-encoded)

    Returns:
        Formatted SSE string with event type and data
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


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
        - metadata: {"session_id": "...", "state": "introduction", "age": 6}
        - text_chunk: {"text": "H"}
        - text_chunk: {"text": "i"}
        - complete: {"success": true, "audio_output": "..."}
        - error: {"message": "error description"}
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

    print(f"[INFO] Created session {session_id[:8]}... with age={age}")

    def generate():
        """Generator for SSE stream."""
        try:
            # Send session metadata first
            yield sse_event("metadata", {
                "session_id": session_id,
                "age": age
            })

            # Stream introduction
            for event_type, event_data in assistant.start_conversation_stream(age=age):
                if event_type == "metadata":
                    yield sse_event("metadata", event_data)
                elif event_type == "text":
                    yield sse_event("text_chunk", {"text": event_data})
                elif event_type == "complete":
                    yield sse_event("complete", event_data)
                elif event_type == "error":
                    yield sse_event("error", event_data)
                    return

            print(f"[INFO] Session {session_id[:8]}... started successfully")

        except Exception as e:
            print(f"[ERROR] Error in start_conversation: {e}")
            yield sse_event("error", {"message": str(e)})

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
        - metadata: {"is_stuck": false, "state": "awaiting_question"}
        - text_chunk: {"text": "W"}
        - text_chunk: {"text": "e"}
        - complete: {"success": true, "audio_output": "..."}
        - error: {"message": "error description"}
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
            for event_type, event_data in assistant.continue_conversation_stream(child_input):
                if event_type == "metadata":
                    yield sse_event("metadata", event_data)
                elif event_type == "text":
                    yield sse_event("text_chunk", {"text": event_data})
                elif event_type == "complete":
                    yield sse_event("complete", event_data)
                elif event_type == "error":
                    yield sse_event("error", event_data)
                    return

            print(f"[INFO] Session {session_id[:8]}... response streamed successfully")

        except Exception as e:
            print(f"[ERROR] Error in continue_conversation: {e}")
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

    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
