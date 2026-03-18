"""
IB PYP theme classification helpers.

The live path classifies a completed chat conversation into one theme when guide
mode begins.
"""
import json
import os
from typing import Any, Optional
from pydantic import BaseModel, Field
from loguru import logger
from google.genai.types import GenerateContentConfig


class ConversationThemeClassificationResult(BaseModel):
    """Result of classifying a conversation into an IB PYP theme."""
    theme_id: str = Field(description="The ID of the matching IB PYP theme")
    theme_name: str = Field(description="The English name of the theme")
    reason: str = Field(description="Brief explanation grounded in the conversation")


def _load_simplified_themes() -> tuple[list[dict[str, str]], dict[str, str]]:
    themes_path = os.path.join(os.path.dirname(__file__), "themes.json")
    with open(themes_path, "r", encoding="utf-8") as f:
        themes_data = json.load(f)

    simplified_themes = [
        {"id": t["id"], "name": t["name"], "description": t["description"]}
        for t in themes_data.get("themes", [])
    ]
    theme_name_by_id = {t["id"]: t["name"] for t in simplified_themes}
    return simplified_themes, theme_name_by_id


def _format_chat_history(history: list[dict[str, Any]]) -> str:
    lines = []
    for msg in history:
        role = msg.get("role")
        if role not in {"assistant", "user"}:
            continue
        if msg.get("mode") == "guide":
            continue
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        speaker = "Guide" if role == "assistant" else "Child"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines[-12:])


async def classify_conversation_to_theme(
    history: list[dict[str, Any]],
    object_name: str,
    age: int,
    client,
    config,
    key_concept: str = "",
    bridge_question: str = "",
) -> Optional[dict[str, str]]:
    """
    Classify the chat-phase conversation into one IB PYP theme.
    The conversation is authoritative; object and concept are supporting context only.
    """
    try:
        from paixueji_prompts import HISTORY_THEME_CLASSIFICATION_PROMPT

        simplified_themes, theme_name_by_id = _load_simplified_themes()
        conversation_text = _format_chat_history(history)
        if not conversation_text:
            logger.warning("[THEME_CLASSIFY] No chat history available for conversation theme analysis")
            return None

        prompt = HISTORY_THEME_CLASSIFICATION_PROMPT.format(
            object_name=object_name,
            age=age,
            key_concept=key_concept or "unknown",
            bridge_question=bridge_question or "unknown",
            themes_json=json.dumps(simplified_themes, indent=2),
            conversation_history=conversation_text,
        )

        logger.info(f"[THEME_CLASSIFY] Classifying conversation theme for: {object_name}")
        response = await client.aio.models.generate_content(
            model=config["model_name"],
            contents=prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        if not response.text:
            logger.error("[THEME_CLASSIFY] Empty response from conversation theme classifier")
            return None

        result = ConversationThemeClassificationResult(**json.loads(response.text))
        if result.theme_id not in theme_name_by_id:
            logger.error(f"[THEME_CLASSIFY] Unknown theme_id from conversation classifier: {result.theme_id}")
            return None

        if not result.theme_name:
            result.theme_name = theme_name_by_id[result.theme_id]

        logger.info(
            f"[THEME_CLASSIFY] Conversation theme success: {object_name} -> {result.theme_name}"
        )
        return result.model_dump()
    except Exception as e:
        logger.error(f"[THEME_CLASSIFY] Conversation theme classification failed: {e}")
        return None


__all__ = [
    "ConversationThemeClassificationResult",
    "classify_conversation_to_theme",
]
