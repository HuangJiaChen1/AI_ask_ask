"""Exploration angle pools and selection logic for CARES attribute pipeline.

Provides structured cognitive directions ("angles") per dimension type,
preventing the LLM from repeating the same question style across turns.
"""

from dataclasses import dataclass


@dataclass
class AngleCoverageRecord:
    angle_id: str
    turn_index: int
    question_text: str
    response_text: str


# Dimensions that map to the "physical" angle pool.
PHYSICAL_DIMENSIONS = frozenset({
    "appearance",
    "senses",
    "structure",
    "function",
    "context",
    "change",
})

EXPLORATION_ANGLES = {
    "physical": [
        {
            "angle_id": "observation",
            "description": "Ask the child to observe and describe the attribute with their own words",
            "response_hint": "Share one concrete sensory fact about the {attribute_label}",
            "question_hint": "Ask what the child notices or sees about the {attribute_label}",
            "example": "What color do you see on the {object_name}?",
        },
        {
            "angle_id": "comparison",
            "description": "Compare this attribute with something familiar to the child",
            "response_hint": "Share a surprising comparison or contrast about the {attribute_label}",
            "question_hint": "Ask the child to compare the {attribute_label} with something they know",
            "example": "Is it more like a banana or a grape in color?",
        },
        {
            "angle_id": "preference",
            "description": "Invite the child to express a personal preference or opinion",
            "response_hint": "Validate that there is no wrong answer",
            "question_hint": "Ask which version of the {attribute_label} they like better",
            "example": "Do you like red apples or green apples better?",
        },
        {
            "angle_id": "association",
            "description": "Connect the attribute to the child's everyday life or other objects",
            "response_hint": "Mention one everyday object that shares this attribute",
            "question_hint": "Ask where else the child has seen this {attribute_label}",
            "example": "What else around you has this same color?",
        },
        {
            "angle_id": "causal",
            "description": "Explore why or how the attribute came to be (age-appropriate)",
            "response_hint": "Give a simple, concrete explanation",
            "question_hint": "Ask why the {object_name} has this {attribute_label}",
            "example": "Why do you think apples turn red when they grow?",
        },
    ],
    "engagement": [
        {
            "angle_id": "emotional",
            "description": "Ask about feelings and emotional reactions",
            "response_hint": "Acknowledge the child's feeling as valid",
            "question_hint": "Ask how the {object_name} makes them feel",
            "example": "Does the red apple make you feel happy or excited?",
        },
        {
            "angle_id": "memory",
            "description": "Connect to personal memories and experiences",
            "response_hint": "Share a brief, relatable memory",
            "question_hint": "Ask if the {object_name} reminds them of something",
            "example": "Does this apple remind you of anything you've eaten before?",
        },
        {
            "angle_id": "imagination",
            "description": "Invite playful imagination and pretend",
            "response_hint": "Play along with the child's imagination",
            "question_hint": "Ask a playful 'what if' about the {attribute_label}",
            "example": "If this apple could change color, what color would you pick?",
        },
        {
            "angle_id": "social",
            "description": "Connect to relationships and social context",
            "response_hint": "Mention how people or animals relate to this",
            "question_hint": "Ask who else might like or use this {attribute_label}",
            "example": "Who do you know that likes red apples?",
        },
    ],
}


def select_next_angle(
    explored_angle_ids: list[str],
    dimension: str,
    interest_score: float = 0,
    pending_verifications: list | None = None,
) -> dict:
    """Select the next exploration angle for the given dimension.

    Args:
        explored_angle_ids: List of angle IDs already used this session.
        dimension: The attribute dimension (e.g. "appearance", "emotion").
        interest_score: Current interest score (0-100). Unlocks deeper angles.

    Returns:
        The selected angle dict with keys: angle_id, description, response_hint,
        question_hint, example.
    """
    pool_key = "physical" if dimension in PHYSICAL_DIMENSIONS else "engagement"
    pool = EXPLORATION_ANGLES.get(pool_key, [])

    # VGC: If there's a pending verification, prefer angles that help verify it
    if pending_verifications:
        property_to_angle_hints = {
            "color": "observation",
            "shape": "observation",
            "pattern": "comparison",
            "texture": "observation",
            "size": "comparison",
        }
        for v in pending_verifications:
            prop = v.property.lower()
            for hint_key, hint_angle in property_to_angle_hints.items():
                if hint_key in prop:
                    preferred = [
                        a for a in pool
                        if a["angle_id"] == hint_angle and a["angle_id"] not in explored_angle_ids
                    ]
                    if preferred:
                        return preferred[0]

    if not pool:
        return {
            "angle_id": "observation",
            "description": "Ask the child to observe and describe",
            "response_hint": "Share one concrete fact",
            "question_hint": "Ask what the child notices",
            "example": "What do you notice about it?",
        }

    unused = [a for a in pool if a["angle_id"] not in explored_angle_ids]

    if unused:
        # Filter by interest-score unlocking
        if interest_score < 30:
            simple = [a for a in unused if a["angle_id"] in ("observation", "comparison")]
            return simple[0] if simple else unused[0]
        elif interest_score < 55:
            medium = [a for a in unused if a["angle_id"] != "causal"]
            return medium[0] if medium else unused[0]
        return unused[0]

    # All angles used: cycle, avoiding the most recently used if possible
    for angle in pool:
        if explored_angle_ids and angle["angle_id"] != explored_angle_ids[-1]:
            return angle
    return pool[0]
