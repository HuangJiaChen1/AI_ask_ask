"""Tests for the Natural Discovery attribute pipeline.

Tests cover:
- AttributeTouchDetector (heuristic keyword matching)
- DiscoverySessionState (new state model)
- evaluate_discovery_readiness (attribute_touch >= 1 AND substantive >= 2)
- Anti-quiz pattern detection
- Integration scenarios
"""
import pytest

from attribute_activity import (
    AttributeProfile,
    AttributeTouchResult,
    DiscoverySessionState,
    detect_attribute_touch,
    evaluate_discovery_readiness,
    start_attribute_session,
    build_attribute_debug,
    SUBSTANTIVE_INTENTS,
    SUBSTANTIVE_TURN_THRESHOLD,
    ATTRIBUTE_TOUCH_THRESHOLD,
)


# --- Helpers ---
def _make_profile(attribute_id="appearance.body_color", label="body color",
                  activity_target="noticing and describing what apple looks like — specifically, apple's body color",
                  branch="in_kb"):
    return AttributeProfile(
        attribute_id=attribute_id,
        label=label,
        activity_target=activity_target,
        branch=branch,
        object_examples=("apple",),
    )


def _make_state(attribute_id="appearance.body_color", label="body color"):
    profile = _make_profile(attribute_id=attribute_id, label=label)
    return start_attribute_session(object_name="apple", profile=profile, age=6)


# --- AttributeTouchDetector tests ---


class TestDetectAttributeTouch:
    """Heuristic keyword-based detection of whether a child's reply
    touched the suggested attribute."""

    def test_direct_touch_body_color(self):
        result = detect_attribute_touch("It's red!", "appearance.body_color")
        assert result.touched is True
        assert result.touch_type == "direct"
        assert result.confidence == "high"
        assert "red" in result.matched

    def test_direct_touch_body_color_multiple(self):
        result = detect_attribute_touch("It's red and green!", "appearance.body_color")
        assert result.touched is True
        assert "red" in result.matched
        assert "green" in result.matched

    def test_indirect_touch_body_color(self):
        result = detect_attribute_touch("It's so bright!", "appearance.body_color")
        assert result.touched is True
        assert result.touch_type == "indirect"
        assert "bright" in result.matched

    def test_preference_touch_body_color(self):
        result = detect_attribute_touch("My favorite color is red", "appearance.body_color")
        assert result.touched is True
        # "red" is a direct match so it gets classified as direct (more precise)
        assert result.touch_type == "direct"

    def test_no_touch_body_color(self):
        """Child talks about shape, not color — no touch."""
        result = detect_attribute_touch("It's round!", "appearance.body_color")
        assert result.touched is False
        assert result.touch_type == "none"
        assert result.matched == []

    def test_no_touch_taste_when_attribute_is_color(self):
        """Child talks about taste but attribute is color — no touch."""
        result = detect_attribute_touch("It's sweet!", "appearance.body_color")
        assert result.touched is False

    def test_direct_touch_taste(self):
        result = detect_attribute_touch("It's sweet and crunchy!", "senses.taste")
        assert result.touched is True
        assert "sweet" in result.matched

    def test_direct_touch_covering(self):
        result = detect_attribute_touch("It's so fluffy!", "covering.covering")
        assert result.touched is True
        assert "fluffy" in result.matched

    def test_direct_touch_sound(self):
        result = detect_attribute_touch("It goes meow!", "senses.sound")
        assert result.touched is True
        assert "meow" in result.matched

    def test_direct_touch_body_parts(self):
        result = detect_attribute_touch("Its tail is so long", "structure.body_parts")
        assert result.touched is True
        assert "tail" in result.matched

    def test_direct_touch_body_size(self):
        result = detect_attribute_touch("It's a big apple", "appearance.body_size")
        assert result.touched is True
        assert "big" in result.matched

    def test_direct_touch_function(self):
        result = detect_attribute_touch("We use it to eat", "function.function_use")
        assert result.touched is True
        assert "use" in result.matched

    def test_empty_reply(self):
        result = detect_attribute_touch("", "appearance.body_color")
        assert result.touched is False
        assert result.touch_type == "none"

    def test_unknown_attribute_id(self):
        """Fallback: unknown sub_attribute has no patterns → no touch."""
        result = detect_attribute_touch("It's red", "appearance.unknown_attr")
        assert result.touched is False


# --- DiscoverySessionState tests ---


class TestDiscoverySessionState:

    def test_initial_state(self):
        state = _make_state()
        assert state.substantive_turns == 0
        assert state.attribute_touches == 0
        assert state.activity_ready is False
        assert state.intent_history == []

    def test_to_debug_dict(self):
        state = _make_state()
        debug = state.to_debug_dict()
        assert debug["substantive_turns"] == 0
        assert debug["attribute_touches"] == 0
        assert debug["profile"]["attribute_id"] == "appearance.body_color"

    def test_start_attribute_session_with_surface_object(self):
        profile = _make_profile()
        state = start_attribute_session(
            object_name="apple",
            profile=profile,
            age=5,
            surface_object_name="red apple",
            anchor_object_name="apple",
        )
        assert state.surface_object_name == "red apple"
        assert state.anchor_object_name == "apple"


# --- evaluate_discovery_readiness tests ---


class TestEvaluateDiscoveryReadiness:

    def test_not_ready_initially(self):
        """Fresh session — no touches, no substantive turns."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "correct_answer")

        assert readiness.activity_ready is False
        assert readiness.chat_phase_complete is False
        assert readiness.substantive_turns == 1  # correct_answer is substantive
        assert readiness.attribute_touches == 0

    def test_not_ready_with_touch_but_no_substantive(self):
        """Child touched attribute but intent was IDK (not substantive)."""
        state = _make_state()
        touch = AttributeTouchResult(touched=True, touch_type="direct", confidence="high", matched=["red"])
        readiness = evaluate_discovery_readiness(state, touch, "clarifying_idk")

        assert readiness.activity_ready is False
        assert readiness.attribute_touches == 1
        assert readiness.substantive_turns == 0  # IDK is not substantive

    def test_not_ready_with_substantive_but_no_touch(self):
        """Child gave substantive reply but didn't touch the attribute."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "correct_answer")

        assert readiness.activity_ready is False
        assert readiness.substantive_turns == 1
        assert readiness.attribute_touches == 0
        assert readiness.state_action == "soft_guide_attribute"

    def test_ready_when_both_thresholds_met(self):
        """Child touched attribute AND has enough substantive turns."""
        state = _make_state()
        # Turn 1: child says "It's red!" → touch + substantive
        touch1 = AttributeTouchResult(touched=True, touch_type="direct", confidence="high", matched=["red"])
        readiness1 = evaluate_discovery_readiness(state, touch1, "correct_answer")

        assert readiness1.activity_ready is False  # only 1 substantive turn, need 2
        assert state.attribute_touches == 1
        assert state.substantive_turns == 1

        # Turn 2: child says more about color → touch + substantive
        touch2 = AttributeTouchResult(touched=True, touch_type="direct", confidence="high", matched=["bright"])
        readiness2 = evaluate_discovery_readiness(state, touch2, "informative")

        assert readiness2.activity_ready is True
        assert readiness2.chat_phase_complete is True
        assert readiness2.state_action == "invite_attribute_activity"
        assert state.attribute_touches == 2
        assert state.substantive_turns == 2

    def test_ready_with_one_touch_and_two_substantive(self):
        """Touch on one turn, substantive on two turns (including the touch turn)."""
        state = _make_state()
        # Turn 1: child says "It's round" → no touch, but substantive (correct_answer)
        touch1 = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness1 = evaluate_discovery_readiness(state, touch1, "correct_answer")

        assert readiness1.activity_ready is False

        # Turn 2: child says "It's red!" → touch + substantive
        touch2 = AttributeTouchResult(touched=True, touch_type="direct", confidence="high", matched=["red"])
        readiness2 = evaluate_discovery_readiness(state, touch2, "correct_answer")

        assert readiness2.activity_ready is True
        assert state.attribute_touches == 1
        assert state.substantive_turns == 2

    def test_stays_ready_once_triggered(self):
        """Once ready, subsequent turns keep returning ready."""
        state = _make_state()
        touch = AttributeTouchResult(touched=True, touch_type="direct", confidence="high", matched=["red"])
        evaluate_discovery_readiness(state, touch, "correct_answer")
        evaluate_discovery_readiness(state, touch, "informative")

        # Already ready
        touch3 = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch3, "social_acknowledgment")

        assert readiness.activity_ready is True
        assert readiness.reason == "attribute activity was already ready"

    def test_social_acknowledgment_not_substantive(self):
        """SOCIAL_ACKNOWLEDGMENT is not in SUBSTANTIVE_INTENTS."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "social_acknowledgment")

        assert readiness.substantive_turns == 0

    def test_avoidance_not_substantive(self):
        """AVOIDANCE is not in SUBSTANTIVE_INTENTS."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "avoidance")

        assert readiness.substantive_turns == 0

    def test_curiosity_is_substantive(self):
        """CURIOSITY is in SUBSTANTIVE_INTENTS."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "curiosity")

        assert readiness.substantive_turns == 1

    def test_play_is_substantive(self):
        """PLAY is in SUBSTANTIVE_INTENTS."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "play")

        assert readiness.substantive_turns == 1

    def test_clarifying_wrong_is_substantive(self):
        """CLARIFYING_WRONG is in SUBSTANTIVE_INTENTS — tried but got wrong."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "clarifying_wrong")

        assert readiness.substantive_turns == 1

    def test_clarifying_constraint_is_substantive(self):
        """CLARIFYING_CONSTRAINT is in SUBSTANTIVE_INTENTS — engaged but constrained."""
        state = _make_state()
        touch = AttributeTouchResult(touched=False, touch_type="none", confidence="low", matched=[])
        readiness = evaluate_discovery_readiness(state, touch, "clarifying_constraint")

        assert readiness.substantive_turns == 1


# --- build_attribute_debug tests ---


class TestBuildAttributeDebug:

    def test_includes_touch_result(self):
        state = _make_state()
        touch = detect_attribute_touch("It's red!", state.profile.attribute_id)
        debug = build_attribute_debug(
            decision="attribute_activity",
            profile=state.profile,
            state=state,
            touch_result=touch,
            intent_type="correct_answer",
        )
        assert debug["touch_result"]["touched"] is True
        assert debug["intent_type"] == "correct_answer"

    def test_includes_readiness(self):
        state = _make_state()
        touch = detect_attribute_touch("It's red!", state.profile.attribute_id)
        readiness = evaluate_discovery_readiness(state, touch, "correct_answer")
        debug = build_attribute_debug(
            decision="attribute_activity",
            profile=state.profile,
            state=state,
            readiness=readiness,
        )
        assert debug["readiness"]["attribute_touches"] == 1
        assert debug["readiness"]["substantive_turns"] == 1


# --- Anti-quiz pattern tests ---


ANTI_QUIZ_PATTERNS = [
    "what color is",
    "what colour is",
    "do you know what",
    "can you tell me what",
    "what color does it have",
    "let's look at its color",
    "what color is the",
]


def _check_quiz_patterns(text: str) -> list[str]:
    """Return quiz-like patterns found in text."""
    text_lower = text.lower()
    found = []
    for pattern in ANTI_QUIZ_PATTERNS:
        if pattern in text_lower:
            found.append(pattern)
    return found


class TestAntiQuizPatterns:
    """These tests verify that the prompt design produces non-quiz-like
    output. They check the prompt text itself, not the LLM output."""

    def test_attribute_intro_prompt_has_no_quiz_instructions(self):
        from paixueji_prompts import ATTRIBUTE_INTRO_PROMPT
        # "only discuss" and "stay strictly within" are hard-lock instructions
        assert "only discuss" not in ATTRIBUTE_INTRO_PROMPT.lower()
        assert "stay strictly within" not in ATTRIBUTE_INTRO_PROMPT.lower()
        # The prompt SHOULD contain "knowledge-testing" in its rules (that's the anti-quiz rule)
        assert "knowledge-testing question" in ATTRIBUTE_INTRO_PROMPT.lower()

    def test_attribute_soft_guide_has_anti_patterns(self):
        from paixueji_prompts import ATTRIBUTE_SOFT_GUIDE
        # Verify BAD examples exist in the guide
        assert "✗" in ATTRIBUTE_SOFT_GUIDE
        assert "knowledge quiz" in ATTRIBUTE_SOFT_GUIDE.lower()
        assert "forced redirect" in ATTRIBUTE_SOFT_GUIDE.lower()
        assert "mechanical announcement" in ATTRIBUTE_SOFT_GUIDE.lower()

    def test_attribute_soft_guide_does_not_contain_hard_lock(self):
        from paixueji_prompts import ATTRIBUTE_SOFT_GUIDE
        assert "only discuss" not in ATTRIBUTE_SOFT_GUIDE.lower()
        assert "stay strictly within" not in ATTRIBUTE_SOFT_GUIDE.lower()
        assert "do not mention other features" not in ATTRIBUTE_SOFT_GUIDE.lower()


# --- Integration scenario tests ---


class TestIntegrationScenarios:

    def test_scenario_child_mentions_attribute_directly(self):
        """Child directly says the attribute — ready in 2 turns."""
        state = _make_state(attribute_id="appearance.body_color", label="body color")

        # Turn 1: child says "It's red!" → touch + substantive
        touch1 = detect_attribute_touch("It's red!", state.profile.attribute_id)
        r1 = evaluate_discovery_readiness(state, touch1, "correct_answer")
        assert not r1.activity_ready  # need 2 substantive turns

        # Turn 2: child says more about color → touch + substantive
        touch2 = detect_attribute_touch("Red and green apples both exist!", state.profile.attribute_id)
        r2 = evaluate_discovery_readiness(state, touch2, "informative")
        assert r2.activity_ready is True

    def test_scenario_child_observes_different_feature_then_touches(self):
        """Child first says shape, then color — still reaches ready."""
        state = _make_state(attribute_id="appearance.body_color", label="body color")

        # Turn 1: "It's round" → no color touch, but substantive
        touch1 = detect_attribute_touch("It's round!", state.profile.attribute_id)
        r1 = evaluate_discovery_readiness(state, touch1, "correct_answer")
        assert not r1.activity_ready
        assert r1.state_action == "soft_guide_attribute"

        # Turn 2: "It's red!" → color touch + substantive
        touch2 = detect_attribute_touch("It's red!", state.profile.attribute_id)
        r2 = evaluate_discovery_readiness(state, touch2, "correct_answer")
        assert r2.activity_ready is True

    def test_scenario_child_says_idk_then_guesses(self):
        """Child says IDK (not substantive), then gives correct answer (substantive + touch)."""
        state = _make_state(attribute_id="appearance.body_color", label="body color")

        # Turn 1: IDK → not substantive, no touch
        touch1 = detect_attribute_touch("I don't know", state.profile.attribute_id)
        r1 = evaluate_discovery_readiness(state, touch1, "clarifying_idk")
        assert not r1.activity_ready
        assert state.substantive_turns == 0

        # Turn 2: "Is it red?" → touch + substantive (clarifying_wrong)
        touch2 = detect_attribute_touch("Is it red?", state.profile.attribute_id)
        r2 = evaluate_discovery_readiness(state, touch2, "clarifying_wrong")
        assert not r2.activity_ready  # only 1 substantive, need 2

        # Turn 3: "Green apples too!" → touch + substantive
        touch3 = detect_attribute_touch("There are green apples too!", state.profile.attribute_id)
        r3 = evaluate_discovery_readiness(state, touch3, "informative")
        assert r3.activity_ready is True

    def test_scenario_child_never_touches_attribute(self):
        """Child keeps talking about other features — never ready."""
        state = _make_state(attribute_id="appearance.body_color", label="body color")

        touch1 = detect_attribute_touch("It's round!", state.profile.attribute_id)
        r1 = evaluate_discovery_readiness(state, touch1, "correct_answer")

        touch2 = detect_attribute_touch("It's crunchy!", state.profile.attribute_id)
        r2 = evaluate_discovery_readiness(state, touch2, "informative")

        # substantive_turns = 2, but attribute_touches = 0
        assert not r2.activity_ready
        assert state.attribute_touches == 0
        assert state.substantive_turns == 2
        assert r2.state_action == "soft_guide_attribute"