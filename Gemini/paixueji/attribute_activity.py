from __future__ import annotations

from dataclasses import asdict, dataclass

import paixueji_prompts
from model_json import extract_json_object


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


MOCK_ATTRIBUTE_PROFILES: tuple[AttributeProfile, ...] = (
    AttributeProfile(
        attribute_id="surface_shiny_smooth",
        label="shiny smooth skin",
        activity_target="noticing/comparing surfaces",
        branch="in_kb",
        object_examples=("apple", "green apple", "red apple"),
    ),
    AttributeProfile(
        attribute_id="fur_paws_soft",
        label="soft fur and paws",
        activity_target="gentle observation game",
        branch="in_kb",
        object_examples=("cat", "kitten"),
    ),
    AttributeProfile(
        attribute_id="strong_smell",
        label="strong smell",
        activity_target="smell-to-reaction activity",
        branch="anchored_not_in_kb",
        object_examples=("cat food",),
    ),
    AttributeProfile(
        attribute_id="sparkle_glow",
        label="pretend sparkly glow",
        activity_target="imagination/light activity",
        branch="unresolved_not_in_kb",
        object_examples=("spaceship fuel",),
    ),
    AttributeProfile(
        attribute_id="round_rolls",
        label="round rolling shape",
        activity_target="roll-and-compare activity",
        branch="in_kb",
        object_examples=("ball", "orange"),
    ),
)


def _normalize(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def find_mock_attribute_profile(object_name: str | None) -> AttributeProfile | None:
    normalized = _normalize(object_name)
    for profile in MOCK_ATTRIBUTE_PROFILES:
        if normalized in profile.object_examples:
            return profile
    return None


def _profile_by_id(attribute_id: str | None) -> AttributeProfile | None:
    normalized = _normalize(attribute_id)
    for profile in MOCK_ATTRIBUTE_PROFILES:
        if profile.attribute_id == normalized:
            return profile
    return None


def _supported_attribute_block(profiles: tuple[AttributeProfile, ...]) -> str:
    lines = []
    for profile in profiles:
        examples = ", ".join(profile.object_examples)
        lines.append(
            f"- {profile.attribute_id}: {profile.label}; activity={profile.activity_target}; "
            f"branch={profile.branch}; examples={examples}"
        )
    return "\n".join(lines)


async def select_attribute_profile(
    *,
    object_name: str,
    age: int | None,
    client,
    config: dict | None,
    supported_profiles: tuple[AttributeProfile, ...] = MOCK_ATTRIBUTE_PROFILES,
) -> tuple[AttributeProfile | None, dict]:
    prompt = paixueji_prompts.get_prompts()["attribute_selection_prompt"].format(
        object_name=object_name,
        age=age or 6,
        supported_attributes=_supported_attribute_block(supported_profiles),
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
        profile = _profile_by_id(payload.get("attribute_id"))
        if profile:
            return profile, {
                "decision": "attribute_selected",
                "source": "gemini",
                "attribute_id": profile.attribute_id,
                "confidence": payload.get("confidence"),
                "reason": payload.get("reason") or "selected by Gemini",
                "payload_kind": payload_kind,
                "json_recovery_applied": recovered,
            }

    fallback = find_mock_attribute_profile(object_name)
    if fallback:
        reason = exc_reason or f"invalid Gemini attribute selection payload: {payload_kind}"
        return fallback, {
            "decision": "attribute_selected",
            "source": "mock_fallback",
            "attribute_id": fallback.attribute_id,
            "confidence": "fallback",
            "reason": reason,
            "payload_kind": payload_kind,
            "json_recovery_applied": recovered,
        }

    return None, {
        "decision": "no_attribute_match_fallback",
        "source": "none",
        "attribute_id": None,
        "confidence": None,
        "reason": exc_reason or f"invalid Gemini attribute selection payload: {payload_kind}",
        "payload_kind": payload_kind,
        "json_recovery_applied": recovered,
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

    if any(token in text for token in ("let's", "lets", "game", "play", "activity", "ready")):
        return AttributeReplyDecision(
            reply_type="activity_ready",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=True,
            state_action="handoff_to_activity",
            reason="child is ready for activity",
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


def build_attribute_debug(
    *,
    decision: str,
    profile: AttributeProfile | None,
    state: AttributeSessionState | None,
    reason: str | None = None,
    reply: dict | None = None,
    response_text: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "reply": reply.to_debug_dict() if hasattr(reply, "to_debug_dict") else reply,
        "response_text": response_text,
    }
