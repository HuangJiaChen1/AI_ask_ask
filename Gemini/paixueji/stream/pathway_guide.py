"""
Pathway Guide module using Multi-Agent Controller Architecture (Navigator & Driver).

This module implements a "System 2" (Navigator) and "System 1" (Driver) approach
to structured pathway-based conversational guidance using WonderLens educational data.

The PathwayNavigator analyzes child responses and determines navigation strategy.
The PathwayDriver generates natural language responses following the pathway structure.
"""
import json
from typing import AsyncGenerator, Optional, Dict, Any, List
from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from schema import TokenUsage
from .utils import convert_messages_to_gemini_format
from wonderlens_data import (
    PathwayData,
    PathwayStep,
    TopicOption
)


class PathwayNavigator:
    """
    The 'Navigator' (System 2): Analyzes the conversation and plans the next move
    based on the structured pathway data.

    Uses pathway's expected_answers for answer checking and trigger_keywords for
    topic switching decisions.
    """

    def __init__(
        self,
        client: genai.Client,
        config: Dict[str, Any],
        model_override: Optional[str] = None
    ):
        self.client = client
        self.config = config
        # Use a faster model for navigation logic if available
        self.model_name = model_override or config.get("navigator_model") or config.get("model_name")

    def analyze_turn(
        self,
        history: List[Dict[str, Any]],
        user_input: str,
        pathway: PathwayData,
        current_step: PathwayStep,
        current_option: Optional[TopicOption],
        current_round: int,
        age: int
    ) -> Dict[str, Any]:
        """
        Analyze the current turn and generate a navigation instruction.

        Uses the pathway's structured data (expected_answers, hints, trigger_keywords)
        to make informed decisions.

        Args:
            history: Conversation history
            user_input: Child's latest input
            pathway: Current PathwayData being followed
            current_step: Current PathwayStep
            current_option: Currently selected TopicOption
            current_round: Current round number (0-indexed)
            age: Child's age

        Returns:
            Navigation plan dict with status, strategy, instruction, etc.
        """
        # Get the topic option to use
        option = current_option or current_step.get_default_option()
        if not option:
            return self._fallback_plan(user_input)

        # Check for trigger keyword to switch topic
        triggered_option = current_step.find_option_by_keyword(user_input)
        if triggered_option and triggered_option != option:
            return {
                "status": "TOPIC_SWITCH",
                "strategy": "SWITCH",
                "reasoning": f"Child mentioned keyword related to {triggered_option.attribute}",
                "instruction": f"Acknowledge their interest in {triggered_option.attribute}, then ask: {triggered_option.question}",
                "new_topic_option": triggered_option,
                "should_advance": False
            }

        # Check answer against expected answers
        answer_lower = user_input.lower().strip()
        is_correct = False
        matched_answer = None

        for expected in option.expected_answers:
            if expected.lower() in answer_lower or answer_lower in expected.lower():
                is_correct = True
                matched_answer = expected
                break

        # Determine strategy based on answer correctness
        total_rounds = len(pathway.steps)
        is_last_round = current_round >= total_rounds - 1

        if is_correct:
            if is_last_round:
                return {
                    "status": "COMPLETED",
                    "strategy": "COMPLETE",
                    "reasoning": "Correct answer on final round - pathway complete",
                    "instruction": f"Celebrate their correct answer: '{option.correct_feedback}' Then wrap up the conversation about {pathway.object_name} warmly.",
                    "feedback": option.correct_feedback,
                    "should_advance": False
                }
            else:
                return {
                    "status": "ON_TRACK",
                    "strategy": "ADVANCE",
                    "reasoning": f"Correct answer (matched: '{matched_answer}')",
                    "instruction": f"Respond with: '{option.correct_feedback}' Then transition to the next question.",
                    "feedback": option.correct_feedback,
                    "should_advance": True
                }
        else:
            # Check if child is drifting (talking about something else)
            is_drifting = self._check_drift(user_input, pathway, option)

            if is_drifting:
                return {
                    "status": "DRIFTING",
                    "strategy": "PIVOT",
                    "reasoning": "Child is talking about something else",
                    "instruction": f"Acknowledge what they said warmly, then bridge back to the question about {option.attribute}. Give hint: '{option.hint}'",
                    "hint": option.hint,
                    "should_advance": False
                }
            else:
                return {
                    "status": "STRUGGLING",
                    "strategy": "HINT",
                    "reasoning": "Answer not in expected list, child may need help",
                    "instruction": f"Encourage them and provide a hint: '{option.hint}'",
                    "hint": option.hint,
                    "should_advance": False
                }

    def _check_drift(
        self,
        user_input: str,
        pathway: PathwayData,
        current_option: TopicOption
    ) -> bool:
        """Check if the child's response indicates they're drifting off topic."""
        input_lower = user_input.lower()
        object_name_lower = pathway.object_name.lower()

        # If they mention the object name, probably not drifting
        if object_name_lower in input_lower:
            return False

        # If their response is very short, probably trying to answer
        if len(input_lower.split()) <= 3:
            return False

        # Check if any expected answer keywords are present
        for expected in current_option.expected_answers:
            if expected.lower() in input_lower:
                return False

        # Check for topic-related keywords
        topic_keywords = [current_option.topic_id, current_option.attribute]
        for kw in topic_keywords:
            if kw.replace("_", " ").lower() in input_lower:
                return False

        # If input is long and doesn't match any criteria, likely drifting
        if len(input_lower.split()) > 10:
            return True

        return False

    def _fallback_plan(self, user_input: str) -> Dict[str, Any]:
        """Return a safe fallback plan when structured data is unavailable."""
        return {
            "status": "ERROR",
            "strategy": "PIVOT",
            "reasoning": "Navigator error - using fallback",
            "instruction": f"Acknowledge '{user_input}' warmly and ask a fun question about it.",
            "should_advance": False
        }


class PathwayDriver:
    """
    The 'Driver' (System 1): Generates natural language responses based on
    Navigator instructions and pathway data.

    Uses the pathway's question templates, correct_feedback, and hints to
    generate appropriate responses.
    """

    def __init__(self, client: genai.Client, config: Dict[str, Any]):
        self.client = client
        self.config = config

    async def generate_response_stream(
        self,
        history: List[Dict[str, Any]],
        nav_plan: Dict[str, Any],
        pathway: PathwayData,
        next_step: Optional[PathwayStep],
        character_prompt: str,
        age: int
    ) -> AsyncGenerator[tuple[str, Optional[TokenUsage], str], None]:
        """
        Stream the final response following the Navigator's instruction.

        Args:
            history: Conversation history
            nav_plan: Navigation plan from PathwayNavigator
            pathway: Current PathwayData
            next_step: Next step to use for follow-up question (if advancing)
            character_prompt: Character persona instructions
            age: Child's age

        Yields:
            Tuple of (text_chunk, token_usage, full_response_so_far)
        """
        strategy = nav_plan.get("strategy", "PIVOT")
        instruction = nav_plan.get("instruction", "Respond naturally and warmly.")

        # Get the system instruction from history
        hist_system_instruction, gemini_contents = convert_messages_to_gemini_format(history)

        # Build the driver instruction based on strategy
        if strategy == "COMPLETE":
            driver_instruction = self._build_completion_instruction(
                instruction, pathway, character_prompt, age
            )
        elif strategy == "ADVANCE":
            driver_instruction = self._build_advance_instruction(
                instruction, next_step, pathway, character_prompt, age
            )
        elif strategy == "SWITCH":
            new_option = nav_plan.get("new_topic_option")
            driver_instruction = self._build_switch_instruction(
                instruction, new_option, character_prompt, age
            )
        elif strategy == "HINT":
            driver_instruction = self._build_hint_instruction(
                instruction, nav_plan.get("hint", ""), character_prompt, age
            )
        else:  # PIVOT or fallback
            driver_instruction = self._build_pivot_instruction(
                instruction, character_prompt, age
            )

        # Combine system instructions
        full_system_instruction = f"{hist_system_instruction}\n\n{driver_instruction}".strip()

        try:
            stream = self.client.models.generate_content_stream(
                model=self.config.get("model_name", "gemini-2.0-flash-exp"),
                contents=gemini_contents,
                config=GenerateContentConfig(
                    system_instruction=full_system_instruction,
                    temperature=0.7
                )
            )

            full_response = ""
            for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    yield (chunk.text, None, full_response)

        except Exception as e:
            logger.error(f"[PathwayDriver] Generation failed: {e}")
            yield ("That sounds interesting! Tell me more.", None, "Fallback")

    def _build_completion_instruction(
        self,
        instruction: str,
        pathway: PathwayData,
        character_prompt: str,
        age: int
    ) -> str:
        """Build instruction for pathway completion."""
        return f"""You are a friendly AI companion for a {age}-year-old child.
{character_prompt}

PATHWAY COMPLETED! This is the final response for our exploration of {pathway.object_name}.

CRITICAL INSTRUCTION:
{instruction}

Guidelines:
- Celebrate their learning journey warmly
- Mention 1-2 things they discovered about {pathway.object_name}
- End with enthusiasm about what a great explorer they are
- Keep response to 2-3 short sentences
- Be warm and encouraging
- Do NOT say "I will now..." - just give the response naturally
"""

    def _build_advance_instruction(
        self,
        instruction: str,
        next_step: Optional[PathwayStep],
        pathway: PathwayData,
        character_prompt: str,
        age: int
    ) -> str:
        """Build instruction for advancing to next round."""
        next_question = ""
        if next_step:
            default_option = next_step.get_default_option()
            if default_option:
                next_question = default_option.question

        return f"""You are a friendly AI companion for a {age}-year-old child.
{character_prompt}

CORRECT ANSWER! The child got it right about {pathway.object_name}.

CRITICAL INSTRUCTION:
{instruction}

NEXT QUESTION TO ASK:
{next_question}

Guidelines:
- First, give positive feedback (1 short sentence)
- Then naturally transition to the next question
- Keep the total response to 2-3 sentences
- Be enthusiastic and encouraging
- Do NOT say "Now let me ask..." - just ask the question naturally
"""

    def _build_switch_instruction(
        self,
        instruction: str,
        new_option: Optional[TopicOption],
        character_prompt: str,
        age: int
    ) -> str:
        """Build instruction for topic switching within the round."""
        new_question = new_option.question if new_option else "Tell me more!"

        return f"""You are a friendly AI companion for a {age}-year-old child.
{character_prompt}

TOPIC SWITCH: The child showed interest in a related topic.

CRITICAL INSTRUCTION:
{instruction}

NEW QUESTION:
{new_question}

Guidelines:
- Acknowledge their interest positively
- Smoothly transition to the new question
- Keep response to 2 sentences
- Be natural and curious
"""

    def _build_hint_instruction(
        self,
        instruction: str,
        hint: str,
        character_prompt: str,
        age: int
    ) -> str:
        """Build instruction for providing a hint."""
        return f"""You are a friendly AI companion for a {age}-year-old child.
{character_prompt}

HINT TIME: The child needs a little help with their answer.

CRITICAL INSTRUCTION:
{instruction}

HINT TO GIVE:
{hint}

Guidelines:
- Encourage them - they're doing great!
- Rephrase the hint in your own warm words
- Keep response to 1-2 sentences
- End by gently repeating or rephrasing the question
- Never make them feel wrong - learning is an adventure!
"""

    def _build_pivot_instruction(
        self,
        instruction: str,
        character_prompt: str,
        age: int
    ) -> str:
        """Build instruction for pivoting back to topic."""
        return f"""You are a friendly AI companion for a {age}-year-old child.
{character_prompt}

PIVOT: The child drifted off topic. Bring them back gently.

CRITICAL INSTRUCTION:
{instruction}

Guidelines:
- First acknowledge what they said (1 sentence)
- Then naturally bridge back to our question
- Be warm and curious, never dismissive
- Keep response to 2-3 sentences
- Make the transition feel fun, not corrective
"""


class PathwayController:
    """
    Convenience class that combines PathwayNavigator and PathwayDriver
    for easier integration with the main streaming logic.
    """

    def __init__(self, client: genai.Client, config: Dict[str, Any]):
        self.navigator = PathwayNavigator(client, config)
        self.driver = PathwayDriver(client, config)

    async def process_turn(
        self,
        history: List[Dict[str, Any]],
        user_input: str,
        assistant,  # PaixuejiAssistant instance
        character_prompt: str,
        age: int
    ) -> AsyncGenerator[tuple[str, Optional[TokenUsage], str, Dict[str, Any]], None]:
        """
        Process a complete turn: navigate, then generate response.

        Args:
            history: Conversation history
            user_input: Child's input
            assistant: PaixuejiAssistant instance with pathway state
            character_prompt: Character persona
            age: Child's age

        Yields:
            Tuple of (text_chunk, token_usage, full_response, nav_plan)
        """
        if not assistant.pathway_mode or not assistant.current_pathway:
            yield ("", None, "", {"error": "Not in pathway mode"})
            return

        pathway = assistant.current_pathway
        current_step = assistant.get_current_step()

        if not current_step:
            yield ("", None, "", {"error": "No current step"})
            return

        # Select topic option based on input
        current_option = assistant.select_topic_option(user_input)

        # Navigate
        nav_plan = self.navigator.analyze_turn(
            history=history,
            user_input=user_input,
            pathway=pathway,
            current_step=current_step,
            current_option=current_option,
            current_round=assistant.current_round,
            age=age
        )

        # Store for debugging
        assistant.last_navigation_state = nav_plan

        # Determine next step for advance scenario
        next_step = None
        if nav_plan.get("should_advance"):
            assistant.advance_round()
            next_step = assistant.get_current_step()

        # Check completion
        if nav_plan.get("strategy") == "COMPLETE":
            assistant.stop_pathway_guide()

        # Generate response
        async for text, usage, full in self.driver.generate_response_stream(
            history=history,
            nav_plan=nav_plan,
            pathway=pathway,
            next_step=next_step,
            character_prompt=character_prompt,
            age=age
        ):
            yield (text, usage, full, nav_plan)
