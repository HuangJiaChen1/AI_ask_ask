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

from wonderlens_data import (
    get_wonderlens_data,
    WonderlensData,
    PathwayData,
    PathwayStep,
    TopicOption
)


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

        # Debugging Flow Tree
        self.flow_tree = None
        self.last_navigation_state = None

        # Pathway guide mode state (new - replaces theme guide)
        self.pathway_mode = False
        self.current_pathway: Optional[PathwayData] = None
        self.current_round = 0
        self.current_topic_option: Optional[TopicOption] = None
        self.pathway_switches_count = 0  # Track topic switches within pathway

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

    def start_theme_guide(self, theme_data):
        """Enable guide mode for a specific theme.
        
        Args:
            theme_data: Theme dictionary or ID string.
        """
        if isinstance(theme_data, str):
            # Fallback/Dummy if ID passed
            theme = {
                "id": theme_data,
                "name": f"Theme {theme_data}",
                "description": "A simulated theme."
            }
        else:
            theme = theme_data

        self.guide_mode = True
        self.target_theme = theme
        self.current_plan = []
        safe_print(f"[THEME] Guide mode STARTED for: {theme['name']}")
        return True

    def stop_theme_guide(self):
        """Disable guide mode."""
        self.guide_mode = False
        self.target_theme = None
        self.current_plan = []
        safe_print(f"[THEME] Guide mode STOPPED.")

    # =========================================================================
    # PATHWAY GUIDE METHODS (New - uses wonderlens data)
    # =========================================================================

    def start_pathway_guide(self, object_name: str, age: int = None) -> bool:
        """
        Enable pathway guide mode for a specific object.

        This validates the object name against the WonderLens database and
        loads the appropriate pathway based on the child's age tier.

        Args:
            object_name: Name of the object (e.g., "Dog", "Butterfly")
            age: Optional age override. Uses self.age if not provided.

        Returns:
            True if pathway started successfully, False otherwise.
        """
        # Use stored age if not provided
        if age is None:
            age = self.age or 6  # Default to age 6

        # Get WonderLens data
        wonderlens = get_wonderlens_data()

        # Validate and get pathway
        success, pathway, error_msg = wonderlens.get_pathway_for_object_and_age(
            object_name, age
        )

        if not success:
            safe_print(f"[PATHWAY] Error: {error_msg}")
            return False

        # Initialize pathway state
        self.pathway_mode = True
        self.current_pathway = pathway
        self.current_round = 0
        self.current_topic_option = None
        self.pathway_switches_count = 0

        # Update object_name to the canonical name from pathway
        self.object_name = pathway.object_name

        # Also set legacy guide_mode for compatibility
        self.guide_mode = True
        self.target_theme = {
            "id": pathway.id,
            "name": pathway.object_name,
            "description": pathway.initial_response_template
        }

        safe_print(f"[PATHWAY] Guide mode STARTED for: {pathway.object_name} "
                   f"(tier {pathway.age_tier}, {pathway.default_rounds} rounds)")
        return True

    def stop_pathway_guide(self):
        """Disable pathway guide mode."""
        self.pathway_mode = False
        self.current_pathway = None
        self.current_round = 0
        self.current_topic_option = None
        self.pathway_switches_count = 0

        # Also clear legacy guide mode
        self.guide_mode = False
        self.target_theme = None
        safe_print(f"[PATHWAY] Guide mode STOPPED.")

    def get_current_step(self) -> Optional[PathwayStep]:
        """
        Get the current pathway step based on current_round.

        Returns:
            PathwayStep or None if not in pathway mode or round out of range.
        """
        if not self.pathway_mode or not self.current_pathway:
            return None

        # Round is 1-indexed in the data, current_round is 0-indexed here
        step_index = self.current_round
        steps = self.current_pathway.steps

        if step_index < len(steps):
            return steps[step_index]
        return None

    def advance_round(self) -> bool:
        """
        Advance to the next round in the pathway.

        Returns:
            True if advanced successfully, False if pathway is complete.
        """
        if not self.pathway_mode or not self.current_pathway:
            return False

        self.current_round += 1
        self.current_topic_option = None  # Reset topic option for new round

        # Check if pathway is complete
        if self.current_round >= len(self.current_pathway.steps):
            safe_print(f"[PATHWAY] All {len(self.current_pathway.steps)} rounds complete!")
            return False

        safe_print(f"[PATHWAY] Advanced to round {self.current_round + 1}")
        return True

    def get_pathway_progress(self) -> dict:
        """
        Get current pathway progress information.

        Returns:
            Dict with progress info or empty dict if not in pathway mode.
        """
        if not self.pathway_mode or not self.current_pathway:
            return {}

        total_rounds = len(self.current_pathway.steps)
        return {
            "current_round": self.current_round + 1,  # 1-indexed for display
            "total_rounds": total_rounds,
            "rounds_remaining": total_rounds - self.current_round - 1,
            "is_complete": self.current_round >= total_rounds,
            "pathway_id": self.current_pathway.id,
            "object_name": self.current_pathway.object_name,
            "age_tier": self.current_pathway.age_tier
        }

    def select_topic_option(self, child_input: str) -> Optional[TopicOption]:
        """
        Select the appropriate topic option for the current step.

        Checks trigger keywords first, then falls back to default.

        Args:
            child_input: The child's latest response text.

        Returns:
            TopicOption or None if not in pathway mode.
        """
        step = self.get_current_step()
        if not step:
            return None

        # Check for trigger keyword match
        triggered_option = step.find_option_by_keyword(child_input)
        if triggered_option:
            self.current_topic_option = triggered_option
            self.pathway_switches_count += 1
            safe_print(f"[PATHWAY] Triggered topic switch to: {triggered_option.attribute}")
            return triggered_option

        # Use default option
        default_option = step.get_default_option()
        if default_option:
            self.current_topic_option = default_option
            return default_option

        return None

    def check_answer(self, child_answer: str) -> dict:
        """
        Check the child's answer against the current topic option's expected answers.

        Args:
            child_answer: The child's response text.

        Returns:
            Dict with 'is_correct', 'matched_answer', and 'feedback'.
        """
        if not self.current_topic_option:
            return {
                "is_correct": None,
                "matched_answer": None,
                "feedback": ""
            }

        answer_lower = child_answer.lower().strip()
        expected = self.current_topic_option.expected_answers

        for exp_answer in expected:
            if exp_answer.lower() in answer_lower or answer_lower in exp_answer.lower():
                return {
                    "is_correct": True,
                    "matched_answer": exp_answer,
                    "feedback": self.current_topic_option.correct_feedback
                }

        return {
            "is_correct": False,
            "matched_answer": None,
            "feedback": self.current_topic_option.hint
        }

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
                model=self.config.get("model", "gemini-2.0-flash-exp"),
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

        # Reset pathway guide state
        self.pathway_mode = False
        self.current_pathway = None
        self.current_round = 0
        self.current_topic_option = None
        self.pathway_switches_count = 0

        # Reset legacy guide mode
        self.guide_mode = False
        self.target_theme = None
