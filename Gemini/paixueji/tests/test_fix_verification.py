"""
Verification tests for 4 behavioral fixes applied to paixueji.

Fix 1: INTRODUCTION_PROMPT — 4-beat structure (EMOTIONAL OPENING, OBJECT CONFIRMATION,
       FEATURE DESCRIPTION, ENGAGEMENT HOOK) — ends with life-experience question, never knowledge test
Fix 2: CORRECT_ANSWER_INTENT_PROMPT BEAT 3 — yes/no preference for ages 3-5
Fix 3: FOLLOWUP_QUESTION_PROMPT rule 6 — "Did you know..." banned; "You know what..." approved
Fix 4: IDK Escalation — unified consecutive_struggle_count (IDK + wrong) + router-level escalation
"""
import asyncio
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

    def test_intro_prompt_declares_older_kid_buddy_voice(self):
        """INTRODUCTION_PROMPT must define the assistant as an older-kid buddy, not a teacher."""
        lower = self.prompt.lower()
        assert "older-kid buddy" in lower or "older kid buddy" in lower, (
            "INTRODUCTION_PROMPT must explicitly anchor the voice to an older-kid buddy"
        )
        assert "not a teacher" in lower, (
            "INTRODUCTION_PROMPT must explicitly forbid teacher-like delivery"
        )

    def test_intro_prompt_bans_literary_or_magic_pivots(self):
        """INTRODUCTION_PROMPT must forbid literary/magical pivots that drift away from the object."""
        lower = self.prompt.lower()
        assert "literary" in lower, (
            "INTRODUCTION_PROMPT must explicitly ban literary-sounding language"
        )
        assert "magic" in lower or "magical" in lower, (
            "INTRODUCTION_PROMPT must explicitly ban magic-style pivots unless the child starts them"
        )

    def test_intro_prompt_consumes_knowledge_context(self):
        """INTRODUCTION_PROMPT should accept grounded intro knowledge context."""
        assert "{knowledge_context}" in self.prompt, (
            "INTRODUCTION_PROMPT must consume knowledge_context so intro wording can stay grounded"
        )

    def test_anchor_bridge_intro_prompt_consumes_bridge_context(self):
        """ANCHOR_BRIDGE_INTRO_PROMPT must consume bridge_context and ban loose redirect wording."""
        import paixueji_prompts

        prompt = paixueji_prompts.ANCHOR_BRIDGE_INTRO_PROMPT
        assert "{bridge_context}" in prompt, (
            "ANCHOR_BRIDGE_INTRO_PROMPT must consume bridge_context"
        )
        assert "Do not invent a scene" in prompt, (
            "ANCHOR_BRIDGE_INTRO_PROMPT must ban fabricated scene-setting"
        )
        assert "Do not ask about unrelated anchor features" in prompt, (
            "ANCHOR_BRIDGE_INTRO_PROMPT must ban unrelated anchor feature pivots"
        )
        assert "must make the connection explicit" in prompt, (
            "ANCHOR_BRIDGE_INTRO_PROMPT must require an explicit connection in the intro"
        )
        assert "Do not stay entirely on the surface object" in prompt, (
            "ANCHOR_BRIDGE_INTRO_PROMPT must forbid a purely surface-object intro"
        )

    def test_unknown_object_intro_prompt_bans_fake_observation_language(self):
        """UNKNOWN_OBJECT_INTRO_PROMPT must ban fake observation and name-implied facts."""
        import paixueji_prompts

        prompt = paixueji_prompts.UNKNOWN_OBJECT_INTRO_PROMPT
        assert "Do not say you can see the object" in prompt
        assert "Do not invent facts from words inside the object's name" in prompt

    def test_bridge_activation_prompt_requires_explicit_surface_to_anchor_connection(self):
        """BRIDGE_ACTIVATION_RESPONSE_PROMPT must explicitly complete the bridge in one turn."""
        import paixueji_prompts

        prompt = paixueji_prompts.BRIDGE_ACTIVATION_RESPONSE_PROMPT
        lower = prompt.lower()
        assert "acknowledge the child's actual answer first" in lower
        assert "mention the surface object exactly once" in lower
        assert "explicitly name the anchor object" in lower
        assert "ask exactly one question" in lower
        assert "stay in the same relation lane" in lower

    def test_bridge_activation_prompt_bans_generic_topic_switch_filler(self):
        """BRIDGE_ACTIVATION_RESPONSE_PROMPT must ban generic excitement and fresh-intro filler."""
        import paixueji_prompts

        prompt = paixueji_prompts.BRIDGE_ACTIVATION_RESPONSE_PROMPT
        lower = prompt.lower()
        assert "do not say things like" in lower
        assert "i love cats" in lower
        assert "i'm excited to learn more" in lower
        assert "do not act like this is a fresh topic introduction" in lower

    def test_bridge_support_prompt_clarifies_without_switching(self):
        """BRIDGE_SUPPORT_RESPONSE_PROMPT must support without activating the anchor."""
        import paixueji_prompts

        prompt = paixueji_prompts.BRIDGE_SUPPORT_RESPONSE_PROMPT
        lower = prompt.lower()
        assert "do not activate the anchor yet" in lower
        assert "support action" in lower
        assert "clarify" in lower
        assert "scaffold" in lower
        assert "steer" in lower
        assert "ask a different, more concrete bridge question" in lower

    def test_anchor_bridge_intro_rejects_vague_food_for_questions(self):
        """ANCHOR_BRIDGE_INTRO_PROMPT should reject vague bridge questions."""
        import paixueji_prompts

        prompt = paixueji_prompts.ANCHOR_BRIDGE_INTRO_PROMPT.lower()
        assert "do not ask vague questions like" in prompt
        assert "most important part" in prompt
        assert "use concrete food_for angles" in prompt
        assert "smell" in prompt
        assert "nose" in prompt
        assert "eat" in prompt
        assert "mouth" in prompt

    def test_bridge_support_prompt_requires_answer_then_different_question(self):
        """Bridge support should answer/explain before asking a different question."""
        import paixueji_prompts

        prompt = paixueji_prompts.BRIDGE_SUPPORT_RESPONSE_PROMPT.lower()
        assert "answer or explain first" in prompt
        assert "ask a different, more concrete bridge question" in prompt


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

    def test_followup_prompt_prioritizes_concrete_directly_answerable_questions(self):
        """FOLLOWUP_QUESTION_PROMPT should favor concrete, directly answerable questions."""
        lower = self.followup.lower()
        assert "directly answerable" in lower, (
            "FOLLOWUP_QUESTION_PROMPT must require directly answerable questions"
        )
        assert "concrete" in lower, (
            "FOLLOWUP_QUESTION_PROMPT must explicitly prefer concrete follow-up questions"
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

    def test_followup_prompt_requires_staying_on_same_detail(self):
        """The follow-up prompt must stay on the same nearby detail instead of jumping sideways."""
        lower = self.prompt.lower()
        assert "same detail" in lower or "same attribute" in lower or "one-hop" in lower, (
            "FOLLOWUP_QUESTION_PROMPT must explicitly keep follow-ups on the same nearby detail"
        )

    def test_followup_prompt_discourages_unprompted_fantasy(self):
        """The follow-up prompt must not add fantasy unless the child already led there."""
        lower = self.prompt.lower()
        assert "unless the child" in lower and ("fantasy" in lower or "imagination" in lower), (
            "FOLLOWUP_QUESTION_PROMPT must limit unprompted fantasy pivots"
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


class TestIntroHookSelection:
    """Intro hook selection should default away from high-imagination hooks for younger kids."""

    def test_select_hook_type_excludes_high_imagination_hooks_for_age_five(self):
        from stream.utils import select_hook_type

        hook_types = {
            "想象导向": {
                "name": "想象导向",
                "concept": "fantasy pivot",
                "examples": ["If it were magic..."],
                "age_weights": {"5": 10},
                "requires_history": False,
            },
            "细节发现": {
                "name": "细节发现",
                "concept": "notice one real detail",
                "examples": ["Look at that detail."],
                "age_weights": {"5": 1},
                "requires_history": False,
            },
        }

        with patch("stream.utils.random.choices", return_value=["细节发现"]) as mock_choices:
            selected_name, _ = select_hook_type(age=5, messages=[], hook_types=hook_types)

        pool = mock_choices.call_args.args[0]
        assert "想象导向" not in pool, (
            "Age-5 intro hook selection should exclude high-imagination hooks by default"
        )
        assert selected_name == "细节发现"


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
        "used_kb_item": None,
        "kb_mapping_status": None,
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


class TestOrdinaryChatKbFlow:
    """Ordinary chat should use dimension KB only, with post-response debug mapping."""

    def test_start_route_does_not_load_object_context_for_ordinary_chat(self):
        import paixueji_app

        client = paixueji_app.app.test_client()

        async def fake_stream_graph_execution(_initial_state):
            if False:
                yield None

        with patch.object(paixueji_app.PaixuejiAssistant, "load_object_context_from_yaml") as mock_load_object, patch.object(
            paixueji_app.PaixuejiAssistant, "load_dimension_data"
        ) as mock_load_dimensions, patch(
            "paixueji_app.stream_graph_execution", new=fake_stream_graph_execution
        ):
            response = client.post("/api/start", json={"object_name": "Cat", "age": 6})

        assert response.status_code == 200
        mock_load_object.assert_not_called()
        mock_load_dimensions.assert_called_once_with("Cat")

    def test_build_chat_kb_context_uses_dimension_data_only(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "Look at the cat"}],
            intent_type="correct_answer",
        )
        state["object_name"] = "Cat"
        state["age"] = 6
        state["physical_dimensions"] = {
            "appearance": {"paw_pads": "Soft pads underneath the paws for quiet steps"},
            "senses": {"purring_vibration": "Gentle rumbling when comfortable"},
        }
        state["engagement_dimensions"] = {
            "emotions": [
                "What do you think makes a cat feel safe enough to fall asleep?",
                "How does it feel when a warm, fluffy cat sits near you?",
            ],
        }

        kb_context = graph._build_chat_kb_context(state)

        assert "paw pads: Soft pads underneath the paws for quiet steps" in kb_context
        assert "How does it feel when a warm, fluffy cat sits near you?" in kb_context
        assert "Children notice and name emotions" not in kb_context
        assert "primary theme reasoning" not in kb_context

    def test_chat_kb_context_is_empty_before_anchor_activation(self):
        import graph

        state = {
            "object_name": "cat food",
            "learning_anchor_active": False,
            "physical_dimensions": {"shape": {"ears": "pointy"}},
            "engagement_dimensions": {"emotions": ["soft and cozy"]},
        }

        assert graph._build_chat_kb_context(state) == ""
        assert graph._build_intro_kb_context(state) == ""

    @pytest.mark.asyncio
    async def test_map_response_to_kb_item_returns_top_physical_item(self):
        from stream.validation import map_response_to_kb_item

        assistant = _make_mock_assistant(struggle_count=0)
        response_text = (
            "Cats tiptoe with soft pads under their paws, which helps them move very quietly."
        )

        result = await map_response_to_kb_item(
            assistant=assistant,
            response_text=response_text,
            object_name="Cat",
            physical_dimensions={
                "appearance": {"paw_pads": "Soft pads underneath the paws for quiet steps"},
            },
            engagement_dimensions={
                "emotions": ["How does it feel when a warm, fluffy cat sits near you?"],
            },
        )

        assert result == {
            "kind": "physical_attribute",
            "dimension": "appearance",
            "attribute": "paw_pads",
            "value": "Soft pads underneath the paws for quiet steps",
        }

    def test_play_prompt_consumes_knowledge_context(self):
        from paixueji_prompts import PLAY_INTENT_PROMPT

        assert "{knowledge_context}" in PLAY_INTENT_PROMPT, (
            "play prompt must explicitly consume knowledge_context to be treated as grounded"
        )

    @pytest.mark.asyncio
    async def test_stream_chunks_emit_used_kb_item_without_legacy_dimension_fields(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        emitted = []

        async def capture(chunk):
            emitted.append(chunk.model_dump())

        state = _build_minimal_state(assistant, intent_type="correct_answer")
        state["stream_callback"] = capture
        state["start_time"] = 0.0
        state["sequence_number"] = 0
        state["status"] = "active"
        state["request_id"] = "req-1"
        state["session_id"] = "session-1"
        state["response_type"] = "correct_answer"
        state["used_kb_item"] = {
            "kind": "engagement_item",
            "dimension": "emotions",
            "seed_text": "How does it feel when a warm, fluffy cat sits near you?",
        }
        state["kb_mapping_status"] = "mapped"

        async def fake_generator():
            yield ("hello", None, "hello")

        await graph.stream_generator_to_callback(fake_generator(), state)

        assert emitted, "stream callback must emit at least one chunk"
        payload = emitted[0]
        assert payload["used_kb_item"] == {
            "kind": "engagement_item",
            "dimension": "emotions",
            "seed_text": "How does it feel when a warm, fluffy cat sits near you?",
        }
        assert payload["kb_mapping_status"] == "mapped"
        assert "dimension_hint_text" not in payload
        assert "active_dimension" not in payload
        assert "current_dimension" not in payload

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


class TestClassificationFailureRouting:
    """Classifier-failure turns should route to the freeform fallback path."""

    def test_router_uses_fallback_freeform_when_classification_failed(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=2)
        state = _build_minimal_state(assistant, intent_type=None)
        state["classification_status"] = "failed"
        state["classification_failure_reason"] = "invalid_output"

        router_result = graph.route_from_analyze_input(state)

        assert router_result == "fallback_freeform", (
            f"Classification failure must route to 'fallback_freeform', got '{router_result}'"
        )

    @pytest.mark.asyncio
    async def test_node_analyze_input_resets_struggle_state_on_classification_failure(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=2)
        assistant.dimensions_covered = []
        assistant.active_dimension = None
        assistant.active_dimension_turn_count = 0

        state = _build_minimal_state(assistant, intent_type=None)
        state["physical_dimensions"] = {}
        state["engagement_dimensions"] = {}
        state["dimensions_covered"] = []
        state["active_dimension"] = None
        state["active_dimension_turn_count"] = 0

        with patch(
            "graph.classify_intent",
            new=AsyncMock(
                return_value={
                    "intent_type": None,
                    "new_object": None,
                    "reasoning": "bad classifier output",
                    "classification_status": "failed",
                    "classification_failure_reason": "invalid_output",
                }
            ),
        ):
            result = await graph.node_analyze_input(state)

        assert assistant.consecutive_struggle_count == 0, (
            "Classification failure must reset the struggle counter instead of carrying old state forward"
        )
        assert result["intent_type"] is None
        assert result["classification_status"] == "failed"
        assert result["classification_failure_reason"] == "invalid_output"


class TestOrdinaryChatKbStreaming:
    """Ordinary chat should use full KB context without deferred dimension tracking."""

    @pytest.mark.asyncio
    async def test_node_analyze_input_returns_used_kb_placeholder_not_dimension_task(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "What color is it?"}],
            intent_type=None,
        )
        state["content"] = "Red"
        state["physical_dimensions"] = {"color": {"hue": "red"}}
        state["engagement_dimensions"] = {}

        with patch(
            "graph.classify_intent",
            new=AsyncMock(
                return_value={
                    "intent_type": "CORRECT_ANSWER",
                    "new_object": None,
                    "reasoning": "Child answered correctly",
                    "classification_status": "ok",
                    "classification_failure_reason": None,
                }
            ),
        ):
            result = await graph.node_analyze_input(state)

        assert result["used_kb_item"] is None
        assert "pending_dimension_task" not in result
        assert "current_dimension" not in result

    @pytest.mark.asyncio
    async def test_social_acknowledgment_followup_receives_full_kb_context(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        assistant.guide_phase = None
        assistant.ibpyp_theme_name = None
        assistant.key_concept = None
        assistant.ibpyp_theme_reason = None
        assistant.bridge_question = None

        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "Wow!"}],
            intent_type="social_acknowledgment",
        )
        state["content"] = "cool"
        state["physical_dimensions"] = {
            "shape": {"form": "round"},
            "color": {"hue": "red"},
        }
        state["engagement_dimensions"] = {
            "emotions": ["How does it feel when a warm, fluffy cat sits near you?"],
        }

        with patch("graph.generate_intent_response_stream", return_value=object()), patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(side_effect=[("brief reaction", 1), ("follow-up question", 2)]),
        ), patch("graph.ask_followup_question_stream", return_value=object()) as mock_followup:
            result = await graph.node_social_acknowledgment(state)

        knowledge_context = mock_followup.call_args.kwargs["knowledge_context"]
        assert "[physical.shape]" in knowledge_context
        assert "[engagement.emotions]" in knowledge_context
        assert result["full_response_text"] == "brief reaction follow-up question"

    @pytest.mark.asyncio
    async def test_intro_receives_physical_grounding_without_engagement_seeds(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "system", "content": "system prompt"}],
            intent_type=None,
        )
        state["response_type"] = "introduction"
        state["hook_types"] = {}
        state["physical_dimensions"] = {
            "function": {"blinking": "Blinking wipes and wets the eye like a quick sweep"},
            "appearance": {"pupil_size": "A black dot that can grow big or small"},
        }
        state["engagement_dimensions"] = {
            "imagination": ["Pretend your eyes have night vision mode"],
        }

        with patch("graph.ask_introduction_question_stream", return_value=object()) as mock_intro, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("intro text", 1)),
        ):
            result = await graph.node_generate_intro(state)

        knowledge_context = mock_intro.call_args.kwargs["knowledge_context"]
        assert "[physical.function]" in knowledge_context
        assert "[physical.appearance]" in knowledge_context
        assert "[engagement.imagination]" not in knowledge_context
        assert result["response_type"] == "introduction"

    @pytest.mark.asyncio
    async def test_pre_anchor_intro_uses_bridge_context_not_full_anchor_kb(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "system", "content": "system prompt"}],
            intent_type=None,
        )
        state["response_type"] = "introduction"
        state["hook_types"] = {}
        state["object_name"] = "cat food"
        state["surface_object_name"] = "cat food"
        state["anchor_object_name"] = "cat"
        state["anchor_status"] = "anchored_high"
        state["anchor_relation"] = "food_for"
        state["anchor_confidence_band"] = "high"
        state["learning_anchor_active"] = False
        state["bridge_attempt_count"] = 1
        state["intro_mode"] = "anchor_bridge"
        state["physical_dimensions"] = {
            "function": {"blinking": "Blinking wipes and wets the eye like a quick sweep"},
            "appearance": {"pupil_size": "A black dot that can grow big or small"},
        }
        state["engagement_dimensions"] = {
            "imagination": ["Pretend your eyes have night vision mode"],
        }

        with patch("graph.ask_introduction_question_stream", return_value=object()) as mock_intro, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("intro text", 1)),
        ):
            result = await graph.node_generate_intro(state)

        assert mock_intro.call_args.kwargs["knowledge_context"] == ""
        assert "smell" in mock_intro.call_args.kwargs["bridge_context"]
        assert result["response_type"] == "introduction"

    @pytest.mark.asyncio
    async def test_pre_anchor_intro_records_bridge_debug_with_visibility_signal(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "system", "content": "system prompt"}],
            intent_type=None,
        )
        state["response_type"] = "introduction"
        state["hook_types"] = {}
        state["object_name"] = "cat food"
        state["surface_object_name"] = "cat food"
        state["anchor_object_name"] = "cat"
        state["anchor_status"] = "anchored_high"
        state["anchor_relation"] = "food_for"
        state["anchor_confidence_band"] = "high"
        state["learning_anchor_active"] = False
        state["bridge_attempt_count"] = 1
        state["intro_mode"] = "anchor_bridge"

        with patch("graph.ask_introduction_question_stream", return_value=object()), patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("Hey! I see you have some cat food there. What does the cat food look like inside the bag?", 1)),
        ):
            result = await graph.node_generate_intro(state)

        assert result["bridge_debug"]["decision"] == "intro_bridge"
        assert result["bridge_debug"]["bridge_visible_in_response"] is False

    @pytest.mark.asyncio
    async def test_unresolved_correct_answer_passes_surface_only_guardrails(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "What does it smell like?"}],
            intent_type="correct_answer",
        )
        state["object_name"] = "cat food"
        state["surface_object_name"] = "cat food"
        state["anchor_status"] = "unresolved"
        state["learning_anchor_active"] = False

        with patch("graph.generate_intent_response_stream", return_value=object()) as mock_response, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(side_effect=[("brief reaction", 1), ("follow-up question", 2)]),
        ), patch("graph.ask_followup_question_stream", return_value=object()) as mock_followup:
            await graph.node_correct_answer(state)

        response_guardrails = mock_response.call_args.kwargs["resolution_guardrails"]
        followup_guardrails = mock_followup.call_args.kwargs["resolution_guardrails"]
        assert "No supported anchor is active" in response_guardrails
        assert "Do not introduce facts about related objects implied by the name" in response_guardrails
        assert "Do not introduce facts about related objects implied by the name" in followup_guardrails

    @pytest.mark.asyncio
    async def test_unresolved_correct_answer_uses_surface_only_response_mode(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "What does it smell like?"}],
            intent_type="correct_answer",
        )
        state["object_name"] = "cat food"
        state["surface_object_name"] = "cat food"
        state["anchor_status"] = "unresolved"
        state["learning_anchor_active"] = False

        with patch("graph.generate_intent_response_stream", return_value=object()) as mock_response, patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(side_effect=[("brief reaction", 1), ("follow-up question", 2)]),
        ), patch("graph.ask_followup_question_stream", return_value=object()) as mock_followup:
            await graph.node_correct_answer(state)

        assert mock_response.call_args.kwargs["surface_only_mode"] is True
        assert mock_response.call_args.kwargs["surface_object_name"] == "cat food"
        assert mock_followup.call_args.kwargs["surface_only_mode"] is True
        assert mock_followup.call_args.kwargs["surface_object_name"] == "cat food"

    def test_unresolved_surface_only_prompt_bans_implied_anchor_facts(self):
        import paixueji_prompts

        prompt = paixueji_prompts.UNRESOLVED_SURFACE_ONLY_PROMPT
        assert "Do not teach facts about related objects implied by the name" in prompt
        assert "If the object name contains another object word, ignore that implied object" in prompt

    @pytest.mark.asyncio
    async def test_node_finalize_emits_used_kb_item_for_one_stage_paths(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        assistant.guide_phase = None
        assistant.ibpyp_theme_name = None
        assistant.key_concept = None
        assistant.ibpyp_theme_reason = None
        assistant.bridge_question = None
        assistant._router_traces = []

        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "It looks funny!"}],
            intent_type="play",
        )
        state["content"] = "a monster"
        state["full_response_text"] = "Let's imagine it together."
        state["response_type"] = "play"
        state["classification_status"] = "ok"
        state["classification_failure_reason"] = None
        state["used_kb_item"] = {
            "kind": "physical_attribute",
            "dimension": "shape",
            "attribute": "form",
            "value": "round",
        }
        state["kb_mapping_status"] = "mapped"

        await graph.node_finalize(state)

        assert state["stream_callback"].await_count == 1
        final_chunk = state["stream_callback"].await_args.args[0]
        assert final_chunk.used_kb_item == {
            "kind": "physical_attribute",
            "dimension": "shape",
            "attribute": "form",
            "value": "round",
        }
        assert final_chunk.kb_mapping_status == "mapped"

    @pytest.mark.asyncio
    async def test_social_turn_marks_kb_mapping_not_applicable_and_skips_mapper(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "Do you think I can see it?"}],
            intent_type="social",
        )
        state["content"] = "Can you smell it?"
        state["used_kb_item"] = {
            "kind": "physical_attribute",
            "dimension": "shape",
            "attribute": "form",
            "value": "round",
        }
        state["kb_mapping_status"] = "mapped"

        with patch("graph.generate_intent_response_stream", return_value=object()), patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(side_effect=[("I don't have a nose.", 1), ("What would it smell like to you?", 2)]),
        ), patch("graph.ask_followup_question_stream", return_value=object()), patch(
            "graph._set_used_kb_item",
            new=AsyncMock(),
        ) as mock_set_used_kb_item:
            result = await graph.node_social(state)

        mock_set_used_kb_item.assert_not_awaited()
        assert result["used_kb_item"] is None
        assert result["kb_mapping_status"] == "not_applicable"

    @pytest.mark.asyncio
    async def test_fallback_freeform_marks_kb_mapping_not_applicable_and_skips_mapper(self):
        import graph

        assistant = _make_mock_assistant(struggle_count=0)
        state = _build_minimal_state(
            assistant,
            messages=[{"role": "assistant", "content": "Tell me more!"}],
            intent_type=None,
        )
        state["response_type"] = "fallback_freeform"
        state["used_kb_item"] = {
            "kind": "engagement_item",
            "dimension": "emotions",
            "seed_text": "How does it feel when a warm, fluffy cat sits near you?",
        }
        state["kb_mapping_status"] = "mapped"

        with patch("graph.generate_classification_fallback_stream", return_value=object()), patch(
            "graph.stream_generator_to_callback",
            new=AsyncMock(return_value=("Natural fallback", 1)),
        ), patch(
            "graph._set_used_kb_item",
            new=AsyncMock(),
        ) as mock_set_used_kb_item:
            result = await graph.node_fallback_freeform(state)

        mock_set_used_kb_item.assert_not_awaited()
        assert result["used_kb_item"] is None
        assert result["kb_mapping_status"] == "not_applicable"


def test_bridge_follow_classifier_prompt_includes_previous_bridge_question():
    import paixueji_prompts

    prompt = paixueji_prompts.BRIDGE_FOLLOW_CLASSIFIER_PROMPT
    assert "Previous bridge question" in prompt
    assert "{previous_bridge_question}" in prompt


@pytest.mark.asyncio
async def test_bridge_support_generator_exists(monkeypatch):
    import stream.response_generators as rg

    class Chunk:
        text = "I mean, a cat can notice food in different ways. What might its nose smell first?"

    async def fake_stream(*args, **kwargs):
        async def agen():
            yield Chunk()
        return agen()

    client = MagicMock()
    client.aio.models.generate_content_stream = fake_stream

    generator = rg.generate_bridge_support_response_stream(
        messages=[],
        child_answer="what do you mean?",
        surface_object_name="cat food",
        anchor_object_name="cat",
        age=6,
        age_prompt="Use short sentences.",
        bridge_context="allowed: smell, eat, mouth, nose",
        previous_bridge_question="What is the most important part?",
        support_action="clarify",
        config={"model_name": "mock", "temperature": 0.3, "max_tokens": 200},
        client=client,
    )

    full = ""
    async for _chunk, _usage, full_so_far in generator:
        full = full_so_far

    assert "cat" in full.lower()
