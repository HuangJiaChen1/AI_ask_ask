import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from attribute_activity import (
    AttributeProfile,
    DiscoverySessionState,
    build_attribute_debug,
    detect_attribute_touch,
    evaluate_discovery_readiness,
    select_attribute_profile,
    start_attribute_session,
    SUBSTANTIVE_INTENTS,
    SUBSTANTIVE_TURN_THRESHOLD,
    ATTRIBUTE_TOUCH_THRESHOLD,
)


# --- select_attribute_profile tests ---


@pytest.mark.asyncio
async def test_select_attribute_profile_gemini_selects_from_dynamic_candidates():
    """Gemini returns a valid attribute_id from the dynamically generated candidates."""
    client = MagicMock()
    response = MagicMock()
    response.text = '{"attribute_id":"senses.taste","confidence":"high","reason":"smell is salient for food"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value="food"):
        profile, debug = await select_attribute_profile(
            object_name="cat food",
            age=6,
            anchor_status="anchored_high",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert profile.attribute_id == "senses.taste"
    assert profile.label == "taste"
    assert "cat food" in profile.activity_target
    assert debug["decision"] == "attribute_selected"
    assert debug["source"] == "gemini"


@pytest.mark.asyncio
async def test_select_attribute_profile_falls_back_to_first_candidate_on_invalid_json():
    """When Gemini returns invalid JSON, the first candidate becomes the fallback."""
    client = MagicMock()
    response = MagicMock()
    response.text = "not json at all"
    client.aio.models.generate_content = AsyncMock(return_value=response)

    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value="food"):
        profile, debug = await select_attribute_profile(
            object_name="cat food",
            age=6,
            anchor_status="unresolved",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert "." in profile.attribute_id
    assert debug["source"] == "first_candidate_fallback"


@pytest.mark.asyncio
async def test_select_attribute_profile_returns_none_when_no_candidates():
    """Edge case: if somehow no candidates are generated, returns None."""
    client = MagicMock()
    with patch("attribute_activity.get_candidate_sub_attributes", return_value=[]):
        with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value=None):
            profile, debug = await select_attribute_profile(
                object_name="impossible thing",
                age=3,
                anchor_status="unresolved",
                client=client,
                config={"model_name": "gemini-test"},
            )

    assert profile is None
    assert debug["decision"] == "no_attribute_match_fallback"


@pytest.mark.asyncio
async def test_select_attribute_profile_uses_mappings_domain_for_known_object():
    """For objects in the mappings DB, domain is resolved from the entity, not Gemini."""
    client = MagicMock()
    response = MagicMock()
    response.text = '{"attribute_id":"appearance.body_color","confidence":"high","reason":"color is salient"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    profile, debug = await select_attribute_profile(
        object_name="cat",
        age=4,
        anchor_status="exact_supported",
        client=client,
        config={"model_name": "gemini-test"},
    )

    assert profile is not None
    assert profile.branch == "in_kb"


@pytest.mark.asyncio
async def test_select_attribute_profile_branch_unresolved_for_unresolved_anchor():
    """Unresolved anchor_status results in branch="unresolved_not_in_kb"."""
    client = MagicMock()
    response = MagicMock()
    response.text = '{"attribute_id":"appearance.color","confidence":"medium","reason":"generic attribute"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value=None):
        profile, debug = await select_attribute_profile(
            object_name="quantum computer",
            age=6,
            anchor_status="unresolved",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert profile.branch == "unresolved_not_in_kb"


# --- attribute touch detection tests (new discovery pipeline) ---


def test_detect_attribute_touch_direct_for_body_color():
    """Direct keyword match for body_color attribute."""
    profile = AttributeProfile(
        attribute_id="appearance.body_color",
        label="body color",
        activity_target="noticing and describing what cat looks like",
        branch="in_kb",
        object_examples=("cat",),
    )
    state = start_attribute_session(object_name="cat", profile=profile, age=6)

    touch = detect_attribute_touch("It has brown fur", state.profile.attribute_id)
    # "brown" is a direct match for body_color
    assert touch.touched is True
    assert touch.confidence == "high"


def test_attribute_readiness_requires_touch_and_substantive():
    """Readiness requires both attribute touch AND substantive turns."""
    profile = AttributeProfile(
        attribute_id="appearance.body_color",
        label="body color",
        activity_target="noticing and describing what apple looks like",
        branch="in_kb",
        object_examples=("apple",),
    )
    state = start_attribute_session(object_name="apple", profile=profile, age=6)

    # Turn 1: substantive + touch
    touch1 = detect_attribute_touch("It's red!", state.profile.attribute_id)
    r1 = evaluate_discovery_readiness(state, touch1, "correct_answer")
    assert r1.activity_ready is False  # need 2 substantive turns
    assert state.substantive_turns == 1
    assert state.attribute_touches == 1

    # Turn 2: another substantive + touch
    touch2 = detect_attribute_touch("It's bright red", state.profile.attribute_id)
    r2 = evaluate_discovery_readiness(state, touch2, "informative")
    assert r2.activity_ready is True
    assert r2.state_action == "invite_attribute_activity"


def test_no_touch_means_not_ready():
    """Without touching the suggested attribute, readiness is never reached."""
    profile = AttributeProfile(
        attribute_id="appearance.body_color",
        label="body color",
        activity_target="noticing and describing what apple looks like",
        branch="in_kb",
        object_examples=("apple",),
    )
    state = start_attribute_session(object_name="apple", profile=profile, age=6)

    # Substantive but no attribute touch
    touch = detect_attribute_touch("It's round", state.profile.attribute_id)
    r = evaluate_discovery_readiness(state, touch, "correct_answer")
    assert r.activity_ready is False
    assert r.state_action == "soft_guide_attribute"


def test_build_attribute_debug_includes_profile_state_and_reason():
    profile = AttributeProfile(
        attribute_id="appearance.color",
        label="color",
        activity_target="noticing and describing what apple looks like",
        branch="in_kb",
        object_examples=("apple",),
    )
    state = start_attribute_session(object_name="apple", profile=profile, age=6)

    debug = build_attribute_debug(
        decision="attribute_lane_started",
        profile=profile,
        state=state,
        reason="selected by test",
    )

    assert debug["decision"] == "attribute_lane_started"
    assert debug["profile"]["attribute_id"] == "appearance.color"
    assert debug["state"]["profile"]["label"] == "color"
    assert debug["reason"] == "selected by test"


def test_attribute_session_does_not_require_surface_or_anchor_objects():
    profile = AttributeProfile(
        attribute_id="senses.taste",
        label="taste",
        activity_target="exploring how cat food feels, sounds, or smells",
        branch="anchored_not_in_kb",
        object_examples=("cat food",),
    )
    state = start_attribute_session(object_name="cat food", profile=profile, age=6)

    assert isinstance(state, DiscoverySessionState)
    assert state.object_name == "cat food"
    assert state.profile.attribute_id == profile.attribute_id
    assert state.surface_object_name is None
    assert state.anchor_object_name is None
    assert state.substantive_turns == 0
    assert state.activity_ready is False