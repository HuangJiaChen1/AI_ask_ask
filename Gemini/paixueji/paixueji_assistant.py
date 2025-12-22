"""
Paixueji Assistant - Manages Gemini client and configuration for object-based learning.

This module provides a wrapper that holds the Gemini client, configuration,
and object learning state, while the actual streaming logic is in paixueji_stream.py.
"""
import json
import os
import random

from google import genai
from google.genai.types import HttpOptions


def safe_print(message):
    """Print message with fallback for encoding errors."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('ascii', 'replace').decode('ascii'))


class PaixuejiAssistant:
    """
    A wrapper that manages Gemini client, configuration,
    and object learning state for the Paixueji assistant.

    All streaming logic has been moved to paixueji_stream.py.
    """

    def __init__(self, config_path="config.json", object_prompts_path="object_prompts.json"):
        """Initialize the assistant with configuration and Gemini client."""
        self.config = self._load_config(config_path)
        self.conversation_history = []
        self.age = None

        # Object learning state
        self.current_object = None
        self.asked_aspects = []  # Track which aspects we've covered
        self.question_count = 0  # Number of questions asked

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

        # Load object prompts
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

    def _load_object_prompts(self, object_prompts_path):
        """Load object-based prompts from JSON file."""
        if not os.path.exists(object_prompts_path):
            safe_print(f"[WARNING] Object prompts file not found: {object_prompts_path}")
            return None

        with open(object_prompts_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_age_prompt(self, age):
        """Get the appropriate age-based prompt for object learning."""
        if not self.object_prompts:
            return ""

        age_groups = self.object_prompts.get('age_groups', {})

        if 3 <= age <= 4:
            return age_groups.get('3-4', {}).get('prompt', '')
        elif 5 <= age <= 6:
            return age_groups.get('5-6', {}).get('prompt', '')
        elif 7 <= age <= 8:
            return age_groups.get('7-8', {}).get('prompt', '')
        else:
            # Default to 5-6 for ages outside range
            return age_groups.get('5-6', {}).get('prompt', '')

    def get_aspects_priority(self, age):
        """Get the priority order of aspects for the given age."""
        if not self.object_prompts:
            return ["appearance", "function", "location", "parts"]

        age_groups = self.object_prompts.get('age_groups', {})

        if 3 <= age <= 4:
            return age_groups.get('3-4', {}).get('aspects_priority', ["appearance", "location", "function"])
        elif 5 <= age <= 6:
            return age_groups.get('5-6', {}).get('aspects_priority', ["function", "parts", "behavior", "appearance"])
        elif 7 <= age <= 8:
            return age_groups.get('7-8', {}).get('aspects_priority', ["function", "comparison", "origin", "lifecycle"])
        else:
            return age_groups.get('5-6', {}).get('aspects_priority', ["function", "parts", "behavior", "appearance"])

    def get_next_aspect(self):
        """
        Select the next aspect to explore based on:
        1. Age-appropriate priority
        2. What hasn't been asked yet

        Returns the next aspect to explore (str).
        """
        # Get all available aspects
        all_aspects = list(self.object_prompts.get('aspects', {}).keys())

        # Get age-appropriate priority
        priority = self.get_aspects_priority(self.age or 6)

        # Find aspects not yet asked
        unasked = [asp for asp in priority if asp not in self.asked_aspects]

        if unasked:
            # Return first unasked aspect from priority list
            return unasked[0]
        else:
            # All aspects covered - check if there are other aspects not in priority
            other_unasked = [asp for asp in all_aspects if asp not in self.asked_aspects]
            if other_unasked:
                return other_unasked[0]
            else:
                # All aspects covered - reset and start over with priority
                self.asked_aspects = []
                return priority[0] if priority else all_aspects[0]

    def get_conversation_history(self):
        """Get the full conversation history."""
        return self.conversation_history

    def reset(self):
        """Reset the conversation."""
        self.conversation_history = []
        self.current_object = None
        self.asked_aspects = []
        self.question_count = 0
        self.age = None
