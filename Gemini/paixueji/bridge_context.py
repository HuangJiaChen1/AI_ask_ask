from __future__ import annotations

from dataclasses import dataclass

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
    allowed_focus_terms: tuple[str, ...]
    forbidden_anchor_terms: tuple[str, ...]
    follow_terms: tuple[str, ...]
    prompt_context: str


_RELATION_POLICIES: dict[str, dict[str, tuple[str, ...] | tuple[str, str]]] = {
    "food_for": {
        "allowed_focus_terms": ("smell", "eat", "mouth", "nose"),
        "forbidden_anchor_terms": ("paw", "paws", "tail", "fur", "whiskers", "jump", "sleep"),
        "follow_terms": ("smell", "sniff", "nose", "mouth", "eat", "eating", "lick"),
        "attempt_1_guidance": ("First bridge attempt.", "Stay on the named item, then bridge through how the anchor notices or eats it."),
        "attempt_2_guidance": ("Second bridge attempt.", "Acknowledge the reply briefly, then make one final eating/smelling bridge."),
    },
    "used_with": {
        "allowed_focus_terms": ("use", "hold", "wear", "help"),
        "forbidden_anchor_terms": ("fur", "tail", "sleep", "run", "jump"),
        "follow_terms": ("use", "hold", "wear", "pull", "help"),
        "attempt_1_guidance": ("First bridge attempt.", "Bridge through how someone uses or holds the item with the anchor."),
        "attempt_2_guidance": ("Second bridge attempt.", "Make one final bridge through use or handling, then give up."),
    },
    "part_of": {
        "allowed_focus_terms": ("part", "inside", "attached", "belongs"),
        "forbidden_anchor_terms": ("whole", "separate", "far away"),
        "follow_terms": ("part", "inside", "on", "attached", "belongs"),
        "attempt_1_guidance": ("First bridge attempt.", "Bridge through where the item goes or what larger thing it belongs to."),
        "attempt_2_guidance": ("Second bridge attempt.", "Make one final belonging/part bridge, then give up."),
    },
    "belongs_to": {
        "allowed_focus_terms": ("owner", "belongs", "with", "keeps"),
        "forbidden_anchor_terms": ("alone", "random", "far away"),
        "follow_terms": ("owner", "belongs", "with", "keeps"),
        "attempt_1_guidance": ("First bridge attempt.", "Bridge through who or what the item belongs with."),
        "attempt_2_guidance": ("Second bridge attempt.", "Make one final belonging bridge, then give up."),
    },
    "made_from": {
        "allowed_focus_terms": ("made", "from", "material", "source"),
        "forbidden_anchor_terms": ("animal", "food", "play"),
        "follow_terms": ("made", "from", "wood", "metal", "plastic", "paper", "cloth"),
        "attempt_1_guidance": ("First bridge attempt.", "Bridge through what the item is made from or comes from."),
        "attempt_2_guidance": ("Second bridge attempt.", "Make one final material/source bridge, then give up."),
    },
    "related_to": {
        "allowed_focus_terms": ("connect", "notice", "go together", "about"),
        "forbidden_anchor_terms": (),
        "follow_terms": (),
        "attempt_1_guidance": ("First bridge attempt.", "Use a very conservative bridge."),
        "attempt_2_guidance": ("Second bridge attempt.", "Ask one last gentle connection question, then give up."),
    },
}


def normalize_relation(value: str | None) -> str:
    normalized = " ".join((value or "").strip().lower().split())
    if normalized in SUPPORTED_RELATIONS:
        return normalized
    return "related_to"


def build_bridge_context(
    surface_object_name: str,
    anchor_object_name: str,
    relation: str | None,
    attempt_number: int,
) -> BridgeContext | None:
    normalized_relation = " ".join((relation or "").strip().lower().split())
    if normalized_relation not in SUPPORTED_RELATIONS:
        return None

    policy = _RELATION_POLICIES[normalized_relation]
    allowed_focus_terms = policy["allowed_focus_terms"]
    forbidden_anchor_terms = policy["forbidden_anchor_terms"]
    follow_terms = policy["follow_terms"]
    guidance_label, guidance = policy["attempt_2_guidance"] if attempt_number >= 2 else policy["attempt_1_guidance"]
    prompt_context = "\n".join(
        [
            guidance_label,
            f"Surface object: {surface_object_name}",
            f"Supported anchor: {anchor_object_name}",
            f"Allowed focus terms: {', '.join(allowed_focus_terms)}",
            f"Forbidden anchor terms: {', '.join(forbidden_anchor_terms)}",
            guidance,
        ]
    )

    return BridgeContext(
        relation=normalized_relation,
        attempt_number=attempt_number,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
        allowed_focus_terms=allowed_focus_terms,
        forbidden_anchor_terms=forbidden_anchor_terms,
        follow_terms=follow_terms,
        prompt_context=prompt_context,
    )
