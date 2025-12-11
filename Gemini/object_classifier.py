"""
Object Classifier for Child Learning Assistant
Uses LLM to classify objects into level2 categories
"""

import json
import os
import requests


# Available level 2 categories
LEVEL2_CATEGORIES = {
    'fresh_ingredients': 'Foods',
    'processed_foods': 'Foods',
    'beverages_drinks': 'Foods',
    'vertebrates': 'Animals',
    'invertebrates': 'Animals',
    'human_raised_animals': 'Animals',
    'ornamental_plants': 'Plants',
    'useful_plants': 'Plants',
    'wild_natural_plants': 'Plants'
}


def classify_object(object_name, config_path="config.json"):
    """
    Classify an object into one of the level2 categories using LLM.

    Args:
        object_name: The name of the object to classify
        config_path: Path to config.json with API credentials

    Returns:
        str or None: The level2 category (e.g., 'fresh_ingredients') or None if cannot classify
    """
    # Load config
    if not os.path.exists(config_path):
        print(f"[WARNING] Config file not found: {config_path}")
        return None

    with open(config_path, 'r') as f:
        config = json.load(f)

    if config.get("gemini_api_key") == "YOUR_GEMINI_API_KEY_HERE":
        print("[WARNING] API key not configured, cannot classify object")
        return None

    # Build classification prompt
    categories_list = "\n".join([f"- {cat}" for cat in LEVEL2_CATEGORIES.keys()])

    prompt = f"""Classify this object: "{object_name}"

Choose EXACTLY ONE category from this list:
{categories_list}

CRITICAL: You must respond with ONLY ONE of these EXACT category names, nothing else.
- If it's a food, use: fresh_ingredients, processed_foods, or beverages_drinks
- If it's an animal, use: vertebrates, invertebrates, or human_raised_animals
- If it's a plant, use: ornamental_plants, useful_plants, or wild_natural_plants
- If none fit, respond with: NONE

Your response (EXACT category name only):"""

    try:
        headers = {
            "Authorization": f"Bearer {config['gemini_api_key']}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": config.get("model_name", "gemini-2.5-pro"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,  # Lower temperature for more consistent classification
            "max_tokens": 200  # Increased to handle potential reasoning tokens
        }

        response = requests.post(
            config.get("api_base_url"),
            headers=headers,
            json=payload,
            timeout=10
        )
        response.raise_for_status()

        response_data = response.json()
        content = response_data["choices"][0]["message"]["content"].strip().lower()

        print(f"[DEBUG] Classification response for '{object_name}': {content}")

        # Extract just the category name (in case LLM added extra text)
        # First, try exact match (most specific)
        if content in LEVEL2_CATEGORIES.keys():
            print(f"[INFO] Classified '{object_name}' as '{content}'")
            return content

        # Then try substring match
        for category in LEVEL2_CATEGORIES.keys():
            if category in content:
                print(f"[INFO] Classified '{object_name}' as '{category}' (substring match)")
                return category

        # Check if response was "none"
        if "none" in content:
            print(f"[INFO] Could not classify '{object_name}' into any category")
            return None

        print(f"[WARNING] Unexpected classification response: {content}")
        return None

    except Exception as e:
        print(f"[ERROR] Classification failed: {str(e)}")
        return None


def get_category_display_name(level2_category):
    """
    Get the display name for a level2 category.

    Args:
        level2_category: The level2 category name

    Returns:
        str: Human-readable category name
    """
    # Replace underscores with spaces and title case
    return level2_category.replace('_', ' ').title()
