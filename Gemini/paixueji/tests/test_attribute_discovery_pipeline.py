"""Tests for the LLM-driven attribute discovery pipeline.

Covers the public API contract: simplified session state, debug payload shape,
prompt invariants, and build_attribute_debug behavior.
"""

from unittest.mock import MagicMock

import pytest

from attribute_activity import (
    AttributeProfile,
    DiscoverySessionState,
    build_attribute_debug,
    start_attribute_session,
)
import paixueji_prompts
from paixueji_prompts import ATTRIBUTE_SOFT_GUIDE
from stream.response_generators import generate_attribute_activation_response_stream
from stream.question_generators import ask_followup_question_stream


def _make_profile(
    attribute_id: str = "appearance.body_color",
    label: str = "body color",
) -> AttributeProfile:
    return AttributeProfile(
        attribute_id=attribute_id,
        label=label,
        activity_target="noticing and describing what apple looks like — specifically, apple's body color",
        branch="in_kb",
        object_examples=("apple",),
    )


def _make_state() -> DiscoverySessionState:
    return start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=6,
    )


# -- Session state -----------------------------------------------------------

def test_start_attribute_session_builds_state_with_all_fields():
    state = start_attribute_session(
        object_name="apple",
        profile=_make_profile(),
        age=None,
        surface_object_name="red apple",
        anchor_object_name="apple",
    )

    assert state.object_name == "apple"
    assert state.profile.attribute_id == "appearance.body_color"
    assert state.age == 6
    assert state.turn_count == 0
    assert state.activity_ready is False
    assert state.surface_object_name == "red apple"
    assert state.anchor_object_name == "apple"


def test_start_attribute_session_preserves_explicit_zero_age():
    state = start_attribute_session(object_name="apple", profile=_make_profile(), age=0)
    assert state.age == 0


def test_session_state_debug_dict_omits_heuristic_fields():
    debug = _make_state().to_debug_dict()

    for retired in ("substantive_turns", "attribute_touches", "intent_history", "touch_result", "readiness"):
        assert retired not in debug


def test_session_state_supports_simple_transitions():
    state = _make_state()

    state.turn_count += 1
    assert state.turn_count == 1
    assert state.activity_ready is False

    state.activity_ready = True
    assert state.activity_ready is True


# -- build_attribute_debug ---------------------------------------------------

def test_build_attribute_debug_includes_marker_flag():
    state = _make_state()
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
        reason="marker detected in follow-up",
        activity_marker_detected=True,
        activity_marker_reason="Child explored color through comparison and preference",
        response_text="Can you spot anything else around you that's bright red?",
        intent_type="correct_answer",
    )

    assert debug["decision"] == "attribute_activity"
    assert debug["activity_marker_detected"] is True
    assert debug["activity_marker_reason"] == "Child explored color through comparison and preference"
    assert debug["intent_type"] == "correct_answer"
    assert "touch_result" not in debug
    assert "readiness" not in debug


def test_build_attribute_debug_defaults_marker_flag_to_false():
    state = _make_state()
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
    )
    assert debug["activity_marker_detected"] is False


def test_build_attribute_debug_defaults_reason_to_none():
    state = _make_state()
    debug = build_attribute_debug(
        decision="attribute_activity",
        profile=state.profile,
        state=state,
    )
    assert debug["activity_marker_reason"] is None


# -- ATTRIBUTE_SOFT_GUIDE invariants -----------------------------------------

def test_soft_guide_defines_marker_and_llm_decides_timing():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "[activity_ready]" in guide_lower
    assert "you feel" in guide_lower or "when you" in guide_lower


def test_soft_guide_requests_reason_line():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "reason:" in guide_lower
    assert "invisible to the child" in guide_lower


def test_soft_guide_rejects_hard_lock_and_quiz_patterns():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "must stay on" not in guide_lower
    assert "do not move on until" not in guide_lower


def test_soft_guide_warns_about_premature_handoff():
    guide_lower = ATTRIBUTE_SOFT_GUIDE.lower()

    assert "premature" in guide_lower or "too early" in guide_lower or "shallow" in guide_lower
    assert "breaks the experience" in guide_lower or "break" in guide_lower


# -- CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT invariants ----------------------------

def test_curiosity_attribute_response_prompt_exists():
    prompts = paixueji_prompts.get_prompts()
    assert "curiosity_attribute_response_prompt" in prompts
    prompt = prompts["curiosity_attribute_response_prompt"]
    assert "BEAT 3" not in prompt
    assert "Do NOT ask a question" in prompt
    assert "BEAT 1" in prompt
    assert "BEAT 2" in prompt


@pytest.mark.asyncio
async def test_curiosity_uses_attribute_prompt_in_pipeline(monkeypatch):
    prompts = {
        "curiosity_intent_prompt": "INTENT_PROMPT",
        "curiosity_attribute_response_prompt": "ATTR_PROMPT",
        "attribute_response_hint": "HINT: {attribute_label}",
    }
    monkeypatch.setattr(paixueji_prompts, "get_prompts", lambda: prompts)

    captured_contents = []

    async def mock_generate(*, model, contents, config):
        # Capture contents to verify prompt used (prompt text is in the user message)
        captured_contents.append(contents)

        class FakeStream:
            async def __anext__(self):
                raise StopAsyncIteration

            def __aiter__(self):
                return self

        return FakeStream()

    client = MagicMock()
    client.aio.models.generate_content_stream = mock_generate

    generator = generate_attribute_activation_response_stream(
        messages=[{"role": "system", "content": "sys"}],
        intent_type="curiosity",
        object_name="cat",
        attribute_label="body color",
        activity_target="find colors",
        child_answer="Why stripes?",
        reply_type="discovery",
        state_action="continue",
        age=5,
        age_prompt="Keep it simple.",
        config={"model_name": "test-model", "temperature": 0.7, "max_tokens": 500},
        client=client,
    )

    # Drain the generator
    async for _ in generator:
        pass

    assert len(captured_contents) > 0
    # The ATTR_PROMPT should have been used, not INTENT_PROMPT
    contents_text = str(captured_contents[0])
    assert "ATTR_PROMPT" in contents_text
    assert "INTENT_PROMPT" not in contents_text


def test_ask_followup_includes_thread_weaving(monkeypatch):
    prompts = {
        "followup_question_prompt": "ASK ONE QUESTION about {object_name}.",
        "attribute_soft_guide": "SOFT GUIDE: {attribute_label}",
    }
    monkeypatch.setattr(paixueji_prompts, "get_prompts", lambda: prompts)

    captured_contents = []
    async def mock_stream(*, model, contents, config):
        captured_contents.append(contents)
        class Fake:
            async def __anext__(self): raise StopAsyncIteration
            def __aiter__(self): return self
        return Fake()

    client = MagicMock()
    client.aio.models.generate_content_stream = mock_stream

    async def drain():
        gen = ask_followup_question_stream(
            messages=[{"role": "system", "content": "sys"}],
            object_name="cat",
            age_prompt="Keep it simple.",
            age=5,
            config={"model_name": "test-model", "temperature": 0.3, "max_tokens": 2000},
            client=client,
            attribute_soft_guide="SOFT GUIDE: body color",
            response_text="Cats have stripes for camouflage!",
        )
        async for _ in gen:
            pass

    import asyncio
    asyncio.run(drain())

    assert len(captured_contents) > 0
    contents_text = str(captured_contents[0])
    assert "RESPONSE THREAD CONTEXT" in contents_text
    assert "Cats have stripes for camouflage!" in contents_text
    assert "grows from this response" in contents_text


def test_ask_followup_skips_thread_weaving_without_soft_guide(monkeypatch):
    prompts = {
        "followup_question_prompt": "ASK ONE QUESTION about {object_name}.",
    }
    monkeypatch.setattr(paixueji_prompts, "get_prompts", lambda: prompts)

    captured_contents = []
    async def mock_stream(*, model, contents, config):
        captured_contents.append(contents)
        class Fake:
            async def __anext__(self): raise StopAsyncIteration
            def __aiter__(self): return self
        return Fake()

    client = MagicMock()
    client.aio.models.generate_content_stream = mock_stream

    async def drain():
        gen = ask_followup_question_stream(
            messages=[{"role": "system", "content": "sys"}],
            object_name="cat",
            age_prompt="Keep it simple.",
            age=5,
            config={"model_name": "test-model", "temperature": 0.3, "max_tokens": 2000},
            client=client,
            response_text="Some response text",
        )
        async for _ in gen:
            pass

    import asyncio
    asyncio.run(drain())

    assert len(captured_contents) > 0
    contents_text = str(captured_contents[0])
    assert "RESPONSE THREAD CONTEXT" not in contents_text
