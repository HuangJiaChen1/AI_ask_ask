from __future__ import annotations

from dataclasses import asdict, dataclass

import paixueji_prompts
from model_json import extract_json_object
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


@dataclass
class DiscoverySessionState:
    object_name: str
    profile: AttributeProfile
    age: int
    turn_count: int = 0
    activity_ready: bool = False
    surface_object_name: str | None = None
    anchor_object_name: str | None = None

    def to_debug_dict(self) -> dict:
        return asdict(self)


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
            config={"temperature": 0.0, "max_output_tokens": 120},
        )
        payload, payload_kind, recovered = extract_json_object(response.text or "")
    except Exception as exc:
        payload = None
        payload_kind = "exception"
        recovered = False
        exc_reason = str(exc)
    else:
        exc_reason = None

    if isinstance(payload, dict):
        chosen_id = payload.get("attribute_id")
        for profile in profiles:
            if profile.attribute_id == chosen_id:
                return profile, {
                    "decision": "attribute_selected",
                    "source": "gemini",
                    "attribute_id": profile.attribute_id,
                    "confidence": payload.get("confidence"),
                    "reason": payload.get("reason") or "selected by Gemini",
                    "payload_kind": payload_kind,
                    "json_recovery_applied": recovered,
                    "domain": domain,
                }

    fallback = profiles[0]
    return fallback, {
        "decision": "attribute_selected",
        "source": "first_candidate_fallback",
        "attribute_id": fallback.attribute_id,
        "confidence": "fallback",
        "reason": exc_reason or f"invalid Gemini attribute selection payload: {payload_kind}",
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
        raise ValueError("profile is required to start an attribute session")
    return DiscoverySessionState(
        object_name=object_name,
        profile=profile,
        age=6 if age is None else age,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
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
    response_text: str | None = None,
    intent_type: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "activity_marker_detected": activity_marker_detected,
        "activity_marker_reason": activity_marker_reason,
        "response_text": response_text,
        "intent_type": intent_type,
    }


AttributeSessionState = DiscoverySessionState
