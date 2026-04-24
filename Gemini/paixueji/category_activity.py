from __future__ import annotations

from dataclasses import asdict, dataclass

from stream.exploration_loader import ALL_DOMAINS


CATEGORY_ACTIVITY_READY_TURN_THRESHOLD = 2
ACTIVITY_COMMAND_WORDS = {"let's", "lets", "game", "play", "activity", "ready"}
CATEGORY_ACTIVITY_TEMPLATES: dict[str, str] = {
    "animals": "discovering different animals and what makes them special",
    "food": "exploring different foods and how we eat them",
    "vehicles": "learning about vehicles and how they help us travel",
    "plants": "discovering plants and how they grow",
    "people_roles": "learning about different people and the jobs they do",
    "buildings_places": "exploring places and what people do there",
    "clothing_accessories": "learning about clothes and accessories people use",
    "daily_objects": "exploring everyday objects and what they are for",
    "natural_phenomena": "discovering weather and natural events in our world",
    "arts_music": "exploring art, music, and the ways people create",
    "signs_symbols": "learning about signs and symbols and what they mean",
    "nature_landscapes": "discovering landscapes and outdoor places in nature",
    "human_body": "learning about body parts and how our bodies work",
    "imagination": "exploring pretend ideas and things we can imagine",
}
GENERIC_CATEGORY_ACTIVITY_TARGET = "exploring different kinds of things in our world"
DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "animals": ("animal", "animals", "cat", "dog", "bird", "fish", "lion"),
    "food": ("food", "foods", "apple", "banana", "bread", "snack", "eat"),
    "vehicles": ("vehicle", "vehicles", "car", "bus", "bike", "train", "plane", "boat"),
    "plants": ("plant", "plants", "tree", "flower", "leaf", "grass"),
    "people_roles": ("teacher", "doctor", "chef", "farmer", "worker"),
    "buildings_places": ("school", "house", "park", "store", "hospital"),
    "clothing_accessories": ("shirt", "hat", "shoe", "dress", "bag"),
    "daily_objects": ("cup", "spoon", "book", "chair", "table"),
    "natural_phenomena": ("rain", "snow", "wind", "storm", "lightning"),
    "arts_music": ("music", "song", "painting", "drum", "dance"),
    "signs_symbols": ("sign", "symbol", "stop sign", "arrow", "flag"),
    "nature_landscapes": ("mountain", "river", "forest", "beach", "desert"),
    "human_body": ("body", "hand", "eye", "heart", "leg"),
    "imagination": ("dragon", "magic", "pretend", "robot", "spaceship"),
}


@dataclass(frozen=True)
class CategoryProfile:
    category_id: str | None
    category_label: str
    activity_target: str
    domain: str | None


@dataclass
class CategorySessionState:
    object_name: str
    profile: CategoryProfile
    age: int
    turn_count: int = 0
    activity_ready: bool = False
    last_question: str | None = None

    def to_debug_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CategoryReplyDecision:
    reply_type: str
    category_id: str | None
    counted_turn: bool
    activity_ready: bool
    state_action: str
    reason: str

    def to_debug_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CategoryReadinessDecision:
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


def _category_label(category_id: str | None) -> str:
    if not category_id:
        return "Category"
    return category_id.replace("_", " ").title()


def _is_other_category_reference(category_id: str | None, text: str) -> bool:
    for candidate, keywords in DOMAIN_KEYWORDS.items():
        if candidate == category_id:
            continue
        if any(keyword in text for keyword in keywords):
            return True
    return False


def build_category_profile(domain: str | None, object_name: str) -> CategoryProfile:
    normalized_domain = domain if domain in ALL_DOMAINS else None
    activity_target = CATEGORY_ACTIVITY_TEMPLATES.get(
        normalized_domain or "",
        GENERIC_CATEGORY_ACTIVITY_TARGET,
    )
    return CategoryProfile(
        category_id=normalized_domain,
        category_label=_category_label(normalized_domain),
        activity_target=activity_target,
        domain=normalized_domain,
    )


def start_category_session(
    *,
    object_name: str,
    profile: CategoryProfile,
    age: int | None,
) -> CategorySessionState:
    if profile is None:
        raise ValueError("profile is required to start a category session")
    return CategorySessionState(
        object_name=object_name,
        profile=profile,
        age=age or 6,
    )


def classify_category_reply(
    state: CategorySessionState,
    child_reply: str | None,
) -> CategoryReplyDecision:
    text = _normalize(child_reply)

    if any(token in text for token in ("don't know", "dont know", "not sure", "idk", "maybe")):
        return CategoryReplyDecision(
            reply_type="uncertainty",
            category_id=state.profile.category_id,
            counted_turn=False,
            activity_ready=False,
            state_action="scaffold_category",
            reason="child expressed uncertainty",
        )

    if any(token in text for token in ("can't", "cannot", "dont want", "don't want", "stop", "no more")):
        return CategoryReplyDecision(
            reply_type="constraint_avoidance",
            category_id=state.profile.category_id,
            counted_turn=False,
            activity_ready=False,
            state_action="low_pressure_repair",
            reason="child expressed constraint or avoidance",
        )

    if _contains_activity_command(text):
        return CategoryReplyDecision(
            reply_type="activity_command",
            category_id=state.profile.category_id,
            counted_turn=False,
            activity_ready=False,
            state_action="acknowledge_keep_category",
            reason="child requested play, but activity readiness stays backend-driven",
        )

    if "?" in (child_reply or "") or text.startswith(("why ", "how ", "what ", "where ", "can ")):
        return CategoryReplyDecision(
            reply_type="curiosity",
            category_id=state.profile.category_id,
            counted_turn=True,
            activity_ready=False,
            state_action="answer_and_reconnect",
            reason="child asked a category-level curiosity question",
        )

    if text and _is_other_category_reference(state.profile.category_id, text):
        return CategoryReplyDecision(
            reply_type="category_drift",
            category_id=state.profile.category_id,
            counted_turn=True,
            activity_ready=False,
            state_action="accept_comparison_keep_category",
            reason="child compared the current category with a different category",
        )

    return CategoryReplyDecision(
        reply_type="aligned",
        category_id=state.profile.category_id,
        counted_turn=bool(text),
        activity_ready=False,
        state_action="continue_category_lane",
        reason="child stayed aligned with the category lane",
    )


def evaluate_category_activity_readiness(
    state: CategorySessionState,
    reply: CategoryReplyDecision,
) -> CategoryReadinessDecision:
    if state.activity_ready:
        return CategoryReadinessDecision(
            activity_ready=True,
            chat_phase_complete=True,
            state_action="invite_category_activity",
            reason="category activity was already ready",
            engaged_turn_count=state.turn_count,
            readiness_threshold=CATEGORY_ACTIVITY_READY_TURN_THRESHOLD,
        )

    if reply.counted_turn and state.turn_count >= CATEGORY_ACTIVITY_READY_TURN_THRESHOLD:
        return CategoryReadinessDecision(
            activity_ready=True,
            chat_phase_complete=True,
            state_action="invite_category_activity",
            reason="child completed two coherent category-engaged turns",
            engaged_turn_count=state.turn_count,
            readiness_threshold=CATEGORY_ACTIVITY_READY_TURN_THRESHOLD,
        )

    return CategoryReadinessDecision(
        activity_ready=False,
        chat_phase_complete=False,
        state_action=reply.state_action,
        reason="category engagement threshold not reached",
        engaged_turn_count=state.turn_count,
        readiness_threshold=CATEGORY_ACTIVITY_READY_TURN_THRESHOLD,
    )


def build_category_debug(
    *,
    decision: str,
    profile: CategoryProfile | None,
    state: CategorySessionState | None,
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
