"""
Focus mode logic for Paixueji assistant.

This module contains functions for managing the focus mode state machine.
Now simplified to only handle DEPTH mode (WIDTH mode removed).

Functions:
    - decide_next_focus_mode: Determine next focus mode based on state
    - generate_object_suggestions: Generate AI suggestions for new objects
"""
import json
from loguru import logger


def decide_next_focus_mode(assistant) -> dict:
    """
    Determine next focus mode based on system-managed focus state.

    Simplified to only handle DEPTH mode. WIDTH mode has been removed.

    Returns:
        dict: {
            'focus_mode': str,  # 'depth' or 'object_selection'
            'reason': str,  # Explanation for the decision
            'suggested_objects': list[str] | None,  # Objects to present if mode = 'object_selection'
            'reset_object': bool  # Whether to reset object state
        }
    """
    if not assistant.system_managed_focus:
        # Not in system-managed mode, return current manual focus
        return {
            'focus_mode': assistant.current_focus_mode,
            'reason': 'Manual focus mode',
            'suggested_objects': None,
            'reset_object': False
        }

    # DEPTH mode: Continue until depth target is reached
    if assistant.current_focus_mode == 'depth':
        if assistant.depth_questions_count < assistant.depth_target:
            # Continue with DEPTH
            return {
                'focus_mode': 'depth',
                'reason': f'Depth phase: {assistant.depth_questions_count}/{assistant.depth_target} questions asked',
                'suggested_objects': None,
                'reset_object': False
            }
        else:
            # Depth target reached - trigger theme guide or object selection
            # Theme guide is now handled in graph.py routing
            return {
                'focus_mode': 'depth',
                'reason': f'Depth phase complete ({assistant.depth_questions_count} questions). Ready for theme guide.',
                'suggested_objects': None,
                'reset_object': False
            }

    # OBJECT_SELECTION mode - waiting for user to pick
    elif assistant.current_focus_mode == 'object_selection':
        return {
            'focus_mode': 'object_selection',
            'reason': 'Awaiting object selection from user',
            'suggested_objects': None,
            'reset_object': False
        }

    # Fallback
    return {
        'focus_mode': 'depth',
        'reason': 'Fallback to depth mode',
        'suggested_objects': None,
        'reset_object': False
    }


async def generate_object_suggestions(assistant, config, client, age: int) -> list[str]:
    """
    Use AI to generate 3-4 related object suggestions.

    Args:
        assistant: PaixuejiAssistant instance
        config: Config dict
        client: Gemini client
        age: Child's age

    Returns:
        List of 3-4 object names
    """
    prompt = f"""The child (age {age}) has been learning about {assistant.object_name}.

Suggest 3-4 NEW objects that would be interesting for them to explore next.

Guidelines:
- Objects should be age-appropriate ({age} years old)
- Objects should be concrete and familiar
- Vary difficulty and category
- Make them engaging and fun

Respond with ONLY a JSON array of object names:
["object1", "object2", "object3", "object4"]
"""

    try:
        # Using async client
        response = await client.aio.models.generate_content(
            model=config.get("model_name", "gemini-2.5-flash-lite"),
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.7,  # Higher temp for variety
                "max_output_tokens": 100
            }
        )

        objects = json.loads(response.text)
        logger.info(f"[OBJECT_SUGGESTIONS] Generated: {objects}")
        return objects[:4]  # Ensure max 4

    except Exception as e:
        logger.error(f"[OBJECT_SUGGESTIONS] Error: {e}")
        # Fallback suggestions
        return ["apple", "dog", "car", "tree"]
