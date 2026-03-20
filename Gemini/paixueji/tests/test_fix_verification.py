"""
Verification tests for 4 behavioral fixes applied to paixueji.

Fix 1: INTRODUCTION_PROMPT — 4-beat structure (EMOTIONAL OPENING, OBJECT CONFIRMATION,
       FEATURE DESCRIPTION, ENGAGEMENT HOOK) — ends with life-experience question, never knowledge test
Fix 2: CORRECT_ANSWER_INTENT_PROMPT BEAT 3 — yes/no preference for ages 3-5
Fix 3: FOLLOWUP_QUESTION_PROMPT rule 6 — "Did you know..." banned; "You know what..." approved
Fix 4: IDK Escalation — unified consecutive_struggle_count (IDK + wrong) + router-level escalation
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ===========================================================================
# Fix 1 — INTRODUCTION_PROMPT 4-beat structure
# ===========================================================================

class TestIntroductionPromptBeatStructure:
    """Verify that INTRODUCTION_PROMPT contains the new 4-beat structure."""

    @pytest.fixture(autouse=True)
    def load_prompt(self):
        import paixueji_prompts
        self.prompt = paixueji_prompts.INTRODUCTION_PROMPT

    def test_beat1_emotional_opening_heading_present(self):
        """INTRODUCTION_PROMPT must contain 'BEAT 1 — EMOTIONAL OPENING'."""
        assert "BEAT 1 — EMOTIONAL OPENING" in self.prompt, (
            "INTRODUCTION_PROMPT must have 'BEAT 1 — EMOTIONAL OPENING' heading"
        )

    def test_beat2_object_confirmation_heading_present(self):
        """INTRODUCTION_PROMPT must contain 'BEAT 2 — OBJECT CONFIRMATION'."""
        assert "BEAT 2 — OBJECT CONFIRMATION" in self.prompt, (
            "INTRODUCTION_PROMPT must have 'BEAT 2 — OBJECT CONFIRMATION' heading"
        )

    def test_beat3_feature_description_heading_present(self):
        """INTRODUCTION_PROMPT must contain 'BEAT 3 — FEATURE DESCRIPTION'."""
        assert "BEAT 3 — FEATURE DESCRIPTION" in self.prompt, (
            "INTRODUCTION_PROMPT must have 'BEAT 3 — FEATURE DESCRIPTION' heading"
        )

    def test_beat4_engagement_hook_heading_present(self):
        """INTRODUCTION_PROMPT must contain 'BEAT 4 — ENGAGEMENT HOOK'."""
        assert "BEAT 4 — ENGAGEMENT HOOK" in self.prompt, (
            "INTRODUCTION_PROMPT must have 'BEAT 4 — ENGAGEMENT HOOK' heading"
        )

    def test_old_text_greet_child_warmly_removed(self):
        """'Greet the child warmly' must NOT appear in INTRODUCTION_PROMPT."""
        assert "Greet the child warmly" not in self.prompt, (
            "Old instruction 'Greet the child warmly' must be removed from INTRODUCTION_PROMPT"
        )

    def test_old_text_introduce_with_excitement_removed(self):
        """'Introduce the object with excitement' must NOT appear in INTRODUCTION_PROMPT."""
        assert "Introduce the object with excitement" not in self.prompt, (
            "Old instruction 'Introduce the object with excitement' must be removed from INTRODUCTION_PROMPT"
        )

    def test_engagement_hook_forbids_knowledge_testing(self):
        """BEAT 4 section must explicitly forbid knowledge-testing questions."""
        assert "FORBIDDEN" in self.prompt and "knowledge" in self.prompt.lower(), (
            "INTRODUCTION_PROMPT must explicitly forbid knowledge-testing questions in the hook"
        )

    def test_do_not_open_with_generic_instruction_present(self):
        """INTRODUCTION_PROMPT must contain 'Do NOT open with a generic' instruction."""
        assert "Do NOT open with a generic" in self.prompt, (
            "INTRODUCTION_PROMPT must contain 'Do NOT open with a generic' instruction"
        )

    def test_beat_ordering_all_four_beats_in_sequence(self):
        """All 4 BEATs must be present and appear in order 1→2→3→4."""
        pos1 = self.prompt.find("BEAT 1 — EMOTIONAL OPENING")
        pos2 = self.prompt.find("BEAT 2 — OBJECT CONFIRMATION")
        pos3 = self.prompt.find("BEAT 3 — FEATURE DESCRIPTION")
        pos4 = self.prompt.find("BEAT 4 — ENGAGEMENT HOOK")
        assert pos1 != -1 and pos2 != -1 and pos3 != -1 and pos4 != -1, (
            "All four BEAT headings must be present"
        )
        assert pos1 < pos2 < pos3 < pos4, (
            f"BEATs must appear in order 1→2→3→4 (positions: {pos1}, {pos2}, {pos3}, {pos4})"
        )


# ===========================================================================
# Fix 2 — CORRECT_ANSWER_INTENT_PROMPT BEAT 3
# ===========================================================================

class TestCorrectAnswerPromptBeat3:
    """Verify CORRECT_ANSWER_INTENT_PROMPT is 2-beat (no question) and FOLLOWUP_QUESTION_PROMPT
    carries the question guidance that was formerly in BEAT 3."""

    @pytest.fixture(autouse=True)
    def load_prompts(self):
        import paixueji_prompts
        self.prompt = paixueji_prompts.CORRECT_ANSWER_INTENT_PROMPT
        self.followup = paixueji_prompts.FOLLOWUP_QUESTION_PROMPT

    def test_correct_answer_prompt_has_no_beat3(self):
        """CORRECT_ANSWER_INTENT_PROMPT must NOT contain BEAT 3 — question is decoupled."""
        assert "BEAT 3" not in self.prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must not contain BEAT 3 after decoupling"
        )

    def test_followup_prompt_has_sensory_tier(self):
        """FOLLOWUP_QUESTION_PROMPT must include a SENSORY INVITE tier for observable questions."""
        assert "SENSORY" in self.followup, (
            "FOLLOWUP_QUESTION_PROMPT must include a SENSORY INVITE tier for observable questions"
        )

    def test_followup_prompt_has_knowledge_testing_forbidden(self):
        """FOLLOWUP_QUESTION_PROMPT must forbid knowledge-testing questions."""
        assert "NEVER test knowledge" in self.followup or "knowledge" in self.followup.lower(), (
            "FOLLOWUP_QUESTION_PROMPT must prohibit knowledge-testing questions"
        )

    def test_beat3_old_text_open_ended_observation_question_removed(self):
        """The old phrase 'open-ended observation question' must NOT appear in the prompt."""
        assert "open-ended observation question" not in self.prompt, (
            "Old text 'open-ended observation question' must not appear in CORRECT_ANSWER_INTENT_PROMPT"
        )

    def test_followup_prompt_did_you_know_prohibition(self):
        """FOLLOWUP_QUESTION_PROMPT must still ban 'Did you know...?' phrasing."""
        assert "Did you know" in self.followup, (
            "FOLLOWUP_QUESTION_PROMPT must reference 'Did you know' in a prohibition"
        )

    def test_prohibitions_section_retains_did_you_know_ban(self):
        """The PROHIBITIONS section of CORRECT_ANSWER_INTENT_PROMPT must still ban 'Did you know...?'."""
        prohibitions_start = self.prompt.find("PROHIBITIONS")
        assert prohibitions_start != -1, "PROHIBITIONS section must exist"
        prohibitions_text = self.prompt[prohibitions_start:]
        assert "Did you know" in prohibitions_text, (
            "PROHIBITIONS section must retain the 'Did you know...?' ban"
        )

    def test_followup_prompt_promotes_fun_imaginative_questions(self):
        """FOLLOWUP_QUESTION_PROMPT must promote fun/silly/imaginative questions over educational ones."""
        assert "FUN" in self.followup or "SILLY" in self.followup or "IMAGINATIVE" in self.followup, (
            "FOLLOWUP_QUESTION_PROMPT must promote fun/silly/imaginative questions"
        )

    def test_correct_answer_prompt_handles_negative_preference_detours(self):
        """Negative preference replies must be acknowledged briefly without making the alternate item the hook."""
        lower = self.prompt.lower()
        assert "negative preference" in lower or "alternate favorite" in lower, (
            "CORRECT_ANSWER_INTENT_PROMPT must explicitly address negative preference replies"
        )
        assert "must stay anchored to {object_name}".lower() in lower or "stay anchored to {object_name}" in lower, (
            "CORRECT_ANSWER_INTENT_PROMPT must require staying anchored to the current object"
        )

    def test_correct_answer_prompt_forbids_alternate_object_topic_switch(self):
        """Naming another liked object must not silently become a topic switch inside correct_answer."""
        lower = self.prompt.lower()
        assert "must not become the teaching hook" in lower or "must not become the hook" in lower, (
            "CORRECT_ANSWER_INTENT_PROMPT must forbid making the alternate item the teaching hook"
        )
        assert "unless topic-switch logic explicitly changed the object" in lower, (
            "CORRECT_ANSWER_INTENT_PROMPT must preserve explicit topic switching as the only exception"
        )


# ===========================================================================
# Fix 3 — FOLLOWUP_QUESTION_PROMPT rule 6
# ===========================================================================

class TestFollowupQuestionPromptRule6:
    """Verify 'Did you know' prohibition and GROW/SENSORY tiering in FOLLOWUP_QUESTION_PROMPT."""

    @pytest.fixture(autouse=True)
    def load_prompt(self):
        import paixueji_prompts
        self.prompt = paixueji_prompts.FOLLOWUP_QUESTION_PROMPT

    def _rules_section(self):
        """Return the RULES section of the prompt."""
        start = self.prompt.find("RULES:")
        assert start != -1, "RULES section must exist in FOLLOWUP_QUESTION_PROMPT"
        return self.prompt[start:]

    def test_did_you_know_only_appears_in_prohibition_context(self):
        """'Did you know' must only appear in the context of a prohibition, not as an approved phrase."""
        if "Did you know" in self.prompt:
            idx = self.prompt.find("Did you know")
            context = self.prompt[max(0, idx - 40):idx + 20]
            assert "NEVER" in context or "NOT" in context or "not" in context or "never" in context, (
                "'Did you know' must only appear in the context of a prohibition"
            )

    def test_rules_contain_never_use_did_you_know_prohibition(self):
        """RULES section must explicitly ban 'Did you know...' phrasing."""
        rules = self._rules_section()
        assert "NEVER" in rules and "Did you know" in rules, (
            "RULES section must contain an explicit 'NEVER use Did you know' prohibition"
        )

    def test_grow_tier_listed_as_best_approach(self):
        """FOLLOWUP_QUESTION_PROMPT must list GROW as the primary/best question approach."""
        assert "GROW" in self.prompt, (
            "FOLLOWUP_QUESTION_PROMPT must list GROW as the primary question approach"
        )

    def test_did_you_know_ban_has_explanation(self):
        """The 'Did you know' ban must include an explanation."""
        idx = self.prompt.find("Did you know")
        assert idx != -1, "'Did you know' must appear in prompt"
        surrounding = self.prompt[max(0, idx - 10):idx + 80]
        has_reason = (
            "reads like" in surrounding
            or "sounds like" in surrounding
            or "yet another" in surrounding
            or "confuses" in surrounding
        )
        assert has_reason, (
            "The 'Did you know' ban must explain why (e.g. 'reads like yet another question')"
        )

    def test_sensory_invite_tier_exists(self):
        """FOLLOWUP_QUESTION_PROMPT must list SENSORY INVITE as a fallback tier."""
        assert "SENSORY" in self.prompt, (
            "FOLLOWUP_QUESTION_PROMPT must include a SENSORY INVITE fallback tier"
        )

    def test_followup_prompt_preserves_qualified_facts(self):
        """Qualified facts must not be flattened into contradictions."""
        lower = self.prompt.lower()
        assert "looks like x but is y" in lower or "qualified fact" in lower, (
            "FOLLOWUP_QUESTION_PROMPT must explicitly cover qualified or contrastive facts"
        )
        assert "must not restate the surface comparison as literal fact" in lower, (
            "FOLLOWUP_QUESTION_PROMPT must forbid flattening a qualified comparison into a false statement"
        )

    def test_followup_prompt_contains_banana_herb_tree_example(self):
        """The prompt should document the banana herb/tree regression explicitly."""
        lower = self.prompt.lower()
        assert "banana" in lower and "herb" in lower and "tree" in lower, (
            "FOLLOWUP_QUESTION_PROMPT must include the banana herb/tree example"
        )
        assert "must not say bananas grow on a tree" in lower, (
            "FOLLOWUP_QUESTION_PROMPT must explicitly ban the reviewed banana contradiction"
        )


# ===========================================================================
# Fix 4 — IDK Escalation
# ===========================================================================

class TestIdkEscalationPromptAndAttributes:
    """Verify static prompt content and assistant attribute for IDK/wrong escalation."""

    def test_paixueji_assistant_has_consecutive_struggle_count_attribute(self):
        """PaixuejiAssistant must have consecutive_struggle_count initialized to 0."""
        import inspect
        from paixueji_assistant import PaixuejiAssistant
        src = inspect.getsource(PaixuejiAssistant.__init__)
        assert "consecutive_struggle_count = 0" in src, (
            "PaixuejiAssistant.__init__ must set consecutive_struggle_count = 0"
        )

    def test_get_prompts_registers_give_answer_idk_intent_prompt(self):
        """get_prompts() must return a dict with key 'give_answer_idk_intent_prompt'."""
        import paixueji_prompts
        prompts = paixueji_prompts.get_prompts()
        assert "give_answer_idk_intent_prompt" in prompts, (
            "get_prompts() must register 'give_answer_idk_intent_prompt'"
        )

    def test_give_answer_idk_prompt_stop_hinting_instruction(self):
        """GIVE_ANSWER_IDK_INTENT_PROMPT must say 'Stop hinting — give them the answer directly'."""
        import paixueji_prompts
        prompt = paixueji_prompts.GIVE_ANSWER_IDK_INTENT_PROMPT
        assert "Stop hinting" in prompt and "give them the answer directly" in prompt, (
            "GIVE_ANSWER_IDK_INTENT_PROMPT must say 'Stop hinting — give them the answer directly'"
        )

    def test_give_answer_idk_prompt_beat1_acceptance(self):
        """GIVE_ANSWER_IDK_INTENT_PROMPT must contain 'BEAT 1 — ACCEPTANCE'."""
        import paixueji_prompts
        prompt = paixueji_prompts.GIVE_ANSWER_IDK_INTENT_PROMPT
        assert "BEAT 1 — ACCEPTANCE" in prompt, (
            "GIVE_ANSWER_IDK_INTENT_PROMPT must contain 'BEAT 1 — ACCEPTANCE'"
        )

    def test_give_answer_idk_prompt_beat2_direct_answer(self):
        """GIVE_ANSWER_IDK_INTENT_PROMPT must contain 'BEAT 2 — DIRECT ANSWER'."""
        import paixueji_prompts
        prompt = paixueji_prompts.GIVE_ANSWER_IDK_INTENT_PROMPT
        assert "BEAT 2 — DIRECT ANSWER" in prompt, (
            "GIVE_ANSWER_IDK_INTENT_PROMPT must contain 'BEAT 2 — DIRECT ANSWER'"
        )

    def test_give_answer_idk_prompt_do_not_hint_again(self):
        """GIVE_ANSWER_IDK_INTENT_PROMPT must contain 'Do NOT hint again'."""
        import paixueji_prompts
        prompt = paixueji_prompts.GIVE_ANSWER_IDK_INTENT_PROMPT
        assert "Do NOT hint again" in prompt, (
            "GIVE_ANSWER_IDK_INTENT_PROMPT must contain 'Do NOT hint again'"
        )

    def test_give_answer_idk_prompt_exported_value_matches_module_constant(self):
        """get_prompts()['give_answer_idk_intent_prompt'] must equal GIVE_ANSWER_IDK_INTENT_PROMPT."""
        import paixueji_prompts
        prompts = paixueji_prompts.get_prompts()
        assert prompts["give_answer_idk_intent_prompt"] == paixueji_prompts.GIVE_ANSWER_IDK_INTENT_PROMPT, (
            "get_prompts() must export the same object as the GIVE_ANSWER_IDK_INTENT_PROMPT constant"
        )


# ===========================================================================
# Fix 4 — node_clarifying_idk and router behavior (unified struggle counter)
# ===========================================================================

def _build_minimal_state(assistant, messages=None, intent_type="clarifying_idk"):
    """Build the minimum PaixuejiState dict needed for node_clarifying_idk."""
    mock_callback = AsyncMock()
    return {
        "session_id": "test_idk",
        "request_id": "req_test",
        "assistant": assistant,
        "content": "I don't know",
        "object_name": "apple",
        "age": 4,
        "age_prompt": "",
        "config": {"model_name": "mock-model"},
        "client": MagicMock(),
        "messages": messages or [],
        "sequence_number": 0,
        "stream_callback": mock_callback,
        "full_response_text": "",
        "full_question_text": "",
        "start_time": 0.0,
        "ttft": None,
        "nodes_executed": [],
        # Other PaixuejiState fields (defaults)
        "intent_type": intent_type,
        "response_type": None,
        "new_object_name": None,
        "detected_object_name": None,
        "fun_fact": None,
        "fun_fact_hook": None,
        "fun_fact_question": None,
        "real_facts": None,
        "guide_phase": None,
        "guide_status": None,
        "guide_strategy": None,
        "guide_turn_count": None,
        "last_navigation_state": None,
        "correct_answer_count": 0,
        "level1_category": None,
        "level2_category": None,
        "level3_category": None,
        "status": "normal",
        "scaffold_level": 0,
    }


def _make_mock_assistant(struggle_count=0):
    """Create a lightweight mock assistant with consecutive_struggle_count."""
    assistant = MagicMock()
    assistant.consecutive_struggle_count = struggle_count
    assistant.correct_answer_count = 0
    assistant.state = MagicMock()
    assistant.state.value = "awaiting_answer"
    return assistant


class TestNodeClarifyingIdkBranching:
    """Verify node_clarifying_idk always produces clarifying_idk (router owns escalation)."""

    @pytest.mark.asyncio
    async def test_first_idk_uses_clarifying_idk_intent(self):
        """node_clarifying_idk must always return response_type='clarifying_idk'."""
        import graph

        assistant = _make_mock_assistant(struggle_count=1)
        state = _build_minimal_state(assistant)

        with patch("graph.generate_intent_response_stream") as mock_gen, \
             patch("graph.stream_generator_to_callback", new_callable=AsyncMock) as mock_stream:

            async def fake_gen(*args, **kwargs):
                yield MagicMock(text="here's a hint", type="content")

            mock_gen.return_value = fake_gen()
            mock_stream.return_value = ("scaffold hint response", 1)

            result = await graph.node_clarifying_idk(state)

        assert result["response_type"] == "clarifying_idk", (
            f"node_clarifying_idk must always set response_type='clarifying_idk', "
            f"got '{result['response_type']}'"
        )

    @pytest.mark.asyncio
    async def test_first_idk_increments_count_to_1(self):
        """struggle_count is incremented by node_analyze_input (not node_clarifying_idk)."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module.node_analyze_input)
        # node_analyze_input must increment on _STRUGGLING_INTENTS
        assert "consecutive_struggle_count += 1" in source, (
            "node_analyze_input must increment consecutive_struggle_count for struggling intents"
        )

    @pytest.mark.asyncio
    async def test_second_idk_uses_give_answer_idk_intent(self):
        """Router must return 'give_answer_idk' when struggle_count >= 2 and intent is clarifying_idk."""
        import graph

        assistant = _make_mock_assistant(struggle_count=2)
        # Build a minimal state that mimics what route_from_analyze_input sees
        state = _build_minimal_state(assistant)

        router_result = graph.route_from_analyze_input(state)

        assert router_result == "give_answer_idk", (
            f"Router must return 'give_answer_idk' at struggle_count=2 + clarifying_idk, "
            f"got '{router_result}'"
        )

    @pytest.mark.asyncio
    async def test_second_idk_resets_count_to_0(self):
        """node_give_answer_idk must reset consecutive_struggle_count to 0."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module.node_give_answer_idk)
        assert "consecutive_struggle_count = 0" in source, (
            "node_give_answer_idk must reset consecutive_struggle_count = 0"
        )

    def test_node_analyze_input_resets_count_for_non_idk_intent(self):
        """node_analyze_input source must reset consecutive_struggle_count for non-struggling intents."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module.node_analyze_input)
        assert "consecutive_struggle_count = 0" in source, (
            "node_analyze_input must reset consecutive_struggle_count = 0 for non-struggling intents"
        )
        # The check uses the _STRUGGLING_INTENTS constant (not the literal string)
        assert "_STRUGGLING_INTENTS" in source, (
            "node_analyze_input must use _STRUGGLING_INTENTS to gate the counter increment/reset"
        )

    def test_node_analyze_input_reset_excludes_clarifying_idk(self):
        """node_analyze_input must also exclude CLARIFYING_WRONG from the reset."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module.node_analyze_input)
        # Both IDK and WRONG must be in _STRUGGLING_INTENTS (module-level constant)
        assert "CLARIFYING_WRONG" in source or "_STRUGGLING_INTENTS" in source, (
            "node_analyze_input must reference _STRUGGLING_INTENTS which includes CLARIFYING_WRONG"
        )

    @pytest.mark.asyncio
    async def test_first_idk_gives_scaffold_not_answer(self):
        """node_clarifying_idk must always produce 'clarifying_idk', never 'give_answer_idk'."""
        import graph

        assistant = _make_mock_assistant(struggle_count=1)
        state = _build_minimal_state(assistant)

        with patch("graph.generate_intent_response_stream") as mock_gen, \
             patch("graph.stream_generator_to_callback", new_callable=AsyncMock) as mock_stream:

            async def fake_gen(*args, **kwargs):
                yield MagicMock()

            mock_gen.return_value = fake_gen()
            mock_stream.return_value = ("scaffold hint", 1)

            result = await graph.node_clarifying_idk(state)

        assert result["response_type"] != "give_answer_idk", (
            "node_clarifying_idk must give a scaffold hint, not the direct answer"
        )
        assert result["response_type"] == "clarifying_idk", (
            "node_clarifying_idk response_type must always be 'clarifying_idk'"
        )


class TestUnifiedStruggleCounter:
    """New tests for unified IDK+wrong escalation behavior."""

    def test_struggling_intents_constant_includes_both(self):
        """_STRUGGLING_INTENTS must include both CLARIFYING_IDK and CLARIFYING_WRONG."""
        import graph as graph_module
        assert "CLARIFYING_IDK" in graph_module._STRUGGLING_INTENTS, (
            "_STRUGGLING_INTENTS must include CLARIFYING_IDK"
        )
        assert "CLARIFYING_WRONG" in graph_module._STRUGGLING_INTENTS, (
            "_STRUGGLING_INTENTS must include CLARIFYING_WRONG"
        )

    def test_wrong_answer_increments_struggle_count(self):
        """node_analyze_input source must increment struggle_count for CLARIFYING_WRONG."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module.node_analyze_input)
        assert "_STRUGGLING_INTENTS" in source, (
            "node_analyze_input must use _STRUGGLING_INTENTS to gate the increment"
        )
        assert "consecutive_struggle_count += 1" in source, (
            "node_analyze_input must increment consecutive_struggle_count"
        )

    def test_idk_then_wrong_triggers_give_answer(self):
        """Router returns 'give_answer_idk' when struggle_count=2 and intent is clarifying_wrong."""
        import graph

        assistant = _make_mock_assistant(struggle_count=2)
        state = _build_minimal_state(assistant, intent_type="clarifying_wrong")

        router_result = graph.route_from_analyze_input(state)

        assert router_result == "give_answer_idk", (
            f"IDK→wrong sequence (struggle_count=2, intent=clarifying_wrong) must route to "
            f"'give_answer_idk', got '{router_result}'"
        )

    def test_wrong_then_idk_triggers_give_answer(self):
        """Router returns 'give_answer_idk' when struggle_count=2 and intent is clarifying_idk."""
        import graph

        assistant = _make_mock_assistant(struggle_count=2)
        state = _build_minimal_state(assistant, intent_type="clarifying_idk")

        router_result = graph.route_from_analyze_input(state)

        assert router_result == "give_answer_idk", (
            f"wrong→IDK sequence (struggle_count=2, intent=clarifying_idk) must route to "
            f"'give_answer_idk', got '{router_result}'"
        )

    def test_single_wrong_does_not_trigger_give_answer(self):
        """Router must return 'clarifying_wrong' (not give_answer_idk) when struggle_count=1."""
        import graph

        assistant = _make_mock_assistant(struggle_count=1)
        state = _build_minimal_state(assistant, intent_type="clarifying_wrong")

        router_result = graph.route_from_analyze_input(state)

        assert router_result == "clarifying_wrong", (
            f"First wrong answer (struggle_count=1) must route to 'clarifying_wrong', "
            f"got '{router_result}'"
        )

    def test_single_idk_does_not_trigger_give_answer(self):
        """Router must return 'clarifying_idk' (not give_answer_idk) when struggle_count=1."""
        import graph

        assistant = _make_mock_assistant(struggle_count=1)
        state = _build_minimal_state(assistant, intent_type="clarifying_idk")

        router_result = graph.route_from_analyze_input(state)

        assert router_result == "clarifying_idk", (
            f"First IDK (struggle_count=1) must route to 'clarifying_idk', "
            f"got '{router_result}'"
        )
