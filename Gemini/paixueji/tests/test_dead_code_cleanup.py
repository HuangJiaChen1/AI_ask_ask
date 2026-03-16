import schema
import stream
from paixueji_assistant import ConversationState, PaixuejiAssistant


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
    assert "AWAITING_ANSWER" not in ConversationState.__members__
    assert "COMPLETION" not in ConversationState.__members__


def test_unused_schema_wrappers_removed():
    assert not hasattr(schema, "StandardResponse")
    assert not hasattr(schema, "CallAskAskRequest")
