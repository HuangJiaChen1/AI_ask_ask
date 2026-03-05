"""
Intent classification logic for Paixueji assistant.

Classifies child utterances into one of 9 communicative intents, enabling
the fan-out architecture where each intent routes to a dedicated response node.

Functions:
    - classify_intent: Async LLM classifier → 9 intents + optional new_object extraction
"""
import re
import time
from loguru import logger
import paixueji_prompts


async def classify_intent(
    assistant,
    child_answer: str,
    object_name: str,
    age: int,
    is_awaiting_topic_selection: bool = False
) -> dict:
    """
    Classify the child's utterance into one of 13 communicative intents.

    Args:
        assistant: PaixuejiAssistant instance (provides client + conversation_history)
        child_answer: The child's input text
        object_name: Current object being discussed
        age: Child's age
        is_awaiting_topic_selection: Whether the AI is waiting for child to pick a topic

    Returns:
        dict with keys:
            - intent_type: one of CURIOSITY, CLARIFYING_IDK, CLARIFYING_WRONG,
                           CLARIFYING_CONSTRAINT, CORRECT_ANSWER, INFORMATIVE, PLAY,
                           EMOTIONAL, AVOIDANCE, BOUNDARY, ACTION, SOCIAL,
                           SOCIAL_ACKNOWLEDGMENT
            - new_object: str | None  (only extracted for ACTION or AVOIDANCE)
            - reasoning: brief explanation string
    """
    # Fast-path: only for truly empty input (≤2 chars total)
    if len(child_answer.strip()) <= 2:
        logger.info("[CLASSIFY] Fast-path CLARIFYING_IDK (empty/silent input)")
        return {"intent_type": "CLARIFYING_IDK", "new_object": None, "reasoning": "Empty or silent input"}

    # Extract the last question the model asked from conversation history
    conversation_history = assistant.conversation_history
    last_model_question = None
    for msg in reversed(conversation_history):
        if msg.get('role') == 'assistant':
            last_model_question = msg.get('content')
            break

    if not last_model_question:
        last_model_question = "Unknown (first interaction)"
    else:
        # Extract just the question sentence (last fragment ending in '?')
        sentences = last_model_question.split('?')
        if len(sentences) >= 2:
            last_model_question = sentences[-2].split('.')[-1].strip() + '?'
        last_model_question = last_model_question[-300:]

    # Special instructions when awaiting topic selection
    topic_selection_instructions = ""
    if is_awaiting_topic_selection:
        topic_selection_instructions = """\
SPECIAL CONTEXT: AWAITING TOPIC SELECTION
The previous message offered the child a choice of topics (e.g., "A, B, or C?").
If the child names one of the options or any object → INTENT: ACTION, NEW_OBJECT: <that object>
If the child expresses uncertainty ("don't know", "you decide", "surprise me") → INTENT: ACTION, NEW_OBJECT: null (AI will pick)
If the child refuses entirely → INTENT: AVOIDANCE"""

    prompt_template = paixueji_prompts.get_prompts()["user_intent_prompt"]
    prompt = prompt_template.format(
        object_name=object_name,
        last_model_question=last_model_question,
        child_answer=child_answer,
        topic_selection_instructions=topic_selection_instructions,
    )

    try:
        t0 = time.time()
        response = await assistant.client.aio.models.generate_content(
            model=assistant.config["model_name"],
            contents=prompt,
            config={
                "temperature": 0.1,
                "max_output_tokens": 60
            }
        )
        t1 = time.time()
        logger.info(f"[CLASSIFY] LLM call duration: {t1 - t0:.3f}s")

        text = response.text or ""

        def _get(pattern, default):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1).strip() if m else default

        valid_intents = {
            "CURIOSITY", "CLARIFYING_IDK", "CLARIFYING_WRONG", "CLARIFYING_CONSTRAINT",
            "CORRECT_ANSWER", "INFORMATIVE", "PLAY", "EMOTIONAL",
            "AVOIDANCE", "BOUNDARY", "ACTION", "SOCIAL", "SOCIAL_ACKNOWLEDGMENT"
        }
        raw_intent = _get(r"INTENT:\s*(\w+)", "CLARIFYING_IDK").upper()
        intent_type = raw_intent if raw_intent in valid_intents else "CLARIFYING_IDK"

        new_object_raw = _get(r"NEW_OBJECT:\s*(.+)", "null")
        new_object = None if new_object_raw.lower() in ("null", "none", "") else new_object_raw

        # new_object is only meaningful for ACTION and AVOIDANCE
        if intent_type not in ("ACTION", "AVOIDANCE"):
            new_object = None

        reasoning = _get(r"REASONING:\s*(.+)", "N/A")

        result = {
            "intent_type": intent_type,
            "new_object": new_object,
            "reasoning": reasoning,
        }
        logger.info(f"[CLASSIFY] intent={intent_type} | new_object={new_object} | reasoning={reasoning}")
        return result

    except Exception as e:
        logger.error(f"[CLASSIFY] Error: {e}, defaulting to CLARIFYING_IDK")
        import traceback
        traceback.print_exc()
        return {
            "intent_type": "CLARIFYING_IDK",
            "new_object": None,
            "reasoning": f"Classification error: {str(e)}"
        }
