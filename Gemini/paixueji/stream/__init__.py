"""
Paixueji Stream Module

This module provides streaming functionality for the Paixueji assistant.
It is organized into several sub-modules:

- utils: Utility functions for message preparation and format conversion
- response_generators: Response-only stream generators (Part 1 of dual-parallel)
- question_generators: Question-only stream generators (Part 2 of dual-parallel)
- validation: Validation and decision logic
- focus_mode: Focus mode state machine logic
- main: Main entry point (call_paixueji_stream)

All public functions are re-exported from this module for backward compatibility.
"""

# Utilities
from .utils import (
    safe_print,
    clean_messages_for_api,
    prepare_messages_for_streaming,
    convert_messages_to_gemini_format,
    extract_previous_question,
    SLOW_LLM_CALL_THRESHOLD
)

# Response generators (Part 1 of dual-parallel)
from .response_generators import (
    generate_feedback_response_stream,
    generate_explanation_response_stream,
    generate_correction_response_stream,
    generate_topic_switch_response_stream,
    generate_child_question_response_stream,
    generate_natural_topic_completion_stream,
    generate_explicit_switch_response_stream
)

# Question generators (Part 2 of dual-parallel)
from .question_generators import (
    ask_introduction_question_stream,
    generate_followup_question_stream,
    generate_completion_message_stream
)

# Validation
from .validation import (
    decide_topic_switch_with_validation,
    is_answer_reasonable
)

# Focus mode (WIDTH mode removed, DEPTH only)
from .focus_mode import (
    decide_next_focus_mode,
    generate_object_suggestions
)

# Fun fact (grounded)
from .fun_fact import generate_fun_fact

# Guide hint (LLM-generated)
from .guide_hint import generate_guide_hint

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
    'generate_child_question_response_stream',
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
    'generate_object_suggestions',

    # Fun fact (grounded)
    'generate_fun_fact',

    # Guide hint (LLM-generated)
    'generate_guide_hint',
]
