from pathlib import Path

import schema
import stream
from paixueji_assistant import ConversationState, PaixuejiAssistant


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_dead_topic_selection_api_removed():
    assert not hasattr(stream, "generate_explicit_switch_response_stream")
    assert "suggested_objects" not in schema.StreamChunk.model_fields
    assert "object_selection_mode" not in schema.StreamChunk.model_fields
    assert "AWAITING_TOPIC_SELECTION" not in ConversationState.__members__


def test_dead_assistant_legacy_api_removed():
    assert not hasattr(PaixuejiAssistant, "classify_theme_background")
    assert not hasattr(PaixuejiAssistant, "start_theme_guide")
    assert not hasattr(PaixuejiAssistant, "stop_theme_guide")
    assert not hasattr(PaixuejiAssistant, "get_conversation_history")
    assert not hasattr(PaixuejiAssistant, "reset_object_state")
    assert not hasattr(PaixuejiAssistant, "reset")
    assert not hasattr(PaixuejiAssistant, "get_current_scaffold_level")
    assert not hasattr(PaixuejiAssistant, "enter_guide_mode")
    assert not hasattr(PaixuejiAssistant, "update_navigation_state")
    assert not hasattr(PaixuejiAssistant, "give_hint")
    assert not hasattr(PaixuejiAssistant, "exit_guide_mode")
    assert not hasattr(PaixuejiAssistant, "should_give_hint")
    assert not hasattr(PaixuejiAssistant, "should_exit_guide")
    assert "AWAITING_ANSWER" not in ConversationState.__members__
    assert "COMPLETION" not in ConversationState.__members__


def test_unused_schema_wrappers_removed():
    assert not hasattr(schema, "StandardResponse")
    assert not hasattr(schema, "CallAskAskRequest")


def test_guide_runtime_schema_removed():
    removed_fields = {
        "guide_phase",
        "guide_turn_count",
        "guide_max_turns",
        "guide_status",
        "guide_strategy",
        "scaffold_level",
        "bridge_question",
        "is_guide_success",
    }
    assert removed_fields.isdisjoint(schema.StreamChunk.model_fields)


def test_guide_modules_removed():
    assert not hasattr(stream, "generate_guide_hint")


def test_chat_complete_workflow_removed_from_graph():
    graph_source = (PROJECT_ROOT / "graph.py").read_text(encoding="utf-8")

    assert "async def node_chat_complete" not in graph_source
    assert 'workflow.add_node("chat_complete"' not in graph_source
    assert 'workflow.add_edge("classify_theme", "chat_complete")' not in graph_source


def test_trace_assembler_no_longer_lists_chat_complete_node():
    trace_source = (PROJECT_ROOT / "trace_assembler.py").read_text(encoding="utf-8")

    assert "- chat_complete:" not in trace_source
