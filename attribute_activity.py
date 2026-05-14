from __future__ import annotations

from dataclasses import asdict, dataclass, field

import paixueji_prompts
from model_json import extract_json_object
from stream.exploration_angles import AngleCoverageRecord
from stream.exploration_loader import (
    SubAttributeCandidate,
    dimension_to_activity_target,
    get_candidate_sub_attributes,
    infer_domain,
    sub_attribute_to_label,
)


@dataclass(frozen=True)
class AttributeProfile:
    attribute_id: str
    label: str
    activity_target: str
    branch: str
    object_examples: tuple[str, ...]
    redirect_entity: str | None = None
    # NEW: fallback attributes for in-lane dynamic switching
    fallback_attributes: tuple["AttributeProfile", ...] = ()


@dataclass
class DiscoverySessionState:
    object_name: str
    profile: AttributeProfile
    age: int
    turn_count: int = 0
    activity_ready: bool = False
    surface_object_name: str | None = None
    anchor_object_name: str | None = None
    # NEW: fallback tracking and switch history
    fallback_profiles: tuple[AttributeProfile, ...] = ()
    switched_to: str | None = None
    switch_reason: str | None = None
    last_activity_ready_rejected_reason: str | None = None
    # NEW: angle coverage tracking (CARES Phase 0)
    explored_angle_ids: list[str] = field(default_factory=list)
    angle_records: list[AngleCoverageRecord] = field(default_factory=list)
    current_angle_id: str | None = None

    def to_debug_dict(self) -> dict:
        d = asdict(self)
        # AngleCoverageRecord is a dataclass; asdict handles it recursively
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
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


def _build_fallback_attribute_block(profiles: tuple[AttributeProfile, ...]) -> str:
    if not profiles:
        return "(no fallback topics)"
    lines = []
    for profile in profiles:
        lines.append(
            f"- {profile.attribute_id}: {profile.label}; activity={profile.activity_target}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API — attribute selection
# ---------------------------------------------------------------------------
async def select_attribute_profile(
    *,
    object_name: str,
    age: int | None,
    anchor_status: str | None = None,
    client,
    config: dict | None,
) -> tuple[AttributeProfile | None, dict]:
    resolved_age = 6 if age is None else age
    branch = _anchor_status_to_branch(anchor_status)

    domain = await infer_domain(object_name, client, config)

    candidates = get_candidate_sub_attributes(domain, resolved_age)

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


# ---------------------------------------------------------------------------
# Public API — session start
# ---------------------------------------------------------------------------
def start_attribute_session(
    *,
    object_name: str,
    profile: AttributeProfile,
    age: int | None,
    surface_object_name: str | None = None,
    anchor_object_name: str | None = None,
) -> DiscoverySessionState:
    if profile is None:
        raise ValueError("profile is required")
    return DiscoverySessionState(
        object_name=object_name,
        profile=profile,
        age=6 if age is None else age,
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
    profile: AttributeProfile | None,
    state: DiscoverySessionState | None,
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


AttributeSessionState = DiscoverySessionState
