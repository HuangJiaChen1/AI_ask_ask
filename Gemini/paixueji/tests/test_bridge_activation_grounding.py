import paixueji_prompts
from bridge_debug import build_bridge_debug
from kb_context import (
    build_bridge_activation_grounding_context,
    build_chat_kb_context,
    normalize_bridge_activation_grounding_mode,
)


PHYSICAL = {
    "eating": {
        "teeth": "Cats use teeth to bite and chew food.",
    }
}

ENGAGEMENT = {
    "behavior": [
        "Cats may sniff food before eating.",
    ]
}


def test_normalize_bridge_activation_grounding_mode_defaults_to_none():
    assert normalize_bridge_activation_grounding_mode(None) == "none"
    assert normalize_bridge_activation_grounding_mode("bogus") == "none"


def test_physical_only_excludes_engagement_lines():
    text = build_bridge_activation_grounding_context(
        mode="physical_only",
        object_name="cat",
        physical_dimensions=PHYSICAL,
        engagement_dimensions=ENGAGEMENT,
    )

    assert "[physical.eating]" in text
    assert "[engagement.behavior]" not in text


def test_full_chat_kb_matches_ordinary_chat_builder_exactly():
    expected = build_chat_kb_context(
        object_name="cat",
        physical_dimensions=PHYSICAL,
        engagement_dimensions=ENGAGEMENT,
    )
    actual = build_bridge_activation_grounding_context(
        mode="full_chat_kb",
        object_name="cat",
        physical_dimensions=PHYSICAL,
        engagement_dimensions=ENGAGEMENT,
    )

    assert actual == expected


def test_bridge_activation_prompt_declares_hidden_latent_grounding_contract():
    prompt = paixueji_prompts.BRIDGE_ACTIVATION_RESPONSE_PROMPT
    lower = prompt.lower()

    assert "{latent_grounding_section}" in prompt
    assert "hidden support" in lower
    assert "child's stated detail stays primary" in lower


def test_bridge_debug_info_exposes_activation_grounding_fields():
    debug = build_bridge_debug(
        surface_object_name="cat food",
        anchor_object_name="cat",
        anchor_status="anchored_high",
        anchor_relation="food_for",
        anchor_confidence_band="high",
        intro_mode="anchor_bridge",
        learning_anchor_active_before=False,
        learning_anchor_active_after=True,
        bridge_attempt_count_before=0,
        bridge_attempt_count_after=0,
        decision="bridge_activation",
        decision_reason="child followed bridge",
        activation_grounding_mode="physical_only",
        activation_grounding_summary="physical only",
    )

    assert debug["activation_grounding_mode"] == "physical_only"
    assert debug["activation_grounding_summary"] == "physical only"


def test_build_run_matrix_expands_each_scenario_across_three_modes():
    from tests.integration_scenarios.bridge_activation_grounding_compare import build_run_matrix

    matrix = build_run_matrix()
    pairs = {(row["scenario_id"], row["mode"]) for row in matrix}

    assert ("cat_food_smell_follow", "none") in pairs
    assert ("cat_food_smell_follow", "physical_only") in pairs
    assert ("cat_food_smell_follow", "full_chat_kb") in pairs
