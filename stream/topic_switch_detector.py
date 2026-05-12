"""Topic switch detector for the attribute lane.

Runs a lightweight LLM call in parallel with intent classification
to decide whether the child has shifted interest to a fallback topic.
"""
import json
import re

from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from schema import TokenUsage
from stream.utils import clean_messages_for_api, convert_messages_to_gemini_format


# Extract JSON from model output even if wrapped in markdown fences.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


async def detect_topic_switch(
    conversation_history: list[dict],
    primary: "AttributeProfile",
    fallbacks: tuple,
    child_input: str,
    config: dict,
    client: genai.Client,
) -> tuple[bool, str | None, str]:
    """Detect whether the child has shifted interest to a fallback topic.

    Returns:
        (should_switch, target_attribute_id, reason)
        should_switch is False when no clear switch is detected or on error.
    """
    fallback_labels = [f"{fb.attribute_id} ({fb.label})" for fb in fallbacks]
    fallback_block = "\n".join(f"- {lbl}" for lbl in fallback_labels) if fallback_labels else "(none)"

    # Format last 6 turns of history for context
    history_lines = []
    for msg in conversation_history[-12:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        history_lines.append(f"{role}: {content}")
    history_text = "\n".join(history_lines)

    prompt = f"""You are a topic-interest detector for a children's education conversation system.

Current topic: {primary.label} (id: {primary.attribute_id})
Fallback topics:
{fallback_block}

Conversation history:
{history_text}

Child's latest input: {child_input}

Decide whether the child has clearly shifted interest to a fallback topic.
"Clearly shifted" means ONE of these:
- The child used 3+ words describing a fallback topic (e.g. "SO BIG! Bigger than my dog!")
- The child compared the object to something else using a fallback topic
- The child asked a direct question about a fallback topic
- The child returned to a fallback topic in 2+ consecutive messages

NEGATIVE EXAMPLES — these are NOT clear shifts:
- The child mentions a fallback attribute in passing while primarily discussing the current topic (e.g., "It's red and very big" — color mentioned incidentally while the child is clearly talking about size).
- A single one-word color or shape descriptor without elaboration or comparison (e.g., "It's red.")
- The adult (assistant) mentions a fallback topic; the child only responds to the adult's mention without initiating their own interest.
- The child returns to the current topic in the same message after briefly mentioning a fallback.

Output ONLY valid JSON (no markdown fences, no extra text):
{{
   "should_switch": boolean,
   "target_attribute_id": string or null,
   "reason": "brief explanation"
}}
"""

    messages = [{"role": "user", "content": prompt}]
    clean_messages = clean_messages_for_api(messages)
    system_instruction, contents = convert_messages_to_gemini_format(clean_messages)

    try:
        gen_config = GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=150,
            system_instruction=system_instruction if system_instruction else None,
        )
        response = await client.aio.models.generate_content(
            model=config["model_name"],
            contents=contents,
            config=gen_config,
        )
        raw_text = response.text or ""

        # Extract JSON even if wrapped in fences
        match = _JSON_FENCE_RE.search(raw_text)
        json_text = match.group(1) if match else raw_text
        parsed = json.loads(json_text)

        should_switch = bool(parsed.get("should_switch", False))
        target_id = parsed.get("target_attribute_id")
        reason = parsed.get("reason", "")

        if should_switch and target_id:
            # Validate target_id is actually in fallbacks
            valid_ids = {fb.attribute_id for fb in fallbacks}
            if target_id not in valid_ids:
                logger.warning(
                    "[TOPIC_SWITCH_DETECTOR] invalid target %s not in fallbacks %s",
                    target_id, valid_ids,
                )
                return False, None, f"invalid target {target_id}"
            return True, target_id, reason

        return False, None, reason or "no_switch_detected"

    except json.JSONDecodeError as exc:
        logger.warning("[TOPIC_SWITCH_DETECTOR] JSON parse error: %s | raw=%r", exc, raw_text[:200])
        return False, None, f"json_error: {exc}"
    except Exception as exc:
        logger.warning("[TOPIC_SWITCH_DETECTOR] error: %s", exc)
        return False, None, f"error: {exc}"
