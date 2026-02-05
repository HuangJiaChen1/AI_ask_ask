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

    def __init__(self, config_path="config.json", age_prompts_path="age_prompts.json", object_prompts_path="object_prompts.json", system_managed=False, client=None):
        """Initialize the assistant with configuration and Gemini client."""
        self.config = self._load_config(config_path)
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.age = None
        self.character = None

        # Paixueji-specific fields
        self.object_name = None
        self.level1_category = None
        self.level2_category = None
        self.level3_category = None
        self.correct_answer_count = 0

        # System-managed focus mode tracking
        self.system_managed_focus = False
        self.current_focus_mode = 'depth'
        self.depth_questions_count = 0
        self.width_wrong_count = 0
        self.width_categories_tried = []  # ['color', 'shape', 'category']
        self.depth_target = 0  # 4 or 5, randomly chosen per object

        # Theme Guide fields
        self.guide_mode = False
        self.target_theme = None
        self.current_plan = []
        self.themes = []
        self._load_themes()

        # Debugging Flow Tree
        self.flow_tree = None

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

        # Initialize system-managed focus mode
        import random
        self.system_managed_focus = system_managed
        if system_managed:
            self.current_focus_mode = 'depth'
            self.depth_target = random.randint(4, 5)
            self.depth_questions_count = 0
            self.width_wrong_count = 0
            self.width_categories_tried = []

    def _load_themes(self):
        """Load themes from themes.json."""
        themes_path = "themes.json"
        if os.path.exists(themes_path):
            try:
                with open(themes_path, 'r', encoding='utf-8') as f:
                    self.themes = json.load(f)
                safe_print(f"[THEME] Loaded {len(self.themes)} themes.")
            except Exception as e:
                safe_print(f"[ERROR] Failed to load themes: {e}")

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

    def init_flow_tree(self, session_id, age, object_name, character, focus_mode):
        """
        Initialize conversation flow tree for debugging.

        Args:
            session_id: Session ID for this conversation
            age: Child's age
            object_name: Initial object being discussed
            character: Conversation character (Teacher/Buddy)
            focus_mode: Focus mode (depth, width, etc.)
        """
        from conversation_tree import ConversationFlowTree
        from datetime import datetime

        self.flow_tree = ConversationFlowTree(
            session_id=session_id,
            metadata={
                "created_at": datetime.now().isoformat(),
                "initial_object": object_name,
                "child_age": age,
                "character": character,
                "initial_focus": focus_mode
            }
        )

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

    def get_character_prompt(self, character_key):
        """Get the appropriate character-based prompt."""
        if not character_key:
            return ""
        
        character_prompts = self.prompts.get('character_prompts', {})
        return character_prompts.get(character_key, "")

    def get_focus_prompt(self, focus_mode):
        """Get the appropriate focus strategy prompt."""
        if not focus_mode:
            return ""
        
        focus_prompts = self.prompts.get('focus_prompts', {})
        prompt = focus_prompts.get(focus_mode, "")
        
        # Format object name into prompt if available
        if self.object_name and "{object_name}" in prompt:
            prompt = prompt.format(object_name=self.object_name)
            
        return prompt

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
                model=self.config.get("model_name", "gemini-2.5-flash-lite"),
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
        Reset state when switching to a new object in system-managed mode.

        Args:
            new_object_name: Name of the new object to switch to
        """
        import random
        self.object_name = new_object_name
        self.depth_questions_count = 0
        self.width_wrong_count = 0
        self.width_categories_tried = []
        self.current_focus_mode = 'depth'
        self.depth_target = random.randint(4, 5)

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
