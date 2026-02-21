"""
TraceObject assembly and storage logic.

Assembles structured TraceObjects from conversation history, node traces,
and human critique data. Saves them as JSON files for the optimization pipeline.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

from trace_schema import (
    TraceObject, NodeTrace, HumanCritique, ExchangeContext,
    identify_culprit,
)


def extract_input_state_for_exchange(assistant, exchange_index: int) -> dict:
    """
    Walk conversation_history to find the Nth model->child->model triplet
    and return the _input_state_snapshot from the responding model message.

    exchange_index is 1-based (matching the critique UI).
    """
    # Build list of model messages (excluding system)
    exchanges_found = 0
    i = 0
    history = assistant.conversation_history

    while i < len(history):
        msg = history[i]
        if msg.get("role") == "system":
            i += 1
            continue

        # Look for model->child->model triplet
        if (msg.get("role") == "assistant"
                and i + 2 < len(history)
                and history[i + 1].get("role") == "user"
                and history[i + 2].get("role") == "assistant"):
            exchanges_found += 1
            if exchanges_found == exchange_index:
                # The responding model message is history[i+2]
                return history[i + 2].get("_input_state_snapshot", {})
            i += 2
        else:
            i += 1

    return {}


def assemble_trace_object(
    session_id: str,
    assistant,
    exchange_index: int,
    exchange_data: dict,
    critique_data: dict,
) -> TraceObject:
    """
    Assemble a complete TraceObject from exchange and critique data.

    Args:
        session_id: The session UUID
        assistant: PaixuejiAssistant instance
        exchange_index: 1-based index of the exchange in the conversation
        exchange_data: Dict with model_question, child_response, model_response,
                       nodes_executed, mode
        critique_data: Dict with human critique fields
    """
    # Build execution path from nodes_executed
    raw_nodes = exchange_data.get("nodes_executed", [])
    execution_path = []
    total_time = 0
    for entry in raw_nodes:
        node_trace = NodeTrace(
            node=entry.get("node", "unknown"),
            time_ms=entry.get("time_ms", 0),
            changes=entry.get("changes", {}),
            state_before=entry.get("state_before", {}),
            validation_result=entry.get("validation_result"),
            navigation_result=entry.get("navigation_result"),
        )
        execution_path.append(node_trace)
        total_time += entry.get("time_ms", 0)

    # Extract input state from conversation history
    input_state = extract_input_state_for_exchange(assistant, exchange_index)

    # Build exchange context
    exchange = ExchangeContext(
        model_question=exchange_data.get("model_question", ""),
        child_response=exchange_data.get("child_response", ""),
        model_response=exchange_data.get("model_response", ""),
        mode=exchange_data.get("mode", "chat"),
    )

    # Build human critique
    critique = HumanCritique(
        exchange_index=exchange_index,
        model_question_expected=critique_data.get("model_question_expected", ""),
        model_question_problem=critique_data.get("model_question_problem", ""),
        model_response_expected=critique_data.get("model_response_expected", ""),
        model_response_problem=critique_data.get("model_response_problem", ""),
        conclusion=critique_data.get("conclusion", ""),
    )

    # Extract validation and navigation results from the execution path
    validation_result = None
    navigation_result = None
    for entry in execution_path:
        if entry.validation_result and not validation_result:
            validation_result = entry.validation_result
        if entry.navigation_result and not navigation_result:
            navigation_result = entry.navigation_result

    # Identify culprit
    culprit = identify_culprit(
        critique=critique,
        execution_path=execution_path,
        exchange=exchange,
        validation_result=validation_result,
        navigation_result=navigation_result,
    )

    # Count conversation length (non-system messages)
    conversation_length = sum(
        1 for msg in assistant.conversation_history
        if msg.get("role") != "system"
    )

    return TraceObject(
        trace_id=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=datetime.now().isoformat(),
        object_name=assistant.object_name or "unknown",
        age=assistant.age,
        key_concept=assistant.key_concept,
        ibpyp_theme_name=assistant.ibpyp_theme_name,
        input_state=input_state,
        execution_path=execution_path,
        culprit=culprit,
        critique=critique,
        exchange=exchange,
        validation_result=validation_result,
        navigation_result=navigation_result,
        exchange_index=exchange_index,
        conversation_length=conversation_length,
        total_execution_time_ms=round(total_time, 1),
    )


def save_trace_object(trace: TraceObject) -> str:
    """
    Save a TraceObject as JSON to the traces/ directory.

    Naming: {object_name}_{session_prefix}_ex{index}_{timestamp}.json
    Returns the file path as a string.
    """
    traces_dir = Path(__file__).parent / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (trace.object_name or "unknown")
    )
    session_prefix = trace.session_id[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_name}_{session_prefix}_ex{trace.exchange_index}_{timestamp}.json"

    file_path = traces_dir / filename
    file_path.write_text(
        trace.model_dump_json(indent=2),
        encoding="utf-8",
    )

    logger.info(f"[TRACE] Saved trace object: {file_path}")
    return str(file_path)
