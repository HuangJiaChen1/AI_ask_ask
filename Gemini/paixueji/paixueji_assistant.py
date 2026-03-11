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
    AWAITING_ANSWER = "awaiting_answer"
    AWAITING_TOPIC_SELECTION = "awaiting_topic_selection"
    COMPLETION = "completion"


class PaixuejiAssistant:
    """
    A lightweight wrapper that manages Gemini client, configuration,
    and conversation state for the Paixueji assistant.

    All streaming logic has been moved to paixueji_stream.py.
    """

    def __init__(self, config_path="config.json", age_prompts_path="age_prompts.json", object_prompts_path="object_prompts.json", client=None):
        """Initialize the assistant with configuration and Gemini client."""
        # Resolve paths relative to this file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isabs(config_path):
            config_path = os.path.join(base_dir, config_path)
        if not os.path.isabs(age_prompts_path):
            age_prompts_path = os.path.join(base_dir, age_prompts_path)
        if not os.path.isabs(object_prompts_path):
            object_prompts_path = os.path.join(base_dir, object_prompts_path)

        self.config = self._load_config(config_path)
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.age = None

        # Paixueji-specific fields
        self.object_name = None
        self.level1_category = None
        self.level2_category = None
        self.level3_category = None
        self.correct_answer_count = 0

        # Theme Guide fields
        self.guide_mode = False
        self.target_theme = None
        self.current_plan = []
        self.themes = []
        self._load_themes()

        # IB PYP Theme Classification fields
        self.ibpyp_theme = None  # Theme ID (e.g., "Category_Nature_And_Physics")
        self.ibpyp_theme_name = None  # Theme name (e.g., "How the World Works")
        self.ibpyp_theme_reason = None  # Classification reasoning
        self.key_concept = None
        self.bridge_question = None
        self.guide_phase = None  # "active", "success", "exit", etc.

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

        # Load object/category prompts
        self.object_prompts = self._load_object_prompts(object_prompts_path)

        # Load prompts
        import paixueji_prompts
        self.prompts = paixueji_prompts.get_prompts()

    def _load_themes(self):
        """Load themes from themes.json."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        themes_path = os.path.join(base_dir, "themes.json")
        if os.path.exists(themes_path):
            try:
                with open(themes_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Handle new structure with "themes" key
                    if isinstance(data, dict) and "themes" in data:
                        self.themes = data["themes"]
                    else:
                        self.themes = data
                safe_print(f"[THEME] Loaded {len(self.themes)} themes.")
            except Exception as e:
                safe_print(f"[ERROR] Failed to load themes: {e}")

    def classify_theme_background(self, object_name: str):
        """
        Trigger background IB PYP theme classification for an object.
        Updates self.ibpyp_theme, ibpyp_theme_name, ibpyp_theme_reason when complete.
        """
        import threading
        from theme_classifier import classify_object_to_theme

        def _classify():
            # Create a localized client copy or usage might be tricky if client isn't thread-safe?
            # Gemini client should be thread-safe for generation.
            result = classify_object_to_theme(
                object_name=object_name,
                client=self.client,
                config=self.config
            )
            if result:
                self.ibpyp_theme = result.theme_id
                self.ibpyp_theme_name = result.theme_name
                self.ibpyp_theme_reason = result.reason
                self.key_concept = result.key_concept
                self.bridge_question = result.bridge_question
                safe_print(f"[THEME_CLASSIFY] Background classification complete: {result.theme_id} | Concept: {result.key_concept}")

        # Fire and forget thread
        thread = threading.Thread(target=_classify, daemon=True)
        thread.start()

    def start_theme_guide(self, theme_id):
        """Enable guide mode for a specific theme."""
        theme = next((t for t in self.themes if t['id'] == theme_id), None)
        if theme:
            self.guide_mode = True
            self.target_theme = theme
            self.current_plan = []
            safe_print(f"[THEME] Guide mode STARTED for: {theme['name']}")
            return True
        return False

    def stop_theme_guide(self):
        """Disable guide mode."""
        self.guide_mode = False
        self.target_theme = None
        self.current_plan = []
        safe_print(f"[THEME] Guide mode STOPPED.")

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

    def _load_object_prompts(self, object_prompts_path):
        """Load object/category prompts from JSON file."""
        if not os.path.exists(object_prompts_path):
            safe_print(f"[WARNING] Object prompts file not found: {object_prompts_path}")
            return None

        with open(object_prompts_path, 'r', encoding='utf-8') as f:
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

    def get_category_prompt(self, level1, level2, level3):
        """
        Get the appropriate category-based prompt with fallback logic.

        Uses the most specific category available (level3 → level2 → level1 → default).
        """
        DEFAULT_FALLBACK = "Ask questions about this object's appearance, properties, uses, and context. Encourage observation and description."

        if not self.object_prompts:
            return DEFAULT_FALLBACK

        # Try level3 first (most specific)
        if level3:
            level3_data = self.object_prompts.get('level3_categories', {}).get(level3)
            if level3_data:
                return level3_data.get('prompt', '')

        # Fall back to level2
        if level2:
            level2_data = self.object_prompts.get('level2_categories', {}).get(level2)
            if level2_data:
                return level2_data.get('prompt', '')

        # Fall back to level1
        if level1:
            level1_data = self.object_prompts.get('level1_categories', {}).get(level1)
            if level1_data:
                return level1_data.get('prompt', '')

        # Final fallback
        return DEFAULT_FALLBACK

    def increment_correct_answers(self):
        """
        Increment the correct answer count.
        
        Returns:
            bool: Always False (conversation never auto-completes)
        """
        self.correct_answer_count += 1
        return False

    def get_conversation_history(self):
        """Get the full conversation history."""
        return self.conversation_history

    def classify_object_sync(self, object_name):
        """
        Classify an object into level2_category and derive level1_category.

        This method is designed to be called in a background thread to avoid
        blocking the main response stream. It updates the assistant's category
        state for subsequent conversation turns.

        Args:
            object_name (str): Name of the object to classify
        """
        try:
            safe_print(f"[CLASSIFY] Starting classification for: {object_name}")

            # Get available level2 categories from object_prompts
            if not self.object_prompts or 'level2_categories' not in self.object_prompts:
                safe_print(f"[CLASSIFY] No object_prompts available, setting categories to None")
                self.level1_category = None
                self.level2_category = None
                self.level3_category = None
                return

            level2_categories = self.object_prompts['level2_categories']

            # Build categories list for prompt
            categories_list = "\n".join([
                f"- {key}: {data.get('prompt', '')[:100]}..."
                for key, data in level2_categories.items()
            ])

            # Get classification prompt template
            classification_prompt = self.prompts['classification_prompt'].format(
                object_name=object_name,
                categories_list=categories_list
            )

            # Call Gemini to classify
            safe_print(f"[CLASSIFY] Calling Gemini for classification...")
            response = self.client.models.generate_content(
                model=self.config["model_name"],
                contents=classification_prompt,
                config={
                    "temperature": 0.1,  # Low temperature for consistent classification
                    "max_output_tokens": 50  # Short response expected
                }
            )

            # Extract classification result
            classified_category = response.text.strip().lower()
            safe_print(f"[CLASSIFY] Raw response: {classified_category}")

            # Check if it's a valid level2 category
            if classified_category in level2_categories:
                # Update level2_category
                self.level2_category = classified_category

                # Derive level1_category from parent relationship
                self.level1_category = level2_categories[classified_category].get('parent')

                # Reset level3_category
                self.level3_category = None

                safe_print(f"[CLASSIFY] SUCCESS: {object_name} -> level2={self.level2_category}, level1={self.level1_category}")
            else:
                # No match or "none" response - set to None (fallback)
                safe_print(f"[CLASSIFY] No match found for {object_name}, setting categories to None")
                self.level1_category = None
                self.level2_category = None
                self.level3_category = None

        except Exception as e:
            safe_print(f"[CLASSIFY] ERROR during classification: {e}")
            import traceback
            traceback.print_exc()
            # On error, set categories to None (fallback)
            self.level1_category = None
            self.level2_category = None
            self.level3_category = None

    def reset_object_state(self, new_object_name: str):
        """
        Reset state when switching to a new object.

        Args:
            new_object_name: Name of the new object to switch to
        """
        self.object_name = new_object_name
        # Reset guide state for new object
        self.exit_guide_mode()

    def reset(self):
        """Reset the conversation."""
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.age = None

        # Reset Paixueji-specific fields
        self.object_name = None
        self.level1_category = None
        self.level2_category = None
        self.level3_category = None
        self.correct_answer_count = 0

        # Reset guide state
        self.exit_guide_mode()

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

    def get_current_scaffold_level(self) -> int:
        """Get the current scaffolding level for the Navigator."""
        return self.scaffold_level