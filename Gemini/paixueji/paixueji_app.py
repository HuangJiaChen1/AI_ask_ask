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
import yaml

from google import genai
from google.genai.types import HttpOptions
from loguru import logger

from paixueji_assistant import PaixuejiAssistant
from graph import paixueji_graph
from schema import StreamChunk
import paixueji_prompts
import time
from graph_lookup import lookup_top_available_concepts
from stream.errors import build_sse_error_payload

app = Flask(__name__, static_folder='static')
CORS(app)

# In-memory session storage
# NOTE: Sessions will be lost on server restart
# For production, consider using Redis or database storage

sessions = {}

ALLOWED_MODELS = {"gemini-3.1-flash-lite-preview", "gemini-2.0-flash-lite"}

# Initialize global Gemini client to enable connection reuse
def init_global_client():
    """Initialize a global Gemini client instance to avoid cold starts."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "config.json")
        if not os.path.exists(config_path):
            print(f"[WARNING] Config file not found: {config_path}")
            return None

        with open(config_path, 'r', encoding='utf-8') as f:
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

# Load hook types config once at startup (runtime-static)
def _load_hook_types() -> dict:
    """Load hook_types.json from the project root."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, "hook_types.json")
        if not os.path.exists(path):
            print(f"[WARNING] hook_types.json not found: {path}")
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"[INFO] Loaded {len(data)} hook types from hook_types.json")
        return data
    except Exception as e:
        print(f"[ERROR] Failed to load hook_types.json: {e}")
        return {}

HOOK_TYPES = _load_hook_types()

# Single persistent event loop running in a dedicated daemon thread.
# All async work is submitted via asyncio.run_coroutine_threadsafe() so that
# the httpx/anyio transport (used by client.aio) always sees the same loop
# and never hits "Event is bound to a different event loop".
_ASYNC_LOOP = asyncio.new_event_loop()
_ASYNC_THREAD = threading.Thread(
    target=_ASYNC_LOOP.run_forever,
    daemon=True,
    name="async-worker",
)
_ASYNC_THREAD.start()


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


GAME_ENTITY_IDS = frozenset({
    'animals_cat', 'animals_dog', 'animals_dinosaur',
    'animals_ladybug', 'plants_dandelion',
})

_DOMAIN_LABELS = {
    'animals': 'Animals',
    'arts_music': 'Arts & Music',
    'buildings_places': 'Buildings & Places',
    'clothing_accessories': 'Clothing & Accessories',
    'daily_objects': 'Daily Objects',
    'food': 'Food',
    'human_body': 'Human Body',
    'imagination': 'Imagination',
    'natural_phenomena': 'Natural Phenomena',
    'nature_landscapes': 'Nature & Landscapes',
    'people_roles': 'People & Roles',
    'plants': 'Plants',
    'signs_symbols': 'Signs & Symbols',
    'vehicles': 'Vehicles',
}


@app.route('/api/objects', methods=['GET'])
def list_objects():
    """Return all supported objects from mappings_dev20_0318, sorted by domain then name."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    mappings_dir = os.path.join(base_dir, 'mappings_dev20_0318')

    with open(os.path.join(mappings_dir, '_index.yaml'), 'r') as f:
        index = yaml.safe_load(f)  # {entity_id: "relative/path.yaml"}

    objects = []
    for entity_id in index.keys():
        rel_path = index[entity_id]
        yaml_path = os.path.join(mappings_dir, rel_path)
        with open(yaml_path, 'r', encoding='utf-8') as f:
            entities = yaml.safe_load(f)
        entity = next((e for e in entities if e.get('entity_id') == entity_id), None)
        if not entity:
            continue
        domain = entity.get('domain', '')
        objects.append({
            'id': entity_id,
            'name': entity['entity_name'],
            'domain': domain,
            'domain_label': _DOMAIN_LABELS.get(domain, domain.replace('_', ' ').title()),
            'has_game': entity_id in GAME_ENTITY_IDS,
        })

    objects.sort(key=lambda x: (x['domain'], x['name']))
    return jsonify(objects)


@app.route('/api/start', methods=['POST'])
def start_conversation():
    """
    Start a new Paixueji conversation with first question about object.

    Request body:
        {
            "age": 6 (optional, 3-8),
            "object_name": "apple" (required),
            "model_name_override": "gemini-3.1-flash-lite-preview" (optional),
            "grounding_model_override": "gemini-3.1-flash-lite-preview" (optional)
        }

    SSE Events:
        - chunk: StreamChunk object (serialized as JSON)
        - complete: Final completion marker
        - error: Error information
    """
    data = request.get_json() or {}
    age = data.get('age')
    object_name = data.get('object_name')
    model_name_override = data.get('model_name_override')
    grounding_model_override = data.get('grounding_model_override')
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
    assistant = PaixuejiAssistant(client=GLOBAL_GEMINI_CLIENT)
    sessions[session_id] = assistant

    # Store session state
    assistant.age = age
    assistant.object_name = object_name
    assistant.correct_answer_count = 0

    # Ordinary chat uses only age-tiered dimension KB.
    assistant.load_dimension_data(object_name)

    # Apply backbone model overrides (validated against whitelist)
    if model_name_override and model_name_override in ALLOWED_MODELS:
        assistant.config["model_name"] = model_name_override
        print(f"[INFO] conversation model overridden to: {model_name_override}")
    if grounding_model_override and grounding_model_override in ALLOWED_MODELS:
        assistant.config["grounding_model"] = grounding_model_override
        print(f"[INFO] grounding model overridden to: {grounding_model_override}")

    # Generate unique request ID for this stream
    request_id = str(uuid.uuid4())

    print(f"[INFO] Created Paixueji session {session_id[:8]}... | age={age}, object={object_name}, "
          f"request_id={request_id[:8]}...")

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

            # Get category prompt (set by YAML classification above)
            category_prompt = assistant.category_prompt or ""

            # Initialize conversation history with system prompt
            assistant.conversation_history = [
                {"role": "system", "content": system_prompt}
            ]

            # Introduction content (trigger first question)
            introduction_content = f"Start conversation about {object_name}"

            loop = _ASYNC_LOOP

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
                        "object_name": object_name,
                        "correct_answer_count": 0,
                        "category_prompt": assistant.category_prompt,

                        # Ordinary-chat KB (loaded at session start)
                        "physical_dimensions": assistant.physical_dimensions,
                        "engagement_dimensions": assistant.engagement_dimensions,
                        "used_kb_item": None,
                        "kb_mapping_status": None,

                        # Initialize outputs
                        "full_response_text": "",
                        "full_question_text": "",
                        "sequence_number": 0,

                        # Initialize flags
                        "intent_type": None,
                        "new_object_name": None,
                        "detected_object_name": None,
                        "response_type": "introduction",

                        # Hook type selection
                        "hook_types": HOOK_TYPES,
                        "selected_hook_type": None,

                        # Node execution tracing
                        "nodes_executed": [],

                        # Input state snapshot for TraceObject assembly
                        "_input_state_snapshot": {
                            "object_name": assistant.object_name,
                            "age": assistant.age,
                            "correct_answer_count": assistant.correct_answer_count,
                            "content": introduction_content,
                            "conversation_state": assistant.state.value,
                            "ibpyp_theme_name": assistant.ibpyp_theme_name,
                            "key_concept": assistant.key_concept,
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
                                "mode": "chat",
                                "classification_status": chunk.classification_status,
                                "classification_failure_reason": chunk.classification_failure_reason,
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
            yield sse_event("error", build_sse_error_payload(e))

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
          f"correct_count: {assistant.correct_answer_count}, request_id={request_id[:8]}...")

    def generate():
        """Generator for SSE stream."""
        try:

            # Get age prompt if age is set
            age_prompt = ""
            if assistant.age is not None:
                age_prompt = assistant.get_age_prompt(assistant.age)

            # Get category prompt (set by YAML classification on session start or topic switch)
            category_prompt = assistant.category_prompt or ""

            # NOTE: User message is added to conversation_history inside the graph after turn completes

            loop = _ASYNC_LOOP

            try:
                async def stream_response():
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
                        "object_name": assistant.object_name,
                        "correct_answer_count": assistant.correct_answer_count,
                        "category_prompt": category_prompt,

                        # Ordinary-chat KB (persisted on assistant between turns)
                        "physical_dimensions": assistant.physical_dimensions,
                        "engagement_dimensions": assistant.engagement_dimensions,
                        "used_kb_item": None,
                        "kb_mapping_status": None,

                        # Initialize outputs
                        "full_response_text": "",
                        "full_question_text": "",
                        "sequence_number": 0,

                        # Initialize flags
                        "intent_type": None,
                        "new_object_name": None,
                        "detected_object_name": None,
                        "response_type": None,

                        # Fun fact (not used in continue, but required by state schema)
                        "fun_fact": "",
                        "fun_fact_hook": "",
                        "fun_fact_question": "",
                        "real_facts": "",

                        # Hook type (not used in continue turns, required by state schema)
                        "hook_types": HOOK_TYPES,
                        "selected_hook_type": None,

                        # Node execution tracing
                        "nodes_executed": [],

                        # Input state snapshot for TraceObject assembly
                        "_input_state_snapshot": {
                            "object_name": assistant.object_name,
                            "age": assistant.age,
                            "correct_answer_count": assistant.correct_answer_count,
                            "content": child_input,
                            "conversation_state": assistant.state.value,
                            "ibpyp_theme_name": assistant.ibpyp_theme_name,
                            "key_concept": assistant.key_concept,
                        },
                    }

                    async for chunk in stream_graph_execution(initial_state):
                        # Update conversation history with final response
                        if chunk.finish:
                            assistant.conversation_history.append({"role": "user", "content": child_input})

                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response,
                                "nodes_executed": chunk.nodes_executed or [],
                                "mode": "chat",
                                "classification_status": chunk.classification_status,
                                "classification_failure_reason": chunk.classification_failure_reason,
                                "_input_state_snapshot": initial_state.get("_input_state_snapshot", {}),
                            })

                            print(f"[INFO] Session {session_id[:8]}... intent={chunk.intent_type} | count={assistant.correct_answer_count}")

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
            yield sse_event("error", build_sse_error_payload(e))

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


#graph_lookup 此处添加改动：年龄对应，搜索概念，返回JSON格式的结果
@app.route('/api/lookup-concepts', methods=['POST'])
def lookup_concepts():
    """
    Lookup top available concepts for a given object and age.

    Request body:
        {
            "object_name": "apple",
            "age": 6
        }

    Age to Tier mapping:
        - 3 years → T0
        - 4 years → T1
        - 5/6 years → T2
        - 7/8 years → T3

    Response:
        {
            "success": true,
            "data": {
                "entity": { ... },
                "themes": { ... },
                "available_concepts": [...]
            }
        }
        OR
        {
            "success": false,
            "error": "..."
        }
    """
    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON"
        }), 400

    object_name = data.get('object_name')
    age = data.get('age')

    if not object_name:
        return jsonify({
            "success": False,
            "error": "Missing object_name"
        }), 400

    if age is None:
        return jsonify({
            "success": False,
            "error": "Missing age"
        }), 400

    try:
        age_int = int(age)
        if age_int == 3:
            age_tier = "T0"
        elif age_int == 4:
            age_tier = "T1"
        elif age_int in {5, 6}:
            age_tier = "T2"
        elif age_int in {7, 8}:
            age_tier = "T3"
        else:
            return jsonify({
                "success": False,
                "error": f"Age must be between 3-8, got {age_int}"
            }), 400

        print(f"[INFO] Looking up concepts for '{object_name}' with age_tier={age_tier}")

        result = lookup_top_available_concepts(object_name, age_tier)
        
        if not result.get("success"):
            return jsonify(result)
        
        return jsonify({
            "success": True,
            "data": {
                "entity": result.get("entity", {}),
                "themes": result.get("themes", {}),
                "available_concepts": result.get("available_concepts", [])
            }
        })

    except ValueError as e:
        print(f"[ERROR] Lookup error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        print(f"[ERROR] Lookup error: {e}")
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

        # Refresh the ordinary-chat KB inventory for the new object.
        assistant.load_dimension_data(new_object)

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
            entry["classification_status"] = msg.get("classification_status")
            entry["classification_failure_reason"] = msg.get("classification_failure_reason")
        transcript.append(entry)

    # Introduction: first model message
    introduction = None
    i = 0
    while i < len(transcript):
        if transcript[i]["role"] == "model":
            intro_nodes = transcript[i].get("nodes_executed", [])
            introduction = {
                "content": transcript[i]["content"],
                "nodes_executed": intro_nodes,
                "mode": transcript[i].get("mode", "chat"),
                "classification_status": transcript[i].get("classification_status"),
                "classification_failure_reason": transcript[i].get("classification_failure_reason"),
            }
            i += 1
            break
        i += 1

    # Exchanges: child → model pairs
    exchanges = []
    exchange_index = 0
    while i < len(transcript) - 1:
        if (transcript[i].get("role") == "child" and
                transcript[i + 1].get("role") == "model"):

            exchange_index += 1
            nodes = transcript[i + 1].get("nodes_executed", [])

            # Extract intent_type: first node whose 'changes' dict sets intent_type
            intent_type = None
            for node_entry in nodes:
                if "intent_type" in node_entry.get("changes", {}):
                    intent_type = node_entry["changes"]["intent_type"]
                    break

            # Total response time in ms (sum of all node times)
            response_time_ms = round(sum(n.get("time_ms", 0) for n in nodes), 1)

            exchanges.append({
                "index": exchange_index,
                "child_response": transcript[i]["content"],
                "model_response": transcript[i + 1]["content"],
                "nodes_executed": nodes,
                "mode": transcript[i + 1].get("mode", "chat"),
                "intent_type": intent_type,
                "classification_status": transcript[i + 1].get("classification_status"),
                "classification_failure_reason": transcript[i + 1].get("classification_failure_reason"),
                "response_time_ms": response_time_ms,
            })
            i += 2
        else:
            i += 1

    return jsonify({
        "success": True,
        "introduction": introduction,
        "exchanges": exchanges,
        "object_name": assistant.object_name,
        "age": assistant.age,
        "key_concept": assistant.key_concept,
        "ibpyp_theme_name": assistant.ibpyp_theme_name,
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
    skip_traces = data.get('skip_traces', False)

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
            entry["classification_status"] = msg.get("classification_status")
            entry["classification_failure_reason"] = msg.get("classification_failure_reason")
        transcript.append(entry)

    # Re-extract introduction and all exchanges (child→model pairs) to match indices
    introduction = None
    all_exchanges = []
    i = 0
    while i < len(transcript):
        if transcript[i]["role"] == "model":
            introduction = {
                "content": transcript[i]["content"],
                "nodes_executed": transcript[i].get("nodes_executed", []),
                "mode": transcript[i].get("mode", "chat"),
                "classification_status": transcript[i].get("classification_status"),
                "classification_failure_reason": transcript[i].get("classification_failure_reason"),
            }
            i += 1
            break
        i += 1
    while i < len(transcript) - 1:
        if (transcript[i].get("role") == "child" and
                transcript[i + 1].get("role") == "model"):
            all_exchanges.append({
                "child_response": transcript[i]["content"],
                "model_response": transcript[i + 1]["content"],
                "nodes_executed": transcript[i + 1].get("nodes_executed", []),
                "mode": transcript[i + 1].get("mode", "chat"),
                "classification_status": transcript[i + 1].get("classification_status"),
                "classification_failure_reason": transcript[i + 1].get("classification_failure_reason"),
            })
            i += 2
        else:
            i += 1

    # Separate out the introduction critique (exchange_index == 0) if present
    introduction_critique = next(
        (ec for ec in exchange_critiques if ec.get("exchange_index") == 0), None
    )

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
            introduction=introduction,
            introduction_critique=introduction_critique,
        )

        # Save to reports/HF/YYYY-MM-DD/
        now = datetime.now()
        date_dir = now.strftime("%Y-%m-%d")
        reports_dir = Path(__file__).parent / "reports" / "HF" / date_dir
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = now.strftime("%Y%m%d_%H%M%S")
        safe_object_name = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in (assistant.object_name or "unknown")
        )
        filename = f"{safe_object_name}_{timestamp}.md"
        report_path = reports_dir / filename

        report_path.write_text(report_md, encoding='utf-8')

        logger.info(f"[MANUAL-CRITIQUE] Report saved: {report_path} | "
                     f"exchanges critiqued: {len(exchange_critiques)}")

        if skip_traces:
            return jsonify({
                "success": True,
                "report_path": str(report_path),
                "exchanges_critiqued": len(exchange_critiques),
                "traces": [],
            })

        # Assemble TraceObjects for each critiqued exchange (skip index 0 = Introduction)
        from trace_assembler import assemble_trace_object, save_trace_object
        trace_paths = []
        saved_traces = []
        for ec in exchange_critiques:
            idx = ec.get("exchange_index")
            if idx is None or idx < 1 or idx > len(all_exchanges):
                continue  # idx == 0 (Introduction) is excluded by idx < 1
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
                                 global_conclusion, key_concept=None,
                                 introduction=None, introduction_critique=None):
    """
    Generate a markdown report for human feedback critique.

    Structures the report into an optional Introduction Critique section,
    then a single conversation critique section.

    Args:
        object_name: Object being discussed
        age: Child's age
        session_id: Session ID
        transcript: Full conversation transcript [{role, content, nodes_executed?, mode?}]
        all_exchanges: All extracted exchanges (list of dicts with mode)
        exchange_critiques: User-submitted critiques (list of dicts)
        global_conclusion: Overall conclusion text
        key_concept: Session-level key concept from final theme classification
        introduction: Optional {content, nodes_executed, mode} for the first model message
        introduction_critique: Optional critique dict for the introduction (exchange_index == 0)

    Returns:
        str: Markdown report content
    """
    from datetime import datetime

    total_exchanges = (len(all_exchanges)
                       + (1 if introduction else 0)
                       + (1 if global_conclusion else 0))
    critiqued_count = (len(exchange_critiques)
                       + (1 if (introduction and introduction_critique) else 0)
                       + (1 if global_conclusion else 0))

    report = f"# Human Feedback Critique Report: {object_name}\n\n"
    report += f"**Session:** {session_id}\n"
    report += f"**Age:** {age}\n"
    if key_concept:
        report += f"**Key Concept:** {key_concept}\n"
    report += f"**Date:** {datetime.now().isoformat()}\n"
    report += f"**Feedback Type:** Manual (Human)\n"
    report += f"**Exchanges Critiqued:** {critiqued_count} / {total_exchanges}\n\n"
    report += "---\n\n"

    # Introduction Critique section (if the reviewer critiqued the introduction)
    if introduction and introduction_critique:
        report += "## Introduction — Human Critique\n\n"
        intro_content = introduction.get("content", "")
        report += f"**Introduction:** \"{intro_content}\"\n\n"
        mr_expected = introduction_critique.get("model_response_expected", "").strip()
        mr_problem = introduction_critique.get("model_response_problem", "").strip()
        if mr_expected or mr_problem:
            report += "**Introduction Content:**\n"
            if mr_expected:
                report += f"- *What is expected:* {mr_expected}\n"
            if mr_problem:
                report += f"- *Why is it problematic:* {mr_problem}\n"
            report += "\n"
        conclusion = introduction_critique.get("conclusion", "").strip()
        if conclusion:
            report += f"#### Conclusion\n\n{conclusion}\n\n"
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

    critiqued_exchanges = []
    for ec in exchange_critiques:
        idx = ec["exchange_index"]
        if idx < 1 or idx > total_exchanges:
            continue
        exchange = all_exchanges[idx - 1]
        critiqued_exchanges.append((idx, exchange, ec))

    if critiqued_exchanges:
        report += "## Conversation Critique\n\n"
        if key_concept:
            report += f"> Session Key Concept: **{key_concept}**\n\n"
        for idx, exchange, ec in critiqued_exchanges:
            report += _render_hf_exchange(idx, exchange, ec)
        report += "\n"
    else:
        report += "## Conversation Critique\n\n"
        report += "*No exchanges were critiqued.*\n\n"

    # Global conclusion
    if global_conclusion and global_conclusion.strip():
        report += f"## Global Conclusion\n\n{global_conclusion.strip()}\n"

    return report


def _render_hf_exchange(idx, exchange, ec):
    """Render a single HF exchange critique as markdown."""
    report = f"### Exchange {idx}\n\n"
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


# ═══════════════════════════════════════════════════════════════════════════
# HF Report Viewer API
# ═══════════════════════════════════════════════════════════════════════════

def _parse_hf_report(filepath):
    """Parse an HF report markdown file into a structured dict."""
    import re

    text = filepath.read_text(encoding='utf-8')
    result = {"meta": {}, "transcript": [], "global_conclusion": None}
    meta = result["meta"]

    # ── Header fields ──────────────────────────────────────────────────────
    m = re.search(r'^# Human Feedback Critique Report: (.+)$', text, re.MULTILINE)
    meta["object"] = m.group(1).strip() if m else "unknown"

    for key, pattern in [
        ("session",       r'\*\*Session:\*\*\s+(.+)'),
        ("age",           r'\*\*Age:\*\*\s+(.+)'),
        ("key_concept",   r'\*\*Key Concept:\*\*\s+(.+)'),
        ("date",          r'\*\*Date:\*\*\s+(.+)'),
        ("feedback_type", r'\*\*Feedback Type:\*\*\s+(.+)'),
    ]:
        m = re.search(pattern, text)
        meta[key] = m.group(1).strip() if m else None

    if meta["age"] == "None":
        meta["age"] = None

    m = re.search(r'\*\*Exchanges Critiqued:\*\*\s+(\d+)\s*/\s*(\d+)', text)
    meta["exchanges_critiqued"] = int(m.group(1)) if m else 0
    meta["exchanges_total"]     = int(m.group(2)) if m else 0

    # ── Split into sections by "## " headings ──────────────────────────────
    section_positions = [sm.start() for sm in re.finditer(r'^## ', text, re.MULTILINE)]
    sections = {}
    for i, pos in enumerate(section_positions):
        end = section_positions[i + 1] if i + 1 < len(section_positions) else len(text)
        sec = text[pos:end]
        name = sec.split('\n', 1)[0][3:].strip()
        sections[name] = sec

    def get_section(*keywords):
        for k, v in sections.items():
            if all(kw in k for kw in keywords):
                return v
        return ""

    # ── Parse transcript ────────────────────────────────────────────────────
    tlines = get_section("Conversation Transcript").splitlines()
    turns = []
    i = 0
    while i < len(tlines):
        line = tlines[i]
        # Model turn: **Model** `[PHASE]`**: [nodes] (Xms)
        mm = re.match(r'\*\*Model\*\*.*?\[([A-Z]+)\].*?\[([^\]]+)\]\s+\((\d+)ms\)', line)
        if mm:
            phase   = mm.group(1)
            nodes   = [n.strip() for n in mm.group(2).split('→')]
            time_ms = int(mm.group(3))
            body = []
            i += 1
            while i < len(tlines) and tlines[i] and not tlines[i].startswith('**') and tlines[i] != '---':
                body.append(tlines[i])
                i += 1
            turns.append({"role": "model", "phase": phase, "text": " ".join(body).strip(),
                          "nodes": nodes, "time_ms": time_ms, "exchange_index": None, "critique": None})
            continue
        # Child turn: **Child:** text
        mm = re.match(r'\*\*Child:\*\*\s*(.*)', line)
        if mm:
            turns.append({"role": "child", "text": mm.group(1).strip(), "exchange_index": None})
        i += 1

    # Assign exchange indices: child turn N → next model turn is exchange N
    # The Introduction (first model turn before any child) gets index 0
    child_count = 0
    waiting_for_model = False
    for turn in turns:
        if turn["role"] == "child":
            child_count += 1
            turn["exchange_index"] = child_count
            waiting_for_model = True
        elif turn["role"] == "model":
            if child_count == 0:
                turn["exchange_index"] = 0  # Introduction: before any child turn
            elif waiting_for_model:
                turn["exchange_index"] = child_count
                waiting_for_model = False

    result["transcript"] = turns

    # ── Parse critique sections ─────────────────────────────────────────────
    critiques = {}

    def parse_exchange_critique_section(sec, phase_key):
        blocks = re.split(r'\n### Exchange (\d+)\n', sec)
        it = iter(blocks[1:])
        for idx_str, block in zip(it, it):
            try:
                eidx = int(idx_str)
            except ValueError:
                continue

            crit = {"phase": phase_key, "expected": None, "problematic": None,
                    "conclusion": None, "node_trace": []}

            for rm in re.finditer(r'\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|', block):
                nd, tm, st = rm.group(1).strip(), rm.group(2).strip(), rm.group(3).strip()
                if nd in ("Node", "") or re.match(r'^-+$', nd):
                    continue
                crit["node_trace"].append({
                    "node":          nd,
                    "time_ms":       int(re.sub(r'[^\d]', '', tm) or '0'),
                    "state_changes": st if st not in ('-', '—', '') else None,
                })

            all_expected = re.findall(r'\*What is expected:\*\s*(.+)', block)
            all_problematic = re.findall(r'\*Why is it problematic:\*\s*(.+)', block)
            crit["expected"] = all_expected[-1].strip() if all_expected else None
            crit["problematic"] = all_problematic[-1].strip() if all_problematic else None

            cm = re.search(r'#### Conclusion\n+(.+?)(?=\n\n---|\n###|\Z)', block, re.DOTALL)
            crit["conclusion"] = cm.group(1).strip() if cm else None
            if crit["expected"] or crit["problematic"] or crit["conclusion"]:
                critiques[eidx] = crit

    for phase_label, phase_key in [("Chat Phase", "CHAT"), ("Guide Phase", "GUIDE")]:
        sec = get_section(phase_label, "Critique")
        if sec:
            parse_exchange_critique_section(sec, phase_key)

    conversation_sec = get_section("Conversation Critique")
    if conversation_sec:
        parse_exchange_critique_section(conversation_sec, "CHAT")

    # Parse Introduction critique (exchange_index == 0)
    intro_sec = get_section("Introduction")
    if intro_sec:
        crit = {"phase": "CHAT", "expected": None, "problematic": None,
                "conclusion": None, "node_trace": []}
        all_expected    = re.findall(r'\*What is expected:\*\s*(.+)', intro_sec)
        all_problematic = re.findall(r'\*Why is it problematic:\*\s*(.+)', intro_sec)
        crit["expected"]    = all_expected[-1].strip()    if all_expected    else None
        crit["problematic"] = all_problematic[-1].strip() if all_problematic else None
        cm = re.search(r'#### Conclusion\n+(.+?)(?=\n\n---|\n###|\Z)', intro_sec, re.DOTALL)
        crit["conclusion"] = cm.group(1).strip() if cm else None
        if crit["expected"] or crit["problematic"] or crit["conclusion"]:
            critiques[0] = crit

    # Attach critiques to matching model turns
    for turn in result["transcript"]:
        if turn["role"] == "model" and turn.get("exchange_index") in critiques:
            turn["critique"] = critiques[turn["exchange_index"]]

    # ── Global conclusion ────────────────────────────────────────────────────
    gc_sec = get_section("Global Conclusion")
    if gc_sec:
        body = re.sub(r'^## Global Conclusion\s*\n+', '', gc_sec).strip()
        result["global_conclusion"] = body or None

    return result


@app.route('/api/reports/hf')
def list_hf_reports():
    """Return metadata list for all HF reports, newest first."""
    from pathlib import Path
    hf_dir = Path(__file__).parent / "reports" / "HF"
    if not hf_dir.exists():
        return jsonify([])

    reports = []
    for date_dir in sorted(hf_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        date_str = date_dir.name
        for md_file in sorted(date_dir.glob("*.md"), reverse=True):
            try:
                parsed = _parse_hf_report(md_file)
                reports.append({"date": date_str, "filename": md_file.name, "meta": parsed["meta"]})
            except Exception as e:
                logger.warning(f"Failed to parse {md_file}: {e}")
    return jsonify(reports)


@app.route('/api/reports/hf/<date>/<filename>')
def get_hf_report(date, filename):
    """Return full parsed HF report as JSON."""
    from pathlib import Path
    filepath = Path(__file__).parent / "reports" / "HF" / date / filename
    if not filepath.exists() or filepath.suffix != '.md':
        return jsonify({"error": "Report not found"}), 404
    try:
        data = _parse_hf_report(filepath)
        data["date"] = date
        data["filename"] = filename
        return jsonify(data)
    except Exception as e:
        logger.error(f"Failed to parse {filepath}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/reports/hf/<date>/<filename>/raw')
def get_hf_report_raw(date, filename):
    """Return raw markdown content of an HF report as plain text."""
    from pathlib import Path
    filepath = Path(__file__).parent / "reports" / "HF" / date / filename
    if not filepath.exists() or filepath.suffix != '.md':
        return "Report not found", 404
    return Response(
        filepath.read_text(encoding='utf-8'),
        mimetype='text/plain',
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


def async_gen_to_sync(async_gen, loop):
    """
    Bridge async generator to sync generator WITHOUT buffering.

    Submits the async consumer coroutine to the persistent _ASYNC_LOOP via
    run_coroutine_threadsafe() so that all requests share one event loop and
    the httpx/anyio transport never sees a mismatched loop.

    Args:
        async_gen: Async generator to bridge
        loop: The persistent event loop (_ASYNC_LOOP)

    Yields:
        Items from async generator in real-time
    """
    import queue

    chunk_queue = queue.Queue()
    exception_holder = [None]

    async def consume():
        try:
            async for item in async_gen:
                chunk_queue.put(('chunk', item))
            chunk_queue.put(('done', None))
        except Exception as e:
            exception_holder[0] = e
            chunk_queue.put(('error', e))

    asyncio.run_coroutine_threadsafe(consume(), loop)  # non-blocking submit

    while True:
        msg_type, data = chunk_queue.get()  # blocks Flask thread until chunk ready
        if msg_type == 'chunk':
            yield data
        elif msg_type == 'done':
            break
        elif msg_type == 'error':
            raise exception_holder[0]


@app.route('/api/handoff', methods=['POST'])
def create_handoff():
    """Save conversation history to /tmp/handoff/ and return a WonderLens redirect URL."""
    data = request.get_json()
    session_id = data.get('session_id')
    assistant = sessions.get(session_id)
    if not assistant:
        return jsonify({'error': 'session not found'}), 404

    entity_name = assistant.object_name or ''
    age = assistant.age or 5
    if age <= 4:
        tier = 'T0'
    elif age <= 6:
        tier = 'T1'
    else:
        tier = 'T2'

    conversation = []
    for msg in assistant.conversation_history:
        if msg.get('role') == 'user':
            conversation.append({'role': 'child', 'text': msg.get('content', '')})
        elif msg.get('role') == 'assistant' and msg.get('content'):
            conversation.append({'role': 'ai', 'text': msg['content']})

    os.makedirs('/tmp/handoff', exist_ok=True)
    filename = uuid.uuid4().hex[:8] + '.json'
    with open(f'/tmp/handoff/{filename}', 'w', encoding='utf-8') as f:
        json.dump(conversation, f, indent=2, ensure_ascii=False)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, 'config.json'), 'r', encoding='utf-8') as f:
        config = json.load(f)
    wonderlens_url = config.get('wonderlens_url', 'http://localhost:5174')

    context_url = request.host_url + f'tmp/handoff/{filename}'
    redirect_url = f'{wonderlens_url}/?entity={entity_name}&tier={tier}&context={context_url}'

    return jsonify({'redirect_url': redirect_url, 'context_path': f'/tmp/handoff/{filename}'})


@app.route('/tmp/handoff/<filename>', methods=['GET'])
def serve_handoff(filename):
    """Serve a saved handoff JSON file from /tmp/handoff/."""
    filename = os.path.basename(filename)
    filepath = f'/tmp/handoff/{filename}'
    if not os.path.exists(filepath):
        return jsonify({'error': 'not found'}), 404
    with open(filepath, 'r', encoding='utf-8') as f:
        contents = f.read()
    return Response(contents, mimetype='application/json')


if __name__ == '__main__':
    print("=" * 60)
    print("Paixueji Assistant - Question-Asking System")
    print("=" * 60)
    print("\nServer starting...")
    print("URL: http://localhost:5000")
    print("\nEndpoints:")
    print("  GET  /api/health          - Health check")
    print("  POST /api/start           - Start conversation (SSE)")
    print("                              Requires: object_name")
    print("  POST /api/continue        - Continue conversation (SSE)")
    print("                              Requires: session_id, child_input")
    print("  POST /api/reset           - Delete session")
    print("  GET  /api/sessions        - List active sessions")
    print("  GET  /                    - Web interface")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
