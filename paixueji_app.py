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
import re
from typing import Optional

from google import genai
from google.genai.types import HttpOptions
from loguru import logger

from paixueji_assistant import PaixuejiAssistant
from graph import paixueji_graph
from schema import BridgeDebugInfo, StreamChunk
import paixueji_prompts
import time
from graph_lookup import lookup_top_available_concepts
from object_resolver import parse_anchor_confirmation, resolve_object_input
from bridge_context import build_bridge_context
from bridge_debug import (
    build_activation_continuity_anchor,
    build_activation_transition_debug,
    build_bridge_debug,
    build_bridge_trace_entry,
    format_bridge_log_line,
)
from bridge_activation_policy import (
    BRIDGE_PHASE_ACTIVATION,
    BRIDGE_PHASE_ANCHOR_GENERAL,
    BRIDGE_PHASE_PRE_ANCHOR,
    classify_activation_reopen_signal,
    extract_final_question,
)
from kb_context import (
    build_bridge_activation_grounding_context,
)
from pre_anchor_policy import classify_pre_anchor_reply
from resolution_debug import format_resolution_log_line
# Module-level compiled regex for stripping REASON lines from activity follow-ups.
# Must be defined here (not inside a function) to avoid re-compiling on every request.
_REASON_RE = re.compile(r"REASON:\s*(.+?)(?:\n|$)")

# Intents that do not receive a follow-up question in the attribute activity stream.
# Defined at module level so tests can import it directly.
INTENTS_WITHOUT_FOLLOWUP = {"play", "emotional"}

from stream import (
    ask_attribute_intro_stream,
    ask_category_intro_stream,
    ask_followup_question_stream,
    classify_intent,
    classify_pre_anchor_semantic_reply,
    generate_attribute_activation_response_stream,
    generate_category_activation_response_stream,
    generate_bridge_activation_response_stream,
    generate_bridge_retry_response_stream,
    generate_bridge_support_response_stream,
    infer_domain,
    generate_topic_switch_response_stream,
    prepare_messages_for_streaming,
    extract_previous_response,
)
from stream.errors import build_sse_error_payload
from stream.validation import (
    validate_bridge_activation_answer,
    validate_bridge_activation_kb_question,
)
from attribute_activity import (
    build_attribute_debug,
    select_attribute_profile,
    start_attribute_session,
)
from category_activity import (
    build_category_debug,
    build_category_profile,
    classify_category_reply,
    evaluate_category_activity_readiness,
    start_category_session,
)

classify_bridge_follow = classify_pre_anchor_semantic_reply

app = Flask(__name__, static_folder='static')
CORS(app)

# In-memory session storage
# NOTE: Sessions will be lost on server restart
# For production, consider using Redis or database storage

sessions = {}

ALLOWED_MODELS = {"gemini-3.1-flash-lite-preview", "gemini-2.0-flash-lite"}
MAX_BRIDGE_ATTEMPTS = 2
MAX_PRE_ANCHOR_SUPPORT_TURNS = 2
MAX_BRIDGE_ACTIVATION_TURNS = 4

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


def _latest_assistant_message(history: list[dict]) -> Optional[dict]:
    for message in reversed(history or []):
        if message.get("role") == "assistant":
            return message
    return None


def _assistant_stream_fields(assistant: PaixuejiAssistant) -> dict:
    activity_ready = getattr(assistant, "attribute_activity_ready", False)
    activity_target = assistant.attribute_activity_target() if hasattr(assistant, "attribute_activity_target") else None
    if getattr(assistant, "category_lane_active", False) or getattr(assistant, "category_pipeline_enabled", False):
        activity_ready = getattr(assistant, "category_activity_ready", False)
        activity_target = assistant.category_activity_target() if hasattr(assistant, "category_activity_target") else None

    latest = _latest_assistant_message(assistant.conversation_history)
    selected_hook_type = latest.get("selected_hook_type") if latest else None
    question_style = latest.get("question_style") if latest else None

    return {
        "current_object_name": assistant.object_name,
        "surface_object_name": assistant.surface_object_name,
        "anchor_object_name": assistant.anchor_object_name,
        "anchor_status": assistant.anchor_status,
        "anchor_relation": assistant.anchor_relation,
        "anchor_confidence_band": assistant.anchor_confidence_band,
        "anchor_confirmation_needed": assistant.anchor_confirmation_needed,
        "bridge_profile": assistant.bridge_profile.__dict__ if assistant.bridge_profile else None,
        "learning_anchor_active": assistant.learning_anchor_active,
        "bridge_phase": getattr(assistant, "bridge_phase", None),
        "bridge_attempt_count": assistant.bridge_attempt_count,
        "pre_anchor_support_count": assistant.pre_anchor_support_count,
        "activation_turn_count": getattr(assistant, "activation_turn_count", 0),
        "activation_handoff_ready": getattr(assistant, "activation_handoff_ready", False),
        "attribute_pipeline_enabled": getattr(assistant, "attribute_pipeline_enabled", False),
        "attribute_lane_active": getattr(assistant, "attribute_lane_active", False),
        "attribute_debug": getattr(assistant, "last_attribute_debug", None),
        "category_pipeline_enabled": getattr(assistant, "category_pipeline_enabled", False),
        "category_lane_active": getattr(assistant, "category_lane_active", False),
        "category_debug": getattr(assistant, "last_category_debug", None),
        "activity_ready": activity_ready,
        "activity_target": activity_target,
        "resolution_debug": assistant.session_resolution_debug,
        "selected_hook_type": selected_hook_type,
        "question_style": question_style,
    }


def _apply_activation_stream_fields(chunk: StreamChunk, initial_state: dict) -> StreamChunk:
    update = {}
    for field in ("activation_child_reply_type", "counted_turn", "counted_turn_reason"):
        value = getattr(chunk, field, None)
        if value is None:
            value = initial_state.get(field)
        update[field] = value
    if getattr(chunk, "bridge_debug", None) is None and initial_state.get("bridge_debug") is not None:
        bridge_debug = initial_state.get("bridge_debug")
        if isinstance(bridge_debug, dict):
            bridge_debug = BridgeDebugInfo.model_validate(bridge_debug)
        update["bridge_debug"] = bridge_debug
    return chunk.model_copy(update=update)


def _normalize_post_handoff_bridge_debug(bridge_debug: dict | BridgeDebugInfo | None) -> dict | None:
    """Rewrite activation debug into provenance for the first ordinary-chat post-handoff turn."""
    if not bridge_debug:
        return None

    if isinstance(bridge_debug, BridgeDebugInfo):
        normalized = bridge_debug.model_dump()
    else:
        normalized = dict(bridge_debug)

    normalized["decision"] = "activation_handoff_committed"
    normalized["decision_reason"] = "post-handoff provenance attached to ordinary chat turn"
    normalized["response_type"] = "correct_answer"
    normalized["kb_mode"] = None
    normalized["activation_grounding_mode"] = None
    normalized["activation_grounding_summary"] = None
    return normalized


def _intro_mode_for_assistant(assistant: PaixuejiAssistant) -> str:
    if assistant.anchor_status == "anchored_high":
        return "anchor_bridge"
    if assistant.anchor_status == "anchored_medium":
        return "anchor_confirmation"
    if assistant.anchor_status == "unresolved":
        return "unknown_object"
    return "supported"


def _bridge_context_summary(bridge_context) -> str:
    if not bridge_context:
        return ""
    summary_lines = [f"intent: {bridge_context.bridge_intent}"]
    if bridge_context.good_question_angles:
        summary_lines.append(f"angles: {', '.join(bridge_context.good_question_angles)}")
    if bridge_context.focus_cues:
        summary_lines.append(f"focus cues: {', '.join(bridge_context.focus_cues)}")
    return " | ".join(summary_lines)


def _activation_grounding_summary(mode: str, activation_grounding_context: str) -> str:
    if not activation_grounding_context:
        return ""
    line_count = len([line for line in activation_grounding_context.splitlines() if line.strip()])
    return f"{mode}: {line_count} non-empty grounding lines"


def _activation_transition_before_state(assistant: PaixuejiAssistant) -> dict:
    return {
        "activation_handoff_ready_before": getattr(assistant, "activation_handoff_ready", False),
        "activation_last_question_before": getattr(assistant, "activation_last_question", None),
        "activation_last_question_kb_item_before": getattr(assistant, "activation_last_question_kb_item", None),
        "activation_last_question_validation_source_before": getattr(assistant, "activation_last_question_validation_source", None),
        "activation_last_question_validation_confidence_before": getattr(assistant, "activation_last_question_validation_confidence", None),
        "activation_last_question_validation_reason_before": getattr(assistant, "activation_last_question_validation_reason", None),
        "activation_last_question_continuity_anchor_before": getattr(assistant, "activation_last_question_continuity_anchor", None),
        "bridge_phase_before": getattr(assistant, "bridge_phase", None),
        "activation_turn_count_before": getattr(assistant, "activation_turn_count", 0),
    }


def _activation_question_validation_state(kb_result: dict | None, final_question: str | None) -> dict:
    kb_item = (kb_result or {}).get("kb_item")
    return {
        "source": (kb_result or {}).get("source"),
        "confidence": (kb_result or {}).get("confidence"),
        "reason": (kb_result or {}).get("reason"),
        "kb_backed_question": (kb_result or {}).get("kb_backed_question"),
        "handoff_ready_question": (kb_result or {}).get("handoff_ready_question"),
        "kb_item": kb_item,
        "activation_last_question_after": final_question,
        "activation_last_question_kb_item_after": kb_item,
        "activation_last_question_continuity_anchor_after": build_activation_continuity_anchor(kb_item),
    }


def _activation_answer_validation_state(answer_result: dict | None, *, attempted: bool) -> dict:
    answer_result = answer_result or {}
    answered_previous_question = answer_result.get(
        "answered_previous_question",
        answer_result.get("answered_previous_kb_question"),
    )
    return {
        "handoff_check_attempted": attempted,
        "source": answer_result.get("source"),
        "reason": answer_result.get("reason"),
        "answered_previous_question": answered_previous_question,
        "answered_previous_kb_question": answer_result.get("answered_previous_kb_question"),
        "answer_polarity": answer_result.get("answer_polarity"),
    }


def _activation_outcome_state(*, handoff_result: str | None, handoff_block_reason: str | None = None) -> dict:
    return {
        "handoff_result": handoff_result,
        "handoff_block_reason": handoff_block_reason,
        "bridge_success": handoff_result == "committed_to_anchor_general",
    }


def _activation_turn_interpretation_state(*, activation_child_reply_type: str | None, counted_turn: bool | None, counted_turn_reason: str | None) -> dict:
    return {
        "activation_child_reply_type": activation_child_reply_type,
        "counted_turn": counted_turn,
        "counted_turn_reason": counted_turn_reason,
    }


def _activation_continuity_state(*, before_anchor: str | None, after_anchor: str | None, handoff_result: str | None) -> dict:
    if handoff_result == "committed_to_anchor_general":
        continuity_preserved = before_anchor is not None
        continuity_break_reason = None
        after_anchor = after_anchor or before_anchor
    elif before_anchor and after_anchor:
        continuity_preserved = before_anchor == after_anchor
        continuity_break_reason = None if continuity_preserved else "local_focus_changed"
    elif before_anchor and not after_anchor:
        continuity_preserved = False
        continuity_break_reason = "new_question_not_kb_backed"
    elif not before_anchor and after_anchor:
        continuity_preserved = False
        continuity_break_reason = "previous_question_not_kb_backed"
    else:
        continuity_preserved = None
        continuity_break_reason = None
    return {
        "continuity_anchor_before": before_anchor,
        "continuity_anchor_after": after_anchor,
        "continuity_preserved": continuity_preserved,
        "continuity_break_reason": continuity_break_reason,
    }


def _build_activation_transition_payload(
    *,
    assistant: PaixuejiAssistant,
    before_state: dict | None = None,
    kb_result: dict | None,
    final_question: str | None,
    answer_result: dict | None,
    handoff_check_attempted: bool,
    handoff_result: str | None,
    handoff_block_reason: str | None,
    activation_child_reply_type: str | None,
    counted_turn: bool | None,
    counted_turn_reason: str | None,
    continuity: dict | None = None,
) -> dict:
    before_state = before_state or _activation_transition_before_state(assistant)
    question_validation = _activation_question_validation_state(kb_result, final_question)
    answer_validation = _activation_answer_validation_state(answer_result, attempted=handoff_check_attempted)
    continuity = continuity or _activation_continuity_state(
        before_anchor=before_state.get("activation_last_question_continuity_anchor_before"),
        after_anchor=question_validation.get("activation_last_question_continuity_anchor_after"),
        handoff_result=handoff_result,
    )
    return build_activation_transition_debug(
        before_state=before_state,
        question_validation=question_validation,
        answer_validation=answer_validation,
        outcome=_activation_outcome_state(
            handoff_result=handoff_result,
            handoff_block_reason=handoff_block_reason,
        ),
        turn_interpretation=_activation_turn_interpretation_state(
            activation_child_reply_type=activation_child_reply_type,
            counted_turn=counted_turn,
            counted_turn_reason=counted_turn_reason,
        ),
        continuity=continuity,
    )


def _is_activation_free_support(child_answer: str) -> bool:
    normalized = " ".join((child_answer or "").strip().lower().split())
    if not normalized:
        return True
    clarification_patterns = {
        "what do you mean",
        "whay do you mean",
        "what you mean",
        "i don't understand",
        "i dont understand",
        "huh",
    }
    idk_patterns = {
        "i don't know",
        "i dont know",
        "don't know",
        "dont know",
        "idk",
        "not sure",
    }
    return normalized in clarification_patterns or normalized in idk_patterns


def _latest_bridge_question(conversation_history: list[dict]) -> str | None:
    intro_bridge_fallback = None

    for message in reversed(conversation_history or []):
        if message.get("role") != "assistant":
            continue

        response_type = message.get("response_type")
        if response_type in {"bridge_retry", "bridge_support"}:
            return (message.get("content") or "").strip()

        if response_type == "introduction":
            bridge_debug = message.get("bridge_debug") or {}
            if bridge_debug.get("decision") == "intro_bridge" and intro_bridge_fallback is None:
                intro_bridge_fallback = (message.get("content") or "").strip()

    return intro_bridge_fallback

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
    attribute_pipeline_enabled = bool(data.get('attribute_pipeline_enabled', False))
    category_pipeline_enabled = bool(data.get('category_pipeline_enabled', False))
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
    assistant.correct_answer_count = 0
    resolution = resolve_object_input(
        raw_object_name=object_name,
        age=age or 6,
        client=assistant.client,
        config=assistant.config,
    )
    assistant.apply_resolution(resolution)
    assistant.attribute_pipeline_enabled = attribute_pipeline_enabled
    assistant.category_pipeline_enabled = category_pipeline_enabled
    if attribute_pipeline_enabled:
        try:
            future = asyncio.run_coroutine_threadsafe(
                select_attribute_profile(
                    object_name=object_name,
                    age=age or 6,
                    anchor_status=assistant.anchor_status,
                    client=assistant.client,
                    config=assistant.config,
                ),
                _ASYNC_LOOP,
            )
            attribute_profile, selection_debug = future.result(timeout=10)
        except Exception as exc:
            attribute_profile = None
            selection_debug = {
                "decision": "no_attribute_match_fallback",
                "source": "exception",
                "reason": str(exc),
            }

        if attribute_profile:
            attribute_state = start_attribute_session(
                object_name=object_name,
                profile=attribute_profile,
                age=age or 6,
            )
            assistant.start_attribute_lane(attribute_state, attribute_profile)
            assistant.set_last_attribute_debug(
                build_attribute_debug(
                    decision="attribute_lane_started",
                    profile=attribute_profile,
                    state=attribute_state,
                    reason=selection_debug.get("reason"),
                )
            )
        else:
            assistant.clear_attribute_lane()
            assistant.attribute_pipeline_enabled = True
            assistant.set_last_attribute_debug(selection_debug)
    if category_pipeline_enabled:
        try:
            future = asyncio.run_coroutine_threadsafe(
                infer_domain(
                    object_name,
                    assistant.client,
                    assistant.config,
                ),
                _ASYNC_LOOP,
            )
            category_domain = future.result(timeout=10)
        except Exception as exc:
            category_domain = None
            category_reason = str(exc)
        else:
            category_reason = "domain inferred for category lane" if category_domain else "generic category fallback"

        category_profile = build_category_profile(category_domain, object_name)
        category_state = start_category_session(
            object_name=object_name,
            profile=category_profile,
            age=age or 6,
        )
        assistant.start_category_lane(category_state, category_profile)
        assistant.set_last_category_debug(
            build_category_debug(
                decision="category_lane_started",
                profile=category_profile,
                state=category_state,
                reason=category_reason,
            )
        )
    logger.info(
        f"[RESOLUTION] {format_resolution_log_line(session_id=session_id, request_id='start', resolution_debug=assistant.session_resolution_debug)}"
    )
    logger.info(
        f"[BRIDGE] {format_bridge_log_line(session_id=session_id, request_id='start', bridge_debug=assistant.session_resolution_debug)}"
    )

    if assistant.learning_anchor_active:
        dimensions_object_name = object_name if resolution.anchor_status == "exact_supported" else assistant.object_name
        assistant.load_dimension_data(dimensions_object_name)
    else:
        assistant.physical_dimensions = {}
        assistant.engagement_dimensions = {}

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
          f"request_id={request_id[:8]}..., resolution={assistant.anchor_status}")

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
            introduction_content = f"Start conversation about {assistant.visible_object_name or object_name}"

            loop = _ASYNC_LOOP

            try:
                async def stream_introduction():
                    if assistant.category_lane_active and assistant.category_state:
                        messages = prepare_messages_for_streaming(
                            assistant.conversation_history.copy(),
                            age_prompt,
                        )
                        generator = ask_category_intro_stream(
                            messages=messages,
                            object_name=assistant.category_state.object_name,
                            category_label=assistant.category_state.profile.category_label,
                            activity_target=assistant.category_state.profile.activity_target,
                            age_prompt=age_prompt,
                            age=age or 6,
                            config=assistant.config,
                            client=assistant.client,
                        )
                        sequence_number = 0
                        full_response = ""
                        async for text_chunk, token_usage, full_so_far, _decision_info in generator:
                            full_response = full_so_far
                            if not text_chunk:
                                continue
                            sequence_number += 1
                            yield sse_event("chunk", StreamChunk(
                                response=text_chunk,
                                session_finished=False,
                                duration=0.0,
                                token_usage=token_usage,
                                finish=False,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type="category_intro",
                                correct_answer_count=assistant.correct_answer_count,
                                **_assistant_stream_fields(assistant),
                            ))

                        category_debug = build_category_debug(
                            decision="category_intro",
                            profile=assistant.category_profile,
                            state=assistant.category_state,
                            reason="intro generated",
                            response_text=full_response,
                        )
                        assistant.set_last_category_debug(category_debug)
                        assistant.conversation_history.append({
                            "role": "assistant",
                            "content": full_response,
                            "nodes_executed": [],
                            "mode": "chat",
                            "response_type": "category_intro",
                            "category_debug": category_debug,
                        })
                        sequence_number += 1
                        yield sse_event("chunk", StreamChunk(
                            response=full_response,
                            session_finished=False,
                            duration=0.0,
                            token_usage=None,
                            finish=True,
                            sequence_number=sequence_number,
                            timestamp=time.time(),
                            session_id=session_id,
                            request_id=request_id,
                            response_type="category_intro",
                            correct_answer_count=assistant.correct_answer_count,
                            **_assistant_stream_fields(assistant),
                        ))
                        return

                    if assistant.attribute_lane_active and assistant.attribute_state:
                        messages = prepare_messages_for_streaming(
                            assistant.conversation_history.copy(),
                            age_prompt,
                        )
                        generator = ask_attribute_intro_stream(
                            messages=messages,
                            object_name=assistant.attribute_state.object_name,
                            attribute_label=assistant.attribute_state.profile.label,
                            activity_target=assistant.attribute_state.profile.activity_target,
                            attribute_branch=assistant.attribute_state.profile.branch,
                            age_prompt=age_prompt,
                            age=age or 6,
                            config=assistant.config,
                            client=assistant.client,
                        )
                        sequence_number = 0
                        full_response = ""
                        async for text_chunk, token_usage, full_so_far, _decision_info in generator:
                            full_response = full_so_far
                            if not text_chunk:
                                continue
                            sequence_number += 1
                            yield sse_event("chunk", StreamChunk(
                                response=text_chunk,
                                session_finished=False,
                                duration=0.0,
                                token_usage=token_usage,
                                finish=False,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type="attribute_intro",
                                correct_answer_count=assistant.correct_answer_count,
                                intent_type=None,
                                **_assistant_stream_fields(assistant),
                            ))

                        attribute_debug = build_attribute_debug(
                            decision="attribute_intro",
                            profile=assistant.attribute_profile,
                            state=assistant.attribute_state,
                            reason="intro generated",
                            response_text=full_response,
                            reply_type="attribute_intro",
                        )
                        assistant.set_last_attribute_debug(attribute_debug)
                        assistant.conversation_history.append({
                            "role": "assistant",
                            "content": full_response,
                            "nodes_executed": [],
                            "mode": "chat",
                            "response_type": "attribute_intro",
                            "attribute_debug": attribute_debug,
                            "resolution_debug": assistant.session_resolution_debug,
                        })
                        sequence_number += 1
                        yield sse_event("chunk", StreamChunk(
                            response=full_response,
                            session_finished=False,
                            duration=0.0,
                            token_usage=None,
                            finish=True,
                            sequence_number=sequence_number,
                            timestamp=time.time(),
                            session_id=session_id,
                            request_id=request_id,
                            response_type="attribute_intro",
                            correct_answer_count=assistant.correct_answer_count,
                            **_assistant_stream_fields(assistant),
                        ))
                        return

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
                        "object_name": assistant.object_name,
                        "surface_object_name": assistant.surface_object_name,
                        "anchor_object_name": assistant.anchor_object_name,
                        "anchor_status": assistant.anchor_status,
                        "anchor_relation": assistant.anchor_relation,
                        "anchor_confidence_band": assistant.anchor_confidence_band,
                        "anchor_confirmation_needed": assistant.anchor_confirmation_needed,
                        "bridge_profile": assistant.bridge_profile,
                        "learning_anchor_active": assistant.learning_anchor_active,
                        "bridge_phase": assistant.bridge_phase,
                        "bridge_attempt_count": 0,
                        "bridge_debug": None,
                        "resolution_debug": assistant.session_resolution_debug,
                        "correct_answer_count": 0,
                        "intro_mode": _intro_mode_for_assistant(assistant),
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
                        "question_style": None,
                        "attribute_pipeline_enabled": assistant.attribute_pipeline_enabled,

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

                    if assistant.anchor_status == "unresolved":
                        initial_state["bridge_debug"] = build_bridge_debug(
                            surface_object_name=assistant.surface_object_name,
                            anchor_object_name=assistant.anchor_object_name,
                            anchor_status=assistant.anchor_status,
                            anchor_relation=assistant.anchor_relation,
                            anchor_confidence_band=assistant.anchor_confidence_band,
                            intro_mode="unknown_object",
                            learning_anchor_active_before=False,
                            learning_anchor_active_after=False,
                            bridge_attempt_count_before=0,
                            bridge_attempt_count_after=0,
                            decision="bridge_not_started",
                            decision_reason="resolution_unresolved",
                            response_type="introduction",
                            pre_anchor_handler_entered=False,
                            kb_mode="surface_only_unresolved",
                        )

                    async for chunk in stream_graph_execution(initial_state):
                        # Yield StreamChunk as SSE event (pass directly for optimized serialization)
                        # Update conversation history with final response
                        chunk = _apply_activation_stream_fields(chunk, initial_state)
                        attribute_update = {
                            key: value
                            for key, value in _assistant_stream_fields(assistant).items()
                            if key.startswith("attribute_") or key in {"activity_ready", "activity_target"}
                        }
                        chunk = chunk.model_copy(update=attribute_update)
                        if chunk.finish:
                            if chunk.bridge_debug:
                                assistant.set_last_bridge_debug(chunk.bridge_debug.model_dump())
                                logger.info(
                                    f"[BRIDGE] {format_bridge_log_line(session_id=session_id, request_id=request_id, bridge_debug=chunk.bridge_debug.model_dump())}"
                                )
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response,
                                "nodes_executed": chunk.nodes_executed or [],
                                "mode": "chat",
                                "response_type": chunk.response_type,
                                "bridge_debug": chunk.bridge_debug.model_dump() if chunk.bridge_debug else None,
                                "resolution_debug": chunk.resolution_debug.model_dump() if chunk.resolution_debug else assistant.session_resolution_debug,
                                "classification_status": chunk.classification_status,
                                "classification_failure_reason": chunk.classification_failure_reason,
                                "selected_hook_type": chunk.selected_hook_type,
                                "question_style": chunk.question_style,
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
            turn_bridge_debug = None
            turn_bridge_traces = []
            activation_child_reply_type = None
            counted_turn = None
            counted_turn_reason = None

            # Get age prompt if age is set
            age_prompt = ""
            if assistant.age is not None:
                age_prompt = assistant.get_age_prompt(assistant.age)

            # Get category prompt (set by YAML classification on session start or topic switch)
            category_prompt = assistant.category_prompt or ""

            # NOTE: User message is added to conversation_history inside the graph after turn completes

            loop = _ASYNC_LOOP

            try:
                if assistant.category_lane_active and assistant.category_state:
                    decision = classify_category_reply(assistant.category_state, child_input)
                    if decision.counted_turn:
                        assistant.category_state.turn_count += 1

                    readiness = evaluate_category_activity_readiness(
                        assistant.category_state,
                        decision,
                    )
                    if readiness.activity_ready:
                        assistant.category_state.activity_ready = True
                        assistant.category_activity_ready = True

                    response_type = "category_activity" if readiness.activity_ready else "category_chat"

                    async def stream_category_activity():
                        messages = prepare_messages_for_streaming(
                            assistant.conversation_history.copy(),
                            age_prompt,
                        )
                        generator = generate_category_activation_response_stream(
                            messages=messages,
                            object_name=assistant.category_state.object_name,
                            category_label=assistant.category_state.profile.category_label,
                            activity_target=assistant.category_state.profile.activity_target,
                            child_answer=child_input,
                            reply_type=decision.reply_type,
                            state_action=readiness.state_action,
                            age=assistant.age or 6,
                            age_prompt=age_prompt,
                            config=assistant.config,
                            client=assistant.client,
                        )

                        sequence_number = 0
                        full_response = ""
                        async for text_chunk, token_usage, full_so_far in generator:
                            full_response = full_so_far
                            if not text_chunk:
                                continue
                            partial_debug = build_category_debug(
                                decision=response_type,
                                profile=assistant.category_profile,
                                state=assistant.category_state,
                                reason=decision.reason,
                                reply=decision,
                                readiness=readiness,
                            )
                            assistant.set_last_category_debug(partial_debug)
                            sequence_number += 1
                            yield sse_event("chunk", StreamChunk(
                                response=text_chunk,
                                session_finished=False,
                                duration=0.0,
                                token_usage=token_usage,
                                finish=False,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type=response_type,
                                correct_answer_count=assistant.correct_answer_count,
                                chat_phase_complete=assistant.category_activity_ready or None,
                                **_assistant_stream_fields(assistant),
                            ))

                        category_debug = build_category_debug(
                            decision=response_type,
                            profile=assistant.category_profile,
                            state=assistant.category_state,
                            reason=decision.reason,
                            reply=decision,
                            readiness=readiness,
                            response_text=full_response,
                        )
                        assistant.set_last_category_debug(category_debug)
                        assistant.conversation_history.append({"role": "user", "content": child_input})
                        assistant.conversation_history.append({
                            "role": "assistant",
                            "content": full_response,
                            "mode": "chat",
                            "response_type": response_type,
                            "category_debug": category_debug,
                        })
                        sequence_number += 1
                        yield sse_event("chunk", StreamChunk(
                            response=full_response,
                            session_finished=False,
                            duration=0.0,
                            token_usage=None,
                            finish=True,
                            sequence_number=sequence_number,
                            timestamp=time.time(),
                            session_id=session_id,
                            request_id=request_id,
                            response_type=response_type,
                            correct_answer_count=assistant.correct_answer_count,
                            chat_phase_complete=assistant.category_activity_ready or None,
                            **_assistant_stream_fields(assistant),
                        ))
                        yield sse_event("complete", {"success": True})

                    gen = stream_category_activity()
                    for event in async_gen_to_sync(gen, loop):
                        yield event
                    return

                if assistant.attribute_lane_active and assistant.attribute_state:
                    assistant.attribute_state.turn_count += 1

                    try:
                        intent_future = asyncio.run_coroutine_threadsafe(
                            classify_intent(
                                assistant=assistant,
                                child_answer=child_input,
                                object_name=assistant.attribute_state.object_name,
                                age=assistant.age or 6,
                            ),
                            _ASYNC_LOOP,
                        )
                        intent_result = intent_future.result(timeout=10)
                        intent_type_lower = (intent_result.get("intent_type") or "classification_fallback").lower()
                        attribute_reason = intent_result.get("reasoning") or "intent classified for discovery continuation"
                    except Exception as exc:
                        intent_type_lower = "classification_fallback"
                        attribute_reason = f"intent classification fallback: {exc}"

                    async def stream_attribute_activity():
                        needs_followup = intent_type_lower not in INTENTS_WITHOUT_FOLLOWUP

                        messages = prepare_messages_for_streaming(
                            assistant.conversation_history.copy(),
                            age_prompt,
                        )
                        attribute_label = assistant.attribute_state.profile.label
                        activity_target = assistant.attribute_state.profile.activity_target
                        object_name_attr = assistant.attribute_state.object_name

                        response_generator = generate_attribute_activation_response_stream(
                            messages=messages,
                            intent_type=intent_type_lower,
                            object_name=object_name_attr,
                            attribute_label=attribute_label,
                            activity_target=activity_target,
                            child_answer=child_input,
                            reply_type="discovery",
                            state_action="continue_conversation",
                            age=assistant.age or 6,
                            age_prompt=age_prompt,
                            knowledge_context="",
                            last_model_response=extract_previous_response(assistant.conversation_history),
                            config=assistant.config,
                            client=assistant.client,
                        )

                        sequence_number = 0
                        full_response = ""
                        async for text_chunk, token_usage, full_so_far in response_generator:
                            full_response = full_so_far
                            if not text_chunk:
                                continue
                            partial_debug = build_attribute_debug(
                                decision="attribute_activity_response",
                                profile=assistant.attribute_profile,
                                state=assistant.attribute_state,
                                reason=attribute_reason,
                                intent_type=intent_type_lower,
                                reply_type="discovery",
                                activity_marker_rejected_reason=None,
                            )
                            assistant.set_last_attribute_debug(partial_debug)
                            sequence_number += 1
                            yield sse_event("chunk", StreamChunk(
                                response=text_chunk,
                                session_finished=False,
                                duration=0.0,
                                token_usage=token_usage,
                                finish=False,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type="attribute_activity",
                                correct_answer_count=assistant.correct_answer_count,
                                intent_type=intent_type_lower,
                                **_assistant_stream_fields(assistant),
                            ))

                        soft_guide = paixueji_prompts.get_prompts()["attribute_soft_guide"].format(
                            attribute_label=attribute_label,
                            activity_target=activity_target,
                        )

                        if needs_followup:
                            messages_with_response = messages + [
                                {"role": "user", "content": child_input},
                                {"role": "assistant", "content": full_response},
                            ]
                            followup_generator = ask_followup_question_stream(
                                messages=messages_with_response,
                                object_name=object_name_attr,
                                age_prompt=age_prompt,
                                age=assistant.age or 6,
                                config=assistant.config,
                                client=assistant.client,
                                attribute_soft_guide=soft_guide,
                                response_text=full_response if intent_type_lower == "curiosity" else "",
                            )

                            activity_marker = "[ACTIVITY_READY]"
                            activity_marker_detected = False
                            activity_marker_reason = None
                            raw_followup_so_far = ""
                            full_followup = ""

                            def _displayable_followup(raw_followup: str) -> str:
                                # Strip the activity marker
                                marker_free_followup = raw_followup.replace(activity_marker, "")
                                if activity_marker in raw_followup:
                                    # Also strip the REASON line if present
                                    marker_free_followup = _REASON_RE.sub("", marker_free_followup)
                                    # Clean up any trailing newlines left after stripping
                                    marker_free_followup = marker_free_followup.rstrip("\n")
                                    return marker_free_followup

                                max_buffered_prefix = min(len(raw_followup), len(activity_marker) - 1)
                                for suffix_len in range(max_buffered_prefix, 0, -1):
                                    if raw_followup.endswith(activity_marker[:suffix_len]):
                                        return marker_free_followup[:-suffix_len]
                                return marker_free_followup

                            async for _text_chunk, token_usage, full_so_far in followup_generator:
                                raw_followup_so_far = full_so_far
                                if activity_marker in raw_followup_so_far:
                                    activity_marker_detected = True
                                displayable_followup = _displayable_followup(raw_followup_so_far)
                                visible_chunk = displayable_followup[len(full_followup):]
                                full_followup = displayable_followup
                                if visible_chunk == "":
                                    continue
                                sequence_number += 1
                                yield sse_event("chunk", StreamChunk(
                                    response=visible_chunk,
                                    session_finished=False,
                                    duration=0.0,
                                    token_usage=token_usage,
                                    finish=False,
                                    sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="attribute_activity",
                                    correct_answer_count=assistant.correct_answer_count,
                                    intent_type=intent_type_lower,
                                    **_assistant_stream_fields(assistant),
                                ))

                            full_followup = _displayable_followup(raw_followup_so_far)

                            # Extract reason from raw text after marker is fully present
                            if activity_marker_detected:
                                reason_match = _REASON_RE.search(raw_followup_so_far)
                                if reason_match:
                                    activity_marker_reason = reason_match.group(1).strip()

                            activity_marker_rejected_reason = None
                            if activity_marker_detected and activity_marker_reason:
                                quotes = re.findall(r'"([^"]+)"', activity_marker_reason)
                                if not quotes:
                                    activity_marker_rejected_reason = "no_evidence_quotes"
                                    logger.info("[ACTIVITY_READY] rejected: no evidence quotes in reason")
                                else:
                                    child_messages = [
                                        msg["content"] for msg in assistant.conversation_history
                                        if msg.get("role") == "user"
                                    ]
                                    found_match = False
                                    for quote in quotes:
                                        quote_lower = quote.lower()
                                        for child_msg in child_messages:
                                            if quote_lower in child_msg.lower():
                                                found_match = True
                                                break
                                        if found_match:
                                            break
                                    if not found_match:
                                        activity_marker_rejected_reason = "evidence_not_in_transcript"
                                        logger.info(
                                            "[ACTIVITY_READY] rejected: evidence quotes not found in transcript — %s",
                                            quotes,
                                        )

                            if activity_marker_detected and not activity_marker_rejected_reason:
                                assistant.attribute_state.activity_ready = True
                                assistant.attribute_activity_ready = True
                        else:
                            full_followup = ""
                            activity_marker_detected = False
                            activity_marker_reason = None

                        combined_response = (full_response + " " + full_followup).strip()
                        attribute_debug = build_attribute_debug(
                            decision="attribute_activity",
                            profile=assistant.attribute_profile,
                            state=assistant.attribute_state,
                            reason=attribute_reason,
                            activity_marker_detected=activity_marker_detected,
                            activity_marker_reason=activity_marker_reason,
                            activity_marker_rejected_reason=activity_marker_rejected_reason,
                            response_text=combined_response,
                            intent_type=intent_type_lower,
                            reply_type="discovery",
                        )
                        assistant.set_last_attribute_debug(attribute_debug)
                        assistant.conversation_history.append({"role": "user", "content": child_input})
                        assistant.conversation_history.append({
                            "role": "assistant",
                            "content": combined_response,
                            "mode": "chat",
                            "response_type": "attribute_activity",
                            "attribute_debug": attribute_debug,
                        })
                        sequence_number += 1
                        yield sse_event("chunk", StreamChunk(
                            response=combined_response,
                            session_finished=False,
                            duration=0.0,
                            token_usage=None,
                            finish=True,
                            sequence_number=sequence_number,
                            timestamp=time.time(),
                            session_id=session_id,
                            request_id=request_id,
                            response_type="attribute_activity",
                            correct_answer_count=assistant.correct_answer_count,
                            chat_phase_complete=assistant.attribute_activity_ready or None,
                            intent_type=intent_type_lower,
                            **_assistant_stream_fields(assistant),
                        ))
                        yield sse_event("complete", {"success": True})

                    gen = stream_attribute_activity()
                    for event in async_gen_to_sync(gen, loop):
                        yield event
                    return

                if (
                    assistant.bridge_phase == "none"
                    and not assistant.learning_anchor_active
                    and assistant.anchor_object_name
                    and not assistant.anchor_confirmation_needed
                ):
                    from stream.db_loader import load_engagement_dimensions, load_physical_dimensions

                    anchor_name = assistant.anchor_object_name
                    activation_physical_dimensions = load_physical_dimensions(anchor_name, assistant.age or 6)
                    activation_engagement_dimensions = load_engagement_dimensions(anchor_name, assistant.age or 6)
                    if not classify_activation_reopen_signal(
                        child_answer=child_input,
                        anchor_object_name=anchor_name,
                        physical_dimensions=activation_physical_dimensions,
                        engagement_dimensions=activation_engagement_dimensions,
                    ):
                        activation_physical_dimensions = None
                    else:
                        activation_grounding_context = build_bridge_activation_grounding_context(
                            object_name=anchor_name,
                            physical_dimensions=activation_physical_dimensions,
                            engagement_dimensions=activation_engagement_dimensions,
                        )
                        assistant.begin_bridge_activation(
                            anchor_name=anchor_name,
                            physical_dimensions=activation_physical_dimensions,
                            engagement_dimensions=activation_engagement_dimensions,
                            grounding_context=activation_grounding_context,
                        )
                        assistant.anchor_status = "anchored_high"
                        activation_before_state = _activation_transition_before_state(assistant)

                    async def stream_reopened_bridge_activation():
                        messages = prepare_messages_for_streaming(
                            assistant.conversation_history.copy(),
                            age_prompt,
                        )
                        generator = generate_bridge_activation_response_stream(
                            messages=messages,
                            child_answer=child_input,
                            surface_object_name=assistant.surface_object_name or assistant.object_name,
                            anchor_object_name=anchor_name,
                            age=assistant.age or 6,
                            age_prompt=age_prompt,
                            bridge_context="",
                            activation_grounding_context=activation_grounding_context,
                            config=assistant.config,
                            client=assistant.client,
                        )

                        sequence_number = 0
                        full_response = ""
                        async for text_chunk, _token_usage, full_so_far in generator:
                            full_response = full_so_far
                            if not text_chunk:
                                continue
                            sequence_number += 1
                            yield sse_event("chunk", StreamChunk(
                                response=text_chunk,
                                session_finished=False,
                                duration=0.0,
                                token_usage=None,
                                finish=False,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type="bridge_activation",
                                correct_answer_count=assistant.correct_answer_count,
                                activation_child_reply_type="counted_continue",
                                counted_turn=True,
                                counted_turn_reason="activation_continuation",
                                **_assistant_stream_fields(assistant),
                            ))

                        final_question = extract_final_question(full_response)
                        kb_result = await validate_bridge_activation_kb_question(
                            assistant=assistant,
                            final_question=final_question,
                            anchor_object_name=anchor_name,
                            physical_dimensions=assistant.activation_physical_dimensions,
                            engagement_dimensions=assistant.activation_engagement_dimensions,
                        )
                        assistant.activation_last_question = final_question
                        assistant.activation_last_question_kb_backed = bool(kb_result.get("kb_backed_question"))
                        assistant.activation_last_question_handoff_ready = bool(kb_result.get("handoff_ready_question"))
                        assistant.activation_last_question_kb_item = kb_result.get("kb_item")
                        assistant.activation_handoff_ready = assistant.activation_last_question_handoff_ready
                        assistant.activation_last_question_validation_source = kb_result.get("source")
                        assistant.activation_last_question_validation_confidence = kb_result.get("confidence")
                        assistant.activation_last_question_validation_reason = kb_result.get("reason")
                        assistant.activation_last_question_continuity_anchor = build_activation_continuity_anchor(
                            kb_result.get("kb_item")
                        )
                        activation_child_reply_type = "counted_continue"
                        counted_turn = True
                        counted_turn_reason = "activation_continuation"
                        activation_transition = _build_activation_transition_payload(
                            assistant=assistant,
                            before_state=activation_before_state,
                            kb_result=kb_result,
                            final_question=final_question,
                            answer_result=None,
                            handoff_check_attempted=False,
                            handoff_result="stayed_in_activation",
                            handoff_block_reason=None,
                            activation_child_reply_type="counted_continue",
                            counted_turn=True,
                            counted_turn_reason="activation_continuation",
                            continuity=_activation_continuity_state(
                                before_anchor=activation_before_state.get("activation_last_question_continuity_anchor_before"),
                                after_anchor=build_activation_continuity_anchor(kb_result.get("kb_item")),
                                handoff_result="stayed_in_activation",
                            ),
                        )

                        sequence_number += 1
                        assistant.conversation_history.append({"role": "user", "content": child_input})
                        assistant.conversation_history.append({
                            "role": "assistant",
                            "content": full_response,
                            "mode": "chat",
                            "response_type": "bridge_activation",
                        })
                        yield sse_event("chunk", StreamChunk(
                            response=full_response,
                            session_finished=False,
                            duration=0.0,
                            token_usage=None,
                            finish=True,
                            sequence_number=sequence_number,
                            timestamp=time.time(),
                            session_id=session_id,
                            request_id=request_id,
                            response_type="bridge_activation",
                            correct_answer_count=assistant.correct_answer_count,
                            bridge_debug=build_bridge_debug(
                                surface_object_name=assistant.surface_object_name or assistant.object_name,
                                anchor_object_name=anchor_name,
                                anchor_status=assistant.anchor_status,
                                anchor_relation=assistant.anchor_relation,
                                anchor_confidence_band=assistant.anchor_confidence_band,
                                intro_mode="anchor_bridge",
                                learning_anchor_active_before=False,
                                learning_anchor_active_after=False,
                                bridge_attempt_count_before=assistant.bridge_attempt_count,
                                bridge_attempt_count_after=assistant.bridge_attempt_count,
                                decision="bridge_activation",
                                decision_reason="activation_continue",
                                response_type="bridge_activation",
                                kb_mode="activation_latent_kb",
                                activation_grounding_mode="full_chat_kb",
                                activation_grounding_summary=_activation_grounding_summary(
                                    "full_chat_kb",
                                    assistant.activation_grounding_context,
                                ),
                                bridge_phase_before=BRIDGE_PHASE_ACTIVATION,
                                bridge_phase_after=BRIDGE_PHASE_ACTIVATION,
                                activation_turn_count_before=assistant.activation_turn_count,
                                activation_turn_count_after=assistant.activation_turn_count,
                                activation_handoff_ready_after=assistant.activation_handoff_ready,
                                activation_last_question=assistant.activation_last_question,
                                activation_last_question_kb_item=assistant.activation_last_question_kb_item,
                                activation_transition=activation_transition,
                                response_text=full_response,
                            ),
                            activation_child_reply_type=activation_child_reply_type,
                            counted_turn=counted_turn,
                            counted_turn_reason=counted_turn_reason,
                            **_assistant_stream_fields(assistant),
                        ))
                        yield sse_event("complete", {"success": True})

                    if activation_physical_dimensions is not None:
                        gen = stream_reopened_bridge_activation()
                        for event in async_gen_to_sync(gen, loop):
                            yield event
                        return

                if assistant.bridge_phase == BRIDGE_PHASE_ACTIVATION:
                    activation_before_state = _activation_transition_before_state(assistant)
                    answer_result = None
                    handoff_check_attempted = False
                    handoff_result = "stayed_in_activation"
                    handoff_block_reason = "previous_question_not_handoff_ready"
                    activation_child_reply_type = None
                    counted_turn = None
                    counted_turn_reason = None

                    if assistant.activation_handoff_ready:
                        if not assistant.activation_last_question:
                            handoff_block_reason = "missing_previous_question"
                            assistant.activation_handoff_ready = False
                        else:
                            handoff_check_attempted = True
                            answer_result = asyncio.run_coroutine_threadsafe(
                                validate_bridge_activation_answer(
                                    assistant=assistant,
                                    child_answer=child_input,
                                    previous_question=assistant.activation_last_question,
                                    anchor_object_name=assistant.activation_anchor_object_name or assistant.anchor_object_name or "",
                                    physical_dimensions=assistant.activation_physical_dimensions,
                                    engagement_dimensions=assistant.activation_engagement_dimensions,
                                ),
                                loop,
                            ).result()
                            answered_previous_question = answer_result.get(
                                "answered_previous_question",
                                answer_result.get("answered_previous_kb_question"),
                            )
                            if answered_previous_question:
                                handoff_result = "committed_to_anchor_general"
                                handoff_block_reason = None
                                activation_transition = _build_activation_transition_payload(
                                    assistant=assistant,
                                    before_state=activation_before_state,
                                    kb_result={
                                        "source": assistant.activation_last_question_validation_source,
                                        "confidence": assistant.activation_last_question_validation_confidence,
                                        "reason": assistant.activation_last_question_validation_reason,
                                        "kb_backed_question": assistant.activation_last_question_kb_backed,
                                        "handoff_ready_question": assistant.activation_last_question_handoff_ready,
                                        "kb_item": assistant.activation_last_question_kb_item,
                                    },
                                    final_question=assistant.activation_last_question,
                                    answer_result=answer_result,
                                    handoff_check_attempted=True,
                                    handoff_result=handoff_result,
                                    handoff_block_reason=handoff_block_reason,
                                    activation_child_reply_type="handoff_answer",
                                    counted_turn=False,
                                    counted_turn_reason="handoff_committed",
                                    continuity=_activation_continuity_state(
                                        before_anchor=activation_before_state.get("activation_last_question_continuity_anchor_before"),
                                        after_anchor=assistant.activation_last_question_continuity_anchor,
                                        handoff_result=handoff_result,
                                    ),
                                )
                                turn_bridge_debug = build_bridge_debug(
                                    surface_object_name=assistant.surface_object_name or assistant.object_name,
                                    anchor_object_name=assistant.activation_anchor_object_name or assistant.anchor_object_name,
                                    anchor_status=assistant.anchor_status,
                                    anchor_relation=assistant.anchor_relation,
                                    anchor_confidence_band=assistant.anchor_confidence_band,
                                    intro_mode="anchor_bridge",
                                    learning_anchor_active_before=False,
                                    learning_anchor_active_after=False,
                                    bridge_attempt_count_before=assistant.bridge_attempt_count,
                                    bridge_attempt_count_after=assistant.bridge_attempt_count,
                                    decision="bridge_activation",
                                    decision_reason="activation_handoff_committed",
                                    response_type="correct_answer",
                                    kb_mode="activation_latent_kb",
                                    activation_grounding_mode="full_chat_kb",
                                    activation_grounding_summary=_activation_grounding_summary(
                                        "full_chat_kb",
                                        assistant.activation_grounding_context,
                                    ),
                                    bridge_phase_before=BRIDGE_PHASE_ACTIVATION,
                                    bridge_phase_after=BRIDGE_PHASE_ANCHOR_GENERAL,
                                    activation_turn_count_before=assistant.activation_turn_count,
                                    activation_turn_count_after=assistant.activation_turn_count,
                                    activation_handoff_ready_after=False,
                                    activation_last_question=assistant.activation_last_question,
                                    activation_last_question_kb_item=assistant.activation_last_question_kb_item,
                                    activation_transition=activation_transition,
                                )
                                assistant.set_last_bridge_debug(turn_bridge_debug)
                                activation_child_reply_type = "handoff_answer"
                                counted_turn = False
                                counted_turn_reason = "handoff_committed"
                                assistant.commit_bridge_activation()
                                turn_bridge_debug = _normalize_post_handoff_bridge_debug(turn_bridge_debug)
                            else:
                                handoff_block_reason = "child_did_not_answer_previous_question"
                                assistant.activation_handoff_ready = False

                    if assistant.bridge_phase == BRIDGE_PHASE_ACTIVATION:
                        if assistant.activation_turn_count >= MAX_BRIDGE_ACTIVATION_TURNS:
                            activation_transition = _build_activation_transition_payload(
                                assistant=assistant,
                                before_state=activation_before_state,
                                kb_result={
                                    "source": assistant.activation_last_question_validation_source,
                                    "confidence": assistant.activation_last_question_validation_confidence,
                                    "reason": assistant.activation_last_question_validation_reason,
                                    "kb_backed_question": assistant.activation_last_question_kb_backed,
                                    "handoff_ready_question": assistant.activation_last_question_handoff_ready,
                                    "kb_item": assistant.activation_last_question_kb_item,
                                },
                                final_question=assistant.activation_last_question,
                                answer_result=answer_result,
                                handoff_check_attempted=handoff_check_attempted,
                                handoff_result="timeout_fallback",
                                handoff_block_reason="timeout",
                                activation_child_reply_type="timeout",
                                counted_turn=False,
                                counted_turn_reason="activation_timeout",
                                continuity=_activation_continuity_state(
                                    before_anchor=activation_before_state.get("activation_last_question_continuity_anchor_before"),
                                    after_anchor=activation_before_state.get("activation_last_question_continuity_anchor_before"),
                                    handoff_result="timeout_fallback",
                                ),
                            )
                            previous_object = assistant.surface_object_name or assistant.object_name
                            previous_question = assistant.activation_last_question
                            previous_question_kb_item = assistant.activation_last_question_kb_item
                            assistant.clear_bridge_activation()
                            assistant.anchor_status = "unresolved"
                            unresolved_debug = build_bridge_debug(
                                surface_object_name=previous_object,
                                anchor_object_name=assistant.anchor_object_name,
                                anchor_status=assistant.anchor_status,
                                anchor_relation=assistant.anchor_relation,
                                anchor_confidence_band=assistant.anchor_confidence_band,
                                intro_mode="anchor_bridge",
                                learning_anchor_active_before=False,
                                learning_anchor_active_after=False,
                                bridge_attempt_count_before=assistant.bridge_attempt_count,
                                bridge_attempt_count_after=assistant.bridge_attempt_count,
                                decision="unresolved_fallback",
                                decision_reason="activation retry budget exhausted",
                                response_type="unresolved_fallback",
                                bridge_followed=False,
                                bridge_follow_reason=None,
                                pre_anchor_handler_entered=True,
                                kb_mode="surface_only",
                                activation_transition=activation_transition,
                                activation_handoff_ready_after=False,
                                activation_last_question=previous_question,
                                activation_last_question_kb_item=previous_question_kb_item,
                            )
                            assistant.set_last_bridge_debug(unresolved_debug)
                            turn_bridge_debug = unresolved_debug
                            turn_bridge_traces = []
                            activation_child_reply_type = "timeout"
                            counted_turn = False
                            counted_turn_reason = "activation_timeout"
                        else:
                            counted_turn = not _is_activation_free_support(child_input)
                            if counted_turn:
                                assistant.activation_turn_count += 1
                                activation_child_reply_type = "counted_continue"
                                counted_turn_reason = "activation_continuation"
                            else:
                                activation_child_reply_type = "free_support"
                                counted_turn_reason = "free_support_exempt"

                            previous_object = assistant.surface_object_name or assistant.object_name
                            interim_bridge_debug = build_bridge_debug(
                                surface_object_name=previous_object,
                                anchor_object_name=assistant.activation_anchor_object_name or assistant.anchor_object_name,
                                anchor_status=assistant.anchor_status,
                                anchor_relation=assistant.anchor_relation,
                                anchor_confidence_band=assistant.anchor_confidence_band,
                                intro_mode="anchor_bridge",
                                learning_anchor_active_before=False,
                                learning_anchor_active_after=False,
                                bridge_attempt_count_before=assistant.bridge_attempt_count,
                                bridge_attempt_count_after=assistant.bridge_attempt_count,
                                decision="bridge_activation",
                                decision_reason="activation_continue",
                                response_type="bridge_activation",
                                kb_mode="activation_latent_kb",
                                activation_grounding_mode="full_chat_kb",
                                activation_grounding_summary=_activation_grounding_summary(
                                    "full_chat_kb",
                                    assistant.activation_grounding_context,
                                ),
                                bridge_phase_before=BRIDGE_PHASE_ACTIVATION,
                                bridge_phase_after=BRIDGE_PHASE_ACTIVATION,
                                activation_turn_count_before=assistant.activation_turn_count,
                                activation_turn_count_after=assistant.activation_turn_count,
                            )

                            async def stream_bridge_activation_continuation():
                                messages = prepare_messages_for_streaming(
                                    assistant.conversation_history.copy(),
                                    age_prompt,
                                )
                                generator = generate_bridge_activation_response_stream(
                                    messages=messages,
                                    child_answer=child_input,
                                    surface_object_name=previous_object,
                                    anchor_object_name=assistant.activation_anchor_object_name or assistant.anchor_object_name or "",
                                    age=assistant.age or 6,
                                    age_prompt=age_prompt,
                                    bridge_context="",
                                    activation_grounding_context=assistant.activation_grounding_context,
                                    config=assistant.config,
                                    client=assistant.client,
                                )

                                sequence_number = 0
                                full_response = ""
                                async for text_chunk, _token_usage, full_so_far in generator:
                                    full_response = full_so_far
                                    if not text_chunk:
                                        continue
                                    sequence_number += 1
                                    yield sse_event("chunk", StreamChunk(
                                        response=text_chunk,
                                        session_finished=False,
                                        duration=0.0,
                                        token_usage=None,
                                        finish=False,
                                        sequence_number=sequence_number,
                                        timestamp=time.time(),
                                        session_id=session_id,
                                        request_id=request_id,
                                        response_type="bridge_activation",
                                        correct_answer_count=assistant.correct_answer_count,
                                        bridge_debug=interim_bridge_debug,
                                        **_assistant_stream_fields(assistant),
                                    ))

                                final_question = extract_final_question(full_response)
                                kb_result = await validate_bridge_activation_kb_question(
                                    assistant=assistant,
                                    final_question=final_question,
                                    anchor_object_name=assistant.activation_anchor_object_name or assistant.anchor_object_name or "",
                                    physical_dimensions=assistant.activation_physical_dimensions,
                                    engagement_dimensions=assistant.activation_engagement_dimensions,
                                )
                                assistant.activation_last_question = final_question
                                assistant.activation_last_question_kb_backed = bool(kb_result.get("kb_backed_question"))
                                assistant.activation_last_question_handoff_ready = bool(kb_result.get("handoff_ready_question"))
                                assistant.activation_last_question_kb_item = kb_result.get("kb_item")
                                assistant.activation_handoff_ready = assistant.activation_last_question_handoff_ready
                                assistant.activation_last_question_validation_source = kb_result.get("source")
                                assistant.activation_last_question_validation_confidence = kb_result.get("confidence")
                                assistant.activation_last_question_validation_reason = kb_result.get("reason")
                                assistant.activation_last_question_continuity_anchor = build_activation_continuity_anchor(
                                    kb_result.get("kb_item")
                                )

                                activation_continuity = _activation_continuity_state(
                                    before_anchor=activation_before_state.get("activation_last_question_continuity_anchor_before"),
                                    after_anchor=assistant.activation_last_question_continuity_anchor,
                                    handoff_result="stayed_in_activation",
                                )
                                activation_child_reply_type = (
                                    "free_support"
                                    if not counted_turn
                                    else (
                                        "recoverable_drift"
                                        if activation_continuity.get("continuity_break_reason") == "local_focus_changed"
                                        else "counted_continue"
                                    )
                                )
                                activation_transition = _build_activation_transition_payload(
                                    assistant=assistant,
                                    before_state=activation_before_state,
                                    kb_result=kb_result,
                                    final_question=final_question,
                                    answer_result=answer_result,
                                    handoff_check_attempted=handoff_check_attempted,
                                    handoff_result="stayed_in_activation",
                                    handoff_block_reason=handoff_block_reason,
                                    activation_child_reply_type=activation_child_reply_type,
                                    counted_turn=counted_turn,
                                    counted_turn_reason="free_support_exempt" if not counted_turn else "activation_continuation",
                                    continuity=activation_continuity,
                                )

                                final_bridge_debug = build_bridge_debug(
                                    surface_object_name=previous_object,
                                    anchor_object_name=assistant.activation_anchor_object_name or assistant.anchor_object_name,
                                    anchor_status=assistant.anchor_status,
                                    anchor_relation=assistant.anchor_relation,
                                    anchor_confidence_band=assistant.anchor_confidence_band,
                                    intro_mode="anchor_bridge",
                                    learning_anchor_active_before=False,
                                    learning_anchor_active_after=False,
                                    bridge_attempt_count_before=assistant.bridge_attempt_count,
                                    bridge_attempt_count_after=assistant.bridge_attempt_count,
                                    decision="bridge_activation",
                                    decision_reason="activation_continue",
                                    response_type="bridge_activation",
                                    kb_mode="activation_latent_kb",
                                    activation_grounding_mode="full_chat_kb",
                                    activation_grounding_summary=_activation_grounding_summary(
                                        "full_chat_kb",
                                        assistant.activation_grounding_context,
                                    ),
                                    bridge_phase_before=BRIDGE_PHASE_ACTIVATION,
                                    bridge_phase_after=BRIDGE_PHASE_ACTIVATION,
                                    activation_turn_count_before=assistant.activation_turn_count,
                                    activation_turn_count_after=assistant.activation_turn_count,
                                    activation_handoff_ready_after=assistant.activation_handoff_ready,
                                    activation_last_question=assistant.activation_last_question,
                                    activation_last_question_kb_item=assistant.activation_last_question_kb_item,
                                    activation_transition=activation_transition,
                                    response_text=full_response,
                                )
                                assistant.set_last_bridge_debug(final_bridge_debug)
                                sequence_number += 1
                                assistant.conversation_history.append({"role": "user", "content": child_input})
                                assistant.conversation_history.append({
                                    "role": "assistant",
                                    "content": full_response,
                                    "mode": "chat",
                                    "response_type": "bridge_activation",
                                    "bridge_debug": final_bridge_debug,
                                })
                                yield sse_event("chunk", StreamChunk(
                                    response=full_response,
                                    session_finished=False,
                                    duration=0.0,
                                    token_usage=None,
                                    finish=True,
                                    sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="bridge_activation",
                                    correct_answer_count=assistant.correct_answer_count,
                                    bridge_debug=final_bridge_debug,
                                    activation_child_reply_type=activation_child_reply_type,
                                    counted_turn=counted_turn,
                                    counted_turn_reason=counted_turn_reason,
                                    **_assistant_stream_fields(assistant),
                                ))
                                yield sse_event("complete", {"success": True})

                            gen = stream_bridge_activation_continuation()
                            for event in async_gen_to_sync(gen, loop):
                                yield event
                            return

                if (
                    assistant.bridge_phase == BRIDGE_PHASE_PRE_ANCHOR
                    and assistant.anchor_object_name
                ):
                    pre_anchor_state_before = {
                        "anchor_status": assistant.anchor_status,
                        "learning_anchor_active": assistant.learning_anchor_active,
                        "bridge_attempt_count": assistant.bridge_attempt_count,
                        "pre_anchor_support_count": assistant.pre_anchor_support_count,
                        "surface_object_name": assistant.surface_object_name or assistant.object_name,
                        "anchor_object_name": assistant.anchor_object_name,
                    }
                    previous_bridge_question = _latest_bridge_question(assistant.conversation_history)
                    pre_anchor_decision = asyncio.run_coroutine_threadsafe(
                        classify_pre_anchor_reply(
                            assistant=assistant,
                            child_answer=child_input,
                            surface_object_name=assistant.surface_object_name or assistant.object_name,
                            anchor_object_name=assistant.anchor_object_name,
                            relation=assistant.anchor_relation,
                            bridge_profile=assistant.bridge_profile,
                            previous_bridge_question=previous_bridge_question,
                            semantic_reply_classifier=classify_bridge_follow,
                        ),
                        loop,
                    ).result()
                    bridge_follow = {
                        "bridge_followed": pre_anchor_decision.bridge_followed,
                        "reason": pre_anchor_decision.bridge_follow_reason or pre_anchor_decision.reason,
                    }
                    gate_trace = build_bridge_trace_entry(
                        node="driver:pre_anchor_gate",
                        state_before=pre_anchor_state_before,
                        changes={"entered": True},
                        time_ms=0.0,
                    )
                    follow_trace = build_bridge_trace_entry(
                        node="validator:bridge_follow",
                        state_before={
                            "child_input": child_input,
                            "previous_bridge_question": previous_bridge_question,
                        },
                        changes={
                            "bridge_followed": bridge_follow.get("bridge_followed"),
                            "reason": bridge_follow.get("reason"),
                            "reply_type": pre_anchor_decision.reply_type,
                            "support_action": pre_anchor_decision.support_action,
                        },
                        time_ms=0.0,
                    )

                    should_soft_activate = (
                        pre_anchor_decision.reply_type == "anchor_related_but_off_lane"
                        and assistant.pre_anchor_support_count + 1 >= MAX_PRE_ANCHOR_SUPPORT_TURNS
                    )

                    if bridge_follow.get("bridge_followed") or should_soft_activate:
                        activation_before_state = _activation_transition_before_state(assistant)
                        previous_object = assistant.surface_object_name or assistant.object_name
                        activation_reason = (
                            "soft activation after anchor-related support"
                            if should_soft_activate
                            else "child followed bridge"
                        )
                        bridge_context = build_bridge_context(
                            assistant.bridge_profile,
                            max(assistant.bridge_attempt_count, 1),
                        )
                        from stream.db_loader import load_engagement_dimensions, load_physical_dimensions

                        anchor_name = assistant.anchor_object_name
                        activation_physical_dimensions = load_physical_dimensions(anchor_name, assistant.age or 6)
                        activation_engagement_dimensions = load_engagement_dimensions(anchor_name, assistant.age or 6)
                        activation_grounding_context = build_bridge_activation_grounding_context(
                            object_name=anchor_name,
                            physical_dimensions=activation_physical_dimensions,
                            engagement_dimensions=activation_engagement_dimensions,
                        )
                        assistant.begin_bridge_activation(
                            anchor_name=anchor_name,
                            physical_dimensions=activation_physical_dimensions,
                            engagement_dimensions=activation_engagement_dimensions,
                            grounding_context=activation_grounding_context,
                        )
                        counted_turn = not _is_activation_free_support(child_input)
                        interim_bridge_debug = build_bridge_debug(
                            surface_object_name=previous_object,
                            anchor_object_name=anchor_name,
                            anchor_status=assistant.anchor_status,
                            anchor_relation=assistant.anchor_relation,
                            anchor_confidence_band=assistant.anchor_confidence_band,
                            bridge_profile=assistant.bridge_profile,
                            intro_mode="anchor_bridge",
                            learning_anchor_active_before=False,
                            learning_anchor_active_after=False,
                            bridge_attempt_count_before=pre_anchor_state_before["bridge_attempt_count"],
                            bridge_attempt_count_after=assistant.bridge_attempt_count,
                            decision="bridge_activation",
                            decision_reason=activation_reason,
                            response_type="bridge_activation",
                            bridge_followed=True,
                            bridge_follow_reason=bridge_follow.get("reason"),
                            pre_anchor_handler_entered=True,
                            kb_mode="activation_latent_kb",
                            bridge_context_summary=_bridge_context_summary(bridge_context),
                            activation_grounding_mode="full_chat_kb",
                            activation_grounding_summary=_activation_grounding_summary(
                                "full_chat_kb",
                                activation_grounding_context,
                            ),
                            bridge_phase_before=BRIDGE_PHASE_PRE_ANCHOR,
                            bridge_phase_after=BRIDGE_PHASE_ACTIVATION,
                            activation_turn_count_before=0,
                            activation_turn_count_after=0,
                            pre_anchor_reply_type=pre_anchor_decision.reply_type,
                            support_action=pre_anchor_decision.support_action,
                            pre_anchor_support_count_before=pre_anchor_state_before["pre_anchor_support_count"],
                            pre_anchor_support_count_after=assistant.pre_anchor_support_count,
                        )
                        decision_trace = build_bridge_trace_entry(
                            node="driver:bridge_decision",
                            state_before=pre_anchor_state_before,
                            changes={"decision": "bridge_activation"},
                            time_ms=0.0,
                        )
                        bridge_traces = [gate_trace, follow_trace, decision_trace]

                        async def stream_bridge_activation():
                            messages = prepare_messages_for_streaming(
                                assistant.conversation_history.copy(),
                                age_prompt,
                            )
                            generator = generate_bridge_activation_response_stream(
                                messages=messages,
                                child_answer=child_input,
                                surface_object_name=previous_object,
                                anchor_object_name=anchor_name,
                                age=assistant.age or 6,
                                age_prompt=age_prompt,
                                bridge_context="",
                                activation_grounding_context=activation_grounding_context,
                                config=assistant.config,
                                client=assistant.client,
                            )

                            sequence_number = 0
                            full_response = ""
                            final_bridge_debug = interim_bridge_debug
                            async for text_chunk, _token_usage, full_so_far in generator:
                                full_response = full_so_far
                                if not text_chunk:
                                    continue
                                sequence_number += 1
                                yield sse_event("chunk", StreamChunk(
                                    response=text_chunk,
                                    session_finished=False,
                                    duration=0.0,
                                    token_usage=None,
                                    finish=False,
                                    sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="bridge_activation",
                                    correct_answer_count=assistant.correct_answer_count,
                                    bridge_debug=interim_bridge_debug,
                                    nodes_executed=bridge_traces,
                                    **_assistant_stream_fields(assistant),
                                ))

                            final_question = extract_final_question(full_response)
                            kb_result = await validate_bridge_activation_kb_question(
                                assistant=assistant,
                                final_question=final_question,
                                anchor_object_name=anchor_name,
                                physical_dimensions=assistant.activation_physical_dimensions,
                                engagement_dimensions=assistant.activation_engagement_dimensions,
                            )
                            assistant.activation_last_question = final_question
                            assistant.activation_last_question_kb_backed = bool(kb_result.get("kb_backed_question"))
                            assistant.activation_last_question_handoff_ready = bool(kb_result.get("handoff_ready_question"))
                            assistant.activation_last_question_kb_item = kb_result.get("kb_item")
                            assistant.activation_handoff_ready = assistant.activation_last_question_handoff_ready
                            assistant.activation_last_question_validation_source = kb_result.get("source")
                            assistant.activation_last_question_validation_confidence = kb_result.get("confidence")
                            assistant.activation_last_question_validation_reason = kb_result.get("reason")
                            assistant.activation_last_question_continuity_anchor = build_activation_continuity_anchor(
                                kb_result.get("kb_item")
                            )
                            activation_continuity = _activation_continuity_state(
                                before_anchor=activation_before_state.get("activation_last_question_continuity_anchor_before"),
                                after_anchor=assistant.activation_last_question_continuity_anchor,
                                handoff_result="stayed_in_activation",
                            )
                            activation_child_reply_type = (
                                "free_support"
                                if not counted_turn
                                else (
                                    "recoverable_drift"
                                    if activation_continuity.get("continuity_break_reason") == "local_focus_changed"
                                    else "counted_continue"
                                )
                            )
                            activation_transition = _build_activation_transition_payload(
                                assistant=assistant,
                                before_state=activation_before_state,
                                kb_result=kb_result,
                                final_question=final_question,
                                answer_result=None,
                                handoff_check_attempted=False,
                                handoff_result="stayed_in_activation",
                                handoff_block_reason=None,
                                activation_child_reply_type=activation_child_reply_type,
                                counted_turn=counted_turn,
                                counted_turn_reason="free_support_exempt" if not counted_turn else "activation_continuation",
                                continuity=activation_continuity,
                            )

                            final_bridge_debug = build_bridge_debug(
                                surface_object_name=previous_object,
                                anchor_object_name=anchor_name,
                                anchor_status=assistant.anchor_status,
                                anchor_relation=assistant.anchor_relation,
                                anchor_confidence_band=assistant.anchor_confidence_band,
                                bridge_profile=assistant.bridge_profile,
                                intro_mode="anchor_bridge",
                                learning_anchor_active_before=False,
                                learning_anchor_active_after=False,
                                bridge_attempt_count_before=pre_anchor_state_before["bridge_attempt_count"],
                                bridge_attempt_count_after=assistant.bridge_attempt_count,
                                decision="bridge_activation",
                                decision_reason=activation_reason,
                                response_type="bridge_activation",
                                bridge_followed=True,
                                bridge_follow_reason=bridge_follow.get("reason"),
                                pre_anchor_handler_entered=True,
                                kb_mode="activation_latent_kb",
                                bridge_context_summary=_bridge_context_summary(bridge_context),
                                activation_grounding_mode="full_chat_kb",
                                activation_grounding_summary=_activation_grounding_summary(
                                    "full_chat_kb",
                                    activation_grounding_context,
                                ),
                                bridge_phase_before=BRIDGE_PHASE_PRE_ANCHOR,
                                bridge_phase_after=BRIDGE_PHASE_ACTIVATION,
                                activation_turn_count_before=0,
                                activation_turn_count_after=0,
                                activation_handoff_ready_after=assistant.activation_handoff_ready,
                                activation_last_question=assistant.activation_last_question,
                                activation_last_question_kb_item=assistant.activation_last_question_kb_item,
                                activation_transition=activation_transition,
                                response_text=full_response,
                                pre_anchor_reply_type=pre_anchor_decision.reply_type,
                                support_action=pre_anchor_decision.support_action,
                                pre_anchor_support_count_before=pre_anchor_state_before["pre_anchor_support_count"],
                                pre_anchor_support_count_after=assistant.pre_anchor_support_count,
                            )
                            assistant.set_last_bridge_debug(final_bridge_debug)
                            logger.info(
                                f"[BRIDGE] {format_bridge_log_line(session_id=session_id, request_id=request_id, bridge_debug=final_bridge_debug)}"
                            )
                            sequence_number += 1
                            assistant.conversation_history.append({"role": "user", "content": child_input})
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": full_response,
                                "mode": "chat",
                                "response_type": "bridge_activation",
                                "bridge_debug": final_bridge_debug,
                                "nodes_executed": bridge_traces,
                            })
                            yield sse_event("chunk", StreamChunk(
                                response=full_response,
                                session_finished=False,
                                duration=0.0,
                                token_usage=None,
                                finish=True,
                                sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="bridge_activation",
                                    correct_answer_count=assistant.correct_answer_count,
                                    bridge_debug=final_bridge_debug,
                                    activation_child_reply_type=activation_child_reply_type,
                                    counted_turn=counted_turn,
                                    counted_turn_reason="free_support_exempt" if not counted_turn else "activation_continuation",
                                    nodes_executed=bridge_traces,
                                    **_assistant_stream_fields(assistant),
                                ))
                            yield sse_event("complete", {"success": True})

                        gen = stream_bridge_activation()
                        for event in async_gen_to_sync(gen, loop):
                            yield event
                        print(f"[INFO] Session {session_id[:8]}... bridge followed -> activation")
                        return

                    if (
                        pre_anchor_decision.reply_type in {
                            "clarification_request",
                            "idk_or_stuck",
                            "anchor_related_but_off_lane",
                        }
                        and assistant.pre_anchor_support_count < MAX_PRE_ANCHOR_SUPPORT_TURNS
                    ):
                        support_before = assistant.pre_anchor_support_count
                        assistant.pre_anchor_support_count += 1
                        bridge_context = build_bridge_context(
                            assistant.bridge_profile,
                            max(assistant.bridge_attempt_count, 1),
                        )
                        bridge_debug = build_bridge_debug(
                            surface_object_name=assistant.surface_object_name or assistant.object_name,
                            anchor_object_name=assistant.anchor_object_name,
                            anchor_status=assistant.anchor_status,
                            anchor_relation=assistant.anchor_relation,
                            anchor_confidence_band=assistant.anchor_confidence_band,
                            bridge_profile=assistant.bridge_profile,
                            intro_mode="anchor_bridge",
                            learning_anchor_active_before=False,
                            learning_anchor_active_after=False,
                            bridge_attempt_count_before=pre_anchor_state_before["bridge_attempt_count"],
                            bridge_attempt_count_after=assistant.bridge_attempt_count,
                            decision="bridge_support",
                            decision_reason=pre_anchor_decision.reason,
                            response_type="bridge_support",
                            bridge_followed=False,
                            bridge_follow_reason=pre_anchor_decision.bridge_follow_reason,
                            pre_anchor_handler_entered=True,
                            kb_mode="bridge_context_only",
                            bridge_context_summary=_bridge_context_summary(bridge_context),
                            pre_anchor_reply_type=pre_anchor_decision.reply_type,
                            support_action=pre_anchor_decision.support_action,
                            pre_anchor_support_count_before=support_before,
                            pre_anchor_support_count_after=assistant.pre_anchor_support_count,
                        )
                        decision_trace = build_bridge_trace_entry(
                            node="driver:bridge_decision",
                            state_before=pre_anchor_state_before,
                            changes={"decision": "bridge_support"},
                            time_ms=0.0,
                        )
                        bridge_traces = [gate_trace, follow_trace, decision_trace]

                        async def stream_bridge_support():
                            messages = prepare_messages_for_streaming(
                                assistant.conversation_history.copy(),
                                age_prompt,
                            )
                            generator = generate_bridge_support_response_stream(
                                messages=messages,
                                child_answer=child_input,
                                surface_object_name=assistant.surface_object_name or assistant.object_name,
                                anchor_object_name=assistant.anchor_object_name,
                                age=assistant.age or 6,
                                age_prompt=age_prompt,
                                bridge_context=bridge_context.prompt_context if bridge_context else "",
                                previous_bridge_question=previous_bridge_question or "",
                                support_action=pre_anchor_decision.support_action or "clarify",
                                config=assistant.config,
                                client=assistant.client,
                            )

                            sequence_number = 0
                            full_response = ""
                            async for text_chunk, _token_usage, full_so_far in generator:
                                full_response = full_so_far
                                if not text_chunk:
                                    continue
                                sequence_number += 1
                                yield sse_event("chunk", StreamChunk(
                                    response=text_chunk,
                                    session_finished=False,
                                    duration=0.0,
                                    token_usage=None,
                                    finish=False,
                                    sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="bridge_support",
                                    correct_answer_count=assistant.correct_answer_count,
                                    bridge_debug=bridge_debug,
                                    nodes_executed=bridge_traces,
                                    **_assistant_stream_fields(assistant),
                                ))

                            sequence_number += 1
                            final_bridge_debug = build_bridge_debug(
                                surface_object_name=assistant.surface_object_name or assistant.object_name,
                                anchor_object_name=assistant.anchor_object_name,
                                anchor_status=assistant.anchor_status,
                                anchor_relation=assistant.anchor_relation,
                                anchor_confidence_band=assistant.anchor_confidence_band,
                                bridge_profile=assistant.bridge_profile,
                                intro_mode="anchor_bridge",
                                learning_anchor_active_before=False,
                                learning_anchor_active_after=False,
                                bridge_attempt_count_before=pre_anchor_state_before["bridge_attempt_count"],
                                bridge_attempt_count_after=assistant.bridge_attempt_count,
                                decision="bridge_support",
                                decision_reason=pre_anchor_decision.reason,
                                response_type="bridge_support",
                                bridge_followed=False,
                                bridge_follow_reason=pre_anchor_decision.bridge_follow_reason,
                                pre_anchor_handler_entered=True,
                                kb_mode="bridge_context_only",
                                bridge_context_summary=_bridge_context_summary(bridge_context),
                                response_text=full_response,
                                pre_anchor_reply_type=pre_anchor_decision.reply_type,
                                support_action=pre_anchor_decision.support_action,
                                pre_anchor_support_count_before=support_before,
                                pre_anchor_support_count_after=assistant.pre_anchor_support_count,
                            )
                            assistant.set_last_bridge_debug(final_bridge_debug)
                            logger.info(
                                f"[BRIDGE] {format_bridge_log_line(session_id=session_id, request_id=request_id, bridge_debug=final_bridge_debug)}"
                            )
                            assistant.conversation_history.append({"role": "user", "content": child_input})
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": full_response,
                                "mode": "chat",
                                "response_type": "bridge_support",
                                "bridge_debug": final_bridge_debug,
                                "nodes_executed": bridge_traces,
                            })
                            yield sse_event("chunk", StreamChunk(
                                response=full_response,
                                session_finished=False,
                                duration=0.0,
                                token_usage=None,
                                finish=True,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type="bridge_support",
                                correct_answer_count=assistant.correct_answer_count,
                                bridge_debug=final_bridge_debug,
                                nodes_executed=bridge_traces,
                                **_assistant_stream_fields(assistant),
                            ))
                            yield sse_event("complete", {"success": True})

                        gen = stream_bridge_support()
                        for event in async_gen_to_sync(gen, loop):
                            yield event
                        print(
                            f"[INFO] Session {session_id[:8]}... bridge support {assistant.pre_anchor_support_count}/{MAX_PRE_ANCHOR_SUPPORT_TURNS}"
                        )
                        return

                    if pre_anchor_decision.consume_bridge_attempt and assistant.bridge_attempt_count < MAX_BRIDGE_ATTEMPTS:
                        attempt_before = assistant.bridge_attempt_count
                        next_attempt = assistant.bridge_attempt_count + 1
                        bridge_context = build_bridge_context(
                            assistant.bridge_profile,
                            next_attempt,
                        )
                        assistant.bridge_attempt_count = next_attempt
                        bridge_debug = build_bridge_debug(
                            surface_object_name=assistant.surface_object_name or assistant.object_name,
                            anchor_object_name=assistant.anchor_object_name,
                            anchor_status=assistant.anchor_status,
                            anchor_relation=assistant.anchor_relation,
                            anchor_confidence_band=assistant.anchor_confidence_band,
                            bridge_profile=assistant.bridge_profile,
                            intro_mode="anchor_bridge",
                            learning_anchor_active_before=False,
                            learning_anchor_active_after=False,
                            bridge_attempt_count_before=attempt_before,
                            bridge_attempt_count_after=assistant.bridge_attempt_count,
                            decision="bridge_retry",
                            decision_reason="child stayed on surface object",
                            response_type="bridge_retry",
                            bridge_followed=False,
                            bridge_follow_reason=bridge_follow.get("reason"),
                            pre_anchor_handler_entered=True,
                            kb_mode="bridge_context_only",
                            bridge_context_summary=_bridge_context_summary(bridge_context),
                            pre_anchor_reply_type=pre_anchor_decision.reply_type,
                            support_action=pre_anchor_decision.support_action,
                            pre_anchor_support_count_before=pre_anchor_state_before["pre_anchor_support_count"],
                            pre_anchor_support_count_after=assistant.pre_anchor_support_count,
                        )
                        assistant.set_last_bridge_debug(bridge_debug)
                        logger.info(
                            f"[BRIDGE] {format_bridge_log_line(session_id=session_id, request_id=request_id, bridge_debug=bridge_debug)}"
                        )
                        decision_trace = build_bridge_trace_entry(
                            node="driver:bridge_decision",
                            state_before=pre_anchor_state_before,
                            changes={"decision": "bridge_retry"},
                            time_ms=0.0,
                        )
                        bridge_traces = [gate_trace, follow_trace, decision_trace]

                        async def stream_bridge_retry():
                            messages = prepare_messages_for_streaming(
                                assistant.conversation_history.copy(),
                                age_prompt,
                            )
                            generator = generate_bridge_retry_response_stream(
                                messages=messages,
                                child_answer=child_input,
                                surface_object_name=assistant.surface_object_name or assistant.object_name,
                                anchor_object_name=assistant.anchor_object_name,
                                age=assistant.age or 6,
                                age_prompt=age_prompt,
                                bridge_context=bridge_context.prompt_context if bridge_context else "",
                                config=assistant.config,
                                client=assistant.client,
                            )

                            sequence_number = 0
                            full_response = ""
                            async for text_chunk, _token_usage, full_so_far in generator:
                                full_response = full_so_far
                                if not text_chunk:
                                    continue
                                sequence_number += 1
                                yield sse_event("chunk", StreamChunk(
                                    response=text_chunk,
                                    session_finished=False,
                                    duration=0.0,
                                    token_usage=None,
                                    finish=False,
                                    sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="bridge_retry",
                                    correct_answer_count=assistant.correct_answer_count,
                                    bridge_debug=bridge_debug,
                                    nodes_executed=bridge_traces,
                                    **_assistant_stream_fields(assistant),
                                ))

                            sequence_number += 1
                            assistant.conversation_history.append({"role": "user", "content": child_input})
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": full_response,
                                "mode": "chat",
                                "response_type": "bridge_retry",
                                "bridge_debug": bridge_debug,
                                "nodes_executed": bridge_traces,
                            })
                            yield sse_event("chunk", StreamChunk(
                                response=full_response,
                                session_finished=False,
                                duration=0.0,
                                token_usage=None,
                                finish=True,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type="bridge_retry",
                                correct_answer_count=assistant.correct_answer_count,
                                bridge_debug=bridge_debug,
                                nodes_executed=bridge_traces,
                                **_assistant_stream_fields(assistant),
                            ))
                            yield sse_event("complete", {"success": True})

                        gen = stream_bridge_retry()
                        for event in async_gen_to_sync(gen, loop):
                            yield event
                        print(
                            f"[INFO] Session {session_id[:8]}... bridge retry {assistant.bridge_attempt_count}/{MAX_BRIDGE_ATTEMPTS}"
                        )
                        return

                    decision_trace = build_bridge_trace_entry(
                        node="driver:bridge_decision",
                        state_before=pre_anchor_state_before,
                        changes={"decision": "unresolved_fallback"},
                        time_ms=0.0,
                    )
                    bridge_traces = [gate_trace, follow_trace, decision_trace]
                    assistant.suppress_anchor(assistant.anchor_object_name)
                    assistant.anchor_status = "unresolved"
                    assistant.learning_anchor_active = False
                    assistant.reset_bridge_state()
                    unresolved_debug = build_bridge_debug(
                        surface_object_name=assistant.surface_object_name or assistant.object_name,
                        anchor_object_name=assistant.anchor_object_name,
                        anchor_status=assistant.anchor_status,
                        anchor_relation=assistant.anchor_relation,
                        anchor_confidence_band=assistant.anchor_confidence_band,
                        intro_mode="anchor_bridge",
                        learning_anchor_active_before=False,
                        learning_anchor_active_after=False,
                        bridge_attempt_count_before=MAX_BRIDGE_ATTEMPTS,
                        bridge_attempt_count_after=0,
                        decision="unresolved_fallback",
                        decision_reason="bridge retry budget exhausted",
                        response_type="unresolved_fallback",
                        bridge_followed=False,
                        bridge_follow_reason=bridge_follow.get("reason"),
                        pre_anchor_handler_entered=True,
                        kb_mode="surface_only",
                        pre_anchor_reply_type=pre_anchor_decision.reply_type,
                        support_action=pre_anchor_decision.support_action,
                        pre_anchor_support_count_before=pre_anchor_state_before["pre_anchor_support_count"],
                        pre_anchor_support_count_after=0,
                    )
                    assistant.set_last_bridge_debug(unresolved_debug)
                    turn_bridge_debug = unresolved_debug
                    turn_bridge_traces = bridge_traces
                    logger.info(
                        f"[BRIDGE] {format_bridge_log_line(session_id=session_id, request_id=request_id, bridge_debug=unresolved_debug)}"
                    )

                if assistant.anchor_confirmation_needed and assistant.anchor_object_name:
                    decision = parse_anchor_confirmation(
                        child_input,
                        assistant.surface_object_name or assistant.object_name,
                        assistant.anchor_object_name,
                    )

                    if decision == "accept":
                        previous_object = assistant.surface_object_name or assistant.object_name
                        assistant.activate_anchor_topic(assistant.anchor_object_name)
                        assistant.anchor_status = "anchored_high"
                        assistant.load_dimension_data(assistant.object_name)
                        assistant.load_object_context_from_yaml(assistant.object_name)

                        async def stream_anchor_switch():
                            messages = prepare_messages_for_streaming(
                                assistant.conversation_history.copy(),
                                age_prompt,
                            )
                            generator = generate_topic_switch_response_stream(
                                messages=messages,
                                previous_object=previous_object,
                                new_object=assistant.object_name,
                                age=assistant.age or 6,
                                config=assistant.config,
                                client=assistant.client,
                            )

                            sequence_number = 0
                            full_response = ""
                            async for text_chunk, _token_usage, full_so_far in generator:
                                full_response = full_so_far
                                if not text_chunk:
                                    continue
                                sequence_number += 1
                                yield sse_event("chunk", StreamChunk(
                                    response=text_chunk,
                                    session_finished=False,
                                    duration=0.0,
                                    token_usage=None,
                                    finish=False,
                                    sequence_number=sequence_number,
                                    timestamp=time.time(),
                                    session_id=session_id,
                                    request_id=request_id,
                                    response_type="topic_switch",
                                    correct_answer_count=assistant.correct_answer_count,
                                    **_assistant_stream_fields(assistant),
                                ))

                            sequence_number += 1
                            assistant.conversation_history.append({"role": "user", "content": child_input})
                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": full_response,
                                "mode": "chat",
                                "response_type": "topic_switch",
                            })
                            yield sse_event("chunk", StreamChunk(
                                response=full_response,
                                session_finished=False,
                                duration=0.0,
                                token_usage=None,
                                finish=True,
                                sequence_number=sequence_number,
                                timestamp=time.time(),
                                session_id=session_id,
                                request_id=request_id,
                                response_type="topic_switch",
                                correct_answer_count=assistant.correct_answer_count,
                                **_assistant_stream_fields(assistant),
                            ))
                            yield sse_event("complete", {"success": True})

                        gen = stream_anchor_switch()
                        for event in async_gen_to_sync(gen, loop):
                            yield event
                        print(f"[INFO] Session {session_id[:8]}... anchor accepted -> {assistant.object_name}")
                        return

                    if decision in {"reject", "unclear"}:
                        assistant.suppress_anchor(assistant.anchor_object_name)
                        assistant.anchor_status = "unresolved"
                        assistant.learning_anchor_active = False
                        assistant.reset_bridge_state()

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
                        "surface_object_name": assistant.surface_object_name,
                        "anchor_object_name": assistant.anchor_object_name,
                        "anchor_status": assistant.anchor_status,
                        "anchor_relation": assistant.anchor_relation,
                        "anchor_confidence_band": assistant.anchor_confidence_band,
                        "anchor_confirmation_needed": assistant.anchor_confirmation_needed,
                        "bridge_profile": assistant.bridge_profile,
                        "learning_anchor_active": assistant.learning_anchor_active,
                        "bridge_phase": assistant.bridge_phase,
                        "bridge_attempt_count": assistant.bridge_attempt_count,
                        "bridge_debug": turn_bridge_debug,
                        "activation_child_reply_type": activation_child_reply_type,
                        "counted_turn": counted_turn,
                        "counted_turn_reason": counted_turn_reason,
                        "resolution_debug": assistant.session_resolution_debug,
                        "correct_answer_count": assistant.correct_answer_count,
                        "intro_mode": None,
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
                        "question_style": None,

                        # Node execution tracing
                        "nodes_executed": turn_bridge_traces,

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
                        chunk = _apply_activation_stream_fields(chunk, initial_state)
                        if chunk.finish:
                            if chunk.bridge_debug:
                                assistant.set_last_bridge_debug(chunk.bridge_debug.model_dump())
                                logger.info(
                                    f"[BRIDGE] {format_bridge_log_line(session_id=session_id, request_id=request_id, bridge_debug=chunk.bridge_debug.model_dump())}"
                                )
                            assistant.conversation_history.append({"role": "user", "content": child_input})

                            assistant.conversation_history.append({
                                "role": "assistant",
                                "content": chunk.response,
                                "nodes_executed": chunk.nodes_executed or [],
                                "mode": "chat",
                                "response_type": chunk.response_type,
                                "bridge_debug": chunk.bridge_debug.model_dump() if chunk.bridge_debug else None,
                                "resolution_debug": chunk.resolution_debug.model_dump() if chunk.resolution_debug else assistant.session_resolution_debug,
                                "classification_status": chunk.classification_status,
                                "classification_failure_reason": chunk.classification_failure_reason,
                                "selected_hook_type": chunk.selected_hook_type,
                                "question_style": chunk.question_style,
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

        resolution = resolve_object_input(
            raw_object_name=new_object,
            age=assistant.age or 6,
            client=assistant.client,
            config=assistant.config,
        )
        assistant.apply_resolution(resolution)
        if assistant.learning_anchor_active:
            assistant.load_dimension_data(assistant.object_name)
        else:
            assistant.physical_dimensions = {}
            assistant.engagement_dimensions = {}

        print(f"[FORCE-SWITCH] User forced switch from {previous_object} to {assistant.object_name}")

        return jsonify({
            "success": True,
            "previous_object": previous_object,
            "new_object": assistant.object_name,
            "message": f"Switched to {assistant.object_name}",
            "learning_anchor_active": assistant.learning_anchor_active,
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
            entry["response_type"] = msg.get("response_type")
            entry["bridge_debug"] = msg.get("bridge_debug")
            entry["attribute_debug"] = msg.get("attribute_debug")
            entry["category_debug"] = msg.get("category_debug")
            entry["resolution_debug"] = msg.get("resolution_debug")
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
                "response_type": transcript[i].get("response_type"),
                "bridge_debug": transcript[i].get("bridge_debug"),
                "attribute_debug": transcript[i].get("attribute_debug"),
                "category_debug": transcript[i].get("category_debug"),
                "resolution_debug": transcript[i].get("resolution_debug"),
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
                "response_type": transcript[i + 1].get("response_type"),
                "bridge_debug": transcript[i + 1].get("bridge_debug"),
                "attribute_debug": transcript[i + 1].get("attribute_debug"),
                "category_debug": transcript[i + 1].get("category_debug"),
                "resolution_debug": transcript[i + 1].get("resolution_debug"),
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
        "session_resolution_debug": assistant.session_resolution_debug,
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
    exchange_critiques = data.get('exchange_critiques') or []
    global_conclusion = data.get('global_conclusion') or ''
    skip_traces = data.get('skip_traces', False)

    if not session_id:
        return jsonify({
            "success": False,
            "error": "Missing session_id"
        }), 400

    has_exchange_critiques = bool(exchange_critiques)
    has_global_conclusion = bool(global_conclusion.strip())

    if not has_exchange_critiques and not has_global_conclusion:
        return jsonify({
            "success": False,
            "error": "Provide at least one exchange critique or a global conclusion"
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
            entry["response_type"] = msg.get("response_type")
            entry["bridge_debug"] = msg.get("bridge_debug")
            entry["attribute_debug"] = msg.get("attribute_debug")
            entry["category_debug"] = msg.get("category_debug")
            entry["resolution_debug"] = msg.get("resolution_debug")
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
                "response_type": transcript[i].get("response_type"),
                "bridge_debug": transcript[i].get("bridge_debug"),
                "attribute_debug": transcript[i].get("attribute_debug"),
                "category_debug": transcript[i].get("category_debug"),
                "resolution_debug": transcript[i].get("resolution_debug"),
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
                "response_type": transcript[i + 1].get("response_type"),
                "bridge_debug": transcript[i + 1].get("bridge_debug"),
                "attribute_debug": transcript[i + 1].get("attribute_debug"),
                "category_debug": transcript[i + 1].get("category_debug"),
                "resolution_debug": transcript[i + 1].get("resolution_debug"),
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
            session_resolution_debug=assistant.session_resolution_debug,
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
                                 introduction=None, introduction_critique=None,
                                 session_resolution_debug=None):
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

    if session_resolution_debug:
        report += "## Anchor Resolution\n\n"
        for label, key in [
            ("Surface Object", "surface_object_name"),
            ("Visible Object", "visible_object_name"),
            ("Anchor Object", "anchor_object_name"),
            ("Anchor Status", "anchor_status"),
            ("Relation", "anchor_relation"),
            ("Confidence", "anchor_confidence_band"),
            ("Learning Active", "learning_anchor_active"),
            ("Decision Source", "decision_source"),
            ("Decision Reason", "decision_reason"),
            ("Raw Payload Kind", "raw_model_payload_kind"),
            ("JSON Recovery Applied", "json_recovery_applied"),
            ("Unresolved Surface-Only Mode", "unresolved_surface_only_mode"),
        ]:
            value = session_resolution_debug.get(key)
            if value is not None:
                report += f"- {label}: `{value}`\n"
        candidates = session_resolution_debug.get("candidate_anchors")
        if candidates is not None:
            report += f"- Candidate Anchors: `{', '.join(candidates) if candidates else 'none'}`\n"
        raw_model_response = session_resolution_debug.get("raw_model_response")
        if raw_model_response:
            raw_excerpt = raw_model_response if len(raw_model_response) <= 200 else raw_model_response[:197] + "..."
            report += f"- Raw Resolver Output: `{raw_excerpt}`\n"
        report += "\n---\n\n"

    diagnostics_entries = {}

    def register_diagnostics(
        exchange_index,
        source_label,
        response_type,
        bridge_debug=None,
        attribute_debug=None,
        category_debug=None,
    ):
        if bridge_debug or attribute_debug or category_debug:
            existing = diagnostics_entries.get(exchange_index, {})
            diagnostics_entries[exchange_index] = {
                "exchange_index": exchange_index,
                "source_label": source_label or existing.get("source_label"),
                "response_type": response_type or existing.get("response_type"),
                "bridge_debug": bridge_debug or existing.get("bridge_debug"),
                "attribute_debug": attribute_debug or existing.get("attribute_debug"),
                "category_debug": category_debug or existing.get("category_debug"),
            }

    register_diagnostics(
        0,
        "introduction",
        introduction.get("response_type") if introduction else None,
        bridge_debug=introduction.get("bridge_debug") if introduction else None,
        attribute_debug=introduction.get("attribute_debug") if introduction else None,
        category_debug=introduction.get("category_debug") if introduction else None,
    )
    for idx, exchange in enumerate(all_exchanges, start=1):
        register_diagnostics(
            idx,
            f"exchange {idx}",
            exchange.get("response_type"),
            bridge_debug=exchange.get("bridge_debug"),
            attribute_debug=exchange.get("attribute_debug"),
            category_debug=exchange.get("category_debug"),
        )

    # Introduction Critique section (if the reviewer critiqued the introduction)
    if introduction and introduction_critique:
        report += "## Introduction — Human Critique\n\n"
        intro_content = introduction.get("content", "")
        report += f"**Introduction:** \"{intro_content}\"\n\n"
        if introduction.get("bridge_debug") or introduction.get("attribute_debug") or introduction.get("category_debug"):
            report += _render_turn_summary(
                introduction.get("bridge_debug"),
                introduction.get("attribute_debug"),
                introduction.get("category_debug"),
                introduction.get("response_type"),
                diagnostics_ref="D0",
            )
        mr_expected = introduction_critique.get("model_response_expected", "").strip()
        mr_problem = introduction_critique.get("model_response_problem", "").strip()
        if mr_expected or mr_problem:
            report += "**Feedback on the introduction:**\n"
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
    child_count = 0
    waiting_for_model = False
    for msg in transcript:
        if msg["role"] == "model":
            mode_label = msg.get("mode", "chat").upper()
            response_type = msg.get("response_type") or "unknown"
            if child_count == 0:
                exchange_index = 0
            elif waiting_for_model:
                exchange_index = child_count
                waiting_for_model = False
            else:
                exchange_index = child_count
            register_diagnostics(
                exchange_index,
                "introduction" if exchange_index == 0 else f"exchange {exchange_index}",
                response_type,
                bridge_debug=msg.get("bridge_debug"),
                attribute_debug=msg.get("attribute_debug"),
                category_debug=msg.get("category_debug"),
            )
            diagnostics = diagnostics_entries.get(exchange_index) or {}
            bridge_debug = msg.get("bridge_debug") or diagnostics.get("bridge_debug")
            attribute_debug = msg.get("attribute_debug") or diagnostics.get("attribute_debug")
            category_debug = msg.get("category_debug") or diagnostics.get("category_debug")
            diagnostics_ref = f"D{exchange_index}" if bridge_debug or attribute_debug or category_debug else None
            turn_diagnostics = _render_turn_summary(
                bridge_debug,
                attribute_debug,
                category_debug,
                response_type,
                diagnostics_ref=diagnostics_ref,
            )
            nodes_executed = msg.get("nodes_executed", [])
            if nodes_executed:
                node_names = [n["node"] for n in nodes_executed]
                total_time = sum(n.get("time_ms", 0) for n in nodes_executed)
                trace_summary = f"[{' → '.join(node_names)}] ({total_time:.0f}ms)"
                report += (
                    f"**Model** `[{mode_label}|{response_type}]`**:** {trace_summary}\n"
                    f"{msg['content']}\n\n"
                )
            else:
                report += (
                    f"**Model** `[{mode_label}|{response_type}]`**:** {msg['content']}\n\n"
                )
            if turn_diagnostics:
                report += turn_diagnostics
            report += "\n"
        else:
            child_count += 1
            waiting_for_model = True
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

    if diagnostics_entries:
        report += "## Raw Diagnostics Appendix\n\n"
        for exchange_index in sorted(diagnostics_entries):
            entry = diagnostics_entries[exchange_index]
            report += _render_raw_diagnostics_entry(
                exchange_index=exchange_index,
                source_label=entry.get("source_label"),
                response_type=entry.get("response_type"),
                bridge_debug=entry.get("bridge_debug"),
                attribute_debug=entry.get("attribute_debug"),
                category_debug=entry.get("category_debug"),
            )

    # Global conclusion
    if global_conclusion and global_conclusion.strip():
        report += f"## Global Conclusion\n\n{global_conclusion.strip()}\n"

    return report


def _markdown_blockquote(text):
    """Render text as a markdown blockquote while preserving paragraph breaks."""
    lines = text.splitlines()
    if not lines:
        return "> "
    return "\n".join("> " + line if line else ">" for line in lines)


def _render_hf_exchange(idx, exchange, ec):
    """Render a single HF exchange critique as markdown."""
    report = f"### Exchange {idx}\n\n"
    report += f"**Child said:** \"{exchange['child_response']}\"\n\n"
    report += f"**Model responded:** \"{exchange['model_response']}\"\n\n"
    if exchange.get("bridge_debug") or exchange.get("attribute_debug") or exchange.get("category_debug"):
        report += _render_turn_summary(
            exchange.get("bridge_debug"),
            exchange.get("attribute_debug"),
            exchange.get("category_debug"),
            exchange.get("response_type"),
            diagnostics_ref=f"D{idx}",
        )

    # Node execution trace
    nodes_executed = exchange.get("nodes_executed", [])
    if nodes_executed:
        report += "#### Node Execution Trace\n\n"
        report += "| Node | Time | State Changes |\n"
        report += "|------|------|---------------|\n"
        for node in nodes_executed:
            node_name = node.get("node", "?")
            time_ms = node.get("time_ms", 0)
            changes = node.get("state_changes", node.get("changes", {}))
            changes_str = ", ".join(
                f"{k}: {v}" for k, v in changes.items()
            ) if changes else "-"
            report += f"| {node_name} | {time_ms:.0f}ms | {changes_str} |\n"
        report += "\n"

    # Human critique sections
    report += "#### Human Critique\n\n"
    report += "**Critiqued Model Response:**\n"
    report += f"{_markdown_blockquote(exchange['model_response'])}\n\n"

    mr_expected = ec.get("model_response_expected", "").strip()
    mr_problem = ec.get("model_response_problem", "").strip()
    if mr_expected or mr_problem:
        report += "**Feedback on the model response:**\n"
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


def _bridge_verdict_text(bridge_debug):
    if not bridge_debug:
        return "No bridge debug was recorded."
    if bridge_debug.get("decision") == "bridge_not_started":
        return "Bridge was never started because anchor resolution ended unresolved."
    if bridge_debug.get("bridge_visible_in_response") is True:
        return "Bridge was visible in the response."
    if bridge_debug.get("bridge_visible_in_response") is False:
        return "Bridge did not expose the connection."
    return "Bridge visibility was not evaluated for this turn."


def _bridge_state_summary(bridge_debug):
    if not bridge_debug:
        return ""

    bridge_state = _derive_report_bridge_state(bridge_debug)
    if not bridge_state:
        return ""

    report = f"**Bridge State:** {bridge_state}\n\n"
    bridge_evidence = _derive_report_bridge_evidence(bridge_debug)
    if bridge_evidence:
        report += f"**Bridge Evidence:** {bridge_evidence}\n\n"
    return report


def _derive_report_bridge_state(bridge_debug):
    if not bridge_debug:
        return None
    decision = bridge_debug.get("decision")
    phase_after = bridge_debug.get("bridge_phase_after")
    activation_outcome = _derive_report_activation_outcome(bridge_debug)
    response_type = bridge_debug.get("response_type")
    if decision == "bridge_activation" and (
        phase_after == "anchor_general" or activation_outcome == "committed_to_anchor_general"
    ):
        return "activation_handoff_committed"
    return decision or response_type


def _derive_report_output_node(bridge_debug, response_type=None):
    return (bridge_debug or {}).get("response_type") or response_type


def _derive_report_bridge_evidence(bridge_debug):
    if not bridge_debug:
        return None
    if bridge_debug.get("bridge_follow_reason"):
        return bridge_debug["bridge_follow_reason"]
    if bridge_debug.get("support_action"):
        return bridge_debug["support_action"]
    return None


def _derive_report_activation_outcome(bridge_debug):
    transition = (bridge_debug or {}).get("activation_transition") or {}
    outcome = transition.get("outcome") or {}
    return outcome.get("handoff_result")


def _attribute_profile(attribute_debug):
    if not attribute_debug:
        return {}
    profile = attribute_debug.get("profile") or {}
    if profile:
        return profile
    state_profile = ((attribute_debug.get("state") or {}).get("profile") or {})
    return state_profile if isinstance(state_profile, dict) else {}


def _attribute_reply(attribute_debug):
    reply = (attribute_debug or {}).get("reply") or {}
    return reply if isinstance(reply, dict) else {}


def _category_profile(category_debug):
    if not category_debug:
        return {}
    profile = category_debug.get("profile") or {}
    if profile:
        return profile
    state_profile = ((category_debug.get("state") or {}).get("profile") or {})
    return state_profile if isinstance(state_profile, dict) else {}


def _category_reply(category_debug):
    reply = (category_debug or {}).get("reply") or {}
    return reply if isinstance(reply, dict) else {}


def _derive_report_attribute_summary(attribute_debug):
    if not attribute_debug:
        return {}
    profile = _attribute_profile(attribute_debug)
    reply = _attribute_reply(attribute_debug)
    return {
        "attribute_pipeline": "on",
        "attribute_lane": "active" if profile or attribute_debug.get("state") else "inactive",
        "attribute_id": profile.get("attribute_id") or reply.get("attribute_id"),
        "attribute_label": profile.get("label"),
        "activity_target": profile.get("activity_target"),
        "attribute_branch": profile.get("branch"),
        "attribute_reply_type": reply.get("reply_type"),
        "attribute_decision": attribute_debug.get("decision"),
    }


def _derive_report_category_summary(category_debug):
    if not category_debug:
        return {}
    profile = _category_profile(category_debug)
    reply = _category_reply(category_debug)
    return {
        "category_pipeline": "on",
        "category_lane": "active" if profile or category_debug.get("state") else "inactive",
        "category_id": profile.get("category_id") or reply.get("category_id"),
        "category_label": profile.get("category_label"),
        "activity_target": profile.get("activity_target"),
        "category_reply_type": reply.get("reply_type"),
        "category_decision": category_debug.get("decision"),
    }


def _render_turn_summary(
    bridge_debug,
    attribute_debug=None,
    category_debug=None,
    response_type=None,
    diagnostics_ref=None,
):
    if not bridge_debug and not attribute_debug and not category_debug:
        return ""
    lines = ["#### Turn Summary\n\n"]
    if bridge_debug:
        bridge_state = _derive_report_bridge_state(bridge_debug)
        output_node = _derive_report_output_node(bridge_debug, response_type=response_type)
        bridge_evidence = _derive_report_bridge_evidence(bridge_debug)
        activation_outcome = _derive_report_activation_outcome(bridge_debug)
        if bridge_state:
            lines.append(f"- Bridge State: `{bridge_state}`\n")
        if output_node:
            lines.append(f"- Output Node: `{output_node}`\n")
        lines.append(f"- Bridge Verdict: `{_bridge_verdict_text(bridge_debug)}`\n")
        if bridge_evidence:
            lines.append(f"- Bridge Evidence: `{bridge_evidence}`\n")
        if activation_outcome:
            lines.append(f"- Activation Outcome: `{activation_outcome}`\n")
    if attribute_debug:
        attribute_summary = _derive_report_attribute_summary(attribute_debug)
        for label, key in [
            ("Attribute Pipeline", "attribute_pipeline"),
            ("Attribute Lane", "attribute_lane"),
            ("Attribute ID", "attribute_id"),
            ("Attribute Label", "attribute_label"),
            ("Activity Target", "activity_target"),
            ("Attribute Branch", "attribute_branch"),
            ("Attribute Reply Type", "attribute_reply_type"),
            ("Attribute Decision", "attribute_decision"),
        ]:
            value = attribute_summary.get(key)
            if value is not None:
                lines.append(f"- {label}: `{value}`\n")
    if category_debug:
        category_summary = _derive_report_category_summary(category_debug)
        for label, key in [
            ("Category Pipeline", "category_pipeline"),
            ("Category Lane", "category_lane"),
            ("Category ID", "category_id"),
            ("Category Label", "category_label"),
            ("Activity Target", "activity_target"),
            ("Category Reply Type", "category_reply_type"),
            ("Category Decision", "category_decision"),
        ]:
            value = category_summary.get(key)
            if value is not None:
                lines.append(f"- {label}: `{value}`\n")
    if diagnostics_ref:
        lines.append(f"- Diagnostics Ref: `{diagnostics_ref}`\n")
    lines.append("\n")
    return "".join(lines)


def _render_raw_bridge_debug(bridge_debug):
    if not bridge_debug:
        return ""
    lines = ["#### Raw Bridge Debug\n\n"]
    for key, value in bridge_debug.items():
        if value is None or key == "activation_transition":
            continue
        lines.append(f"- {key}: `{value}`\n")
    activation_transition = bridge_debug.get("activation_transition") or {}
    if activation_transition:
        lines.append("\n##### Activation Transition\n\n")
        ordered_groups = [
            ("before_state", "Before State"),
            ("question_validation", "Question Validation"),
            ("answer_validation", "Answer Validation"),
            ("outcome", "Outcome"),
            ("turn_interpretation", "Turn Interpretation"),
            ("continuity", "Continuity"),
        ]
        for group_key, group_label in ordered_groups:
            group_value = activation_transition.get(group_key) or {}
            if not group_value:
                continue
            lines.append(f"###### {group_label}\n\n")
            for key, value in group_value.items():
                if value is None:
                    continue
                lines.append(f"- {key}: `{value}`\n")
            lines.append("\n")
    lines.append("\n")
    return "".join(lines)


def _format_report_debug_value(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_raw_attribute_group(group_label, group_value):
    if not isinstance(group_value, dict) or not group_value:
        return ""
    lines = [f"\n##### {group_label}\n\n"]
    for key, value in group_value.items():
        if value is None:
            continue
        lines.append(f"- {key}: `{_format_report_debug_value(value)}`\n")
    return "".join(lines)


def _render_raw_attribute_debug(attribute_debug):
    if not attribute_debug:
        return ""
    lines = ["#### Raw Attribute Debug\n\n"]
    for key in ("decision", "reason", "response_text"):
        value = attribute_debug.get(key)
        if value is not None:
            lines.append(f"- {key}: `{_format_report_debug_value(value)}`\n")
    for key, label in [
        ("profile", "Attribute Profile"),
        ("state", "Attribute State"),
        ("reply", "Attribute Reply"),
        ("readiness", "Attribute Readiness"),
    ]:
        lines.append(_render_raw_attribute_group(label, attribute_debug.get(key)))
    lines.append("\n")
    return "".join(lines)


def _render_raw_category_debug(category_debug):
    if not category_debug:
        return ""
    lines = ["#### Raw Category Debug\n\n"]
    for key in ("decision", "reason", "response_text"):
        value = category_debug.get(key)
        if value is not None:
            lines.append(f"- {key}: `{_format_report_debug_value(value)}`\n")
    for key, label in [
        ("profile", "Category Profile"),
        ("state", "Category State"),
        ("reply", "Category Reply"),
        ("readiness", "Category Readiness"),
    ]:
        lines.append(_render_raw_attribute_group(label, category_debug.get(key)))
    lines.append("\n")
    return "".join(lines)


def _render_raw_diagnostics_entry(
    exchange_index,
    source_label,
    response_type,
    bridge_debug,
    attribute_debug=None,
    category_debug=None,
):
    if not bridge_debug and not attribute_debug and not category_debug:
        return ""
    lines = [
        f"### Diagnostics D{exchange_index} — {source_label}\n",
        f"**Exchange Index:** {exchange_index}\n",
    ]
    bridge_state = _derive_report_bridge_state(bridge_debug)
    output_node = _derive_report_output_node(bridge_debug, response_type=response_type)
    bridge_evidence = _derive_report_bridge_evidence(bridge_debug)
    activation_outcome = _derive_report_activation_outcome(bridge_debug)
    if bridge_state:
        lines.append(f"**Bridge State:** {bridge_state}\n")
    if output_node:
        lines.append(f"**Output Node:** {output_node}\n")
    if bridge_evidence:
        lines.append(f"**Bridge Evidence:** {bridge_evidence}\n")
    if activation_outcome:
        lines.append(f"**Activation Outcome:** {activation_outcome}\n")
    attribute_summary = _derive_report_attribute_summary(attribute_debug)
    for label, key in [
        ("Attribute ID", "attribute_id"),
        ("Attribute Label", "attribute_label"),
        ("Attribute Branch", "attribute_branch"),
        ("Attribute Reply Type", "attribute_reply_type"),
    ]:
        value = attribute_summary.get(key)
        if value is not None:
            lines.append(f"**{label}:** {value}\n")
    category_summary = _derive_report_category_summary(category_debug)
    for label, key in [
        ("Category ID", "category_id"),
        ("Category Label", "category_label"),
        ("Category Reply Type", "category_reply_type"),
    ]:
        value = category_summary.get(key)
        if value is not None:
            lines.append(f"**{label}:** {value}\n")
    lines.append("\n")
    lines.append(_render_raw_bridge_debug(bridge_debug))
    lines.append(_render_raw_attribute_debug(attribute_debug))
    lines.append(_render_raw_category_debug(category_debug))
    return "".join(lines)


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

    def parse_raw_bridge_debug(raw_text):
        debug = {}
        activation_transition = {}
        current_activation_group = None
        in_activation_transition = False

        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line == "##### Activation Transition":
                in_activation_transition = True
                current_activation_group = None
                continue
            if line.startswith("###### "):
                label = line[7:].strip().lower().replace(" ", "_")
                current_activation_group = label
                activation_transition.setdefault(current_activation_group, {})
                continue
            m = re.match(r'-\s+([^:]+):\s+`(.+)`', line)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                if in_activation_transition and current_activation_group:
                    activation_transition.setdefault(current_activation_group, {})[key] = value
                else:
                    debug[key] = value

        if activation_transition:
            debug["activation_transition"] = activation_transition
        return debug or None

    def parse_attribute_value(value):
        if value.startswith(("{", "[")):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def parse_raw_attribute_debug(raw_text):
        debug = {}
        group_map = {
            "attribute_profile": "profile",
            "attribute_state": "state",
            "attribute_reply": "reply",
            "attribute_readiness": "readiness",
        }
        current_group = None

        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("##### "):
                label = line[6:].strip().lower().replace(" ", "_")
                current_group = group_map.get(label)
                if current_group:
                    debug.setdefault(current_group, {})
                continue
            m = re.match(r'-\s+([^:]+):\s+`(.*)`', line)
            if not m:
                continue
            key = m.group(1).strip()
            value = parse_attribute_value(m.group(2).strip())
            if current_group:
                debug.setdefault(current_group, {})[key] = value
            else:
                debug[key] = value

        return debug or None

    def parse_raw_category_debug(raw_text):
        debug = {}
        group_map = {
            "category_profile": "profile",
            "category_state": "state",
            "category_reply": "reply",
            "category_readiness": "readiness",
        }
        current_group = None

        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("##### "):
                label = line[6:].strip().lower().replace(" ", "_")
                current_group = group_map.get(label)
                if current_group:
                    debug.setdefault(current_group, {})
                continue
            m = re.match(r'-\s+([^:]+):\s+`(.*)`', line)
            if not m:
                continue
            key = m.group(1).strip()
            value = parse_attribute_value(m.group(2).strip())
            if current_group:
                debug.setdefault(current_group, {})[key] = value
            else:
                debug[key] = value

        return debug or None

    def parse_summary_block(block_text):
        summary = {
            "bridge_state": None,
            "output_node": None,
            "bridge_verdict": None,
            "bridge_evidence": None,
            "activation_outcome": None,
            "attribute_pipeline": None,
            "attribute_lane": None,
            "attribute_id": None,
            "attribute_label": None,
            "activity_target": None,
            "attribute_branch": None,
            "attribute_reply_type": None,
            "attribute_decision": None,
            "category_pipeline": None,
            "category_lane": None,
            "category_id": None,
            "category_label": None,
            "category_reply_type": None,
            "category_decision": None,
            "diagnostics_ref": None,
        }
        sm = re.search(r'#### Turn Summary\n+(.+?)(?=\n\n#### |\n\n---|\n\*\*|\n### |\n## |\Z)', block_text, re.DOTALL)
        if not sm:
            return summary
        summary_text = sm.group(1)
        for label, key in [
            ("Bridge State", "bridge_state"),
            ("Output Node", "output_node"),
            ("Bridge Verdict", "bridge_verdict"),
            ("Bridge Evidence", "bridge_evidence"),
            ("Activation Outcome", "activation_outcome"),
            ("Attribute Pipeline", "attribute_pipeline"),
            ("Attribute Lane", "attribute_lane"),
            ("Attribute ID", "attribute_id"),
            ("Attribute Label", "attribute_label"),
            ("Activity Target", "activity_target"),
            ("Attribute Branch", "attribute_branch"),
            ("Attribute Reply Type", "attribute_reply_type"),
            ("Attribute Decision", "attribute_decision"),
            ("Category Pipeline", "category_pipeline"),
            ("Category Lane", "category_lane"),
            ("Category ID", "category_id"),
            ("Category Label", "category_label"),
            ("Category Reply Type", "category_reply_type"),
            ("Category Decision", "category_decision"),
            ("Diagnostics Ref", "diagnostics_ref"),
        ]:
            lm = re.search(rf'- {re.escape(label)}:\s+`(.+?)`', summary_text)
            if lm:
                summary[key] = lm.group(1).strip()
        return summary

    def parse_turn_diagnostics(turn_text):
        text_part, marker, diagnostics_part = turn_text.partition("\n#### Turn Summary\n\n")
        if marker:
            cleaned_text = text_part.strip()
            summary = parse_summary_block(marker + diagnostics_part)
            return {
                "text": cleaned_text,
                "bridge_verdict": summary["bridge_verdict"],
                "bridge_debug": None,
                "bridge_state": summary["bridge_state"],
                "output_node": summary["output_node"],
                "bridge_evidence": summary["bridge_evidence"],
                "activation_outcome": summary["activation_outcome"],
                "attribute_pipeline": summary["attribute_pipeline"],
                "attribute_lane": summary["attribute_lane"],
                "attribute_id": summary["attribute_id"],
                "attribute_label": summary["attribute_label"],
                "activity_target": summary["activity_target"],
                "attribute_branch": summary["attribute_branch"],
                "attribute_reply_type": summary["attribute_reply_type"],
                "attribute_decision": summary["attribute_decision"],
                "attribute_debug": None,
                "category_pipeline": summary["category_pipeline"],
                "category_lane": summary["category_lane"],
                "category_id": summary["category_id"],
                "category_label": summary["category_label"],
                "category_reply_type": summary["category_reply_type"],
                "category_decision": summary["category_decision"],
                "category_debug": None,
                "diagnostics_ref": summary["diagnostics_ref"],
            }

        text_part, marker, diagnostics_part = turn_text.partition("\n#### Turn Diagnostics\n\n")
        if marker:
            cleaned_text = text_part.strip()
            bridge_debug = None
            vm = re.search(r'\*\*Bridge Verdict:\*\*\s*(.+)', diagnostics_part)
            verdict = vm.group(1).strip() if vm else None
            raw_bridge = re.search(
                r'#### Raw Bridge Debug\n+(.+?)(?=\n\n#### Raw Attribute Debug|\n\n#### Raw Category Debug|\n\n#### (?!#)|\Z)',
                diagnostics_part,
                re.DOTALL,
            )
            if raw_bridge:
                bridge_debug = parse_raw_bridge_debug(raw_bridge.group(1))
            raw_attribute = re.search(
                r'#### Raw Attribute Debug\n+(.+?)(?=\n\n#### Raw Category Debug|\n\n#### (?!#)|\Z)',
                diagnostics_part,
                re.DOTALL,
            )
            attribute_debug = parse_raw_attribute_debug(raw_attribute.group(1)) if raw_attribute else None
            raw_category = re.search(
                r'#### Raw Category Debug\n+(.+?)(?=\n\n#### (?!#)|\Z)',
                diagnostics_part,
                re.DOTALL,
            )
            category_debug = parse_raw_category_debug(raw_category.group(1)) if raw_category else None
            return {
                "text": cleaned_text,
                "bridge_verdict": verdict,
                "bridge_debug": bridge_debug,
                "bridge_state": (bridge_debug or {}).get("decision") or (bridge_debug or {}).get("response_type"),
                "output_node": None,
                "bridge_evidence": (bridge_debug or {}).get("bridge_follow_reason"),
                "activation_outcome": (((bridge_debug or {}).get("activation_transition") or {}).get("outcome") or {}).get("handoff_result"),
                "attribute_pipeline": None,
                "attribute_lane": None,
                "attribute_id": ((attribute_debug or {}).get("profile") or {}).get("attribute_id"),
                "attribute_label": ((attribute_debug or {}).get("profile") or {}).get("label"),
                "activity_target": (
                    ((attribute_debug or {}).get("profile") or {}).get("activity_target")
                    or ((category_debug or {}).get("profile") or {}).get("activity_target")
                ),
                "attribute_branch": ((attribute_debug or {}).get("profile") or {}).get("branch"),
                "attribute_reply_type": ((attribute_debug or {}).get("reply") or {}).get("reply_type"),
                "attribute_decision": (attribute_debug or {}).get("decision"),
                "attribute_debug": attribute_debug,
                "category_pipeline": None,
                "category_lane": None,
                "category_id": ((category_debug or {}).get("profile") or {}).get("category_id"),
                "category_label": ((category_debug or {}).get("profile") or {}).get("category_label"),
                "category_reply_type": ((category_debug or {}).get("reply") or {}).get("reply_type"),
                "category_decision": (category_debug or {}).get("decision"),
                "category_debug": category_debug,
                "diagnostics_ref": None,
            }
        return {
            "text": turn_text.strip(),
            "bridge_verdict": None,
            "bridge_debug": None,
            "bridge_state": None,
            "output_node": None,
            "bridge_evidence": None,
            "activation_outcome": None,
            "attribute_pipeline": None,
            "attribute_lane": None,
            "attribute_id": None,
            "attribute_label": None,
            "activity_target": None,
            "attribute_branch": None,
            "attribute_reply_type": None,
            "attribute_decision": None,
            "attribute_debug": None,
            "category_pipeline": None,
            "category_lane": None,
            "category_id": None,
            "category_label": None,
            "category_reply_type": None,
            "category_decision": None,
            "category_debug": None,
            "diagnostics_ref": None,
        }

    def parse_raw_diagnostics_appendix(sec):
        appendix = {}
        blocks = re.split(r'\n### Diagnostics D(\d+)\s+[—-]\s+([^\n]+)\n', sec)
        it = iter(blocks[1:])
        for idx_str, source_label, block in zip(it, it, it):
            exchange_index = int(idx_str)
            entry = {
                "exchange_index": exchange_index,
                "source_label": source_label.strip(),
                "bridge_state": None,
                "output_node": None,
                "bridge_evidence": None,
                "activation_outcome": None,
                "bridge_debug": None,
                "attribute_pipeline": None,
                "attribute_lane": None,
                "attribute_id": None,
                "attribute_label": None,
                "activity_target": None,
                "attribute_branch": None,
                "attribute_reply_type": None,
                "attribute_decision": None,
                "attribute_debug": None,
                "category_pipeline": None,
                "category_lane": None,
                "category_id": None,
                "category_label": None,
                "category_reply_type": None,
                "category_decision": None,
                "category_debug": None,
            }
            for label, key in [
                ("Bridge State", "bridge_state"),
                ("Output Node", "output_node"),
                ("Bridge Evidence", "bridge_evidence"),
                ("Activation Outcome", "activation_outcome"),
            ]:
                sm = re.search(rf'\*\*{re.escape(label)}:\*\*\s+(.+)', block)
                if sm:
                    entry[key] = sm.group(1).strip()
            for label, key in [
                ("Attribute ID", "attribute_id"),
                ("Attribute Label", "attribute_label"),
                ("Attribute Branch", "attribute_branch"),
                ("Attribute Reply Type", "attribute_reply_type"),
            ]:
                sm = re.search(rf'\*\*{re.escape(label)}:\*\*\s+(.+)', block)
                if sm:
                    entry[key] = sm.group(1).strip()
            for label, key in [
                ("Category ID", "category_id"),
                ("Category Label", "category_label"),
                ("Category Reply Type", "category_reply_type"),
            ]:
                sm = re.search(rf'\*\*{re.escape(label)}:\*\*\s+(.+)', block)
                if sm:
                    entry[key] = sm.group(1).strip()
            raw_bridge = re.search(
                r'#### Raw Bridge Debug\n+(.+?)(?=\n\n#### Raw Attribute Debug|\n\n#### Raw Category Debug|\n\n### |\n## |\Z)',
                block,
                re.DOTALL,
            )
            if raw_bridge:
                entry["bridge_debug"] = parse_raw_bridge_debug(raw_bridge.group(1))
            raw_attribute = re.search(
                r'#### Raw Attribute Debug\n+(.+?)(?=\n\n#### Raw Category Debug|\n\n### |\n## |\Z)',
                block,
                re.DOTALL,
            )
            if raw_attribute:
                entry["attribute_debug"] = parse_raw_attribute_debug(raw_attribute.group(1))
            raw_category = re.search(
                r'#### Raw Category Debug\n+(.+?)(?=\n\n### |\n## |\Z)',
                block,
                re.DOTALL,
            )
            if raw_category:
                entry["category_debug"] = parse_raw_category_debug(raw_category.group(1))
                entry["activity_target"] = entry["activity_target"] or ((entry["category_debug"] or {}).get("profile") or {}).get("activity_target")
            appendix[exchange_index] = entry
        return appendix

    # ── Parse transcript ────────────────────────────────────────────────────
    tlines = get_section("Conversation Transcript").splitlines()
    turns = []
    i = 0
    while i < len(tlines):
        line = tlines[i]
        # Model turn: **Model** `[PHASE|response_type]`**:** [nodes] (Xms)
        # or:         **Model** `[PHASE|response_type]`**:** inline content
        mm = re.match(r'\*\*Model\*\*\s*`\[([A-Z]+)(?:\|([^\]]+))?\]`\*\*:\*\*\s*(.*)', line)
        if mm:
            phase   = mm.group(1)
            response_type = mm.group(2)
            line_tail = mm.group(3)
            trace_match = re.fullmatch(r'\[([^\]]+)\]\s+\((\d+)ms\)', line_tail)
            nodes = [n.strip() for n in trace_match.group(1).split('→')] if trace_match else []
            time_ms = int(trace_match.group(2)) if trace_match else 0
            body = [line_tail] if line_tail and not trace_match else []
            i += 1
            while (
                i < len(tlines)
                and tlines[i] != '---'
                and not tlines[i].startswith('**Child:**')
                and not tlines[i].startswith('**Model**')
            ):
                body.append(tlines[i])
                i += 1
            turn_meta = parse_turn_diagnostics("\n".join(body).strip())
            turns.append({
                "role": "model",
                "phase": phase,
                "text": turn_meta["text"],
                "response_type": response_type,
                "nodes": nodes,
                "time_ms": time_ms,
                "exchange_index": None,
                "bridge_verdict": turn_meta["bridge_verdict"],
                "bridge_debug": turn_meta["bridge_debug"],
                "bridge_state": turn_meta["bridge_state"],
                "output_node": turn_meta["output_node"],
                "bridge_evidence": turn_meta["bridge_evidence"],
                "activation_outcome": turn_meta["activation_outcome"],
                "attribute_pipeline": turn_meta["attribute_pipeline"],
                "attribute_lane": turn_meta["attribute_lane"],
                "attribute_id": turn_meta["attribute_id"],
                "attribute_label": turn_meta["attribute_label"],
                "activity_target": turn_meta["activity_target"],
                "attribute_branch": turn_meta["attribute_branch"],
                "attribute_reply_type": turn_meta["attribute_reply_type"],
                "attribute_decision": turn_meta["attribute_decision"],
                "attribute_debug": turn_meta["attribute_debug"],
                "category_pipeline": turn_meta["category_pipeline"],
                "category_lane": turn_meta["category_lane"],
                "category_id": turn_meta["category_id"],
                "category_label": turn_meta["category_label"],
                "category_reply_type": turn_meta["category_reply_type"],
                "category_decision": turn_meta["category_decision"],
                "category_debug": turn_meta["category_debug"],
                "diagnostics_ref": turn_meta["diagnostics_ref"],
                "critique": None,
            })
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

    appendix = parse_raw_diagnostics_appendix(get_section("Raw Diagnostics Appendix"))
    for turn in result["transcript"]:
        if turn["role"] != "model":
            continue
        entry = appendix.get(turn.get("exchange_index"))
        if not entry:
            continue
        turn["bridge_state"] = entry.get("bridge_state") or turn.get("bridge_state")
        turn["output_node"] = entry.get("output_node") or turn.get("output_node")
        turn["bridge_evidence"] = entry.get("bridge_evidence") or turn.get("bridge_evidence")
        turn["activation_outcome"] = entry.get("activation_outcome") or turn.get("activation_outcome")
        turn["attribute_pipeline"] = entry.get("attribute_pipeline") or turn.get("attribute_pipeline")
        turn["attribute_lane"] = entry.get("attribute_lane") or turn.get("attribute_lane")
        turn["attribute_id"] = entry.get("attribute_id") or turn.get("attribute_id")
        turn["attribute_label"] = entry.get("attribute_label") or turn.get("attribute_label")
        turn["activity_target"] = entry.get("activity_target") or turn.get("activity_target")
        turn["attribute_branch"] = entry.get("attribute_branch") or turn.get("attribute_branch")
        turn["attribute_reply_type"] = entry.get("attribute_reply_type") or turn.get("attribute_reply_type")
        turn["attribute_decision"] = entry.get("attribute_decision") or turn.get("attribute_decision")
        turn["attribute_debug"] = entry.get("attribute_debug") or turn.get("attribute_debug")
        turn["category_pipeline"] = entry.get("category_pipeline") or turn.get("category_pipeline")
        turn["category_lane"] = entry.get("category_lane") or turn.get("category_lane")
        turn["category_id"] = entry.get("category_id") or turn.get("category_id")
        turn["category_label"] = entry.get("category_label") or turn.get("category_label")
        turn["category_reply_type"] = entry.get("category_reply_type") or turn.get("category_reply_type")
        turn["category_decision"] = entry.get("category_decision") or turn.get("category_decision")
        turn["category_debug"] = entry.get("category_debug") or turn.get("category_debug")
        turn["diagnostics_ref"] = f"D{turn['exchange_index']}"
        turn["bridge_debug"] = entry.get("bridge_debug") or turn.get("bridge_debug")

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
                    "conclusion": None, "node_trace": [], "bridge_verdict": None,
                    "bridge_debug": None, "attribute_debug": None, "category_debug": None}

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
            verdict = re.search(r'\*\*Bridge Verdict:\*\*\s*(.+)', block)
            crit["bridge_verdict"] = verdict.group(1).strip() if verdict else None
            summary = parse_summary_block(block)
            if crit["bridge_verdict"] is None:
                crit["bridge_verdict"] = summary["bridge_verdict"]
            raw_bridge = re.search(
                r'#### Raw Bridge Debug\n+(.+?)(?=\n\n#### Raw Attribute Debug|\n\n#### Raw Category Debug|\n\n#### (?!#)|\n\n---|\Z)',
                block,
                re.DOTALL,
            )
            if raw_bridge:
                crit["bridge_debug"] = parse_raw_bridge_debug(raw_bridge.group(1))
            raw_attribute = re.search(r'#### Raw Attribute Debug\n+(.+?)(?=\n\n#### Raw Category Debug|\n\n#### (?!#)|\n\n---|\Z)', block, re.DOTALL)
            if raw_attribute:
                crit["attribute_debug"] = parse_raw_attribute_debug(raw_attribute.group(1))
            raw_category = re.search(r'#### Raw Category Debug\n+(.+?)(?=\n\n#### (?!#)|\n\n---|\Z)', block, re.DOTALL)
            if raw_category:
                crit["category_debug"] = parse_raw_category_debug(raw_category.group(1))
            if (
                crit["expected"]
                or crit["problematic"]
                or crit["conclusion"]
                or crit["bridge_verdict"]
                or crit["bridge_debug"]
                or crit["attribute_debug"]
                or crit["category_debug"]
                or crit["node_trace"]
            ):
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
                "conclusion": None, "node_trace": [], "bridge_verdict": None,
                "bridge_debug": None, "attribute_debug": None, "category_debug": None}
        all_expected    = re.findall(r'\*What is expected:\*\s*(.+)', intro_sec)
        all_problematic = re.findall(r'\*Why is it problematic:\*\s*(.+)', intro_sec)
        crit["expected"]    = all_expected[-1].strip()    if all_expected    else None
        crit["problematic"] = all_problematic[-1].strip() if all_problematic else None
        cm = re.search(r'#### Conclusion\n+(.+?)(?=\n\n---|\n###|\Z)', intro_sec, re.DOTALL)
        crit["conclusion"] = cm.group(1).strip() if cm else None
        verdict = re.search(r'\*\*Bridge Verdict:\*\*\s*(.+)', intro_sec)
        crit["bridge_verdict"] = verdict.group(1).strip() if verdict else None
        summary = parse_summary_block(intro_sec)
        if crit["bridge_verdict"] is None:
            crit["bridge_verdict"] = summary["bridge_verdict"]
        raw_bridge = re.search(
            r'#### Raw Bridge Debug\n+(.+?)(?=\n\n#### Raw Attribute Debug|\n\n#### Raw Category Debug|\n\n#### (?!#)|\n\n---|\Z)',
            intro_sec,
            re.DOTALL,
        )
        if raw_bridge:
            crit["bridge_debug"] = parse_raw_bridge_debug(raw_bridge.group(1))
        raw_attribute = re.search(r'#### Raw Attribute Debug\n+(.+?)(?=\n\n#### Raw Category Debug|\n\n#### (?!#)|\n\n---|\Z)', intro_sec, re.DOTALL)
        if raw_attribute:
            crit["attribute_debug"] = parse_raw_attribute_debug(raw_attribute.group(1))
        raw_category = re.search(r'#### Raw Category Debug\n+(.+?)(?=\n\n#### (?!#)|\n\n---|\Z)', intro_sec, re.DOTALL)
        if raw_category:
            crit["category_debug"] = parse_raw_category_debug(raw_category.group(1))
        if (
            crit["expected"]
            or crit["problematic"]
            or crit["conclusion"]
            or crit["bridge_verdict"]
            or crit["bridge_debug"]
            or crit["attribute_debug"]
            or crit["category_debug"]
            or crit["node_trace"]
            or appendix.get(0)
        ):
            critiques[0] = crit

    # Attach critiques to matching model turns
    for turn in result["transcript"]:
        if turn["role"] == "model" and turn.get("exchange_index") in critiques:
            turn["critique"] = critiques[turn["exchange_index"]]
            if turn["bridge_debug"] is None and turn["critique"].get("bridge_debug") is not None:
                turn["bridge_debug"] = turn["critique"]["bridge_debug"]
            if turn["bridge_verdict"] is None and turn["critique"].get("bridge_verdict") is not None:
                turn["bridge_verdict"] = turn["critique"]["bridge_verdict"]
            if turn["critique"].get("bridge_debug") is None and turn.get("bridge_debug") is not None:
                turn["critique"]["bridge_debug"] = turn["bridge_debug"]
            if turn["critique"].get("bridge_verdict") is None and turn.get("bridge_verdict") is not None:
                turn["critique"]["bridge_verdict"] = turn["bridge_verdict"]
            if turn["critique"].get("attribute_debug") is None and turn.get("attribute_debug") is not None:
                turn["critique"]["attribute_debug"] = turn["attribute_debug"]
            if turn["critique"].get("category_debug") is None and turn.get("category_debug") is not None:
                turn["critique"]["category_debug"] = turn["category_debug"]

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

    handoff_payload = conversation
    activity_target = assistant.attribute_activity_target() if hasattr(assistant, "attribute_activity_target") else None
    attribute_ready = getattr(assistant, "attribute_activity_ready", False) or bool(
        getattr(getattr(assistant, "attribute_state", None), "activity_ready", False)
    )
    if activity_target and attribute_ready:
        handoff_payload = {
            "conversation": conversation,
            "activity_source": "attribute",
            "attribute_id": activity_target.get("attribute_id"),
            "attribute_label": activity_target.get("attribute_label"),
            "activity_target": activity_target.get("activity_target"),
        }
    category_target = assistant.category_activity_target() if hasattr(assistant, "category_activity_target") else None
    category_ready = getattr(assistant, "category_activity_ready", False) or bool(
        getattr(getattr(assistant, "category_state", None), "activity_ready", False)
    )
    if category_target and category_ready:
        handoff_payload = {
            "conversation": conversation,
            "activity_source": "category",
            "category_id": category_target.get("category_id"),
            "category_label": category_target.get("category_label"),
            "activity_target": category_target.get("activity_target"),
        }

    os.makedirs('/tmp/handoff', exist_ok=True)
    filename = uuid.uuid4().hex[:8] + '.json'
    with open(f'/tmp/handoff/{filename}', 'w', encoding='utf-8') as f:
        json.dump(handoff_payload, f, indent=2, ensure_ascii=False)

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
