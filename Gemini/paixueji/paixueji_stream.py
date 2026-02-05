"""
Streaming functions for Paixueji assistant.

This module provides async streaming responses for the Paixueji assistant,
where the LLM asks questions about objects and children answer.

NOTE: This file is now a thin wrapper that re-exports from the stream/ module.
The actual implementation has been decoupled into:
  - stream/utils.py: Utility functions
  - stream/response_generators.py: Response-only stream generators
  - stream/question_generators.py: Question-only stream generators
  - stream/validation.py: Validation and decision logic
  - stream/focus_mode.py: Focus mode state machine
  - stream/main.py: Main entry point (call_paixueji_stream)

All public functions are imported from stream/ and re-exported here
for backward compatibility.
"""

# Re-export everything from the stream module
from stream import (
    # Utils
    safe_print,
    clean_messages_for_api,
    prepare_messages_for_streaming,
    convert_messages_to_gemini_format,
    extract_previous_question,
    SLOW_LLM_CALL_THRESHOLD,

    # Response generators
    generate_feedback_response_stream,
    generate_explanation_response_stream,
    generate_correction_response_stream,
    generate_topic_switch_response_stream,
    generate_natural_topic_completion_stream,
    generate_explicit_switch_response_stream,

    # Question generators
    ask_introduction_question_stream,
    generate_followup_question_stream,
    generate_completion_message_stream,

    # Validation
    decide_topic_switch_with_validation,
    is_answer_reasonable,

    # Focus mode
    decide_next_focus_mode,
    handle_width_wrong_answer,
    generate_object_suggestions,
)

__all__ = [
    # Utils
    'safe_print',
    'clean_messages_for_api',
    'prepare_messages_for_streaming',
    'convert_messages_to_gemini_format',
    'extract_previous_question',
    'SLOW_LLM_CALL_THRESHOLD',

    # Response generators
    'generate_feedback_response_stream',
    'generate_explanation_response_stream',
    'generate_correction_response_stream',
    'generate_topic_switch_response_stream',
    'generate_natural_topic_completion_stream',
    'generate_explicit_switch_response_stream',

    # Question generators
    'ask_introduction_question_stream',
    'generate_followup_question_stream',
    'generate_completion_message_stream',

    # Validation
    'decide_topic_switch_with_validation',
    'is_answer_reasonable',

    # Focus mode
    'decide_next_focus_mode',
    'handle_width_wrong_answer',
    'generate_object_suggestions',
]
