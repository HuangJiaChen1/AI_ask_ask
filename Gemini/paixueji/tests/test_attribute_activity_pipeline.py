import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from attribute_activity import (
    AttributeProfile,
    AttributeSessionState,
    build_attribute_debug,
    classify_attribute_reply,
    evaluate_attribute_activity_readiness,
    select_attribute_profile,
    start_attribute_session,
)


# --- select_attribute_profile tests ---


@pytest.mark.asyncio
async def test_select_attribute_profile_gemini_selects_from_dynamic_candidates():
    """Gemini returns a valid attribute_id from the dynamically generated candidates."""
    client = MagicMock()
    response = MagicMock()
    # New format: "dimension.sub_attribute"
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
    # Fallback is the first candidate; exact value depends on domain inference
    # but attribute_id should be in "dimension.sub_attribute" format
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

    # "cat" is in the mappings DB with domain="animals"
    # We need Gemini only for attribute selection, not domain inference
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

    # "quantum computer" is not in mappings → domain=None → default sub_attributes
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


# --- classify_attribute_reply tests (unchanged behavior, new attribute_id format) ---


def test_classify_attribute_reply_preserves_selected_attribute():
    """classify_attribute_reply still works with new attribute_id format."""
    profile = AttributeProfile(
        attribute_id="appearance.body_color",
        label="body color",
        activity_target="noticing and describing what cat looks like",
        branch="in_kb",
        object_examples=("cat",),
    )
    state = start_attribute_session(object_name="cat", profile=profile, age=6)

    decision = classify_attribute_reply(state, "It has brown fur")
    assert decision.attribute_id == "appearance.body_color"
    assert decision.reply_type == "aligned"
    assert decision.counted_turn is True


@pytest.mark.parametrize(
    ("child_reply", "reply_type", "counted_turn", "activity_ready"),
    [
        ("I don't know", "uncertainty", False, False),
        ("The apple is crunchy too", "same_object_feature_drift", True, False),
        ("My spoon is shiny too", "new_object_same_attribute_drift", True, False),
        ("Why is it shiny?", "curiosity", True, False),
        ("I can't smell it", "constraint_avoidance", False, False),
        ("Let's play a shiny game", "activity_command", False, False),
        ("It feels smooth", "aligned", True, False),
    ],
)
def test_classify_attribute_reply_all_cases(
    child_reply,
    reply_type,
    counted_turn,
    activity_ready,
):
    profile = AttributeProfile(
        attribute_id="appearance.surface_texture",
        label="shiny smooth skin",
        activity_target="noticing and describing what apple looks like",
        branch="in_kb",
        object_examples=("apple",),
    )
    state = start_attribute_session(object_name="apple", profile=profile, age=6)

    decision = classify_attribute_reply(state, child_reply)

    assert decision.reply_type == reply_type
    assert decision.attribute_id == profile.attribute_id
    assert decision.counted_turn is counted_turn
    assert decision.activity_ready is activity_ready


def test_attribute_readiness_requires_two_counted_engaged_turns():
    profile = AttributeProfile(
        attribute_id="appearance.surface_texture",
        label="shiny smooth skin",
        activity_target="noticing and describing what apple looks like",
        branch="in_kb",
        object_examples=("apple",),
    )
    state = start_attribute_session(object_name="apple", profile=profile, age=6)

    first = classify_attribute_reply(state, "It feels smooth")
    if first.counted_turn:
        state.turn_count += 1
    first_ready = evaluate_attribute_activity_readiness(state, first)
    assert first_ready.activity_ready is False
    assert first_ready.chat_phase_complete is False
    assert first_ready.engaged_turn_count == 1

    second = classify_attribute_reply(state, "My spoon is shiny too")
    if second.counted_turn:
        state.turn_count += 1
    second_ready = evaluate_attribute_activity_readiness(state, second)
    assert second_ready.activity_ready is True
    assert second_ready.chat_phase_complete is True
    assert second_ready.state_action == "invite_attribute_activity"
    assert second_ready.readiness_source == "backend_engagement_policy"


def test_activity_command_does_not_count_or_trigger_readiness():
    profile = AttributeProfile(
        attribute_id="appearance.surface_texture",
        label="shiny smooth skin",
        activity_target="noticing and describing what apple looks like",
        branch="in_kb",
        object_examples=("apple",),
    )
    state = start_attribute_session(object_name="apple", profile=profile, age=6)

    decision = classify_attribute_reply(state, "Let's play a shiny game")
    ready = evaluate_attribute_activity_readiness(state, decision)

    assert decision.reply_type == "activity_command"
    assert decision.counted_turn is False
    assert ready.activity_ready is False
    assert ready.engaged_turn_count == 0


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

    assert isinstance(state, AttributeSessionState)
    assert state.object_name == "cat food"
    assert state.profile.attribute_id == profile.attribute_id
    assert state.surface_object_name is None
    assert state.anchor_object_name is None
    assert state.turn_count == 0
    assert state.activity_ready is False
