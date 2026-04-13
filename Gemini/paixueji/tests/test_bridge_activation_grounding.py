import json
from pathlib import Path

import paixueji_prompts
from bridge_debug import build_bridge_debug
from kb_context import (
    build_bridge_activation_grounding_context,
    build_chat_kb_context,
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


def test_bridge_activation_grounding_context_matches_chat_kb_exactly():
    expected = build_chat_kb_context(
        object_name="cat",
        physical_dimensions=PHYSICAL,
        engagement_dimensions=ENGAGEMENT,
    )
    actual = build_bridge_activation_grounding_context(
        object_name="cat",
        physical_dimensions=PHYSICAL,
        engagement_dimensions=ENGAGEMENT,
    )

    assert actual == expected


def test_config_no_longer_exposes_bridge_activation_grounding_mode():
    config = json.loads(Path("config.json").read_text(encoding="utf-8"))

    assert "bridge_activation_grounding_mode" not in config


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
        activation_grounding_mode="full_chat_kb",
        activation_grounding_summary="full_chat_kb: 2 non-empty grounding lines",
    )

    assert debug["activation_grounding_mode"] == "full_chat_kb"
    assert debug["activation_grounding_summary"] == "full_chat_kb: 2 non-empty grounding lines"

def test_compare_runner_module_is_removed():
    compare_runner = Path("tests/integration_scenarios/bridge_activation_grounding_compare.py")

    assert not compare_runner.exists()
