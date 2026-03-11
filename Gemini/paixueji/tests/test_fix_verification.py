"""
Verification tests for 4 behavioral fixes applied to paixueji.

Fix 1: INTRODUCTION_PROMPT — 3-beat structure (RECOGNITION, EMOTIONAL HOOK, SIMPLE QUESTION)
Fix 2: CORRECT_ANSWER_INTENT_PROMPT BEAT 3 — yes/no preference for ages 3-5
Fix 3: FOLLOWUP_QUESTION_PROMPT rule 6 — "Did you know..." banned; "You know what..." approved
Fix 4: IDK Escalation — consecutive_idk_count field + node_clarifying_idk branching
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ===========================================================================
# Fix 1 — INTRODUCTION_PROMPT beat structure
# ===========================================================================

class TestIntroductionPromptBeatStructure:
    """Verify that INTRODUCTION_PROMPT contains the new 3-beat structure."""

    @pytest.fixture(autouse=True)
    def load_prompt(self):
        import paixueji_prompts
        self.prompt = paixueji_prompts.INTRODUCTION_PROMPT

    def test_beat1_recognition_heading_present(self):
        """INTRODUCTION_PROMPT must contain 'BEAT 1 — RECOGNITION'."""
        assert "BEAT 1 — RECOGNITION" in self.prompt, (
            "INTRODUCTION_PROMPT must have 'BEAT 1 — RECOGNITION' heading"
        )

    def test_beat2_emotional_hook_heading_present(self):
        """INTRODUCTION_PROMPT must contain 'BEAT 2 — EMOTIONAL HOOK'."""
        assert "BEAT 2 — EMOTIONAL HOOK" in self.prompt, (
            "INTRODUCTION_PROMPT must have 'BEAT 2 — EMOTIONAL HOOK' heading"
        )

    def test_beat3_simple_question_heading_present(self):
        """INTRODUCTION_PROMPT must contain 'BEAT 3 — SIMPLE QUESTION'."""
        assert "BEAT 3 — SIMPLE QUESTION" in self.prompt, (
            "INTRODUCTION_PROMPT must have 'BEAT 3 — SIMPLE QUESTION' heading"
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

    def test_beat3_yes_no_or_simple_choice_for_ages_3_5(self):
        """BEAT 3 must specify 'YES/NO or simple-choice only' for ages 3-5."""
        assert "YES/NO or simple-choice only" in self.prompt, (
            "INTRODUCTION_PROMPT BEAT 3 must say 'YES/NO or simple-choice only' for ages 3-5"
        )

    def test_do_not_open_with_generic_instruction_present(self):
        """INTRODUCTION_PROMPT must contain 'Do NOT open with a generic' instruction."""
        assert "Do NOT open with a generic" in self.prompt, (
            "INTRODUCTION_PROMPT must contain 'Do NOT open with a generic' instruction"
        )

    def test_beat_ordering_recognition_before_hook_before_question(self):
        """BEAT 1 must appear before BEAT 2, which must appear before BEAT 3."""
        pos1 = self.prompt.find("BEAT 1 — RECOGNITION")
        pos2 = self.prompt.find("BEAT 2 — EMOTIONAL HOOK")
        pos3 = self.prompt.find("BEAT 3 — SIMPLE QUESTION")
        assert pos1 != -1 and pos2 != -1 and pos3 != -1, (
            "All three BEAT headings must be present"
        )
        assert pos1 < pos2 < pos3, (
            f"BEATs must appear in order 1→2→3 (positions: {pos1}, {pos2}, {pos3})"
        )


# ===========================================================================
# Fix 2 — CORRECT_ANSWER_INTENT_PROMPT BEAT 3
# ===========================================================================

class TestCorrectAnswerPromptBeat3:
    """Verify that BEAT 3 in CORRECT_ANSWER_INTENT_PROMPT prefers yes/no for ages 3-5."""

    @pytest.fixture(autouse=True)
    def load_prompt(self):
        import paixueji_prompts
        self.prompt = paixueji_prompts.CORRECT_ANSWER_INTENT_PROMPT

    def _beat3_section(self):
        """Return the text from BEAT 3 onward (up to PROHIBITIONS section)."""
        start = self.prompt.find("BEAT 3")
        end = self.prompt.find("PROHIBITIONS", start)
        if end == -1:
            end = len(self.prompt)
        return self.prompt[start:end]

    def test_beat3_prefer_yes_no_or_simple_choice(self):
        """BEAT 3 must contain 'PREFER yes/no or simple-choice format' for ages 3-5."""
        beat3 = self._beat3_section()
        assert "PREFER yes/no or simple-choice format" in beat3, (
            "CORRECT_ANSWER_INTENT_PROMPT BEAT 3 must say 'PREFER yes/no or simple-choice format'"
        )

    def test_beat3_too_abstract_bad_example_label_present(self):
        """BEAT 3 must contain a 'too abstract' label on the BAD example."""
        beat3 = self._beat3_section()
        assert "too abstract" in beat3, (
            "CORRECT_ANSWER_INTENT_PROMPT BEAT 3 must label the BAD example as 'too abstract'"
        )

    def test_beat3_old_text_open_ended_observation_question_removed(self):
        """The old phrase 'open-ended observation question' must NOT appear in BEAT 3."""
        beat3 = self._beat3_section()
        assert "open-ended observation question" not in beat3, (
            "Old text 'open-ended observation question' must be removed from BEAT 3"
        )

    def test_beat3_did_you_know_prohibition_present(self):
        """BEAT 3 must still say 'Do NOT use "Did you know...?" format'."""
        beat3 = self._beat3_section()
        assert 'Did you know' in beat3, (
            "BEAT 3 must still reference 'Did you know' (in the prohibition)"
        )

    def test_prohibitions_section_retains_did_you_know_ban(self):
        """The PROHIBITIONS section must still prohibit 'Did you know...?' anywhere."""
        prohibitions_start = self.prompt.find("PROHIBITIONS")
        assert prohibitions_start != -1, "PROHIBITIONS section must exist"
        prohibitions_text = self.prompt[prohibitions_start:]
        assert "Did you know" in prohibitions_text, (
            "PROHIBITIONS section must retain the 'Did you know...?' ban"
        )

    def test_what_do_you_think_happens_if_is_a_bad_example(self):
        """'What do you think happens' must be listed as a BAD example in BEAT 3, not approved."""
        beat3 = self._beat3_section()
        # The phrase should appear near a BAD label, not a GOOD label
        bad_pos = beat3.find("BAD")
        phrase_pos = beat3.find("What do you think happens")
        # phrase should exist and appear after (or in the vicinity of) a BAD label
        assert phrase_pos != -1, (
            "'What do you think happens' phrase should be present in BEAT 3 as a BAD example"
        )
        # Verify it appears after the first BAD label (within 200 chars is a reasonable window)
        assert bad_pos != -1, "BEAT 3 must have a BAD label"
        assert abs(phrase_pos - bad_pos) < 200, (
            "'What do you think happens' must be labelled as BAD, not as an approved framing"
        )


# ===========================================================================
# Fix 3 — FOLLOWUP_QUESTION_PROMPT rule 6
# ===========================================================================

class TestFollowupQuestionPromptRule6:
    """Verify rule 6 changes in FOLLOWUP_QUESTION_PROMPT."""

    @pytest.fixture(autouse=True)
    def load_prompt(self):
        import paixueji_prompts
        self.prompt = paixueji_prompts.FOLLOWUP_QUESTION_PROMPT

    def _rule6_section(self):
        """Return the text of the bridge-phrase / 'Did you know' rule (formerly rule 6)."""
        # Find the rule that discusses bridge phrases regardless of its number
        start = self.prompt.find("bridge phrase")
        assert start != -1, "Bridge phrase rule must exist in FOLLOWUP_QUESTION_PROMPT"
        # Walk back to the start of this rule's line
        rule_start = self.prompt.rfind("\n", 0, start) + 1
        # Find where the next numbered rule begins
        end = len(self.prompt)
        for candidate in [f"\n{n}. " for n in range(1, 10)]:
            idx = self.prompt.find(candidate, rule_start + 1)
            if idx != -1 and idx < end:
                end = idx
        return self.prompt[rule_start:end]

    def test_rule6_does_not_list_did_you_know_as_approved(self):
        """Rule 6 must NOT include 'Did you know...' as an approved bridge phrase."""
        rule6 = self._rule6_section()
        # The phrase exists but only as a prohibition target
        # Ensure it is mentioned in the context of a prohibition (DO NOT), not as a plain example
        if "Did you know" in rule6:
            # Acceptable only if explicitly preceded by a prohibition marker
            idx = rule6.find("Did you know")
            context = rule6[max(0, idx - 40):idx + 20]
            assert "NOT" in context or "not" in context or "DO NOT" in context or "Don't" in context, (
                "In rule 6, 'Did you know...' must only appear in the context of a prohibition"
            )

    def test_rule6_contains_do_not_use_did_you_know_prohibition(self):
        """Rule 6 must explicitly say 'Do NOT use \"Did you know...\"'."""
        rule6 = self._rule6_section()
        assert "Do NOT use" in rule6 and "Did you know" in rule6, (
            "Rule 6 must contain an explicit 'Do NOT use \"Did you know...\"' prohibition"
        )

    def test_rule6_approves_you_know_what_as_alternative(self):
        """Rule 6 must list 'You know what...' as an approved bridge phrase."""
        rule6 = self._rule6_section()
        assert "You know what" in rule6, (
            "Rule 6 must list 'You know what...' as an approved bridge phrase"
        )

    def test_rule6_contains_explanation_for_did_you_know_ban(self):
        """Rule 6 must explain WHY 'Did you know...' is banned."""
        rule6 = self._rule6_section()
        # Explanation should reference something about sounding like a question or confusing children
        has_reason = (
            "sounds like a question" in rule6
            or "confuses" in rule6
            or "sounds like" in rule6
            or "whether to respond" in rule6
        )
        assert has_reason, (
            "Rule 6 must explain why 'Did you know...' is banned "
            "(e.g. 'sounds like a question and confuses children')"
        )

    def test_rule6_approves_and_as_bridge(self):
        """Rule 6 must still list 'And...' as an approved bridge phrase."""
        rule6 = self._rule6_section()
        assert '"And..."' in rule6 or '"And...' in rule6 or "And..." in rule6, (
            "Rule 6 must still list 'And...' as an approved bridge phrase"
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
        "category_prompt": "",
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
        "suggested_objects": None,
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
