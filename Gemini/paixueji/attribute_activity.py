from __future__ import annotations

from dataclasses import asdict, dataclass

import paixueji_prompts
from model_json import extract_json_object
from stream.exploration_loader import (
    SubAttributeCandidate,
    get_candidate_sub_attributes,
    infer_domain,
    sub_attribute_to_label,
    dimension_to_activity_target,
)


ATTRIBUTE_ACTIVITY_READY_TURN_THRESHOLD = 2
ACTIVITY_COMMAND_WORDS = {"let's", "lets", "game", "play", "activity", "ready"}


@dataclass(frozen=True)
class AttributeProfile:
    attribute_id: str
    label: str
    activity_target: str
    branch: str
    object_examples: tuple[str, ...]
    redirect_entity: str | None = None


@dataclass
class AttributeSessionState:
    object_name: str
    profile: AttributeProfile
    age: int
    turn_count: int = 0
    activity_ready: bool = False
    last_question: str | None = None
    surface_object_name: str | None = None
    anchor_object_name: str | None = None

    def to_debug_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AttributeReplyDecision:
    reply_type: str
    attribute_id: str
    counted_turn: bool
    activity_ready: bool
    state_action: str
    reason: str

    def to_debug_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AttributeReadinessDecision:
    activity_ready: bool
    chat_phase_complete: bool
    state_action: str
    reason: str
    engaged_turn_count: int
    readiness_threshold: int
    readiness_source: str = "backend_engagement_policy"

    def to_debug_dict(self) -> dict:
        return asdict(self)


def _normalize(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def _contains_activity_command(text: str) -> bool:
    words = {word.strip(".,!?;:") for word in text.split()}
    return bool(ACTIVITY_COMMAND_WORDS.intersection(words))


def _anchor_status_to_branch(anchor_status: str | None) -> str:
    """Map anchor_status to attribute branch."""
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
    """Convert a SubAttributeCandidate to an AttributeProfile."""
    return AttributeProfile(
        attribute_id=f"{candidate.dimension}.{candidate.sub_attribute}",
        label=sub_attribute_to_label(candidate.sub_attribute),
        activity_target=dimension_to_activity_target(candidate.dimension, object_name, candidate.sub_attribute),
        branch=branch,
        object_examples=(object_name,),
    )


def _build_supported_attribute_block(profiles: tuple[AttributeProfile, ...]) -> str:
    """Build the text block listing all candidate attributes for the Gemini prompt."""
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
    client,
    config: dict | None,
) -> tuple[AttributeProfile | None, dict]:
    """
    Select an attribute profile for the given object.

    Dynamically generates candidates from exploration_categories.yaml
    based on the surface object's domain and the child's age tier.
    Then asks Gemini to pick the best one.

    Args:
        object_name: The surface object the child named.
        age: Child's age.
        anchor_status: From object resolution — determines the branch.
        client: Gemini client.
        config: Config dict with model_name.

    Returns:
        (AttributeProfile | None, debug_dict)
    """
    resolved_age = age or 6
    branch = _anchor_status_to_branch(anchor_status)

    # Determine domain for the surface object
    domain = await infer_domain(object_name, client, config)

    # Generate candidates from YAML
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

    # Convert all candidates to profiles
    profiles = tuple(
        _candidate_to_profile(c, object_name, branch) for c in candidates
    )

    # Ask Gemini to select
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

    # Try to match Gemini's choice to a profile
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

    # Fallback: use the first candidate
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


def start_attribute_session(
    *,
    object_name: str,
    profile: AttributeProfile,
    age: int | None,
    surface_object_name: str | None = None,
    anchor_object_name: str | None = None,
) -> AttributeSessionState:
    if profile is None:
        raise ValueError("profile is required to start an attribute session")
    return AttributeSessionState(
        object_name=object_name,
        profile=profile,
        age=age or 6,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
    )


def classify_attribute_reply(
    state: AttributeSessionState,
    child_reply: str | None,
) -> AttributeReplyDecision:
    text = _normalize(child_reply)
    object_name = _normalize(state.object_name)
    attribute_words = set(_normalize(state.profile.label).replace("/", " ").split())

    if any(token in text for token in ("don't know", "dont know", "not sure", "idk", "maybe")):
        return AttributeReplyDecision(
            reply_type="uncertainty",
            attribute_id=state.profile.attribute_id,
            counted_turn=False,
            activity_ready=False,
            state_action="scaffold_attribute",
            reason="child expressed uncertainty",
        )

    if any(token in text for token in ("can't", "cannot", "dont want", "don't want", "stop", "no more")):
        return AttributeReplyDecision(
            reply_type="constraint_avoidance",
            attribute_id=state.profile.attribute_id,
            counted_turn=False,
            activity_ready=False,
            state_action="low_pressure_repair",
            reason="child expressed constraint or avoidance",
        )

    if _contains_activity_command(text):
        return AttributeReplyDecision(
            reply_type="activity_command",
            attribute_id=state.profile.attribute_id,
            counted_turn=False,
            activity_ready=False,
            state_action="acknowledge_keep_attribute",
            reason="child mentioned play or activity, but readiness is backend-policy driven",
        )

    if "?" in (child_reply or "") or text.startswith(("why ", "how ", "what ", "where ", "can ")):
        return AttributeReplyDecision(
            reply_type="curiosity",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=False,
            state_action="answer_and_reconnect",
            reason="child asked a curiosity question",
        )

    drift_words = {"crunchy", "sweet", "color", "red", "green", "tail", "eyes", "bowl"}
    text_words = set(text.split())
    if object_name and object_name in text and drift_words.intersection(text_words) and not attribute_words.intersection(text_words):
        return AttributeReplyDecision(
            reply_type="same_object_feature_drift",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=False,
            state_action="accept_then_return_to_attribute",
            reason="child stayed on object but shifted feature",
        )

    other_object_words = {"spoon", "ball", "toy", "car", "rock", "cup", "bowl", "blanket"}
    if attribute_words.intersection(text_words) and other_object_words.intersection(text_words) and object_name not in text:
        return AttributeReplyDecision(
            reply_type="new_object_same_attribute_drift",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=False,
            state_action="accept_comparison_keep_attribute",
            reason="child named another object with same attribute",
        )

    return AttributeReplyDecision(
        reply_type="aligned",
        attribute_id=state.profile.attribute_id,
        counted_turn=True,
        activity_ready=False,
        state_action="continue_attribute_lane",
        reason="child stayed aligned with selected attribute",
    )


def evaluate_attribute_activity_readiness(
    state: AttributeSessionState,
    reply: AttributeReplyDecision,
) -> AttributeReadinessDecision:
    if state.activity_ready:
        return AttributeReadinessDecision(
            activity_ready=True,
            chat_phase_complete=True,
            state_action="invite_attribute_activity",
            reason="attribute activity was already ready",
            engaged_turn_count=state.turn_count,
            readiness_threshold=ATTRIBUTE_ACTIVITY_READY_TURN_THRESHOLD,
        )

    if reply.counted_turn and state.turn_count >= ATTRIBUTE_ACTIVITY_READY_TURN_THRESHOLD:
        return AttributeReadinessDecision(
            activity_ready=True,
            chat_phase_complete=True,
            state_action="invite_attribute_activity",
            reason="child completed two coherent attribute-engaged turns",
            engaged_turn_count=state.turn_count,
            readiness_threshold=ATTRIBUTE_ACTIVITY_READY_TURN_THRESHOLD,
        )

    return AttributeReadinessDecision(
        activity_ready=False,
        chat_phase_complete=False,
        state_action=reply.state_action,
        reason="attribute engagement threshold not reached",
        engaged_turn_count=state.turn_count,
        readiness_threshold=ATTRIBUTE_ACTIVITY_READY_TURN_THRESHOLD,
    )


def build_attribute_debug(
    *,
    decision: str,
    profile: AttributeProfile | None,
    state: AttributeSessionState | None,
    reason: str | None = None,
    reply: dict | None = None,
    readiness: dict | None = None,
    response_text: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "reply": reply.to_debug_dict() if hasattr(reply, "to_debug_dict") else reply,
        "readiness": readiness.to_debug_dict() if hasattr(readiness, "to_debug_dict") else readiness,
        "response_text": response_text,
    }
