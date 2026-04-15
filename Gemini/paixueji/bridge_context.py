from __future__ import annotations

from dataclasses import dataclass

from bridge_profile import BridgeProfile

SUPPORTED_RELATIONS = (
    "food_for",
    "used_with",
    "part_of",
    "belongs_to",
    "made_from",
    "related_to",
)


@dataclass(frozen=True)
class BridgeContext:
    relation: str
    attempt_number: int
    surface_object_name: str
    anchor_object_name: str
    bridge_intent: str
    good_question_angles: tuple[str, ...]
    avoid_angles: tuple[str, ...]
    steer_back_rule: str
    focus_cues: tuple[str, ...]
    prompt_context: str


def normalize_relation(value: str | None) -> str:
    normalized = " ".join((value or "").strip().lower().split())
    if normalized in SUPPORTED_RELATIONS:
        return normalized
    return "related_to"


def build_bridge_context(
    bridge_profile: BridgeProfile | None,
    attempt_number: int,
) -> BridgeContext | None:
    if bridge_profile is None:
        return None

    guidance_label, guidance = (
        ("Second bridge attempt.", "Acknowledge briefly, then make one final bridge inside the same semantic lane.")
        if attempt_number >= 2
        else ("First bridge attempt.", "Start from the surface object, then bridge through the intended semantic connection.")
    )
    lines = [
        guidance_label,
        f"Surface object: {bridge_profile.surface_object_name}",
        f"Supported anchor: {bridge_profile.anchor_object_name}",
        f"Bridge intent: {bridge_profile.bridge_intent}",
        f"Good question angles: {', '.join(bridge_profile.good_question_angles)}",
    ]
    if bridge_profile.avoid_angles:
        lines.append(f"Avoid angles: {', '.join(bridge_profile.avoid_angles)}")
    lines.append(f"Steer-back rule: {bridge_profile.steer_back_rule}")
    if bridge_profile.focus_cues:
        lines.append(f"Focus cues: {', '.join(bridge_profile.focus_cues)}")
    lines.append(guidance)
    prompt_context = "\n".join(lines)

    return BridgeContext(
        relation=bridge_profile.relation,
        attempt_number=attempt_number,
        surface_object_name=bridge_profile.surface_object_name,
        anchor_object_name=bridge_profile.anchor_object_name,
        bridge_intent=bridge_profile.bridge_intent,
        good_question_angles=bridge_profile.good_question_angles,
        avoid_angles=bridge_profile.avoid_angles,
        steer_back_rule=bridge_profile.steer_back_rule,
        focus_cues=bridge_profile.focus_cues,
        prompt_context=prompt_context,
    )
