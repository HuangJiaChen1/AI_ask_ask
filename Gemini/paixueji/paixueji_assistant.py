"""
Paixueji Assistant - Simplified wrapper for managing Gemini client and configuration.

This module provides a lightweight wrapper that holds the Gemini client and configuration,
while the actual streaming logic is in paixueji_stream.py.
"""
import json
import os
from enum import Enum

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
        self.correct_answer_count = 0

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
        self.guide_phase = None  # "active", "success", "exit", etc.

        # Dimension coverage tracking (from mappings_dev20_0318/)
        self.physical_dimensions: dict = {}    # {dim: {attr: value}}
        self.engagement_dimensions: dict = {}  # {dim: [topic_examples]}
        self.dimensions_covered: list = []     # dimension names visited so far

        # Multi-turn guide state (new Navigator/Driver integration)
        self.guide_turn_count = 0
        self.guide_max_turns = 6
        self.hint_given = False  # Track if hint was given at timeout
        self.last_navigation_state = None  # Last Navigator analysis result
        self.consecutive_stuck_count = 0  # Track consecutive STUCK statuses (renamed from resistance)
        self.consecutive_idk_count = 0  # Resets when child gives any non-IDK response
        self.scaffold_level = 0  # 0=original question, 1-4=progressive hint levels

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

    # =========================================================================
    # MULTI-TURN GUIDE STATE MANAGEMENT
    # =========================================================================

    def enter_guide_mode(self):
        """
        Called when entering theme guide after 4 correct answers.
        Initializes the multi-turn guide state.
        """
        self.guide_phase = "active"
        self.guide_turn_count = 0
        self.hint_given = False
        self.last_navigation_state = None
        self.consecutive_stuck_count = 0
        self.scaffold_level = 0  # Start with no scaffolding
        safe_print(f"[GUIDE] Entered guide mode for theme: {self.ibpyp_theme_name}")

    def update_navigation_state(self, nav_state: dict):
        """
        Update state after Navigator analysis.

        Args:
            nav_state: Dictionary from ThemeNavigator.analyze_turn() containing:
                - status: ON_TRACK, DRIFTING, STUCK, COMPLETED
                - strategy: ADVANCE, PIVOT, SCAFFOLD, COMPLETE
                - scaffold_level: 1-4 (only if SCAFFOLD)
                - reasoning: Brief explanation
                - instruction: Instruction for the Driver
        """
        self.guide_turn_count += 1
        self.last_navigation_state = nav_state

        # Track consecutive stuck and update scaffold level
        if nav_state.get("status") == "STUCK":
            self.consecutive_stuck_count += 1
            # Use Navigator's suggested scaffold level, or increment our own
            suggested_level = nav_state.get("scaffold_level", 0)
            if suggested_level:
                self.scaffold_level = min(suggested_level, 4)
            else:
                self.scaffold_level = min(self.scaffold_level + 1, 4)
        else:
            # Reset stuck count on progress, but keep scaffold_level for reference
            self.consecutive_stuck_count = 0

        safe_print(f"[GUIDE] Turn {self.guide_turn_count}/{self.guide_max_turns} | "
                   f"Status: {nav_state.get('status')} | Strategy: {nav_state.get('strategy')} | "
                   f"Scaffold: L{self.scaffold_level}")

    def give_hint(self):
        """Mark that a hint was given at timeout."""
        self.hint_given = True
        safe_print(f"[GUIDE] Hint given for concept: {self.key_concept}")

    def exit_guide_mode(self):
        """
        Reset guide state after completion/exit.
        Called when guide succeeds, times out, or child drops off.
        """
        self.guide_phase = None
        self.guide_turn_count = 0
        self.hint_given = False
        self.last_navigation_state = None
        self.consecutive_stuck_count = 0
        self.scaffold_level = 0
        safe_print(f"[GUIDE] Exited guide mode")

    def should_give_hint(self) -> bool:
        """Check if we should give a hint (max turns reached, no hint yet)."""
        return self.guide_turn_count >= self.guide_max_turns and not self.hint_given

    def should_exit_guide(self) -> bool:
        """Check if we should exit guide (scaffold level 4 reached twice or hint already given at max turns)."""
        # Exit if stuck at max scaffold level (gave direct answer but still stuck)
        if self.consecutive_stuck_count >= 2 and self.scaffold_level >= 4:
            return True
        if self.guide_turn_count >= self.guide_max_turns and self.hint_given:
            return True
        return False
