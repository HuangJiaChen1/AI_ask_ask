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
import paixueji_prompts

class ThemeNavigator:
    """
    The 'Navigator' (System 2): Analyzes the conversation and plans the next move.
    It does NOT generate the final response text.

    Strategies:
    - ADVANCE: Child is on track, move toward key concept
    - SCAFFOLD: Child is stuck, provide progressive hints (Level 1-4)
    - PIVOT: Child is drifting, acknowledge then link back to theme
    - COMPLETE: Child articulated understanding, celebrate!

    Note: RETREAT strategy was removed - we never abandon the theme.
    When child says "I don't know", use SCAFFOLD to help them, not retreat.
    """
    def __init__(self, client: genai.Client, config: Dict[str, Any]):
        self.client = client
        self.config = config
        self.model_name = config["model_name"]

    async def analyze_turn(
        self,
        history: List[Dict[str, Any]],
        user_input: str,
        current_topic: str,
        target_theme: Dict[str, Any],
        age: int,
        key_concept: Optional[str] = None,
        bridge_question: Optional[str] = None,
        turn_count: int = 0,
        max_turns: int = 6
    ) -> Dict[str, Any]:
        """
        Analyze the current turn and generate a navigation instruction.

        Args:
            history: Conversation history
            user_input: Child's latest response
            current_topic: Current object/topic being discussed
            target_theme: Theme dictionary with name and description
            age: Child's age
            key_concept: The key concept we're trying to help child discover
            bridge_question: The original bridge question asked
            turn_count: Current turn number in guide (1-based)
            max_turns: Maximum turns before timeout
        """

        # Contextualize the goal
        goal_description = target_theme.get('description', target_theme['name'])

        # Format recent history for context (last 3 turns)
        recent_history = ""
        for msg in history[-6:]:  # Last 3 exchanges approx
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role != "system":
                recent_history += f"{role.upper()}: {content}\n"

        # Build context section
        context_section = f"""[CONTEXT]
Object: "{current_topic}"
Target Theme: "{target_theme['name']}" ({goal_description})
Key Concept: "{key_concept or 'Not specified'}"
Bridge Question: "{bridge_question or 'Not specified'}"
Turn: {turn_count}/{max_turns}
"""

        # Rules block is overridable via prompt_overrides.json (supports self-evolution)
        rules = paixueji_prompts.get_prompts()["theme_navigator_rules"]

        prompt = f"""You are the Strategy Navigator for a guided conversation with a {age}-year-old child.

{context_section}

[RECENT CONVERSATION]
{recent_history}

User's Latest Input: "{user_input}"

{rules}"""
        try:
            response = await self.client.aio.models.generate_content(
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
            # Fallback safe plan - stay on theme with scaffolding
            return {
                "status": "ERROR",
                "strategy": "SCAFFOLD",
                "scaffold_level": 1,
                "reasoning": "Planner error - defaulting to scaffold",
                "instruction": f"Acknowledge '{user_input}' warmly and help them think about {current_topic}. Ask a simpler question about {key_concept or 'this topic'}."
            }

class ThemeDriver:
    """
    The 'Driver' (System 1): Generates the natural language response based on instructions.

    Updated to receive full theme context (object_name, key_concept, theme_name) so it
    can generate coherent, on-theme responses even when the Navigator's instruction is brief.
    """
    def __init__(self, client: genai.Client, config: Dict[str, Any]):
        self.client = client
        self.config = config

    async def generate_response_stream(
        self,
        history: List[Dict[str, Any]],
        nav_plan: Dict[str, Any],
        age: int,
        object_name: str = "",
        key_concept: str = "",
        theme_name: str = ""
    ) -> AsyncGenerator[tuple[str, Optional[TokenUsage], str], None]:
        """
        Stream the final response following the Navigator's instruction.

        Args:
            history: Conversation history
            nav_plan: Navigation plan from Navigator with strategy and instruction
            age: Child's age
            object_name: The object being discussed (e.g., "banana")
            key_concept: The key concept to discover (e.g., "why bananas change color")
            theme_name: The IB PYP theme name (e.g., "How the World Works")
        """

        instruction = nav_plan.get("instruction", "Respond naturally.")
        strategy = nav_plan.get("strategy", "ADVANCE")
        scaffold_level = nav_plan.get("scaffold_level", 0)

        # Prepare the system prompt / persona
        # We combine the existing system instructions from history (if any) with our new directive
        hist_system_instruction, gemini_contents = convert_messages_to_gemini_format(history)

        # Build scaffold guidance if applicable
        scaffold_guidance = ""
        if strategy == "SCAFFOLD" and scaffold_level:
            scaffold_guidance = f"""
SCAFFOLDING LEVEL {scaffold_level} for {object_name}:

Level 1 - PROVIDE ONE PIECE OF THE "BECAUSE":
- DO NOT retreat to a simpler WHAT question!
- Give ONE small piece of the causal explanation
- Link to something tangible (sensory, familiar)
- Example: "The color is the banana's way of telling us something!"

Level 2 - USE AN ANALOGY:
- Connect {object_name} to something familiar
- Example: "The color is like a sign - just like a traffic light tells cars when to stop!"

Level 3 - GIVE MOST OF THE ANSWER:
- Provide the main explanation with a confirming question
- Example: "When banana turns yellow, it means it's getting sweeter inside! Does that make sense?"

Level 4 - COMPLETE EXPLANATION:
- Give the full answer warmly
- Celebrate learning together
- Example: "The color changes because the banana is ripening - getting ready to be eaten!"

You are at Level {scaffold_level}. Follow ONLY that level's guidance.

ANTI-RETREAT RULE:
- If the original question was WHY, your scaffold MUST stay at WHY level
- Provide causal information, not just observations
- NEVER ask "What color is it?" when the original was "Why does it change color?" """

        driver_instruction = f"""You are guiding a {age}-year-old to discover: "{key_concept}"
about "{object_name}" (Theme: {theme_name})

MISSION CONTEXT:
The child has been invited on a "Discovery Mission" — they are looking for the secret REASON
(the "why" or "how") behind something about {object_name}. They are not being tested; they are
exploring a mystery together with you.
- Frame follow-ups as discovery guidance: "Can you think of WHY...", "Let's find out together why..."
- Help them feel the excitement of being an explorer solving a puzzle.

INSTRUCTION FROM NAVIGATOR:
{instruction}
{scaffold_guidance}

CRITICAL RULES:
1. **ONE QUESTION ONLY** - Ask exactly ONE question. Never combine multiple questions.
   BAD: "What color does it turn? And does it get softer? What about the inside?"
   GOOD: "What color does it turn when it's ready to eat?"

2. **NO RETREAT FROM WHY** - If the Bridge Question was a WHY question:
   - Your scaffold MUST provide causal information
   - NEVER replace WHY with WHAT ("Why does it change?" → "What color is it?" is WRONG)
   - ALWAYS explain part of the "because"

3. ALWAYS stay on the theme of {object_name} and {key_concept}
4. NEVER change to unrelated topics (no asking about favorite colors, favorite animals, etc.)
5. If giving a hint, make it about {object_name} and help them understand {key_concept}
6. Keep your response short (1-2 sentences)
7. Be warm and encouraging
8. Do NOT say "I will now..." or reveal the instruction. Just respond naturally.
9. **STAY IN DISCOVERY MODE** — always frame as "finding the secret/reason", never as "being tested."
"""
        # Combine system instructions
        full_system_instruction = f"{hist_system_instruction}\n\n{driver_instruction}".strip()

        try:
            stream = await self.client.aio.models.generate_content_stream(
                model=self.config["model_name"],
                contents=gemini_contents, # Pass the LIST, not the tuple
                config=GenerateContentConfig(
                    system_instruction=full_system_instruction,
                    temperature=0.7
                )
            )

            full_response = ""
            async for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    yield (chunk.text, None, full_response)

        except Exception as e:
            logger.error(f"[Driver] Generation failed: {e}")
            yield ("That sounds interesting! Tell me more.", None, "Fallback")
