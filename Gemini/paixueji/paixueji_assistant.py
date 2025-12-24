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
    COMPLETION = "completion"


class PaixuejiAssistant:
    """
    A lightweight wrapper that manages Gemini client, configuration,
    and conversation state for the Paixueji assistant.

    All streaming logic has been moved to paixueji_stream.py.
    """

    def __init__(self, config_path="config.json", age_prompts_path="age_prompts.json", object_prompts_path="object_prompts.json"):
        """Initialize the assistant with configuration and Gemini client."""
        self.config = self._load_config(config_path)
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.age = None

        # Paixueji-specific fields
        self.object_name = None
        self.level1_category = None
        self.level2_category = None
        self.correct_answer_count = 0

        # Set up authentication if credentials file is specified in environment
        credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if credentials_path and not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_SET'):
            # Ensure the environment variable is set for the Google client
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
            os.environ['GOOGLE_APPLICATION_CREDENTIALS_SET'] = '1'

        # Initialize Google Gemini client
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

    def get_category_prompt(self, level1, level2):
        """
        Get the appropriate category-based prompt with fallback logic.

        Tries level2 first (most specific), then level1, then default.
        """
        DEFAULT_FALLBACK = "Ask questions about this object's appearance, properties, uses, and context. Encourage observation and description."

        if not self.object_prompts:
            return DEFAULT_FALLBACK

        # Try level2 first (most specific)
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
            bool: True if conversation is complete (4 answers), False otherwise
        """
        self.correct_answer_count += 1
        return self.correct_answer_count >= 4

    def get_conversation_history(self):
        """Get the full conversation history."""
        return self.conversation_history

    def reset(self):
        """Reset the conversation."""
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.age = None

        # Reset Paixueji-specific fields
        self.object_name = None
        self.level1_category = None
        self.level2_category = None
        self.correct_answer_count = 0
