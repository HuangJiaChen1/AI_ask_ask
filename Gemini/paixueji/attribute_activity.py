from __future__ import annotations

from dataclasses import asdict, dataclass, field

import paixueji_prompts
from model_json import extract_json_object
from stream.exploration_loader import (
    SubAttributeCandidate,
    get_candidate_sub_attributes,
    infer_domain,
    sub_attribute_to_label,
    dimension_to_activity_target,
)


# ---------------------------------------------------------------------------
# Readiness thresholds
# ---------------------------------------------------------------------------
SUBSTANTIVE_TURN_THRESHOLD = 2
ATTRIBUTE_TOUCH_THRESHOLD = 1
ACTIVITY_COMMAND_WORDS = {"let's", "lets", "game", "play", "activity", "ready"}

# Intents that count as substantive engagement (used for readiness).
SUBSTANTIVE_INTENTS = {
    "correct_answer", "informative", "curiosity", "play",
    "emotional", "clarifying_wrong", "clarifying_constraint",
    "concept_confusion",
}


# ---------------------------------------------------------------------------
# Attribute touch detection — heuristic keyword patterns
# ---------------------------------------------------------------------------
ATTRIBUTE_TOUCH_PATTERNS: dict[str, dict[str, list[str]]] = {
    "body_color": {
        "direct": [
            "red", "green", "yellow", "blue", "orange", "black",
            "white", "pink", "purple", "brown", "gold", "silver",
            "color", "colour", "colored", "coloured",
        ],
        "indirect": [
            "bright", "shiny", "dark", "light", "vivid", "pale",
            "looks like", "same color as", "brightest",
            "dull", "striped", "spotted",
        ],
        "preference": [
            "i like the", "my favorite color", "which color",
            "favorite colour",
        ],
    },
    "covering": {
        "direct": [
            "fur", "hair", "feathers", "skin", "shell", "scales",
            "fluffy", "smooth", "rough", "bumpy", "fuzzy", "soft",
            "hairy", "feathered", "scales",
        ],
        "indirect": [
            "fur", "furry", "hairy", "smooth", "rough",
            "hard", "fuzzy", "coat", "cover",
        ],
        "preference": [
            "i like touching", "feels nice", "soft is better",
        ],
    },
    "taste": {
        "direct": [
            "sweet", "sour", "bitter", "salty", "spicy", "taste",
            "yummy", "delicious", "flavor", "tangy", "savory",
            "bland", "gross taste",
        ],
        "indirect": [
            "tastes like", "fresh", "flavor", "tangy",
            "flavour", "mouth", "lick",
        ],
        "preference": [
            "i like how it", "my favorite taste", "tastes good",
            "tastes bad",
        ],
    },
    "sound": {
        "direct": [
            "loud", "quiet", "roar", "bark", "chirp", "meow",
            "buzz", "crunch", "squeak", "honk", "purr",
            "sound", "noise", "hear",
        ],
        "indirect": [
            "sounds like", "makes a", "you can hear",
            "quiet", "noisy", "silent",
        ],
        "preference": [
            "i like the sound", "sounds cool", "sounds funny",
        ],
    },
    "smell": {
        "direct": [
            "smell", "stinky", "fragrant", "scent", "odor",
            "aroma", "stinks", "smells", "sniff",
        ],
        "indirect": [
            "smells like", "you can smell", "scented",
            "fresh smell",
        ],
        "preference": [
            "i like the smell", "smells good", "smells bad",
        ],
    },
    "body_size": {
        "direct": [
            "big", "small", "tiny", "huge", "giant", "little",
            "long", "short", "tall", "wide", "narrow",
            "size", "heavy", "light",
        ],
        "indirect": [
            "as big as", "as small as", "bigger than", "smaller than",
            "fits in", "can hold",
        ],
        "preference": [
            "i like big", "i like small", "too big", "too small",
        ],
    },
    "body_parts": {
        "direct": [
            "legs", "arms", "eyes", "ears", "nose", "mouth",
            "teeth", "claws", "paws", "tail", "wing", "wings",
            "fin", "fins", "horn", "horns", "beak",
            "head", "neck", "back", "stomach", "belly",
        ],
        "indirect": [
            "has", "with", "uses its", "part",
        ],
        "preference": [
            "i like its", "my favorite part",
        ],
    },
    "markings": {
        "direct": [
            "stripes", "spots", "pattern", "dots", "lines",
            "spots", "striped", "spotted", "patches",
            "markings", "marks",
        ],
        "indirect": [
            "looks like it has", "you can see",
        ],
        "preference": [],
    },
    "function_use": {
        "direct": [
            "use", "used", "does", "works", "helps", "help",
            "tool", "purpose", "made for", "can do",
            "job", "role", "used for",
        ],
        "indirect": [
            "helps you", "people use", "we use",
            "good for", "useful",
        ],
        "preference": [
            "i like using", "my favorite way",
        ],
    },
}


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
    """Session state for the natural-discovery attribute pipeline.

    Tracks substantive engagement and attribute touches separately,
    so the conversation can flow naturally while still guaranteeing
    that the handoff activity connects to what the child explored.
    """
    object_name: str
    profile: AttributeProfile
    age: int
    substantive_turns: int = 0
    attribute_touches: int = 0
    attribute_touch_types: list[str] = field(default_factory=list)
    intent_history: list[str] = field(default_factory=list)
    activity_ready: bool = False
    surface_object_name: str | None = None
    anchor_object_name: str | None = None

    def to_debug_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AttributeTouchResult:
    """Result of heuristic attribute touch detection."""
    touched: bool
    touch_type: str       # "direct", "indirect", "preference", or "none"
    confidence: str       # "high", "medium", "low"
    matched: list[str]    # keywords that triggered the match

    def to_debug_dict(self) -> dict:
        return {
            "touched": self.touched,
            "touch_type": self.touch_type,
            "confidence": self.confidence,
            "matched": self.matched,
        }


@dataclass(frozen=True)
class AttributeReadinessDecision:
    activity_ready: bool
    chat_phase_complete: bool
    state_action: str
    reason: str
    substantive_turns: int
    attribute_touches: int
    readiness_threshold_substantive: int = SUBSTANTIVE_TURN_THRESHOLD
    readiness_threshold_touch: int = ATTRIBUTE_TOUCH_THRESHOLD
    readiness_source: str = "discovery_engagement_policy"

    def to_debug_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _normalize(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def _contains_activity_command(text: str) -> bool:
    words = {word.strip(".,!?;:") for word in text.split()}
    return bool(ACTIVITY_COMMAND_WORDS.intersection(words))


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
# Public API — attribute selection (unchanged)
# ---------------------------------------------------------------------------
async def select_attribute_profile(
    *,
    object_name: str,
    age: int | None,
    anchor_status: str | None = None,
    client,
    config: dict | None,
) -> tuple[AttributeProfile | None, dict]:
    resolved_age = age or 6
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
# Public API — session start (adapted for DiscoverySessionState)
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
        age=age or 6,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
    )


# ---------------------------------------------------------------------------
# Public API — attribute touch detection (heuristic)
# ---------------------------------------------------------------------------
def detect_attribute_touch(
    child_reply: str,
    attribute_id: str,
) -> AttributeTouchResult:
    """Detect whether the child's reply touched the suggested attribute.

    Uses heuristic keyword matching — no LLM call needed.
    The sub_attribute part of attribute_id (e.g. "body_color" from
    "appearance.body_color") is used as the lookup key.
    """
    text = _normalize(child_reply)
    if not text:
        return AttributeTouchResult(
            touched=False, touch_type="none",
            confidence="low", matched=[],
        )

    sub_attribute = attribute_id.split(".", 1)[-1] if "." in attribute_id else attribute_id
    patterns = ATTRIBUTE_TOUCH_PATTERNS.get(sub_attribute, {})

    direct_hits = [w for w in patterns.get("direct", []) if w in text]
    indirect_hits = [w for w in patterns.get("indirect", []) if w in text]
    preference_hits = [w for w in patterns.get("preference", []) if w in text]

    if direct_hits:
        return AttributeTouchResult(
            touched=True, touch_type="direct",
            confidence="high", matched=direct_hits,
        )
    if indirect_hits:
        return AttributeTouchResult(
            touched=True, touch_type="indirect",
            confidence="medium", matched=indirect_hits,
        )
    if preference_hits:
        return AttributeTouchResult(
            touched=True, touch_type="preference",
            confidence="medium", matched=preference_hits,
        )

    return AttributeTouchResult(
        touched=False, touch_type="none",
        confidence="low", matched=[],
    )


# ---------------------------------------------------------------------------
# Public API — readiness evaluation (discovery-based)
# ---------------------------------------------------------------------------
def evaluate_discovery_readiness(
    state: DiscoverySessionState,
    touch_result: AttributeTouchResult,
    intent_type: str,
) -> AttributeReadinessDecision:
    """Evaluate whether the child is ready for an attribute activity handoff.

    Two conditions must BOTH be met:
    1. attribute_touches >= 1: child has engaged the suggested attribute
       (guarantees activity connects to conversation)
    2. substantive_turns >= 2: enough conversational depth
       (prevents premature handoff after one word)
    """
    # Update state
    if touch_result.touched:
        state.attribute_touches += 1
        state.attribute_touch_types.append(touch_result.touch_type)
    if intent_type in SUBSTANTIVE_INTENTS:
        state.substantive_turns += 1
    state.intent_history.append(intent_type)

    # Already ready — stay ready
    if state.activity_ready:
        return AttributeReadinessDecision(
            activity_ready=True,
            chat_phase_complete=True,
            state_action="invite_attribute_activity",
            reason="attribute activity was already ready",
            substantive_turns=state.substantive_turns,
            attribute_touches=state.attribute_touches,
        )

    # Check both thresholds
    has_attribute_engagement = state.attribute_touches >= ATTRIBUTE_TOUCH_THRESHOLD
    has_conversation_richness = state.substantive_turns >= SUBSTANTIVE_TURN_THRESHOLD

    if has_attribute_engagement and has_conversation_richness:
        state.activity_ready = True
        return AttributeReadinessDecision(
            activity_ready=True,
            chat_phase_complete=True,
            state_action="invite_attribute_activity",
            reason=f"child engaged attribute ({state.attribute_touches} touches) "
                   f"with sufficient depth ({state.substantive_turns} substantive turns)",
            substantive_turns=state.substantive_turns,
            attribute_touches=state.attribute_touches,
        )

    # Not ready yet — determine guidance action
    if not has_attribute_engagement:
        action = "soft_guide_attribute"
    elif not has_conversation_richness:
        action = "continue_conversation"
    else:
        action = "continue_conversation"

    return AttributeReadinessDecision(
        activity_ready=False,
        chat_phase_complete=False,
        state_action=action,
        reason=f"attribute_touches={state.attribute_touches} "
               f"(need {ATTRIBUTE_TOUCH_THRESHOLD}), "
               f"substantive_turns={state.substantive_turns} "
               f"(need {SUBSTANTIVE_TURN_THRESHOLD})",
        substantive_turns=state.substantive_turns,
        attribute_touches=state.attribute_touches,
    )


# ---------------------------------------------------------------------------
# Public API — debug builder (adapted for DiscoverySessionState)
# ---------------------------------------------------------------------------
def build_attribute_debug(
    *,
    decision: str,
    profile: AttributeProfile | None,
    state: DiscoverySessionState | None,
    reason: str | None = None,
    touch_result: AttributeTouchResult | None = None,
    readiness: AttributeReadinessDecision | None = None,
    response_text: str | None = None,
    intent_type: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "touch_result": touch_result.to_debug_dict() if touch_result else None,
        "readiness": readiness.to_debug_dict() if readiness else None,
        "response_text": response_text,
        "intent_type": intent_type,
    }


# ---------------------------------------------------------------------------
# Legacy compatibility — old names still work but delegate to new functions
# ---------------------------------------------------------------------------
AttributeSessionState = DiscoverySessionState

def classify_attribute_reply(state, child_reply):
    """Legacy wrapper — delegates to detect_attribute_touch + intent logic."""
    touch = detect_attribute_touch(child_reply, state.profile.attribute_id)
    # Map touch result to a reply_type for backward compat
    if touch.touched:
        reply_type = "aligned" if touch.touch_type == "direct" else "attribute_touch"
    else:
        reply_type = "other_feature"
    counted = touch.touched
    return type("LegacyReplyDecision", (), {
        "reply_type": reply_type,
        "attribute_id": state.profile.attribute_id,
        "counted_turn": counted,
        "activity_ready": False,
        "state_action": "soft_guide_attribute" if not touch.touched else "continue_attribute_lane",
        "reason": touch.touch_type if touch.touched else "child did not engage suggested attribute",
        "to_debug_dict": lambda: {
            "reply_type": reply_type,
            "attribute_id": state.profile.attribute_id,
            "counted_turn": counted,
            "touch_result": touch.to_debug_dict(),
        },
    })()

def evaluate_attribute_activity_readiness(state, reply, intent_type="aligned"):
    """Legacy wrapper — delegates to evaluate_discovery_readiness."""
    touch = detect_attribute_touch("", state.profile.attribute_id)
    # If reply has counted_turn, we had a touch from the earlier classify call
    if hasattr(reply, "counted_turn") and reply.counted_turn:
        touch = AttributeTouchResult(
            touched=True, touch_type="direct",
            confidence="high", matched=[],
        )
    return evaluate_discovery_readiness(state, touch, intent_type)