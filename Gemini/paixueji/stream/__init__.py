"""
Paixueji Stream Module

This module provides streaming functionality for the Paixueji assistant.
It is organized into several sub-modules:

- utils: Utility functions for message preparation and format conversion
- response_generators: Intent-based response generators (9-node architecture)
- question_generators: Question-only stream generators (intro path + followup)
- validation: Intent classification logic
- fun_fact: Grounded fun fact generation
- fun_fact: Grounded fun fact generation

All public functions are re-exported from this module for backward compatibility.
"""

# Utilities
from .utils import (
    safe_print,
    clean_messages_for_api,
    prepare_messages_for_streaming,
    convert_messages_to_gemini_format,
    extract_previous_response,
    select_hook_type,
    SLOW_LLM_CALL_THRESHOLD
)

# Response generators (intent-based, 9-node architecture)
from .response_generators import (
    generate_classification_fallback_stream,
    generate_intent_response_stream,
    generate_topic_switch_response_stream,
)

# Question generators (intro path + followup)
from .question_generators import (
    ask_introduction_question_stream,
    ask_followup_question_stream,
)

# Intent classification (replaces decide_topic_switch_with_validation)
from .validation import (
    classify_intent,
    classify_dimension,
    map_response_to_kb_item,
)

# Fun fact (grounded)
from .fun_fact import generate_fun_fact

__all__ = [
    # Utils
    'safe_print',
    'clean_messages_for_api',
    'prepare_messages_for_streaming',
    'convert_messages_to_gemini_format',
    'extract_previous_response',
    'select_hook_type',
    'SLOW_LLM_CALL_THRESHOLD',

    # Response generators
    'generate_classification_fallback_stream',
    'generate_intent_response_stream',
    'generate_topic_switch_response_stream',

    # Question generators (intro path + followup)
    'ask_introduction_question_stream',
    'ask_followup_question_stream',

    # Intent classification
    'classify_intent',
    'classify_dimension',
    'map_response_to_kb_item',

    # Fun fact (grounded)
    'generate_fun_fact',
]
