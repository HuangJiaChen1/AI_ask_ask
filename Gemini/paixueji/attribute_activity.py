from __future__ import annotations

from dataclasses import asdict, dataclass


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
        "reply": reply,
        "response_text": response_text,
    }
