from __future__ import annotations

from dataclasses import asdict, dataclass, field

from activities import (
    ActivityDefinition,
    get_eligible_activities_for_object,
)
from stream.activity_discovery import discover_talkable_activities, ActivityDiscoveryResult
from stream.exploration_angles import AngleCoverageRecord
from stream.verification_guided_conversation import VerificationItem
from stream.llm_client import llm_generate
from stream.errors import RateLimitError


@dataclass
class DiscoverySessionState:
    """Activity-centric session state for the attribute lane."""
    object_name: str
    age: int
    turn_count: int = 0
    activity_ready: bool = False

    # Activity-centric fields (replaces old profile-centric state)
    primary_activity: ActivityDefinition | None = None
    primary_category: str = ""  # "ready" | "verifiable" | "weak"
    secondary_activities: list[ActivityDefinition] = field(default_factory=list)
    verification_queue: list[VerificationItem] = field(default_factory=list)
    verified_properties: dict[str, str] = field(default_factory=dict)  # property -> verified|rejected|unclear
    current_topic: str | None = None

    # Angle coverage tracking (CARES Phase 0)
    explored_angle_ids: list[str] = field(default_factory=list)
    angle_records: list[AngleCoverageRecord] = field(default_factory=list)
    current_angle_id: str | None = None

    # Legacy compatibility: profile fields for topic switching
    profile: "AttributeProfile | None" = None
    fallback_profiles: tuple = ()
    switched_to: str | None = None
    switch_reason: str | None = None
    last_activity_ready_rejected_reason: str | None = None
    surface_object_name: str | None = None
    anchor_object_name: str | None = None

    def to_debug_dict(self) -> dict:
        d = asdict(self)
        # Strip non-serializable objects for debug output
        if self.primary_activity:
            d["primary_activity"] = {
                "activity_id": self.primary_activity.activity_id,
                "name": self.primary_activity.name,
            }
        d["secondary_activities"] = [
            {"activity_id": a.activity_id, "name": a.name}
            for a in self.secondary_activities
        ]
        return d

    def record_angle(
        self,
        turn_index: int,
        angle_id: str,
        question_text: str,
        response_text: str,
    ) -> None:
        """Record that an angle was used for a given turn."""
        self.explored_angle_ids.append(angle_id)
        self.angle_records.append(
            AngleCoverageRecord(
                angle_id=angle_id,
                turn_index=turn_index,
                question_text=question_text,
                response_text=response_text,
            )
        )


# Legacy AttributeProfile kept for compatibility during transition
@dataclass(frozen=True)
class AttributeProfile:
    attribute_id: str
    label: str
    activity_target: str
    branch: str
    object_examples: tuple[str, ...]
    redirect_entity: str | None = None
    fallback_attributes: tuple = ()


# ---------------------------------------------------------------------------
# Public API — activity selection (replaces select_attribute_profile)
# ---------------------------------------------------------------------------
async def select_activities_for_object(
    *,
    object_name: str,
    anchor_name: str | None,
    age: int,
    client,
    config: dict | None,
) -> tuple[DiscoverySessionState | None, dict]:
    """Select activities for an object using the new activity-driven flow.

    Returns:
        (DiscoverySessionState, debug_dict) — state is None if no match.
    """
    resolved_age = 6 if age is None else age
    resolved_anchor = (anchor_name or object_name).strip().lower()

    # Layer 1: Code filter — eligible activities from catalog
    eligible = get_eligible_activities_for_object(resolved_anchor, resolved_age)

    if not eligible:
        return None, {
            "decision": "no_eligible",
            "source": "empty_catalog",
            "reason": f"no eligible activities for {resolved_anchor}, age={resolved_age}",
        }

    # Layer 2: LLM selection from eligible activities
    try:
        discovery_result, discovery_debug = await discover_talkable_activities(
            eligible_activities=eligible,
            object_name=object_name,
            anchor_name=resolved_anchor,
            age=resolved_age,
            client=client,
            config=config,
        )
    except RateLimitError:
        raise
    except Exception as exc:
        return None, {
            "decision": "discovery_error",
            "reason": str(exc),
        }

    if not discovery_result.proceed or not discovery_result.primary_activity_id:
        return None, {
            "decision": "no_strong_match",
            "source": "llm",
            "assessment": discovery_result.assessment,
            **discovery_debug,
        }

    # Resolve primary and secondary activity definitions
    id_to_activity = {a.activity_id: a for a in eligible}
    primary = id_to_activity.get(discovery_result.primary_activity_id)
    if not primary:
        return None, {
            "decision": "primary_not_in_eligible",
            "reason": f"LLM returned {discovery_result.primary_activity_id} not in eligible",
        }

    secondary = [
        id_to_activity[sid]
        for sid in discovery_result.secondary_activity_ids
        if sid in id_to_activity and sid != primary.activity_id
    ]

    # Build verification queue
    verification_queue = [
        VerificationItem(
            property=v.get("property", ""),
            question=v.get("question", ""),
            for_activity_id=v.get("for_activity", ""),
        )
        for v in discovery_result.verification_queue
    ]

    # Build legacy AttributeProfile for compatibility during transition
    primary_profile = AttributeProfile(
        attribute_id=f"activity.{primary.activity_id}",
        label=primary.name,
        activity_target=primary.preview_prompt or primary.description,
        branch="in_kb",
        object_examples=(object_name,),
    )

    state = DiscoverySessionState(
        object_name=object_name,
        age=resolved_age,
        primary_activity=primary,
        primary_category=discovery_result.primary_category,
        secondary_activities=secondary,
        verification_queue=verification_queue,
        profile=primary_profile,
    )

    return state, {
        "decision": "activities_selected",
        "source": "llm",
        "primary_activity_id": primary.activity_id,
        "secondary_activity_ids": [a.activity_id for a in secondary],
        "verification_count": len(verification_queue),
        **discovery_debug,
    }


# ---------------------------------------------------------------------------
# Public API — session start
# ---------------------------------------------------------------------------
def start_attribute_session(
    state: DiscoverySessionState = None,
    *,
    object_name: str = "",
    profile: AttributeProfile = None,
    age: int | None = None,
    surface_object_name: str | None = None,
    anchor_object_name: str | None = None,
) -> DiscoverySessionState:
    """Initialize an attribute lane session.

    Supports two calling conventions:
      1. New: start_attribute_session(state)
      2. Legacy: start_attribute_session(object_name=..., profile=..., age=...)
    """
    if state is not None and isinstance(state, DiscoverySessionState):
        return state
    # Legacy path
    if profile is None:
        raise ValueError("profile is required for legacy start_attribute_session")
    return DiscoverySessionState(
        object_name=object_name,
        age=6 if age is None else age,
        profile=profile,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        fallback_profiles=profile.fallback_attributes,
    )


# ---------------------------------------------------------------------------
# Public API — debug builder
# ---------------------------------------------------------------------------
def build_attribute_debug(
    *,
    decision: str,
    profile: AttributeProfile | None = None,
    state: DiscoverySessionState | None = None,
    reason: str | None = None,
    activity_marker_detected: bool = False,
    activity_marker_reason: str | None = None,
    activity_marker_rejected_reason: str | None = None,
    response_text: str | None = None,
    intent_type: str | None = None,
    reply_type: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "activity_marker_detected": activity_marker_detected,
        "activity_marker_reason": activity_marker_reason,
        "activity_marker_rejected_reason": activity_marker_rejected_reason,
        "response_text": response_text,
        "intent_type": intent_type,
        "reply_type": reply_type,
    }


# Compatibility alias
AttributeSessionState = DiscoverySessionState


# ---------------------------------------------------------------------------
# Backward compatibility wrappers (deprecated — use select_activities_for_object)
# ---------------------------------------------------------------------------
import warnings

from stream.exploration_loader import (
    SubAttributeCandidate,
    dimension_to_activity_target,
    get_candidate_sub_attributes,
    infer_domain,
    sub_attribute_to_label,
)
import paixueji_prompts
from model_json import extract_json_object
from activities import attribute_to_angles


def _anchor_status_to_branch(anchor_status: str | None) -> str:
    if anchor_status == "exact_supported":
        return "in_kb"
    if anchor_status in ("anchored_high", "anchored_medium"):
        return "anchored_not_in_kb"
    return "unresolved_not_in_kb"


def _candidate_to_profile(
    candidate: SubAttributeCandidate,
    object_name: str,
    branch: str,
) -> AttributeProfile:
    return AttributeProfile(
        attribute_id=f"{candidate.dimension}.{candidate.sub_attribute}",
        label=sub_attribute_to_label(candidate.sub_attribute),
        activity_target=dimension_to_activity_target(candidate.dimension, object_name, candidate.sub_attribute),
        branch=branch,
        object_examples=(object_name,),
    )


def _build_supported_attribute_block(profiles: tuple[AttributeProfile, ...]) -> str:
    lines = []
    for profile in profiles:
        lines.append(
            f"- {profile.attribute_id}: {profile.label}; activity={profile.activity_target}; "
            f"branch={profile.branch}"
        )
    return "\n".join(lines)


async def select_attribute_profile(
    *,
    object_name: str,
    age: int | None,
    anchor_status: str | None = None,
    available_angles: set[str] | None = None,
    client,
    config: dict | None,
) -> tuple[AttributeProfile | None, dict]:
    """DEPRECATED: Use select_activities_for_object instead."""
    warnings.warn(
        "select_attribute_profile is deprecated. Use select_activities_for_object instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    resolved_age = 6 if age is None else age
    branch = _anchor_status_to_branch(anchor_status)

    domain = await infer_domain(object_name, client, config)

    candidates = get_candidate_sub_attributes(domain, resolved_age)

    if available_angles:
        candidates = [
            c for c in candidates
            if any(a in available_angles for a in attribute_to_angles(f"{c.dimension}.{c.sub_attribute}"))
        ]

    if not candidates:
        return None, {
            "decision": "no_attribute_match_fallback",
            "source": "empty_candidates",
            "attribute_id": None,
            "confidence": None,
            "reason": f"no candidates for domain={domain}, age={resolved_age}",
            "domain": domain,
        }

    profiles = tuple(
        _candidate_to_profile(c, object_name, branch) for c in candidates
    )

    # Only one candidate — return directly with no fallback
    if len(profiles) == 1:
        return profiles[0], {
            "decision": "attribute_selected",
            "source": "only_candidate",
            "attribute_id": profiles[0].attribute_id,
            "fallback_attribute_ids": [],
            "confidence": "high",
            "reason": "only one candidate available",
            "domain": domain,
        }

    prompt = paixueji_prompts.get_prompts()["attribute_selection_prompt"].format(
        object_name=object_name,
        age=resolved_age,
        domain=domain or "unknown",
        supported_attributes=_build_supported_attribute_block(profiles),
    )

    try:
        response = await client.aio.models.generate_content(
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 256},
        )
        payload, payload_kind, recovered = extract_json_object(response.text or "")
    except Exception as exc:
        payload = None
        payload_kind = "exception"
        recovered = False
        exc_reason = str(exc)
    else:
        exc_reason = None

    chosen_id = None
    fallback_ids = []
    if isinstance(payload, dict):
        chosen_id = payload.get("attribute_id")
        raw_fallbacks = payload.get("fallback_attribute_ids")
        if isinstance(raw_fallbacks, list):
            fallback_ids = raw_fallbacks
        elif isinstance(raw_fallbacks, str):
            fallback_ids = [raw_fallbacks]

    # Find primary profile
    primary = next((p for p in profiles if p.attribute_id == chosen_id), profiles[0])

    # Collect up to 2 fallback profiles, preserving order and excluding primary
    fallbacks = []
    seen = {primary.attribute_id}
    for fb_id in fallback_ids:
        if fb_id in seen:
            continue
        match = next((p for p in profiles if p.attribute_id == fb_id), None)
        if match and len(fallbacks) < 2:
            fallbacks.append(match)
            seen.add(match.attribute_id)

    # If no valid fallbacks from model, pick from remaining candidates
    if not fallbacks:
        for p in profiles:
            if p.attribute_id != primary.attribute_id and len(fallbacks) < 2:
                fallbacks.append(p)
                break

    # Build primary with fallbacks embedded
    primary_with_fallback = AttributeProfile(
        attribute_id=primary.attribute_id,
        label=primary.label,
        activity_target=primary.activity_target,
        branch=primary.branch,
        object_examples=primary.object_examples,
        redirect_entity=primary.redirect_entity,
        fallback_attributes=tuple(fallbacks),
    )

    source = "gemini" if chosen_id and any(p.attribute_id == chosen_id for p in profiles) else "first_candidate_fallback"
    return primary_with_fallback, {
        "decision": "attribute_selected",
        "source": source,
        "attribute_id": primary_with_fallback.attribute_id,
        "fallback_attribute_ids": [fb.attribute_id for fb in fallbacks],
        "confidence": payload.get("confidence") if isinstance(payload, dict) else ("fallback" if source == "first_candidate_fallback" else "high"),
        "reason": (payload.get("reason") if isinstance(payload, dict) else None) or exc_reason or f"invalid Gemini attribute selection payload: {payload_kind}",
        "payload_kind": payload_kind,
        "json_recovery_applied": recovered,
        "domain": domain,
    }


def _legacy_start_attribute_session(
    *,
    object_name: str,
    profile: AttributeProfile,
    age: int | None,
    surface_object_name: str | None = None,
    anchor_object_name: str | None = None,
) -> DiscoverySessionState:
    """Legacy start_attribute_session signature kept for compatibility."""
    if profile is None:
        raise ValueError("profile is required")
    return DiscoverySessionState(
        object_name=object_name,
        age=6 if age is None else age,
        profile=profile,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        fallback_profiles=profile.fallback_attributes,
    )
