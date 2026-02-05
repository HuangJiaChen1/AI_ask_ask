"""
Theme Guide module using Multi-Agent Controller Architecture (Navigator & Driver).

This module implements a "System 2" (Navigator) and "System 1" (Driver) approach
to conversational guidance.
"""
import json
from typing import AsyncGenerator, Optional, Dict, Any, List
from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger
from schema import TokenUsage
from .utils import convert_messages_to_gemini_format

class ThemeNavigator:
    """
    The 'Navigator' (System 2): Analyzes the conversation and plans the next move.
    It does NOT generate the final response text.
    """
    def __init__(self, client: genai.Client, config: Dict[str, Any], model_override: Optional[str] = None):
        self.client = client
        self.config = config
        # Allow using a faster model (e.g. gemini-2.5-flash-lite) for logic steps
        self.model_name = model_override or config.get("navigator_model") or config["model_name"]

    def analyze_turn(
        self,
        history: List[Dict[str, Any]],
        user_input: str,
        current_topic: str,
        target_theme: Dict[str, Any],
        age: int
    ) -> Dict[str, Any]:
        """
        Analyze the current turn and generate a navigation instruction.
        """
        
        # Contextualize the goal
        goal_description = target_theme.get('description', target_theme['name'])
        
        # Format recent history for context (last 3 turns)
        recent_history = ""
        for msg in history[-6:]: # Last 3 exchanges approx
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role != "system":
                recent_history += f"{role.upper()}: {content}\n"

        prompt = f"""You are the Strategy Navigator for a conversation with a {age}-year-old child.
Current Topic: "{current_topic}"
Target Theme: "{target_theme['name']}" ({goal_description})

[RECENT CONVERSATION]
{recent_history}

User's Latest Input: "{user_input}"

YOUR TASK:
1. Analyze the User's Input:
   - Are they engaged?
   - Are they drifting away?
   - Are they resisting the topic?

2. Determine Strategy:
   - "ADVANCE": User is on track. Move 1 step closer to the Target Theme.
   - "PIVOT": User is slightly off-topic. Acknowledge their point, then link it back to our path.
   - "RETREAT": User is resisting or confused. Stop pushing. Validate them and stay on their topic for a moment.
   - "COMPLETE": We have successfully reached the Target Theme.

3. Generate Instruction (for the Chatbot):
   - Write a specific, hidden instruction for the chatbot on what to say.
   - Example (Advance): "Acknowledge the apple, then ask if they know where apples grow."
   - Example (Pivot): "Laugh at the joke, but then ask if they like playing outside in the spring."

OUTPUT JSON ONLY:
{{
  "status": "ON_TRACK" | "DRIFTING" | "RESISTANCE" | "COMPLETED",
  "strategy": "ADVANCE" | "PIVOT" | "RETREAT" | "COMPLETE",
  "reasoning": "Brief explanation of your logic",
  "instruction": "The instruction for the chatbot"
}}
"""
        try:
            # Note: Using sync call as per existing patterns in this project
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1 # Low temperature for consistent logic
                )
            )
            
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            
            plan = json.loads(text)
            return plan

        except Exception as e:
            logger.error(f"[Navigator] Planning failed: {e}")
            # Fallback safe plan
            return {
                "status": "ERROR",
                "strategy": "PIVOT",
                "reasoning": "Planner error",
                "instruction": f"Acknowledge '{user_input}' warmly and ask a fun question about it."
            }

class ThemeDriver:
    """
    The 'Driver' (System 1): Generates the natural language response based on instructions.
    """
    def __init__(self, client: genai.Client, config: Dict[str, Any]):
        self.client = client
        self.config = config

    async def generate_response_stream(
        self,
        history: List[Dict[str, Any]],
        nav_plan: Dict[str, Any],
        character_prompt: str,
        age: int
    ) -> AsyncGenerator[tuple[str, Optional[TokenUsage], str], None]:
        """
        Stream the final response following the Navigator's instruction.
        """
        
        instruction = nav_plan.get("instruction", "Respond naturally.")
        
        # Prepare the system prompt / persona
        # We combine the existing system instructions from history (if any) with our new directive
        hist_system_instruction, gemini_contents = convert_messages_to_gemini_format(history)
        
        driver_instruction = f"""You are a friendly AI companion for a {age}-year-old child.
{character_prompt}

CRITICAL INSTRUCTION:
{instruction}

- Follow the instruction above exactly.
- Keep your response short (1-2 sentences).
- Be conversational and warm.
- Do NOT say "I will now..." or "My instruction is...". Just say the response.
"""
        
        # Combine system instructions
        full_system_instruction = f"{hist_system_instruction}\n\n{driver_instruction}".strip()

        try:
            stream = self.client.models.generate_content_stream(
                model=self.config["model_name"],
                contents=gemini_contents, # Pass the LIST, not the tuple
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
            logger.error(f"[Driver] Generation failed: {e}")
            yield ("That sounds interesting! Tell me more.", None, "Fallback")
