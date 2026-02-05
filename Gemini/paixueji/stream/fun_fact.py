"""
Grounded fun fact generation for Paixueji assistant.

Uses Google Search Grounding to retrieve verified fun facts and real factual
context about objects, then structures them via a second JSON-mode call.

Two-step pipeline (grounding + JSON cannot be combined in one call):
1. Grounded Research: Gemini + Google Search -> raw facts text
2. JSON Structuring: Gemini + JSON mode -> structured fun facts + real facts
3. Cache pool: Store 3-5 fun facts, randomly pick one per conversation

Functions:
    - generate_fun_fact: Main entry point, returns one fun fact + real facts
    - get_cached_fun_fact: Cache lookup with random selection
    - cache_fun_fact: Store structured result in cache
"""

import json
import random
import time
from typing import Optional

from google.genai.types import Tool, GoogleSearch
from loguru import logger

import paixueji_prompts

# Module-level cache: object_name (lowercased) -> full structured result
_fun_fact_cache: dict[str, dict] = {}


def _pick_random_fact(cached: dict) -> dict:
    """Pick one random fun fact from a cached pool and combine with real_facts."""
    fun_facts = cached.get("fun_facts", [])
    if not fun_facts:
        return {"fun_fact": "", "hook": "", "question": "", "real_facts": ""}

    chosen = random.choice(fun_facts)
    return {
        "fun_fact": chosen.get("fun_fact", ""),
        "hook": chosen.get("hook", ""),
        "question": chosen.get("question", ""),
        "real_facts": cached.get("real_facts", "")
    }


def get_cached_fun_fact(object_name: str) -> Optional[dict]:
    """
    Look up cached fun facts for an object.

    Args:
        object_name: Name of the object to look up

    Returns:
        dict with one randomly-selected fun_fact + real_facts, or None if not cached
    """
    key = object_name.strip().lower()
    cached = _fun_fact_cache.get(key)
    if cached is None:
        return None

    result = _pick_random_fact(cached)
    logger.info(f"[FUN_FACT] Cache hit for '{object_name}' | fun_fact='{result['fun_fact'][:60]}...'")
    return result


def cache_fun_fact(object_name: str, fact_data: dict):
    """
    Store structured fun fact result in cache.

    Args:
        object_name: Name of the object
        fact_data: Full structured result with fun_facts list and real_facts
    """
    key = object_name.strip().lower()
    _fun_fact_cache[key] = fact_data
    count = len(fact_data.get("fun_facts", []))
    logger.info(f"[FUN_FACT] Cached {count} fun facts for '{object_name}'")


async def generate_fun_fact(
    object_name: str,
    age: int,
    config: dict,
    client,
    category: str = ""
) -> dict:
    """
    Generate grounded fun facts about an object using Google Search.

    Two-step pipeline:
    1. Gemini + Google Search Grounding -> raw research text
    2. Gemini + JSON mode -> structured fun facts + real facts

    Results are cached as a pool; one random fact is returned per call.

    Args:
        object_name: Name of the object
        age: Child's age (3-8)
        config: Configuration dict with model settings
        client: Gemini client instance
        category: Optional category context

    Returns:
        dict with keys: fun_fact, hook, question, real_facts
        On any error, returns empty strings for all keys (graceful fallback)
    """
    empty_fallback = {"fun_fact": "", "hook": "", "question": "", "real_facts": ""}

    # Check cache first
    cached_result = get_cached_fun_fact(object_name)
    if cached_result is not None:
        return cached_result

    grounding_model = config.get("grounding_model", config.get("model_name", "gemini-2.5-flash-lite"))

    # Safety settings: strict for children's content
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_LOW_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_LOW_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_LOW_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_LOW_AND_ABOVE"},
    ]

    # ── Step 1: Grounded Research ──
    try:
        prompts = paixueji_prompts.get_prompts()
        grounding_prompt = prompts['fun_fact_grounding_prompt'].format(
            object_name=object_name,
            age=age,
            category=category or "general"
        )

        logger.info(f"[FUN_FACT] Step 1: Grounded research for '{object_name}' (model={grounding_model})")
        t0 = time.time()

        grounding_response = await client.aio.models.generate_content(
            model=grounding_model,
            contents=grounding_prompt,
            config={
                "tools": [Tool(google_search=GoogleSearch())],
                "temperature": 0.3,
                "max_output_tokens": 1000,
                "safety_settings": safety_settings,
            }
        )

        t1 = time.time()
        grounded_text = grounding_response.text
        logger.info(f"[FUN_FACT] Step 1 completed in {t1 - t0:.3f}s | text_length={len(grounded_text or '')}")

        if not grounded_text or not grounded_text.strip():
            logger.warning(f"[FUN_FACT] Grounding returned empty text for '{object_name}'")
            return empty_fallback

    except Exception as e:
        logger.error(f"[FUN_FACT] Step 1 (grounding) failed for '{object_name}': {e}")
        return empty_fallback

    # ── Step 2: JSON Structuring ──
    try:
        structuring_prompt = prompts['fun_fact_structuring_prompt'].format(
            object_name=object_name,
            age=age,
            grounded_text=grounded_text
        )

        logger.info(f"[FUN_FACT] Step 2: JSON structuring for '{object_name}'")
        t0 = time.time()

        structuring_response = await client.aio.models.generate_content(
            model=grounding_model,
            contents=structuring_prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": 800,
                "safety_settings": safety_settings,
            }
        )

        t1 = time.time()
        logger.info(f"[FUN_FACT] Step 2 completed in {t1 - t0:.3f}s")

        # Parse JSON
        structured_data = json.loads(structuring_response.text)

        # Safety check: if content flagged as unsafe, return fallback
        if not structured_data.get("is_safe_for_kids", True):
            logger.warning(f"[FUN_FACT] Content flagged as unsafe for '{object_name}'")
            return empty_fallback

        # Validate structure
        fun_facts = structured_data.get("fun_facts", [])
        real_facts = structured_data.get("real_facts", "")

        if not fun_facts:
            logger.warning(f"[FUN_FACT] No fun facts in structured output for '{object_name}'")
            return empty_fallback

        # Cache the full result
        cache_fun_fact(object_name, structured_data)

        # Return one random fact + real_facts
        result = _pick_random_fact(structured_data)
        logger.info(
            f"[FUN_FACT] Success for '{object_name}' | "
            f"facts_count={len(fun_facts)}, "
            f"selected='{result['fun_fact'][:60]}...'"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[FUN_FACT] Step 2 JSON parse error for '{object_name}': {e}")
        return empty_fallback
    except Exception as e:
        logger.error(f"[FUN_FACT] Step 2 (structuring) failed for '{object_name}': {e}")
        return empty_fallback
