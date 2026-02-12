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

    Strategies:
    - ADVANCE: Child is on track, move toward key concept
    - SCAFFOLD: Child is stuck, provide progressive hints (Level 1-4)
    - PIVOT: Child is drifting, acknowledge then link back to theme
    - COMPLETE: Child articulated understanding, celebrate!

    Note: RETREAT strategy was removed - we never abandon the theme.
    When child says "I don't know", use SCAFFOLD to help them, not retreat.
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
        age: int,
        key_concept: Optional[str] = None,
        bridge_question: Optional[str] = None,
        turn_count: int = 0,
        max_turns: int = 6,
        child_question_type: Optional[str] = None
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
Child Question Type: "{child_question_type or 'none'}"
"""

        prompt = f"""You are the Strategy Navigator for a guided conversation with a {age}-year-old child.

{context_section}

[RECENT CONVERSATION]
{recent_history}

User's Latest Input: "{user_input}"

YOUR TASK:
1. Analyze the User's Input against the Key Concept and Bridge Question:
   - Are they showing understanding or curiosity about the Key Concept?
   - Are they engaged but off-topic?
   - Are they stuck or saying "I don't know"?

2. Determine Status:
   - "ON_TRACK": Child is engaged and moving toward understanding the Key Concept.
   - "DRIFTING": Child is engaged but wandering off-topic.
   - "STUCK": Child is stuck - "I don't know", confused, needs help, can't answer.
   - "COMPLETED": Child has ARTICULATED understanding or genuine curiosity about the Key Concept.

3. Determine Strategy:
   - "ADVANCE": Child is on track. Move 1 step closer to the Key Concept.
   - "PIVOT": Child is slightly off-topic. Acknowledge their point, then link back to the theme.
   - "SCAFFOLD": Child is stuck. Provide a hint to help them understand (see scaffold levels below).
   - "MICRO_ANSWER_BRIDGE": Child asks a curiosity question. Give a brief answer, then bridge back.
   - "COMPLETE": Success! Child demonstrated understanding.

   ⚠️ NEVER abandon the theme. If child says "I don't know", use SCAFFOLD to HELP them,
   not retreat to unrelated topics. Always stay focused on "{current_topic}" and "{key_concept}".
   Briefly answering child curiosity is allowed only if you reconnect to the concept in the same turn.

4. If SCAFFOLD, determine the appropriate scaffold level:
   - Level 1: Provide ONE piece of the "because" (NOT a simpler question!)
   - Level 2: Use an analogy connecting {current_topic} to something familiar
   - Level 3: Give most of the answer with a confirming question
   - Level 4: Give the full answer and celebrate learning together

   ⚠️ ANTI-RETREAT RULE: If Bridge Question was WHY, ALL scaffold levels must provide
   causal information. NEVER replace WHY with WHAT.

   Choose the level based on how stuck the child seems and how many times they've been stuck.

5. STRICT SUCCESS CRITERIA for "COMPLETED":
   ✓ Child articulated something showing understanding or curiosity about the Key Concept
   ✓ Child made a connection between object and theme/concept
   ✓ Examples: "Because wheels roll!", "So the car can move!", "It helps us go places!"

   ✗ NOT just "yes", "ok", "uh huh" (parroting)
   ✗ NOT "I don't know" (this is STUCK, needs SCAFFOLD)
   ✗ NOT polite deflection or changing subject

6. Generate Instruction (for the Chatbot):
   - Write a SPECIFIC instruction for what to say next.
   - ALWAYS include "{current_topic}" and "{key_concept}".
   - If SCAFFOLD Level 1: Specify EXACTLY what piece of the "because" to give.
     Example: "Tell the child that the color change is the banana's way of showing it's getting sweeter."
   - If SCAFFOLD Level 2: Specify EXACTLY what analogy to use.
     Example: "Use the analogy of a traffic light - the color is a signal."
   - If SCAFFOLD Level 3: Specify the main explanation to provide.
   - Ask ONE question only at the end.
   - If ADVANCE: Guide toward the Key Concept about {current_topic}.
   - If PIVOT: Acknowledge, then link back to {current_topic} and {key_concept}.
   - If COMPLETE: Celebrate their discovery about {current_topic}!

OUTPUT JSON ONLY:
{{
  "status": "ON_TRACK" | "DRIFTING" | "STUCK" | "COMPLETED",
  "strategy": "ADVANCE" | "PIVOT" | "SCAFFOLD" | "MICRO_ANSWER_BRIDGE" | "COMPLETE",
  "scaffold_level": 1 | 2 | 3 | 4,
  "reasoning": "Brief explanation of your logic",
  "instruction": "Specific instruction including {current_topic} and {key_concept}"
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
        character_prompt: str,
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
            character_prompt: Character persona prompt
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

{character_prompt}

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

3. If strategy is MICRO_ANSWER_BRIDGE:
   - Start with one short direct answer to the child's question.
   - Then add one bridge sentence linking to {object_name} and {key_concept}.
   - End with exactly one bridging question.

4. ALWAYS stay on the theme of {object_name} and {key_concept}
5. Avoid repeating the exact same bridge question from the previous turn.
6. NEVER change to unrelated topics (no asking about favorite colors, favorite animals, etc.)
7. If giving a hint, make it about {object_name} and help them understand {key_concept}
8. Keep your response short (1-2 sentences, or 3 short clauses max for MICRO_ANSWER_BRIDGE)
9. Be warm and encouraging
10. Do NOT say "I will now..." or reveal the instruction. Just respond naturally."""
        
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
