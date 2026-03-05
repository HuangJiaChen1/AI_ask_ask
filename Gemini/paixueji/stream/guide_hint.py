"""
LLM-generated guide hints for Paixueji assistant.

When the child has tried multiple times but not yet discovered the concept,
we generate a meaningful, age-appropriate hint using the LLM instead of
a hardcoded template.

The key insight is that abstract IB PYP concepts like "Change" or
"How the World Works" are meaningless to young children. The LLM
translates these into concrete, observable examples that relate
to the specific object being discussed.

Example transformation:
    BAD:  "Banana is connected to Change!"
    GOOD: "You know what? Bananas start out green, then turn yellow,
           then get brown spots! Just like how you grow and change!"
"""

import time
from loguru import logger


async def generate_guide_hint(
    object_name: str,
    key_concept: str,
    key_concept_reason: str,
    bridge_question: str,
    theme_name: str,
    age: int,
    messages: list,
    config: dict,
    client
) -> str:
    """
    Generate a concrete, age-appropriate hint using LLM.

    The hint should:
    1. Explain the abstract concept in concrete, observable terms
    2. Relate specifically to the object being discussed
    3. Be age-appropriate for the child
    4. Give the child a real clue without giving away the answer
    5. End with an encouraging question to keep them thinking

    Args:
        object_name: The object being discussed (e.g., "banana")
        key_concept: The abstract IB PYP concept (e.g., "Change")
        key_concept_reason: Why this concept applies (from theme classification)
        bridge_question: The original question we asked the child
        theme_name: The IB PYP theme name (e.g., "How the World Works")
        age: Child's age (3-8)
        messages: Conversation history
        config: Configuration dict with model settings
        client: Gemini client instance

    Returns:
        str: A child-friendly hint message
    """
    model_name = config["model_name"]

    # Build age-appropriate language guidance
    if age <= 4:
        age_guidance = "Use very simple words. Short sentences. Relate to things they see every day."
    elif age <= 6:
        age_guidance = "Use simple words and short sentences. Use comparisons they understand."
    else:
        age_guidance = "Use clear language. Can include slightly more complex ideas but keep it fun."

    prompt = f"""You are helping a {age}-year-old child understand something special about {object_name}.

CONTEXT:
- Object: {object_name}
- The concept we want them to discover: {key_concept}
- Why this concept applies: {key_concept_reason}
- The original question we asked: {bridge_question}

YOUR TASK:
Generate a helpful hint that explains the concept in CONCRETE, child-friendly terms.

CRITICAL RULES:
1. DO NOT use abstract words like "{key_concept}" or "{theme_name}" directly - children don't understand these
2. Use CONCRETE examples the child can see, touch, or imagine
3. Keep it short - 2-3 sentences maximum
4. End with a simple, encouraging question to keep them thinking
5. Be warm, friendly, and enthusiastic
6. {age_guidance}

GOOD EXAMPLE for "banana" and "Change":
"You know what? Bananas start out green when they're young, then turn yellow, then get brown spots when they're old! Just like how you change as you grow! What do you think makes the banana change color?"

BAD EXAMPLE (avoid this!):
"Banana is connected to Change! Think about how banana relates to How the World Works."

Now generate a hint for {object_name} about {key_concept}. Remember: concrete examples, not abstract words!"""

    try:
        logger.info(f"[GUIDE_HINT] Generating LLM hint for '{object_name}' | concept='{key_concept}'")
        t0 = time.time()

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "temperature": 0.7,
                "max_output_tokens": 200,
            }
        )

        t1 = time.time()
        hint_text = response.text.strip() if response.text else ""

        logger.info(f"[GUIDE_HINT] Generated hint in {t1 - t0:.3f}s | length={len(hint_text)}")

        if hint_text:
            return hint_text
        else:
            # Fallback to a generic but friendly message
            logger.warning(f"[GUIDE_HINT] LLM returned empty hint for '{object_name}'")
            return _fallback_hint(object_name)

    except Exception as e:
        logger.error(f"[GUIDE_HINT] LLM hint generation failed for '{object_name}': {e}")
        return _fallback_hint(object_name)


def _fallback_hint(object_name: str) -> str:
    """
    Fallback hint when LLM generation fails.

    Still better than the original hardcoded template since it
    avoids abstract terminology entirely.
    """
    return (
        f"Let me give you a little clue! Think about {object_name} really carefully. "
        f"What's something special about it that might connect to bigger things in the world? "
        f"Take your time!"
    )
