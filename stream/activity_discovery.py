"""Activity discovery — LLM-driven activity selection from eligible catalog."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from activities import ActivityDefinition
from stream.llm_client import llm_generate
from stream.errors import RateLimitError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


@dataclass
class ActivityDiscoveryResult:
    """Output of discover_talkable_activities."""
    primary_activity_id: str | None = None
    primary_category: str = ""           # "ready" | "verifiable" | "weak"
    secondary_activity_ids: list[str] = field(default_factory=list)
    verification_queue: list[dict] = field(default_factory=list)
    assessment: str = ""
    proceed: bool = False
    all_activity_categories: dict[str, str] = field(default_factory=dict)  # activity_id -> category


def _build_activity_block(activity: ActivityDefinition) -> str:
    """Format a single activity for the LLM prompt (condensed: ID + angle + focal attribute)."""
    return (
        f"- ID: {activity.activity_id}\n"
        f"  Observation angle: {activity.observation_angle or 'any'}\n"
        f"  Focal attribute: {activity.focal_attribute or '(none)'}"
    )


async def discover_talkable_activities(
    eligible_activities: list[ActivityDefinition],
    object_name: str,
    anchor_name: str,
    age: int,
    client,
    config: dict | None,
) -> tuple[ActivityDiscoveryResult, dict]:
    """Ask LLM to select the best activity(ies) for this object.

    Returns:
        (ActivityDiscoveryResult, debug_dict)
    """
    if not eligible_activities:
        return ActivityDiscoveryResult(
            proceed=False,
            assessment="No eligible activities in catalog",
        ), {
            "decision": "no_eligible",
            "reason": "empty_catalog",
        }

    activity_block = "\n\n".join(
        _build_activity_block(a) for a in eligible_activities
    )

    prompt = f"""You are an activity matcher for a children's education conversation system.

Object the child mentioned: "{object_name}"
Anchor object (canonical name): "{anchor_name}"
Child age: {age}

Below are the eligible activities for this object. Your job is to pick the BEST match and decide whether we can proceed.

ELIGIBLE ACTIVITIES:
{activity_block}

INSTRUCTIONS:
1. For each activity, judge whether the object plausibly has the focal attribute under that observation angle.
   Example: object="orange cat", activity=(angle=color, focal_attribute=body_color) → the cat clearly has a color → "ready"
   Example: object="cat", activity=(angle=pattern, focal_attribute=polka_dots) → the cat might have spots, but we need to check → "verifiable"
   Example: object="apple", activity=(angle=origin, focal_attribute=time_period) → an apple doesn't have a time period → "weak"

2. Category rules:
   - "ready": the object clearly possesses the focal attribute for that angle
   - "verifiable": the object might possess it, but a child would need to confirm first
   - "weak": the object does not plausibly have this attribute/angle combination

3. If the best match is verifiable, list 1-3 specific properties to verify. Use the exact focal_attribute names when possible.

4. If NO activity is a strong or verifiable match, set proceed=false. Do NOT force a match.

5. For EVERY eligible activity (not just primary/secondary), output its category in `all_activities`.

6. Respond ONLY with valid JSON (no markdown fences, no extra text):
{{
  "primary": {{"activity_id": "...", "topic": "...", "category": "ready|verifiable|weak", "certainty": "high|medium|low", "why": "..."}},
  "secondary": [{{"activity_id": "...", "category": "...", "why": "..."}}],
  "all_activities": [{{"activity_id": "...", "category": "ready|verifiable|weak"}}],
  "verification_queue": [{{"property": "has_polka_dots", "question": "Does it have polka dots?", "for_activity": "polka_dot_patrol"}}],
  "assessment": "...",
  "proceed": true|false
}}"""

    try:
        response = await llm_generate(
            client=client,
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.1, "max_output_tokens": 2048},
            call_name="discover_talkable_activities",
        )
        raw_text = response.text or ""

        # Debug: log full raw response for troubleshooting parse failures
        logger.info(
            "[ACTIVITY_DISCOVERY] raw_text_len=%d finish_reason=%r raw_preview=%r",
            len(raw_text),
            getattr(response.candidates[0], "finish_reason", "N/A") if getattr(response, "candidates", None) else "N/A",
            raw_text[:500],
        )

        # Extract JSON even if wrapped in fences
        match = _JSON_FENCE_RE.search(raw_text)
        json_text = match.group(1) if match else raw_text
        parsed = json.loads(json_text)

        primary = parsed.get("primary", {}) or {}
        secondary = parsed.get("secondary", []) or []
        all_activities = parsed.get("all_activities", []) or []
        verification_queue = parsed.get("verification_queue", []) or []
        proceed = bool(parsed.get("proceed", False))

        # Build all_activity_categories map
        valid_ids = {a.activity_id for a in eligible_activities}
        all_categories: dict[str, str] = {}
        for item in all_activities:
            aid = item.get("activity_id")
            if aid and aid in valid_ids:
                all_categories[aid] = item.get("category", "weak")
        # Fallback: infer from primary/secondary if all_activities missing
        if not all_categories:
            pid = primary.get("activity_id")
            if pid and pid in valid_ids:
                all_categories[pid] = primary.get("category", "ready")
            for s in secondary:
                sid = s.get("activity_id")
                if sid and sid in valid_ids:
                    all_categories[sid] = s.get("category", "verifiable")
            for aid in valid_ids:
                if aid not in all_categories:
                    all_categories[aid] = "weak"

        # Validate primary activity_id exists in eligible
        primary_id = primary.get("activity_id")
        if primary_id and primary_id not in valid_ids:
            logger.warning(
                "[ACTIVITY_DISCOVERY] primary %s not in eligible %s",
                primary_id, valid_ids,
            )
            primary_id = None
            proceed = False

        result = ActivityDiscoveryResult(
            primary_activity_id=primary_id,
            primary_category=primary.get("category", ""),
            secondary_activity_ids=[
                s.get("activity_id") for s in secondary
                if s.get("activity_id") in valid_ids
            ],
            verification_queue=[
                {
                    "property": v.get("property", ""),
                    "question": v.get("question", ""),
                    "for_activity": v.get("for_activity", ""),
                }
                for v in verification_queue
                if v.get("property")
            ],
            assessment=parsed.get("assessment", ""),
            proceed=proceed and primary_id is not None,
            all_activity_categories=all_categories,
        )

        debug = {
            "decision": "discovered" if result.proceed else "no_proceed",
            "primary_id": result.primary_activity_id,
            "primary_category": result.primary_category,
            "secondary_ids": result.secondary_activity_ids,
            "all_categories": result.all_activity_categories,
            "verification_count": len(result.verification_queue),
            "assessment": result.assessment,
            "raw_response": raw_text[:500],
        }
        return result, debug

    except RateLimitError:
        raise
    except json.JSONDecodeError as exc:
        logger.warning("[ACTIVITY_DISCOVERY] JSON parse error: %s | raw=%r", exc, raw_text[:200])
        return ActivityDiscoveryResult(proceed=False), {
            "decision": "parse_error",
            "reason": str(exc),
            "raw_response": raw_text[:200],
        }
    except Exception as exc:
        logger.warning("[ACTIVITY_DISCOVERY] error: %s", exc)
        return ActivityDiscoveryResult(proceed=False), {
            "decision": "error",
            "reason": str(exc),
        }
