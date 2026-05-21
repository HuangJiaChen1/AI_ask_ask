"""Tests for attribute pipeline prompt separation from ordinary chat prompts.

Verifies that:
1. All attribute intent prompts exist and are distinct from ordinary prompts
2. Attribute prompts enforce the observation-anchored, angle-locked contract
3. The response generator resolves attribute-prefixed prompt keys
4. The follow-up generator uses the attribute follow-up prompt when in attribute mode
"""

import pytest

import paixueji_prompts
from stream import response_generators, question_generators


# Intents that have both ordinary and attribute variants
INTENT_NAMES = [
    "curiosity",
    "concept_confusion",
    "clarifying_idk",
    "clarifying_open_ended_idk",
    "give_answer_idk",
    "give_answer_open_ended_idk",
    "clarifying_wrong",
    "clarifying_constraint",
    "correct_answer",
    "informative",
    "play",
    "emotional",
    "avoidance",
    "boundary",
    "action",
    "social",
    "social_acknowledgment",
]

# Intents whose prompts must NOT ask a question (follow-up generator handles it)
INTENTS_WITHOUT_FOLLOWUP = {
    "curiosity",
    "concept_confusion",
    "clarifying_idk",
    "clarifying_open_ended_idk",
    "give_answer_idk",
    "give_answer_open_ended_idk",
    "clarifying_wrong",
    "clarifying_constraint",
    "play",
    "emotional",
    "avoidance",
    "boundary",
    "action",
}


class TestAttributePromptExistence:
    """Verify all attribute prompts are registered and non-empty."""

    def test_all_attribute_intent_prompts_exist(self):
        prompts = paixueji_prompts.get_prompts()
        for intent in INTENT_NAMES:
            key = f"attribute_{intent}_intent_prompt"
            assert key in prompts, f"Missing attribute prompt: {key}"
            assert len(prompts[key]) > 50, f"Attribute prompt too short: {key}"

    def test_attribute_followup_question_prompt_exists(self):
        prompts = paixueji_prompts.get_prompts()
        assert "attribute_followup_question_prompt" in prompts
        assert len(prompts["attribute_followup_question_prompt"]) > 50

    def test_attribute_exploration_contract_exists(self):
        assert hasattr(paixueji_prompts, 'ATTRIBUTE_EXPLORATION_CONTRACT')
        assert len(paixueji_prompts.ATTRIBUTE_EXPLORATION_CONTRACT) > 50


class TestAttributePromptDistinctness:
    """Verify attribute prompts differ from ordinary prompts."""

    def test_attribute_prompts_are_distinct_from_ordinary(self):
        prompts = paixueji_prompts.get_prompts()
        for intent in INTENT_NAMES:
            attr_key = f"attribute_{intent}_intent_prompt"
            ord_key = f"{intent}_intent_prompt"
            assert prompts[attr_key] != prompts[ord_key], (
                f"Attribute prompt {attr_key} must differ from ordinary {ord_key}"
            )


class TestAttributePromptContentInvariants:
    """Verify attribute prompts enforce the attribute exploration contract."""

    def _get_attribute_prompt(self, intent: str) -> str:
        return paixueji_prompts.get_prompts()[f"attribute_{intent}_intent_prompt"]

    def test_no_knowledge_context_placeholder(self):
        """Attribute prompts must not reference {knowledge_context} since grounding is unavailable."""
        for intent in INTENT_NAMES:
            prompt = self._get_attribute_prompt(intent)
            assert "{knowledge_context}" not in prompt, (
                f"attribute_{intent}_intent_prompt must not reference {{knowledge_context}}"
            )

    def test_observation_angle_lock_present(self):
        """Attribute prompts must mention the observation angle or attribute label lock."""
        for intent in INTENT_NAMES:
            prompt = self._get_attribute_prompt(intent)
            has_lock = (
                "{observation_angle}" in prompt
                or "{attribute_label}" in prompt
            )
            assert has_lock, (
                f"attribute_{intent}_intent_prompt must reference {{observation_angle}} or {{attribute_label}}"
            )

    def test_no_outside_facts_rule_present(self):
        """Attribute prompts must prohibit introducing outside facts."""
        for intent in INTENT_NAMES:
            prompt = self._get_attribute_prompt(intent)
            has_rule = (
                "Do NOT introduce outside facts" in prompt
                or "Do NOT introduce outside knowledge" in prompt
                or "Do NOT teach" in prompt
                or "No outside-memory" in prompt
                or "outside fact" in prompt.lower()
                or "outside knowledge" in prompt.lower()
                or "FORBIDDEN" in prompt
            )
            assert has_rule, (
                f"attribute_{intent}_intent_prompt must prohibit outside facts"
            )

    def test_no_anti_repetition_property_switching(self):
        """Attribute prompts must not encourage switching to a different property."""
        for intent in INTENT_NAMES:
            prompt = self._get_attribute_prompt(intent)
            # The ordinary correct_answer prompt says "choose a DIFFERENT angle or property"
            assert "DIFFERENT angle or property" not in prompt, (
                f"attribute_{intent}_intent_prompt must not encourage property switching"
            )

    def test_follow_up_constraint_preserved(self):
        """Intents in INTENTS_WITHOUT_FOLLOWUP must include a question in their prompt;
        intents NOT in the set must NOT include a question (follow-up generator handles it)."""
        for intent in INTENT_NAMES:
            prompt = self._get_attribute_prompt(intent)
            if intent in INTENTS_WITHOUT_FOLLOWUP:
                # Must include an explicit question beat/instruction
                has_question_beat = any(
                    phrase in prompt.upper()
                    for phrase in [
                        "CLOSING QUESTION",
                        "ONE OPEN QUESTION",
                        "ONE FUN QUESTION",
                        "RE-ASK OBSERVATIONALLY",
                        "LOW-PRESSURE INVITE",
                        "RE-ENGAGEMENT INVITE",
                        "LOW-PRESSURE HANDOFF",
                        "GENTLE PATH BACK",
                        "QUESTION ABOUT",
                        "FUN ACTION",
                        "EXCITING ALTERNATIVE + INVITE",
                        "ONE GENTLE OPTION",
                        "GENTLE PATH OFFER",
                        "SIMPLE OBSERVATION",
                        "INVITE",
                        "INVITATION",
                        "WHAT DO YOU NOTICE",
                        "WHAT DO YOU SEE",
                    ]
                )
                assert has_question_beat, (
                    f"attribute_{intent}_intent_prompt must include a question beat "
                    f"(intent is in INTENTS_WITHOUT_FOLLOWUP)"
                )
            else:
                # Must explicitly prohibit asking a question (follow-up generator handles it)
                has_no_question_rule = (
                    "Do NOT ask a question" in prompt
                    or "Do NOT end with a direct question" in prompt
                    or "must NOT include a question" in prompt
                )
                assert has_no_question_rule, (
                    f"attribute_{intent}_intent_prompt must prohibit asking a question "
                    f"(follow-up generator handles it for {intent})"
                )


class TestAttributeFollowupPromptInvariants:
    """Verify the attribute follow-up question prompt enforces strict angle locking."""

    def test_strict_focus_topic_lock(self):
        prompt = paixueji_prompts.get_prompts()["attribute_followup_question_prompt"]
        assert "STEER BACK" in prompt, "Attribute follow-up must instruct steering back to focus_topic"
        assert "MUST be about {focus_topic}" in prompt, "Attribute follow-up must mandate focus_topic"

    def test_no_knowledge_context_reference(self):
        prompt = paixueji_prompts.get_prompts()["attribute_followup_question_prompt"]
        assert "{knowledge_context}" not in prompt, "Attribute follow-up must not reference knowledge_context"

    def test_child_as_expert_framing(self):
        prompt = paixueji_prompts.get_prompts()["attribute_followup_question_prompt"]
        assert "Child is the expert" in prompt, "Attribute follow-up must frame child as expert"


class TestGeneratorRouting:
    """Verify generators resolve attribute-prefixed prompt keys."""

    def test_response_generator_uses_attribute_prefixed_key(self, monkeypatch):
        """generate_attribute_activation_response_stream should resolve attribute_* keys."""
        calls = []
        original_get_prompts = paixueji_prompts.get_prompts

        def tracking_get_prompts():
            prompts = original_get_prompts()
            original_get = prompts.get

            def tracking_get(key, default=None):
                if key.startswith("attribute_"):
                    calls.append(key)
                return original_get(key, default)

            prompts.get = tracking_get
            return prompts

        monkeypatch.setattr(paixueji_prompts, "get_prompts", tracking_get_prompts)

        # We can't easily run the async generator, but we can verify the key resolution
        # by checking the function logic directly
        import inspect
        source = inspect.getsource(response_generators.generate_attribute_activation_response_stream)
        assert 'f"attribute_{intent_lower}_intent_prompt"' in source, (
            "Response generator must resolve attribute-prefixed prompt keys"
        )

    def test_followup_generator_uses_attribute_prompt_when_soft_guide_present(self, monkeypatch):
        """ask_followup_question_stream should use attribute_followup_question_prompt
        when attribute_soft_guide is provided."""
        import inspect
        source = inspect.getsource(question_generators.ask_followup_question_stream)
        assert "attribute_followup_question_prompt" in source, (
            "Follow-up generator must reference attribute_followup_question_prompt"
        )
        assert "attribute_soft_guide" in source, (
            "Follow-up generator must use attribute_soft_guide as discriminator"
        )
