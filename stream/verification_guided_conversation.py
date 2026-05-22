"""Verification-Guided Conversation (VGC) layer.

Injects verification context into prompts and classifies child responses
as confirm / deny / unclear for pending activity properties.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from stream.llm_client import llm_generate
from stream.errors import RateLimitError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")

# Fast-path keyword patterns
_CONFIRM_KEYWORDS = {"yes", "yeah", "yep", "yup", "sure", "definitely", "of course", "right", "correct", "true", "has", "does"}
_DENY_KEYWORDS = {"no", "nope", "not", "never", "none", "doesn't", "dont", "without", "isn't"}


@dataclass
class VerificationItem:
    """A single property that needs confirmation before an activity can launch."""
    property: str                    # e.g. "has_polka_dots"
    question: str                    # e.g. "Does the cat have polka dots?"
    for_activity_id: str             # e.g. "polka_dot_patrol"
    status: str = "pending"          # pending | verified | rejected | unclear
    pending_turns: int = 0           # How many turns this has been pending
    suggested_topics: list[str] = field(default_factory=list)
    natural_pivots: list[str] = field(default_factory=list)
    escalation_question: str = ""    # L3 direct probe question


def build_verification_context(pending_items: list[VerificationItem]) -> str:
    """Build a prompt snippet that tells the LLM what properties need verification.

    Returns empty string if no pending items.
    """
    if not pending_items:
        return ""

    lines = ["[VERIFICATION NEEDED]"]
    for item in pending_items:
        lines.append(f"- Property: {item.property}")
        lines.append(f"  Question to answer: {item.question}")
        lines.append(f"  For activity: {item.for_activity_id}")
        if item.escalation_question:
            lines.append(f"  If unclear after 2 turns, ask: {item.escalation_question}")
    lines.append(
        "\nGuide the conversation naturally toward answering these questions. "
        "Do NOT ask the verification question directly unless the child seems stuck or gives a very unclear answer."
    )
    return "\n".join(lines)


async def classify_verification(
    child_input: str,
    property: str,
    conversation_context: str,
    client,
    config: dict | None,
) -> dict:
    """Classify whether the child's input confirms, denies, or is unclear about a property.

    Uses LLM with conversation context to determine if the child is actually
    responding to the verification question before judging confirm/deny/unclear.

    Returns dict with keys: verdict (confirm|deny|unclear), confidence, reason, source (llm|fallback)
    """
    if client is None or config is None:
        return {
            "verdict": "unclear",
            "confidence": "low",
            "reason": "No LLM client available for context-aware verification",
            "source": "fallback",
        }

    prompt = f"""You are a verification classifier for a children's education system.

Property to verify: "{property}"
Conversation context: {conversation_context or "(none)"}
Child's latest input: "{child_input}"

Step 1: Is the child responding to the verification question in the conversation context?
- If NO (e.g., answering a different question, describing something unrelated, or changing topic): respond with {{"verdict": "unclear", "confidence": "high", "reason": "..."}}
- If YES: proceed to Step 2.

Step 2: Does the child's input confirm or deny the property?
- confirm: The child clearly indicates the property is true.
- deny: The child clearly indicates the property is false.
- unclear: The child's input is ambiguous or does not clearly address the property.

Respond ONLY with valid JSON:
{{"verdict": "confirm|deny|unclear", "confidence": "high|medium|low", "reason": "..."}}"""

    try:
        response = await llm_generate(
            client=client,
            model=config.get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 128},
            call_name="classify_verification",
        )
        raw_text = response.text or ""
        match = _JSON_FENCE_RE.search(raw_text)
        json_text = match.group(1) if match else raw_text
        parsed = json.loads(json_text)

        verdict = parsed.get("verdict", "unclear")
        if verdict not in ("confirm", "deny", "unclear"):
            verdict = "unclear"

        return {
            "verdict": verdict,
            "confidence": parsed.get("confidence", "low"),
            "reason": parsed.get("reason", ""),
            "source": "llm",
        }
    except RateLimitError:
        raise
    except Exception as exc:
        logger.warning("[CLASSIFY_VERIFICATION] error: %s", exc)
        return {
            "verdict": "unclear",
            "confidence": "low",
            "reason": f"classification_error: {exc}",
            "source": "error",
        }


def check_probe_needed(pending_items: list[VerificationItem], max_pending_turns: int = 2) -> bool:
    """Return True if any pending verification has exceeded the turn threshold."""
    return any(item.pending_turns >= max_pending_turns for item in pending_items)


def build_probe_verification_context(pending_items: list[VerificationItem]) -> str:
    """Build a gentle, direct verification guide for PROBE mode follow-ups.

    Unlike `build_verification_context` which tells the LLM to guide naturally
    and NOT ask directly, this function instructs the LLM to ask the pending
    verification question directly but gently.
    """
    lines = ["[VERIFICATION -- ask gently and directly]"]
    for item in pending_items:
        q = getattr(item, "question", "")
        if q:
            lines.append(f"- {q}")
    lines.append(
        "\nAsk ONE of these questions in a warm, natural way. "
        "Do NOT command. Do NOT demand. Sound like a curious friend."
    )
    return "\n".join(lines)
