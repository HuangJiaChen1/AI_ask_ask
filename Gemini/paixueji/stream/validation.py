"""
Validation and decision logic for Paixueji assistant.

This module contains functions for validating child answers and making
routing decisions based on engagement, correctness, and topic switching.

Functions:
    - decide_topic_switch_with_validation: Unified AI validation
    - is_answer_reasonable: Simple heuristic for engagement check
"""
import json
import time
from loguru import logger
import paixueji_prompts


async def decide_topic_switch_with_validation(
    assistant,
    child_answer: str,
    object_name: str,
    age: int,
    focus_mode: str | None = None,
    is_awaiting_topic_selection: bool = False
) -> dict:
    """
    Unified AI validation: Checks engagement, factual correctness, AND topic switching in single call.

    Args:
        assistant: PaixuejiAssistant instance
        child_answer: The child's answer text
        object_name: Current object being discussed
        age: Child's age
        focus_mode: Current focus mode
        is_awaiting_topic_selection: Whether we are waiting for user to pick a topic from a list

    Returns:
        dict: Decision result with keys:
            - decision: "SWITCH" or "CONTINUE"
            - new_object: Object name or None
            - switching_reasoning: Brief reason
            - is_engaged: True or False
            - is_factually_correct: True or False
            - correctness_reasoning: Brief reason
    """
    # Extract the last question the model asked from conversation history
    conversation_history = assistant.conversation_history
    last_model_question = None

    # Find the most recent assistant message
    for msg in reversed(conversation_history):
        if msg.get('role') == 'assistant':
            last_model_question = msg.get('content')
            break

    if not last_model_question:
        last_model_question = "Unknown (first interaction)"

    # Add specific instructions for topic selection state
    topic_selection_instructions = ""
    if is_awaiting_topic_selection:
        topic_selection_instructions = """
SPECIAL CONTEXT: AWAITING TOPIC SELECTION
The previous message offered the child a choice of topics (e.g., "A, B, or C?").

RULES FOR THIS STATE:
1. **Uncertainty / Request to Pick**: If the child expresses uncertainty (e.g., "not sure", "don't know", "no idea") or asks YOU to pick (e.g., "you decide", "surprise me"):
   - **DECISION: SWITCH**
   - **new_object**: Pick one of the valid options from the previous message (e.g., "Apple").
   - **switching_reasoning**: "Child expressed uncertainty or asked me to pick."

2. **Valid Choice**: If child names a valid object:
   - **DECISION: SWITCH**
   - **new_object**: The object they named.

3. **New Topic**: If child talks about something else entirely:
   - **DECISION: SWITCH** (to their new topic).
"""

    # Rules block is overridable via prompt_overrides.json (supports self-evolution)
    rules = paixueji_prompts.get_prompts()["input_analyzer_rules"]

    # Build contextual THREE-PART validation prompt (context section + overridable rules)
    decision_prompt = f"""You are an educational AI helping a {age}-year-old child learn.

CONTEXT:
- Topic: {object_name}
- Question: "{last_model_question}"
- Answer: "{child_answer}"
{topic_selection_instructions}
{rules}"""

    try:
        # Call Gemini with JSON mode via async client
        t0 = time.time()
        # Use gemini-1.5-flash for stable and fast validation
        response = await assistant.client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=decision_prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": 200
            }
        )
        t1 = time.time()
        logger.info(f"[VALIDATE] LLM Call Duration: {t1 - t0:.3f}s (using gemini-2.5-flash-lite async)")

        # Parse JSON response
        decision_data = json.loads(response.text)

        logger.info(
            f"[VALIDATE] {decision_data['decision']} | "
            f"new_object={decision_data.get('new_object')}, "
            f"engaged={decision_data.get('is_engaged')}, "
            f"correct={decision_data.get('is_factually_correct')}, "
            f"switch_reasoning={decision_data.get('switching_reasoning')}, "
            f"correctness_reasoning={decision_data.get('correctness_reasoning')}"
        )

        return decision_data

    except Exception as e:
        logger.error(f"[VALIDATE] Error: {e}, defaulting to safe state")
        import traceback
        traceback.print_exc()
        return {
            'decision': 'CONTINUE',
            'new_object': None,
            'switching_reasoning': f'Error in validation: {str(e)}',
            'is_engaged': True,
            'is_factually_correct': True,
            'correctness_reasoning': 'Could not evaluate due to error'
        }


    except Exception as e:
        logger.error(f"[VALIDATE] Error: {e}, defaulting to safe state")
        import traceback
        traceback.print_exc()
        return {
            'decision': 'CONTINUE',
            'new_object': None,
            'switching_reasoning': f'Error in validation: {str(e)}',
            'is_engaged': True,  # Safe default - continue conversation
            'is_factually_correct': True,  # Safe default - don't incorrectly penalize
            'correctness_reasoning': 'Could not evaluate due to error'
        }


def is_answer_reasonable(child_answer: str) -> bool:
    """
    Check if child's answer shows reasonable engagement.

    Simple heuristic - be encouraging, not strict!

    Args:
        child_answer: The child's answer

    Returns:
        True if answer seems reasonable, False if child appears stuck
    """
    answer_lower = child_answer.lower().strip()

    # Too short
    if len(answer_lower) <= 3:
        return False

    # Stuck phrases
    stuck_phrases = [
        "don't know", "dont know", "idk", "dunno",
        "not sure", "no idea", "help me"
    ]
    if any(phrase in answer_lower for phrase in stuck_phrases):
        return False

    # Has some letters (shows attempt)
    if sum(c.isalpha() for c in answer_lower) < 2:
        return False

    # Accept everything else - be encouraging!
    return True
