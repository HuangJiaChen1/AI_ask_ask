"""
Paixueji Assistant - Simplified wrapper for managing Gemini client and configuration.

This module provides a lightweight wrapper that holds the Gemini client and configuration,
while the actual streaming logic is in paixueji_stream.py.
"""
import json
import os
from enum import Enum
from typing import Optional

from google import genai
from google.genai.types import HttpOptions


def safe_print(message):
    """Print message with fallback for encoding errors."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('ascii', 'replace').decode('ascii'))


class ConversationState(Enum):
    """Tracks the current state of the Paixueji conversation."""
    INTRODUCTION = "introduction"
    ASKING_QUESTION = "asking_question"


class PaixuejiAssistant:
    """
    A lightweight wrapper that manages Gemini client, configuration,
    and conversation state for the Paixueji assistant.

    All streaming logic has been moved to paixueji_stream.py.
    """

    def __init__(self, config_path="config.json", age_prompts_path="age_prompts.json", client=None):
        """Initialize the assistant with configuration and Gemini client."""
        # Resolve paths relative to this file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isabs(config_path):
            config_path = os.path.join(base_dir, config_path)
        if not os.path.isabs(age_prompts_path):
            age_prompts_path = os.path.join(base_dir, age_prompts_path)

        self.config = self._load_config(config_path)
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.age = None

        # Paixueji-specific fields
        self.object_name = None
        self.surface_object_name = None
        self.visible_object_name = None
        self.anchor_object_name = None
        self.anchor_status = None
        self.anchor_relation = None
        self.anchor_confidence_band = None
        self.anchor_confirmation_needed = False
        self.learning_anchor_active = False
        self.bridge_attempt_count = 0
        self.suppressed_anchor_names = set()
        self.correct_answer_count = 0
        self.session_resolution_debug = None
        self.last_bridge_debug = None

        # IB PYP Theme Classification fields
        self.ibpyp_theme = None  # Theme ID (e.g., "Category_Nature_And_Physics")
        self.ibpyp_theme_name = None  # Theme name (e.g., "How the World Works")
        self.ibpyp_theme_reason = None  # Classification reasoning
        self.fallback_theme_id = None
        self.fallback_theme_name = None
        self.fallback_theme_reason = None
        self.key_concept = None
        self.bridge_question = None
        self.category_prompt = None  # Formatted YAML anchor block for {category_prompt} slot

        # Dimension coverage tracking (from mappings_dev20_0318/)
        self.physical_dimensions: dict = {}    # {dim: {attr: value}}
        self.engagement_dimensions: dict = {}  # {dim: [topic_examples]}
        self.dimensions_covered: list = []     # dimension names visited so far
        self.active_dimension: Optional[str] = None
        self.active_dimension_turn_count: int = 0

        # Ordinary chat struggle tracking
        self.consecutive_struggle_count = 0  # Resets on any non-struggling response (IDK or wrong)

        # Initialize Google Gemini client
        if client:
            self.client = client
        else:
            self.client = genai.Client(
                vertexai=True,
                project=self.config["project"],
                location=self.config["location"],
                http_options=HttpOptions(api_version="v1")
            )

        # Load age prompts
        self.age_prompts = self._load_age_prompts(age_prompts_path)

        # Load prompts
        import paixueji_prompts
        self.prompts = paixueji_prompts.get_prompts()

    def load_dimension_data(self, object_name: str):
        """Load age-tiered dimension map from mappings_dev20_0318/."""
        from stream.db_loader import load_physical_dimensions, load_engagement_dimensions
        self.physical_dimensions = load_physical_dimensions(object_name, self.age or 6)
        self.engagement_dimensions = load_engagement_dimensions(object_name, self.age or 6)
        self.dimensions_covered = []
        self.active_dimension = None
        self.active_dimension_turn_count = 0

    def load_object_context_from_yaml(self, object_name: str):
        """
        Load object-derived concept context and fallback theme from YAML.
        The fallback theme is retained internally; the authoritative guide theme
        is set later from conversation history when guide mode starts.
        """
        from graph_lookup import classify_object_yaml

        result = classify_object_yaml(object_name, self.age or 6)
        self.fallback_theme_id = result["theme_id"]
        self.fallback_theme_name = result["theme_name"]
        self.fallback_theme_reason = result["theme_reasoning"]
        self.key_concept = result["key_concept"]
        self.bridge_question = result["bridge_question"]
        self.category_prompt = result["category_prompt"]
        return result

    def apply_fallback_theme(self):
        """Promote the stored object-derived fallback theme to the active theme."""
        self.ibpyp_theme = self.fallback_theme_id
        self.ibpyp_theme_name = self.fallback_theme_name
        self.ibpyp_theme_reason = self.fallback_theme_reason

    def clear_active_theme(self):
        """Clear the active guide theme until conversation-based analysis runs."""
        self.ibpyp_theme = None
        self.ibpyp_theme_name = None
        self.ibpyp_theme_reason = None

    def apply_resolution(self, resolution):
        """Apply an ObjectResolutionResult to session-visible state."""
        self.surface_object_name = resolution.surface_object_name
        self.visible_object_name = resolution.visible_object_name
        self.object_name = resolution.visible_object_name
        self.anchor_object_name = resolution.anchor_object_name
        self.anchor_status = resolution.anchor_status
        self.anchor_relation = resolution.anchor_relation
        self.anchor_confidence_band = resolution.anchor_confidence_band
        self.anchor_confirmation_needed = resolution.anchor_confirmation_needed
        self.learning_anchor_active = resolution.learning_anchor_active
        self.bridge_attempt_count = 0
        self.session_resolution_debug = {
            "surface_object_name": resolution.surface_object_name,
            "visible_object_name": resolution.visible_object_name,
            "anchor_object_name": resolution.anchor_object_name,
            "anchor_status": resolution.anchor_status,
            "anchor_relation": resolution.anchor_relation,
            "anchor_confidence_band": resolution.anchor_confidence_band,
            "learning_anchor_active": resolution.learning_anchor_active,
        }
        if resolution.resolution_debug:
            self.session_resolution_debug.update(resolution.resolution_debug)

    def activate_anchor_topic(self, anchor_name: str):
        """Make the anchor object the visible/learning topic and reset progress."""
        anchor_name = (anchor_name or "").strip().lower()
        self.object_name = anchor_name
        self.visible_object_name = anchor_name
        self.anchor_object_name = anchor_name
        self.anchor_confirmation_needed = False
        self.learning_anchor_active = True
        self.bridge_attempt_count = 0
        self.correct_answer_count = 0

    def suppress_anchor(self, anchor_name: str):
        """Remember that the current surface topic should not auto-bridge to this anchor."""
        anchor_name = (anchor_name or "").strip().lower()
        if anchor_name:
            self.suppressed_anchor_names.add(anchor_name)
        self.anchor_confirmation_needed = False

    def reset_bridge_state(self):
        """Clear bridge attempts for the current topic."""
        self.bridge_attempt_count = 0

    def mark_bridge_attempt_emitted(self):
        """Record that a pre-anchor bridge prompt has been shown."""
        self.bridge_attempt_count += 1

    def set_last_bridge_debug(self, debug_dict):
        self.last_bridge_debug = debug_dict

    def _load_config(self, config_path):
        """Load configuration from JSON file."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            config = json.load(f)

        return config

    def _load_age_prompts(self, age_prompts_path):
        """Load age-based prompts from JSON file."""
        if not os.path.exists(age_prompts_path):
            safe_print(f"[WARNING] Age prompts file not found: {age_prompts_path}")
            return None

        with open(age_prompts_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_age_prompt(self, age):
        """Get the appropriate age-based prompt."""
        if not self.age_prompts:
            return ""

        age_groups = self.age_prompts.get('age_groups', {})

        if 3 <= age <= 4:
            return age_groups.get('3-4', {}).get('prompt', '')
        elif 5 <= age <= 6:
            return age_groups.get('5-6', {}).get('prompt', '')
        elif 7 <= age <= 8:
            return age_groups.get('7-8', {}).get('prompt', '')
        else:
            return age_groups.get('5-6', {}).get('prompt', '')

    def increment_correct_answers(self):
        """
        Increment the correct answer count.
        
        Returns:
            bool: Always False (conversation never auto-completes)
        """
        self.correct_answer_count += 1
        return False
