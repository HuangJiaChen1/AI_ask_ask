"""
Child Simulator - Generates realistic child responses for automated testing.

Replaces the manual process of playing with the chatbot by simulating children
of different ages and personality profiles (engaged, confused, distracted, etc.).

Each profile has a carefully crafted system prompt that produces age-appropriate
responses matching that personality type.
"""
import json
from google.genai.types import GenerateContentConfig
from loguru import logger


class ChildSimulator:
    """Simulates a child of a given age and personality profile using LLM."""

    def __init__(self, client, config, age: int, profile: dict, object_name: str):
        """
        Initialize the child simulator.

        Args:
            client: Gemini client instance
            config: App config dict (model_name, etc.)
            age: Child's age (3-8)
            profile: Profile dict with 'id', 'name', 'system_prompt' fields
            object_name: The object being discussed
        """
        self.client = client
        self.config = config
        self.age = age
        self.profile = profile
        self.object_name = object_name

        # Build the child's system prompt from template
        self.system_prompt = profile["system_prompt"].format(
            age=age,
            object_name=object_name
        )

    def generate_response(self, chatbot_message: str, conversation_so_far: list[str]) -> str:
        """
        Generate a child's response to a chatbot message.

        Args:
            chatbot_message: The chatbot's most recent message
            conversation_so_far: List of previous chatbot messages (for context)

        Returns:
            The simulated child's response string
        """
        # Build conversation context (last 3 exchanges max to keep it focused)
        context_messages = []
        recent = conversation_so_far[-3:] if len(conversation_so_far) > 3 else conversation_so_far
        for i, msg in enumerate(recent):
            context_messages.append(f"AI said: {msg}")

        context_text = "\n".join(context_messages) if context_messages else "(This is the start of the conversation)"

        prompt = (
            f"{self.system_prompt}\n\n"
            f"CONVERSATION SO FAR:\n{context_text}\n\n"
            f"THE AI JUST SAID:\n\"{chatbot_message}\"\n\n"
            f"YOUR RESPONSE (as a {self.age}-year-old child):"
        )

        settings = self.config.get("feedback_settings", {})
        temperature = settings.get("simulator_temperature", 0.8)
        max_tokens = settings.get("simulator_max_tokens", 80)

        try:
            response = self.client.models.generate_content(
                model=self.config["model_name"],
                contents=prompt,
                config=GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )
            result = response.text.strip()
            # Remove quotes if the model wraps the response in them
            if result.startswith('"') and result.endswith('"'):
                result = result[1:-1]
            logger.debug(f"[CHILD_SIM] age={self.age}, profile={self.profile['id']}: \"{result}\"")
            return result

        except Exception as e:
            logger.error(f"[CHILD_SIM] Error generating response: {e}")
            # Fallback responses by profile type
            fallbacks = {
                "engaged_correct": "Yes!",
                "engaged_wrong": "I think so!",
                "dont_know": "I don't know",
                "off_topic": "Look at that!"
            }
            return fallbacks.get(self.profile["id"], "Hmm")
