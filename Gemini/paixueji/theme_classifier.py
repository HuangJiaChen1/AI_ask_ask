"""
IB PYP Theme Classifier - LLM-based object to theme classification.

This module classifies objects into one of the 6 IB PYP Transdisciplinary Themes
using an LLM. Classification runs in the background and updates the assistant state.
"""
import json
import os
from typing import Optional
from pydantic import BaseModel, Field
from loguru import logger


class ThemeClassificationResult(BaseModel):
    """Result of classifying an object into an IB PYP theme."""
    theme_id: str = Field(description="The ID of the matching IB PYP theme")
    theme_name: str = Field(description="The English name of the theme")
    reason: str = Field(description="Brief explanation for why the object fits this theme")
    key_concept: Optional[str] = Field(None, description="The selected IB PYP Key Concept (e.g., Function, Change)")
    key_concept_reason: Optional[str] = Field(None, description="Why this key concept was selected")
    bridge_question: Optional[str] = Field(None, description="A heuristic bridge question connecting object -> concept -> theme")
    thinking: Optional[str] = Field(None, description="Internal Chain-of-Thought reasoning for classification and question generation")


def classify_object_to_theme(object_name: str, client, config) -> Optional[ThemeClassificationResult]:
    """
    Classifies an object into one of the 6 IB PYP themes using LLM.
    Uses the advanced prompt from paixueji_prompts.py.
    """
    try:
        from paixueji_prompts import THEME_CLASSIFICATION_PROMPT
        
        # Load themes
        themes_path = os.path.join(os.path.dirname(__file__), 'themes.json')
        with open(themes_path, 'r', encoding='utf-8') as f:
            themes_data = json.load(f)
            # Remove detailed keywords to save tokens, keep id/name/desc
            simplified_themes = [
                {"id": t["id"], "name": t["name"], "description": t["description"]} 
                for t in themes_data.get("themes", [])
            ]
            themes_json = json.dumps(simplified_themes, indent=2)

        # Load concepts
        concepts_path = os.path.join(os.path.dirname(__file__), 'concepts.json')
        with open(concepts_path, 'r', encoding='utf-8') as f:
            concepts_data = json.load(f)
            concepts_json = json.dumps(concepts_data.get("concepts", []), indent=2)

        prompt = THEME_CLASSIFICATION_PROMPT.format(
            object_name=object_name,
            themes_json=themes_json,
            concepts_json=concepts_json
        )

        logger.info(f"[THEME_CLASSIFY] Classifying object: {object_name}")

        response = client.models.generate_content(
            model=config["model_name"],
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'temperature': 0.1,  # Low temp for deterministic classification
            }
        )

        if not response.text:
            logger.error("[THEME_CLASSIFY] Empty response from LLM")
            return None

        result_dict = json.loads(response.text)
        result = ThemeClassificationResult(**result_dict)
        
        logger.info(f"[THEME_CLASSIFY] SUCCESS: {object_name} -> {result.theme_id} | Concept: {result.key_concept} | Question: {result.bridge_question} | Thinking: {result.thinking}")
        return result

    except Exception as e:
        logger.error(f"[THEME_CLASSIFY] Error classifying object: {e}")
        return None