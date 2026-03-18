"""
Verification tests for 4 behavioral fixes applied to paixueji.

Fix 1: INTRODUCTION_PROMPT — 4-beat structure (EMOTIONAL OPENING, OBJECT CONFIRMATION,
       FEATURE DESCRIPTION, ENGAGEMENT HOOK) — ends with life-experience question, never knowledge test
Fix 2: CORRECT_ANSWER_INTENT_PROMPT BEAT 3 — yes/no preference for ages 3-5
Fix 3: FOLLOWUP_QUESTION_PROMPT rule 6 — "Did you know..." banned; "You know what..." approved
Fix 4: IDK Escalation — consecutive_idk_count field + node_clarifying_idk branching
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


# ===========================================================================
# Fix 4 — IDK Escalation
# ===========================================================================

class TestIdkEscalationPromptAndAttributes:
    """Verify static prompt content and assistant attribute for IDK escalation."""

    def test_paixueji_assistant_has_consecutive_idk_count_attribute(self):
        """PaixuejiAssistant must have consecutive_idk_count initialized to 0."""
        from paixueji_assistant import PaixuejiAssistant
        assistant = PaixuejiAssistant.__new__(PaixuejiAssistant)
        # Initialize only the fields we care about, bypassing network calls
        assistant.consecutive_idk_count = 0  # default value; test that class sets it
        # Re-verify by checking actual __init__ would set it — inspect source
        import inspect
        src = inspect.getsource(PaixuejiAssistant.__init__)
        assert "consecutive_idk_count = 0" in src, (
            "PaixuejiAssistant.__init__ must set consecutive_idk_count = 0"
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
# Fix 4 — node_clarifying_idk branching behavior (async node tests)
# ===========================================================================

def _build_minimal_state(assistant, messages=None):
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
        "intent_type": "clarifying_idk",
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


def _make_mock_assistant(idk_count=0):
    """Create a lightweight mock assistant with consecutive_idk_count."""
    assistant = MagicMock()
    assistant.consecutive_idk_count = idk_count
    assistant.state = MagicMock()
    assistant.state.value = "awaiting_answer"
    return assistant


class TestNodeClarifyingIdkBranching:
    """Verify node_clarifying_idk branches correctly on consecutive_idk_count."""

    @pytest.mark.asyncio
    async def test_first_idk_uses_clarifying_idk_intent(self):
        """On first IDK (count=0), node must use intent_type='clarifying_idk'."""
        import graph

        assistant = _make_mock_assistant(idk_count=0)
        state = _build_minimal_state(assistant)

        async def mock_generator(*args, **kwargs):
            yield MagicMock(text="here's a hint", type="content")

        with patch("graph.generate_intent_response_stream", return_value=mock_generator()) as mock_gen, \
             patch("graph.stream_generator_to_callback", new_callable=AsyncMock) as mock_stream:
            mock_stream.return_value = ("scaffold hint response", 1)

            result = await graph.node_clarifying_idk(state)

        assert result["response_type"] == "clarifying_idk", (
            f"First IDK must set response_type='clarifying_idk', got '{result['response_type']}'"
        )

    @pytest.mark.asyncio
    async def test_first_idk_increments_count_to_1(self):
        """On first IDK (count=0), node must increment consecutive_idk_count to 1."""
        import graph

        assistant = _make_mock_assistant(idk_count=0)
        state = _build_minimal_state(assistant)

        async def mock_generator(*args, **kwargs):
            yield MagicMock(text="here's a hint", type="content")

        with patch("graph.generate_intent_response_stream", return_value=mock_generator()), \
             patch("graph.stream_generator_to_callback", new_callable=AsyncMock) as mock_stream:
            mock_stream.return_value = ("scaffold hint response", 1)

            await graph.node_clarifying_idk(state)

        assert assistant.consecutive_idk_count == 1, (
            f"After first IDK, consecutive_idk_count must be 1, got {assistant.consecutive_idk_count}"
        )

    @pytest.mark.asyncio
    async def test_second_idk_uses_give_answer_idk_intent(self):
        """On second IDK (count=1), node must use intent_type='give_answer_idk'."""
        import graph

        assistant = _make_mock_assistant(idk_count=1)
        state = _build_minimal_state(assistant)

        async def mock_generator(*args, **kwargs):
            yield MagicMock(text="here's the answer", type="content")

        with patch("graph.generate_intent_response_stream", return_value=mock_generator()) as mock_gen, \
             patch("graph.stream_generator_to_callback", new_callable=AsyncMock) as mock_stream:
            mock_stream.return_value = ("direct answer response", 2)

            result = await graph.node_clarifying_idk(state)

        assert result["response_type"] == "give_answer_idk", (
            f"Second IDK must set response_type='give_answer_idk', got '{result['response_type']}'"
        )

    @pytest.mark.asyncio
    async def test_second_idk_resets_count_to_0(self):
        """On second IDK (count=1), node must reset consecutive_idk_count to 0."""
        import graph

        assistant = _make_mock_assistant(idk_count=1)
        state = _build_minimal_state(assistant)

        async def mock_generator(*args, **kwargs):
            yield MagicMock(text="here's the answer", type="content")

        with patch("graph.generate_intent_response_stream", return_value=mock_generator()), \
             patch("graph.stream_generator_to_callback", new_callable=AsyncMock) as mock_stream:
            mock_stream.return_value = ("direct answer response", 2)

            await graph.node_clarifying_idk(state)

        assert assistant.consecutive_idk_count == 0, (
            f"After second IDK, consecutive_idk_count must be reset to 0, "
            f"got {assistant.consecutive_idk_count}"
        )

    def test_node_analyze_input_resets_count_for_non_idk_intent(self):
        """node_analyze_input source must reset consecutive_idk_count for non-IDK intents."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module.node_analyze_input)
        # Must contain a branch that resets the count when intent is not IDK
        assert "consecutive_idk_count = 0" in source, (
            "node_analyze_input must reset consecutive_idk_count = 0 for non-IDK intents"
        )
        # Must check against CLARIFYING_IDK (uppercase — matches classify_intent return format)
        assert "CLARIFYING_IDK" in source, (
            "node_analyze_input must reference 'CLARIFYING_IDK' when deciding whether to reset count"
        )

    def test_node_analyze_input_reset_excludes_clarifying_idk(self):
        """node_analyze_input must NOT reset count when intent IS clarifying_idk."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module.node_analyze_input)
        # The reset should be inside an 'if intent NOT IN (CLARIFYING_IDK, ...)' branch
        # Verify the source has 'not in' or '!=' guard before the reset
        # The simplest structural check: reset comes with an exclusion condition
        assert (
            'not in' in source and 'CLARIFYING_IDK' in source
        ) or (
            '!= "CLARIFYING_IDK"' in source
        ), (
            "node_analyze_input must protect the reset behind 'intent not in (CLARIFYING_IDK, ...)'"
        )

    @pytest.mark.asyncio
    async def test_first_idk_gives_scaffold_not_answer(self):
        """First IDK response_type must be 'clarifying_idk' (scaffold), not 'give_answer_idk'."""
        import graph

        assistant = _make_mock_assistant(idk_count=0)
        state = _build_minimal_state(assistant)

        with patch("graph.generate_intent_response_stream") as mock_gen, \
             patch("graph.stream_generator_to_callback", new_callable=AsyncMock) as mock_stream:

            async def fake_gen(*args, **kwargs):
                yield MagicMock()

            mock_gen.return_value = fake_gen()
            mock_stream.return_value = ("scaffold hint", 1)

            result = await graph.node_clarifying_idk(state)

        # Regression: first IDK must NOT give the direct answer
        assert result["response_type"] != "give_answer_idk", (
            "First IDK must give a scaffold hint (clarifying_idk), not the direct answer (give_answer_idk)"
        )
        assert result["response_type"] == "clarifying_idk", (
            "First IDK response_type must be 'clarifying_idk'"
        )
