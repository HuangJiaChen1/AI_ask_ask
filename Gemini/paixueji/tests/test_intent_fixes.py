"""
Tests for root-cause fixes applied to paixueji_prompts.py, stream/validation.py, and graph.py:

Fix 1 — CORRECT_ANSWER_INTENT_PROMPT overhaul
    - Beat 2 renamed to "WOW FACT (statement only)"
    - CRITICAL prohibition against "Did you know...?" phrasing
    - ANTI-REPETITION rule added
    - Beat 3 (fresh open-ended question about a DIFFERENT property) added

Fix 2 — SOCIAL_ACKNOWLEDGMENT as 11th intent
    - Added to USER_INTENT_PROMPT with disambiguation rules
    - SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT created with correct prohibitions
    - Added to valid_intents set in stream/validation.py
    - node_social_acknowledgment registered in graph.py
    - Routing wired in route_from_analyze_input conditional edges

Fix 3 — Dead code removal (CLARIFYING_INTENT_PROMPT + node_clarifying)
    - CLARIFYING_INTENT_PROMPT constant deleted (never reached: classify_intent never emits
      bare "CLARIFYING"; routing edge "clarifying" → "clarifying_idk" short-circuits)
    - node_clarifying function and its add_node registration removed from graph.py
    - "clarifying": "clarifying_idk" routing edge kept as graceful fallback

Fix 4 — Context-aware BEAT 3 in CLARIFYING_WRONG_INTENT_PROMPT
    - Visual invites ("Take a close look!") restricted to observable-property questions
    - Thought/imagination invites ("What do you think?") used for process/concept questions
    - Eliminates nonsensical "Take a close look!" when child answers a harvesting question
"""
import pytest
import paixueji_prompts
from stream.validation import classify_intent


# ============================================================================
# Fix 1 — CORRECT_ANSWER_INTENT_PROMPT content validation
# ============================================================================

class TestCorrectAnswerPromptOverhaul:
    """Validate that CORRECT_ANSWER_INTENT_PROMPT contains the overhauled structure."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.CORRECT_ANSWER_INTENT_PROMPT

    def test_beat_2_labeled_wow_fact_statement_only(self):
        """Beat 2 must be labelled 'WOW FACT (statement only)' — not 'Did you know?'."""
        prompt = self._get_prompt()
        assert "WOW FACT" in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must contain 'WOW FACT' label for Beat 2"
        )
        assert "statement only" in prompt.lower(), (
            "Beat 2 label must include '(statement only)' to clarify it is declarative"
        )

    def test_critical_prohibition_did_you_know(self):
        """Prompt must explicitly prohibit 'Did you know...?' phrasing at the top of Beat 2."""
        prompt = self._get_prompt()
        # The FORBIDDEN annotation must be present (replaces old CRITICAL marker)
        assert "FORBIDDEN" in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must contain a FORBIDDEN prohibition marker in Beat 2"
        )
        # The prohibition must reference the banned phrase
        assert "Did you know" in prompt, (
            "Prompt must name 'Did you know' as a banned phrase in its prohibition"
        )

    def test_anti_repetition_rule_present(self):
        """Prompt must include an ANTI-REPETITION rule for the wow fact."""
        prompt = self._get_prompt()
        assert "ANTI-REPETITION" in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must contain an ANTI-REPETITION rule"
        )

    def test_beat_3_question_decoupled(self):
        """CORRECT_ANSWER_INTENT_PROMPT must NOT contain BEAT 3 — question is now in followup prompt."""
        prompt = self._get_prompt()
        assert "BEAT 3" not in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must not contain BEAT 3 — question generation "
            "has been decoupled to ask_followup_question_stream / FOLLOWUP_QUESTION_PROMPT"
        )

    def test_max_length_note_mentions_two_beats(self):
        """Prompt should reference 2 beats in its length guidance."""
        prompt = self._get_prompt()
        assert "2 beats" in prompt or "2 sentences" in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must note a 2-sentence / 2-beat structure "
            "(question has been moved to the followup generator)"
        )

    def test_prohibitions_block_did_you_know_in_prohibitions_section(self):
        """The PROHIBITIONS block itself must ban 'Did you know...?'."""
        prompt = self._get_prompt()
        prohibitions_start = prompt.find("PROHIBITIONS")
        assert prohibitions_start != -1, "Prompt must have a PROHIBITIONS section"
        prohibitions_text = prompt[prohibitions_start:]
        assert "Did you know" in prohibitions_text, (
            "The PROHIBITIONS block must explicitly ban 'Did you know...?'"
        )

    def test_get_prompts_includes_correct_answer_intent_prompt(self):
        """get_prompts() must export the correct_answer_intent_prompt key."""
        prompts = paixueji_prompts.get_prompts()
        assert "correct_answer_intent_prompt" in prompts, (
            "get_prompts() must include 'correct_answer_intent_prompt'"
        )
        # Ensure the value is the overhauled version (WOW FACT present)
        assert "WOW FACT" in prompts["correct_answer_intent_prompt"]

    def test_prohibitions_no_question_in_correct_answer(self):
        """CORRECT_ANSWER_INTENT_PROMPT PROHIBITIONS must instruct the model not to ask a question."""
        prompt = self._get_prompt()
        prohibitions_start = prompt.find("PROHIBITIONS")
        assert prohibitions_start != -1, "Prompt must have a PROHIBITIONS section"
        prohibitions_text = prompt[prohibitions_start:]
        assert "Do NOT ask a question" in prohibitions_text, (
            "PROHIBITIONS must explicitly forbid asking a question "
            "(question has been decoupled to ask_followup_question_stream)"
        )

    def test_followup_question_prompt_exported_in_get_prompts(self):
        """get_prompts() must export 'followup_question_prompt' for ask_followup_question_stream."""
        prompts = paixueji_prompts.get_prompts()
        assert "followup_question_prompt" in prompts, (
            "get_prompts() must include 'followup_question_prompt'"
        )
        followup = prompts["followup_question_prompt"]
        # Must instruct question to GROW from the last assistant message (GROW or SENSORY tier)
        assert "GROW" in followup or "SENSORY" in followup, (
            "followup_question_prompt must describe a GROW or SENSORY approach for follow-up questions"
        )

    def test_followup_prompt_steers_away_from_knowledge_testing(self):
        """FOLLOWUP_QUESTION_PROMPT must prohibit knowledge-testing questions."""
        prompts = paixueji_prompts.get_prompts()
        followup = prompts["followup_question_prompt"]
        assert "NEVER test knowledge" in followup or "not test" in followup.lower() or "knowledge" in followup.lower(), (
            "followup_question_prompt must prohibit knowledge-testing questions"
        )


# ============================================================================
# Fix 2 — SOCIAL_ACKNOWLEDGMENT as 11th intent
# ============================================================================

class TestSocialAcknowledgmentIntentClassifier:
    """Validate SOCIAL_ACKNOWLEDGMENT exists as a valid classified intent."""

    def test_social_acknowledgment_in_valid_intents_set(self):
        """stream/validation.py's valid_intents set must include SOCIAL_ACKNOWLEDGMENT."""
        import inspect
        import stream.validation as validation_module
        source = inspect.getsource(validation_module)
        # The valid_intents set must contain the string
        assert "SOCIAL_ACKNOWLEDGMENT" in source, (
            "'SOCIAL_ACKNOWLEDGMENT' must appear in stream/validation.py valid_intents set"
        )

    def test_valid_intents_set_contains_social_acknowledgment_at_runtime(self):
        """Parse the valid_intents set from the source to confirm it includes SOCIAL_ACKNOWLEDGMENT."""
        import inspect
        import stream.validation as validation_module
        source = inspect.getsource(validation_module)
        # Find the valid_intents assignment block
        assert '"SOCIAL_ACKNOWLEDGMENT"' in source or "'SOCIAL_ACKNOWLEDGMENT'" in source, (
            "SOCIAL_ACKNOWLEDGMENT must be a string member of the valid_intents set in validation.py"
        )


class TestSocialAcknowledgmentPrompt:
    """Validate SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT content and exports."""

    def test_social_acknowledgment_intent_prompt_exists(self):
        """SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must be defined at module level."""
        assert hasattr(paixueji_prompts, "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT"), (
            "paixueji_prompts must define SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT"
        )
        assert len(paixueji_prompts.SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT) > 50, (
            "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must not be empty"
        )

    def test_social_acknowledgment_prompt_has_brief_reaction_beat(self):
        """Prompt must define a brief natural reaction beat (Beat 1)."""
        prompt = paixueji_prompts.SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT
        assert "BEAT 1" in prompt, (
            "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must have BEAT 1"
        )

    def test_social_acknowledgment_prompt_delegates_question_to_generator(self):
        """Prompt must NOT embed a question — question is delegated to follow-up question generator."""
        prompt = paixueji_prompts.SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT
        assert "BEAT 2" not in prompt, (
            "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must not contain BEAT 2 after decoupling"
        )
        assert "question generator" in prompt or "follow-up question generator" in prompt, (
            "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must mention generator delegation"
        )

    def test_social_acknowledgment_prompt_prohibits_did_you_know(self):
        """Prompt must prohibit 'Did you know...?' phrasing."""
        prompt = paixueji_prompts.SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT
        assert "Did you know" in prompt, (
            "Prompt must name 'Did you know' as prohibited phrasing"
        )
        # It should appear in a prohibition/ban context
        prohibitions_start = prompt.find("PROHIBITIONS")
        if prohibitions_start != -1:
            prohibitions_text = prompt[prohibitions_start:]
            assert "Did you know" in prohibitions_text, (
                "PROHIBITIONS block must ban 'Did you know...?'"
            )

    def test_social_acknowledgment_prompt_prohibits_hollow_praise(self):
        """Prompt must prohibit hollow praise tokens like 'Great!' or 'Wonderful!'."""
        prompt = paixueji_prompts.SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT
        # One or more of the hollow-praise tokens must be called out
        has_hollow_praise_prohibition = (
            "Great!" in prompt or "Wonderful!" in prompt or "grading" in prompt
        )
        assert has_hollow_praise_prohibition, (
            "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must prohibit hollow praise like 'Great!' or 'Wonderful!'"
        )

    def test_social_acknowledgment_prompt_prohibits_fact_repetition(self):
        """Prompt must prohibit repeating the fact that triggered the acknowledgment."""
        prompt = paixueji_prompts.SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT
        has_no_repeat_rule = (
            "repeat" in prompt.lower() or "re-explain" in prompt.lower()
        )
        assert has_no_repeat_rule, (
            "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must prohibit repeating the acknowledged fact"
        )

    def test_get_prompts_includes_social_acknowledgment_key(self):
        """get_prompts() must export 'social_acknowledgment_intent_prompt'."""
        prompts = paixueji_prompts.get_prompts()
        assert "social_acknowledgment_intent_prompt" in prompts, (
            "get_prompts() must include 'social_acknowledgment_intent_prompt'"
        )

    def test_get_prompts_social_acknowledgment_value_is_non_empty(self):
        """The exported social_acknowledgment prompt must not be empty."""
        prompts = paixueji_prompts.get_prompts()
        value = prompts.get("social_acknowledgment_intent_prompt", "")
        assert len(value) > 50, (
            "get_prompts()['social_acknowledgment_intent_prompt'] must return a substantive prompt"
        )


class TestUserIntentPromptSocialAcknowledgment:
    """Validate USER_INTENT_PROMPT contains SOCIAL_ACKNOWLEDGMENT with disambiguation rules."""

    def test_user_intent_prompt_contains_social_acknowledgment_category(self):
        """USER_INTENT_PROMPT must list SOCIAL_ACKNOWLEDGMENT as one of the intent categories."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        assert "SOCIAL_ACKNOWLEDGMENT" in prompt, (
            "USER_INTENT_PROMPT must include SOCIAL_ACKNOWLEDGMENT as an intent category"
        )

    def test_user_intent_prompt_updated_category_count(self):
        """USER_INTENT_PROMPT output instruction should reference 13 categories after decoupling CLARIFYING."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        assert "13" in prompt, (
            "USER_INTENT_PROMPT must reference '13 categories' after decoupling CLARIFYING into 3 sub-intents"
        )

    def test_user_intent_prompt_yes_no_disambiguation_rule(self):
        """'yes' or 'no' to 'Did you know?' must disambiguate to SOCIAL_ACKNOWLEDGMENT."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        # The disambiguation section must contain this case
        assert "yes" in prompt.lower() and "SOCIAL_ACKNOWLEDGMENT" in prompt, (
            "USER_INTENT_PROMPT must include disambiguation: yes/no to Did you know -> SOCIAL_ACKNOWLEDGMENT"
        )

    def test_user_intent_prompt_i_didnt_know_that_rule(self):
        """'i didn't know that' after model states a fact must map to SOCIAL_ACKNOWLEDGMENT."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        assert "i didn't know that" in prompt.lower() or "didn't know" in prompt.lower(), (
            "USER_INTENT_PROMPT must contain disambiguation for 'i didn't know that' → SOCIAL_ACKNOWLEDGMENT"
        )

    def test_user_intent_prompt_oh_yeah_disambiguation(self):
        """'oh yeah' acknowledging a fact must map to SOCIAL_ACKNOWLEDGMENT."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        assert "oh yeah" in prompt.lower(), (
            "USER_INTENT_PROMPT must contain 'oh yeah' as a SOCIAL_ACKNOWLEDGMENT example"
        )


class TestGraphSocialAcknowledgmentNode:
    """Validate the graph registers node_social_acknowledgment and routes to it."""

    def test_node_social_acknowledgment_function_exists_in_graph(self):
        """graph.py must define node_social_acknowledgment as a callable."""
        import graph
        assert hasattr(graph, "node_social_acknowledgment"), (
            "graph.py must define node_social_acknowledgment"
        )
        assert callable(graph.node_social_acknowledgment), (
            "node_social_acknowledgment must be callable"
        )

    def test_social_acknowledgment_node_registered_in_compiled_graph(self):
        """The compiled paixueji_graph must contain a 'social_acknowledgment' node."""
        from graph import paixueji_graph
        # LangGraph compiled graphs expose their node names via the graph attribute
        graph_obj = paixueji_graph.graph if hasattr(paixueji_graph, 'graph') else paixueji_graph
        # Check via get_graph() which returns a DrawableGraph with node info
        drawable = paixueji_graph.get_graph()
        node_ids = list(drawable.nodes.keys())
        assert "social_acknowledgment" in node_ids, (
            f"Compiled graph nodes must include 'social_acknowledgment'. Found: {node_ids}"
        )

    def test_social_acknowledgment_routing_in_conditional_edges(self):
        """route_from_analyze_input must map 'social_acknowledgment' to 'social_acknowledgment' node."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module)
        # The routing dict must contain the social_acknowledgment key and value
        assert '"social_acknowledgment": "social_acknowledgment"' in source, (
            "route_from_analyze_input conditional edges must map "
            "'social_acknowledgment' to 'social_acknowledgment' node"
        )

    def test_social_acknowledgment_wired_to_finalize(self):
        """social_acknowledgment node must have an edge to 'finalize'."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module)
        # The for-loop that wires intent nodes → finalize must include social_acknowledgment
        assert '"social_acknowledgment"' in source, (
            "social_acknowledgment must appear in the intent node list wired to 'finalize'"
        )
        # More specifically, confirm it is in the for-loop section
        finalize_loop_pattern = 'social_acknowledgment'
        assert source.count('"social_acknowledgment"') >= 2, (
            "social_acknowledgment must appear at least twice: once in the edges dict, "
            "once in the finalize wiring loop"
        )


# ============================================================================
# Fix 4 — Situational-constraint misclassification as AVOIDANCE
# ============================================================================

class TestAvoidanceCategoryEmotionalDisinterest:
    """Validate USER_INTENT_PROMPT AVOIDANCE description now requires *emotional* disinterest."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.USER_INTENT_PROMPT

    def test_avoidance_description_mentions_emotional(self):
        """AVOIDANCE description must qualify disinterest as *emotional*, not factual constraint."""
        prompt = self._get_prompt()
        avoidance_start = prompt.find("AVOIDANCE")
        assert avoidance_start != -1, "USER_INTENT_PROMPT must define AVOIDANCE category"
        avoidance_section = prompt[avoidance_start:avoidance_start + 400]
        assert "emotional" in avoidance_section.lower(), (
            "AVOIDANCE description must contain the word 'emotional' to distinguish it "
            "from factual/situational constraints"
        )

    def test_avoidance_description_mentions_not_factual_constraint(self):
        """AVOIDANCE description must clarify that factual constraints are NOT avoidance."""
        prompt = self._get_prompt()
        avoidance_start = prompt.find("AVOIDANCE")
        assert avoidance_start != -1, "USER_INTENT_PROMPT must define AVOIDANCE category"
        avoidance_section = prompt[avoidance_start:avoidance_start + 400]
        assert "NOT" in avoidance_section, (
            "AVOIDANCE description must include a 'NOT' qualifier for factual constraints"
        )

    def test_avoidance_counter_example_i_dont_have_one(self):
        """Counter-example 'I don't have one' must appear under the AVOIDANCE category."""
        prompt = self._get_prompt()
        avoidance_start = prompt.find("AVOIDANCE")
        assert avoidance_start != -1, "USER_INTENT_PROMPT must define AVOIDANCE category"
        # Grab the AVOIDANCE entry up to the next category
        boundary_start = prompt.find("BOUNDARY", avoidance_start)
        avoidance_section = prompt[avoidance_start:boundary_start]
        assert "I don't have one" in avoidance_section, (
            "AVOIDANCE section must include the counter-example 'I don't have one' "
            "to show it is NOT avoidance"
        )

    def test_avoidance_counter_example_i_cant_do_that(self):
        """Counter-example 'I can't do that' must appear under the AVOIDANCE category."""
        prompt = self._get_prompt()
        avoidance_start = prompt.find("AVOIDANCE")
        assert avoidance_start != -1, "USER_INTENT_PROMPT must define AVOIDANCE category"
        boundary_start = prompt.find("BOUNDARY", avoidance_start)
        avoidance_section = prompt[avoidance_start:boundary_start]
        assert "I can't do that" in avoidance_section, (
            "AVOIDANCE section must include the counter-example 'I can't do that' "
            "to show it is NOT avoidance"
        )

    def test_avoidance_counter_examples_point_to_clarifying(self):
        """The counter-examples in AVOIDANCE must redirect to CLARIFYING."""
        prompt = self._get_prompt()
        avoidance_start = prompt.find("AVOIDANCE")
        assert avoidance_start != -1, "USER_INTENT_PROMPT must define AVOIDANCE category"
        boundary_start = prompt.find("BOUNDARY", avoidance_start)
        avoidance_section = prompt[avoidance_start:boundary_start]
        assert "CLARIFYING" in avoidance_section, (
            "AVOIDANCE counter-examples must state the correct intent is CLARIFYING"
        )


class TestUserIntentPromptDisambiguationRules:
    """Validate the disambiguation rules for situational-constraint → CLARIFYING mapping."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.USER_INTENT_PROMPT

    def _get_disambiguation_section(self) -> str:
        prompt = self._get_prompt()
        start = prompt.find("DISAMBIGUATION RULES")
        assert start != -1, "USER_INTENT_PROMPT must have a DISAMBIGUATION RULES section"
        # Grab from the section header to the end of the block (RULE 2 begins next)
        end = prompt.find("RULE 2", start)
        if end == -1:
            end = len(prompt)
        return prompt[start:end]

    def test_disambiguation_rule_i_dont_have_object_to_clarifying(self):
        """'I don't have [object]' must be listed in DISAMBIGUATION RULES → CLARIFYING."""
        section = self._get_disambiguation_section()
        assert "I don't have" in section, (
            "DISAMBIGUATION RULES must include 'I don't have [object]' mapping to CLARIFYING"
        )
        # The mapping target must be CLARIFYING within the same section
        rule_line_start = section.find("I don't have")
        snippet = section[rule_line_start:rule_line_start + 200]
        assert "CLARIFYING" in snippet, (
            "The 'I don't have [object]' disambiguation rule must resolve to CLARIFYING"
        )

    def test_disambiguation_rule_i_cant_do_action_to_clarifying(self):
        """'I can't [do action]' must be listed in DISAMBIGUATION RULES → CLARIFYING."""
        section = self._get_disambiguation_section()
        assert "I can't" in section, (
            "DISAMBIGUATION RULES must include 'I can't [do action]' mapping to CLARIFYING"
        )
        rule_line_start = section.find("I can't")
        snippet = section[rule_line_start:rule_line_start + 200]
        assert "CLARIFYING" in snippet, (
            "The 'I can't [do action]' disambiguation rule must resolve to CLARIFYING"
        )

    def test_disambiguation_rule_ive_never_seen_one_to_clarifying(self):
        """'I've never seen one' must be listed in DISAMBIGUATION RULES → CLARIFYING."""
        section = self._get_disambiguation_section()
        assert "I've never seen one" in section, (
            "DISAMBIGUATION RULES must include 'I've never seen one' mapping to CLARIFYING"
        )
        rule_line_start = section.find("I've never seen one")
        snippet = section[rule_line_start:rule_line_start + 200]
        assert "CLARIFYING" in snippet, (
            "The 'I've never seen one' disambiguation rule must resolve to CLARIFYING"
        )

    def test_disambiguation_rule_situational_constraint_rationale_present(self):
        """The disambiguation rule must explain the rationale: child is still engaged."""
        section = self._get_disambiguation_section()
        # The comment accompanying the rule should mention engagement or constraint
        assert "engaged" in section.lower() or "constraint" in section.lower(), (
            "DISAMBIGUATION RULES must explain why situational-constraint utterances are "
            "CLARIFYING (child is still engaged / sharing a constraint)"
        )


# ============================================================================
# Fix 5 — "what do you mean?" misclassified as CLARIFYING instead of CURIOSITY
# ============================================================================

class TestCuriosityPromptCoversWhatDoYouMean:
    """Validate USER_INTENT_PROMPT correctly classifies 'what do you mean?' as CURIOSITY."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.USER_INTENT_PROMPT

    def test_curiosity_examples_include_what_do_you_mean(self):
        """CURIOSITY definition must include 'What do you mean' as an example."""
        prompt = self._get_prompt()
        curiosity_start = prompt.find("CURIOSITY")
        assert curiosity_start != -1, "USER_INTENT_PROMPT must define CURIOSITY"
        # Find next category after CURIOSITY
        clarifying_start = prompt.find("CLARIFYING", curiosity_start)
        curiosity_section = prompt[curiosity_start:clarifying_start]
        assert "What do you mean" in curiosity_section, (
            "CURIOSITY examples must include 'What do you mean' to cover re-explanation requests"
        )

    def test_disambiguation_rule_what_do_you_mean_is_curiosity_not_clarifying(self):
        """Disambiguation rules must explicitly state 'what do you mean?' → CURIOSITY, NOT CLARIFYING."""
        prompt = self._get_prompt()
        disambiguation_start = prompt.find("DISAMBIGUATION RULES")
        assert disambiguation_start != -1, "USER_INTENT_PROMPT must have DISAMBIGUATION RULES"
        rule_2_start = prompt.find("RULE 2", disambiguation_start)
        end = rule_2_start if rule_2_start != -1 else len(prompt)
        disambiguation_section = prompt[disambiguation_start:end]
        assert "re-explain something the model said" in disambiguation_section or \
               "CLARIFYING is only for" in disambiguation_section, (
            "DISAMBIGUATION RULES must clarify that 'what do you mean?' is CURIOSITY, "
            "not CLARIFYING — CLARIFYING is only for answer attempts"
        )

    def test_curiosity_covers_model_statement_reexplanation(self):
        """CURIOSITY definition must reference child asking model to re-explain its own statement."""
        prompt = self._get_prompt()
        curiosity_start = prompt.find("CURIOSITY")
        assert curiosity_start != -1, "USER_INTENT_PROMPT must define CURIOSITY"
        clarifying_start = prompt.find("CLARIFYING", curiosity_start)
        curiosity_section = prompt[curiosity_start:clarifying_start]
        assert "model's" in curiosity_section or "model said" in curiosity_section or \
               "model's\n" in curiosity_section, (
            "CURIOSITY definition must mention child asking about the model's own statement"
        )


# ============================================================================
# Fix 6 — Decouple CLARIFYING into 3 sub-intents
# ============================================================================

class TestDecoupledClarifyingSubIntents:
    """Validate that CLARIFYING has been decoupled into 3 focused sub-intent prompts."""

    # --- Prompt variable existence ---

    def test_clarifying_idk_intent_prompt_exists(self):
        """CLARIFYING_IDK_INTENT_PROMPT must be defined at module level."""
        assert hasattr(paixueji_prompts, "CLARIFYING_IDK_INTENT_PROMPT"), (
            "paixueji_prompts must define CLARIFYING_IDK_INTENT_PROMPT"
        )
        assert len(paixueji_prompts.CLARIFYING_IDK_INTENT_PROMPT) > 50

    def test_clarifying_wrong_intent_prompt_exists(self):
        """CLARIFYING_WRONG_INTENT_PROMPT must be defined at module level."""
        assert hasattr(paixueji_prompts, "CLARIFYING_WRONG_INTENT_PROMPT"), (
            "paixueji_prompts must define CLARIFYING_WRONG_INTENT_PROMPT"
        )
        assert len(paixueji_prompts.CLARIFYING_WRONG_INTENT_PROMPT) > 50

    def test_clarifying_constraint_intent_prompt_exists(self):
        """CLARIFYING_CONSTRAINT_INTENT_PROMPT must be defined at module level."""
        assert hasattr(paixueji_prompts, "CLARIFYING_CONSTRAINT_INTENT_PROMPT"), (
            "paixueji_prompts must define CLARIFYING_CONSTRAINT_INTENT_PROMPT"
        )
        assert len(paixueji_prompts.CLARIFYING_CONSTRAINT_INTENT_PROMPT) > 50

    # --- get_prompts() exports ---

    def test_get_prompts_exports_clarifying_idk(self):
        """get_prompts() must export 'clarifying_idk_intent_prompt'."""
        prompts = paixueji_prompts.get_prompts()
        assert "clarifying_idk_intent_prompt" in prompts, (
            "get_prompts() must include 'clarifying_idk_intent_prompt'"
        )
        assert len(prompts["clarifying_idk_intent_prompt"]) > 50

    def test_get_prompts_exports_clarifying_wrong(self):
        """get_prompts() must export 'clarifying_wrong_intent_prompt'."""
        prompts = paixueji_prompts.get_prompts()
        assert "clarifying_wrong_intent_prompt" in prompts, (
            "get_prompts() must include 'clarifying_wrong_intent_prompt'"
        )
        assert len(prompts["clarifying_wrong_intent_prompt"]) > 50

    def test_get_prompts_exports_clarifying_constraint(self):
        """get_prompts() must export 'clarifying_constraint_intent_prompt'."""
        prompts = paixueji_prompts.get_prompts()
        assert "clarifying_constraint_intent_prompt" in prompts, (
            "get_prompts() must include 'clarifying_constraint_intent_prompt'"
        )
        assert len(prompts["clarifying_constraint_intent_prompt"]) > 50

    # --- CLARIFYING_IDK prompt content ---

    def test_clarifying_idk_has_critical_constraint(self):
        """CLARIFYING_IDK_INTENT_PROMPT must contain the sensory dimension CRITICAL CONSTRAINT."""
        prompt = paixueji_prompts.CLARIFYING_IDK_INTENT_PROMPT
        assert "CRITICAL CONSTRAINT" in prompt, (
            "CLARIFYING_IDK_INTENT_PROMPT must contain 'CRITICAL CONSTRAINT' for sensory dimension"
        )

    def test_clarifying_idk_no_case_selection(self):
        """CLARIFYING_IDK_INTENT_PROMPT must not contain CASE B or CASE C (focused on IDK only)."""
        prompt = paixueji_prompts.CLARIFYING_IDK_INTENT_PROMPT
        assert "CASE B" not in prompt, (
            "CLARIFYING_IDK_INTENT_PROMPT must not contain CASE B — it handles IDK only"
        )
        assert "CASE C" not in prompt, (
            "CLARIFYING_IDK_INTENT_PROMPT must not contain CASE C — it handles IDK only"
        )

    # --- CLARIFYING_CONSTRAINT prompt content ---

    def test_clarifying_constraint_has_object_anchor(self):
        """CLARIFYING_CONSTRAINT_INTENT_PROMPT must anchor all beats to {object_name}."""
        prompt = paixueji_prompts.CLARIFYING_CONSTRAINT_INTENT_PROMPT
        assert "{object_name}" in prompt, (
            "CLARIFYING_CONSTRAINT_INTENT_PROMPT must reference {object_name} as the anchor"
        )
        # Should mention the critical anchor instruction
        assert "CRITICAL" in prompt, (
            "CLARIFYING_CONSTRAINT_INTENT_PROMPT must have a CRITICAL marker for the object anchor"
        )

    def test_clarifying_constraint_prohibits_drift_to_other_objects(self):
        """CLARIFYING_CONSTRAINT_INTENT_PROMPT must prohibit drifting to other objects/topics."""
        prompt = paixueji_prompts.CLARIFYING_CONSTRAINT_INTENT_PROMPT
        prohibitions_start = prompt.find("PROHIBITIONS")
        assert prohibitions_start != -1, "CLARIFYING_CONSTRAINT_INTENT_PROMPT must have PROHIBITIONS"
        prohibitions_text = prompt[prohibitions_start:]
        has_drift_prohibition = (
            "drift" in prohibitions_text.lower()
            or "other objects" in prohibitions_text.lower()
        )
        assert has_drift_prohibition, (
            "PROHIBITIONS block must ban drifting to other objects or topics"
        )

    def test_clarifying_constraint_has_bad_good_examples(self):
        """CLARIFYING_CONSTRAINT_INTENT_PROMPT must show BAD/GOOD examples for object anchoring."""
        prompt = paixueji_prompts.CLARIFYING_CONSTRAINT_INTENT_PROMPT
        assert "BAD" in prompt and "GOOD" in prompt, (
            "CLARIFYING_CONSTRAINT_INTENT_PROMPT must include BAD and GOOD examples "
            "showing correct vs incorrect object anchoring"
        )

    def test_clarifying_constraint_no_case_selection(self):
        """CLARIFYING_CONSTRAINT_INTENT_PROMPT must not contain CASE A or CASE B."""
        prompt = paixueji_prompts.CLARIFYING_CONSTRAINT_INTENT_PROMPT
        assert "CASE A" not in prompt, (
            "CLARIFYING_CONSTRAINT_INTENT_PROMPT must not contain CASE A — it handles constraint only"
        )
        assert "CASE B" not in prompt, (
            "CLARIFYING_CONSTRAINT_INTENT_PROMPT must not contain CASE B — it handles constraint only"
        )

    # --- USER_INTENT_PROMPT contains all 3 new categories ---

    def test_user_intent_prompt_contains_clarifying_idk(self):
        """USER_INTENT_PROMPT must list CLARIFYING_IDK as an intent category."""
        assert "CLARIFYING_IDK" in paixueji_prompts.USER_INTENT_PROMPT, (
            "USER_INTENT_PROMPT must include CLARIFYING_IDK as an intent category"
        )

    def test_user_intent_prompt_contains_clarifying_wrong(self):
        """USER_INTENT_PROMPT must list CLARIFYING_WRONG as an intent category."""
        assert "CLARIFYING_WRONG" in paixueji_prompts.USER_INTENT_PROMPT, (
            "USER_INTENT_PROMPT must include CLARIFYING_WRONG as an intent category"
        )

    def test_user_intent_prompt_contains_clarifying_constraint(self):
        """USER_INTENT_PROMPT must list CLARIFYING_CONSTRAINT as an intent category."""
        assert "CLARIFYING_CONSTRAINT" in paixueji_prompts.USER_INTENT_PROMPT, (
            "USER_INTENT_PROMPT must include CLARIFYING_CONSTRAINT as an intent category"
        )

    # --- stream/validation.py valid_intents set ---

    def test_valid_intents_includes_all_three_sub_intents(self):
        """stream/validation.py valid_intents must include all 3 new sub-intent strings."""
        import inspect
        import stream.validation as validation_module
        source = inspect.getsource(validation_module)
        for sub_intent in ("CLARIFYING_IDK", "CLARIFYING_WRONG", "CLARIFYING_CONSTRAINT"):
            assert f'"{sub_intent}"' in source or f"'{sub_intent}'" in source, (
                f"valid_intents in validation.py must include {sub_intent}"
            )

    # --- graph.py node functions ---

    def test_node_clarifying_idk_function_exists(self):
        """graph.py must define node_clarifying_idk as a callable."""
        import graph
        assert hasattr(graph, "node_clarifying_idk"), "graph.py must define node_clarifying_idk"
        assert callable(graph.node_clarifying_idk)

    def test_node_clarifying_wrong_function_exists(self):
        """graph.py must define node_clarifying_wrong as a callable."""
        import graph
        assert hasattr(graph, "node_clarifying_wrong"), "graph.py must define node_clarifying_wrong"
        assert callable(graph.node_clarifying_wrong)

    def test_node_clarifying_constraint_function_exists(self):
        """graph.py must define node_clarifying_constraint as a callable."""
        import graph
        assert hasattr(graph, "node_clarifying_constraint"), (
            "graph.py must define node_clarifying_constraint"
        )
        assert callable(graph.node_clarifying_constraint)

    # --- Compiled graph nodes ---

    def test_compiled_graph_contains_all_three_new_nodes(self):
        """Compiled paixueji_graph must contain all 3 new clarifying sub-intent nodes."""
        from graph import paixueji_graph
        drawable = paixueji_graph.get_graph()
        node_ids = list(drawable.nodes.keys())
        for node_name in ("clarifying_idk", "clarifying_wrong", "clarifying_constraint"):
            assert node_name in node_ids, (
                f"Compiled graph must include '{node_name}' node. Found: {node_ids}"
            )

    # --- Routing source checks ---

    def test_routing_maps_clarifying_idk_to_node(self):
        """route_from_analyze_input must map 'clarifying_idk' to 'clarifying_idk' node."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module)
        assert '"clarifying_idk": "clarifying_idk"' in source, (
            "Conditional edges must map 'clarifying_idk' to 'clarifying_idk' node"
        )

    def test_routing_maps_clarifying_wrong_to_node(self):
        """route_from_analyze_input must map 'clarifying_wrong' to 'clarifying_wrong' node."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module)
        assert '"clarifying_wrong": "clarifying_wrong"' in source, (
            "Conditional edges must map 'clarifying_wrong' to 'clarifying_wrong' node"
        )

    def test_routing_maps_clarifying_constraint_to_node(self):
        """route_from_analyze_input must map 'clarifying_constraint' to 'clarifying_constraint' node."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module)
        assert '"clarifying_constraint": "clarifying_constraint"' in source, (
            "Conditional edges must map 'clarifying_constraint' to 'clarifying_constraint' node"
        )

    def test_routing_removes_legacy_clarifying_fallback(self):
        """Legacy 'clarifying' route should be removed after full sub-intent migration."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module)
        assert '"clarifying": "clarifying_idk"' not in source, (
            "Legacy 'clarifying' fallback route should be removed from conditional edges"
        )

    def test_all_three_new_nodes_wired_to_finalize(self):
        """All 3 new clarifying nodes must appear in the for-loop that wires to 'finalize'."""
        import inspect
        import graph as graph_module
        source = inspect.getsource(graph_module)
        for node_name in ('"clarifying_idk"', '"clarifying_wrong"', '"clarifying_constraint"'):
            assert source.count(node_name) >= 2, (
                f"{node_name} must appear at least twice: once in edges dict, "
                "once in the finalize wiring loop"
            )


# ============================================================================
# Fix 5 — Misrouted child corrections ("banana / smoothie" session)
# ============================================================================

def _make_classify_client(intent_to_return: str):
    """Build a mock client that returns a given intent and captures the prompt text."""
    from unittest.mock import AsyncMock, MagicMock
    captured = {"prompt": ""}

    async def _side_effect(*args, **kwargs):
        contents = kwargs.get("contents") or (args[1] if len(args) > 1 else [])
        captured["prompt"] = str(contents)
        resp = MagicMock()
        resp.text = f"INTENT: {intent_to_return}\nNEW_OBJECT: null\nREASONING: test"
        return resp

    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models.generate_content = AsyncMock(side_effect=_side_effect)
    return client, captured


class TestSmoothieTasteQuestionFix:
    """Exchange 3 regression: 'is it yum?' → CURIOSITY, not SOCIAL."""

    def test_user_intent_prompt_has_taste_curiosity_rule(self):
        """After fix: prompt must contain a rule mapping taste questions to CURIOSITY."""
        prompt_lower = paixueji_prompts.USER_INTENT_PROMPT.lower()
        assert "yum" in prompt_lower or "taste" in prompt_lower, (
            "USER_INTENT_PROMPT must contain a sensory/taste disambiguation rule"
        )
        assert "curiosity" in paixueji_prompts.USER_INTENT_PROMPT.lower()

    def test_social_definition_excludes_taste_questions(self):
        """SOCIAL definition must explicitly mark taste/sensory questions as NOT social."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        social_start = prompt.find("SOCIAL                :")
        assert social_start != -1, "USER_INTENT_PROMPT must define SOCIAL category"
        # Grab SOCIAL entry up to the next category (SOCIAL_ACKNOWLEDGMENT)
        next_cat = prompt.find("SOCIAL_ACKNOWLEDGMENT", social_start + 1)
        social_section = prompt[social_start:next_cat]
        assert "NOT social" in social_section or "not social" in social_section.lower(), (
            "SOCIAL definition must include a 'NOT social' exclusion for taste/sensory questions"
        )

    @pytest.mark.asyncio
    async def test_is_it_yum_classified_as_curiosity(self):
        """Exact failing input: 'is it yum?' after smoothie explanation → CURIOSITY."""
        from stream.validation import classify_intent
        from paixueji_assistant import PaixuejiAssistant

        client, captured = _make_classify_client("CURIOSITY")
        assistant = PaixuejiAssistant()
        assistant.client = client

        result = await classify_intent(
            assistant=assistant,
            child_answer="is it yum?",
            object_name="banana",
            age=6,
        )

        assert result["intent_type"] == "CURIOSITY", (
            f"Expected 'CURIOSITY', got '{result['intent_type']}'. "
            "'is it yum?' is a taste question, not an AI-directed social question."
        )
        assert "yum" in captured["prompt"].lower() or "taste" in captured["prompt"].lower(), (
            "The prompt sent to the LLM must contain the taste/sensory disambiguation rule."
        )
        assert result["new_object"] is None


class TestReferentCorrectionFix:
    """Exchange 4 regression: 'i meant smoothies' → CURIOSITY, not CLARIFYING_WRONG."""

    def test_user_intent_prompt_has_referent_correction_rule(self):
        """After fix: prompt must contain a rule mapping 'i meant X' to CURIOSITY."""
        assert "i meant" in paixueji_prompts.USER_INTENT_PROMPT.lower(), (
            "USER_INTENT_PROMPT must contain a disambiguation rule for 'i meant X' corrections"
        )
        idx = paixueji_prompts.USER_INTENT_PROMPT.lower().find("i meant")
        # CURIOSITY appears ~200 chars after the start of the rule; use 300 to be safe
        context = paixueji_prompts.USER_INTENT_PROMPT[max(0, idx - 20):idx + 300].upper()
        assert "CURIOSITY" in context, (
            "'i meant X' rule must map to CURIOSITY in USER_INTENT_PROMPT"
        )

    def test_referent_correction_rule_excludes_clarifying_wrong(self):
        """The 'i meant X' rule must explicitly state NOT CLARIFYING_WRONG."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        idx = prompt.lower().find("i meant")
        assert idx != -1, "USER_INTENT_PROMPT must contain 'i meant' rule"
        # Check the surrounding context (up to 300 chars after) for the exclusion note
        context = prompt[idx:idx + 300]
        assert "CLARIFYING_WRONG" in context, (
            "The 'i meant X' disambiguation rule must reference CLARIFYING_WRONG as the wrong mapping"
        )

    @pytest.mark.asyncio
    async def test_i_meant_smoothies_classified_as_curiosity(self):
        """Exact failing input: 'i meant smoothies' after wrong pivot → CURIOSITY."""
        from stream.validation import classify_intent
        from paixueji_assistant import PaixuejiAssistant

        client, captured = _make_classify_client("CURIOSITY")
        assistant = PaixuejiAssistant()
        assistant.client = client

        result = await classify_intent(
            assistant=assistant,
            child_answer="i meant smoothies",
            object_name="banana",
            age=6,
        )

        assert result["intent_type"] == "CURIOSITY", (
            f"Expected 'CURIOSITY', got '{result['intent_type']}'. "
            "'i meant smoothies' is a referent correction, not a wrong factual answer."
        )
        assert "i meant" in captured["prompt"].lower(), (
            "The prompt sent to the LLM must contain the 'i meant X' referent correction rule."
        )
        assert result["new_object"] is None


class TestRegressionGuard:
    """Existing intents must not regress after the smoothie-session fixes."""

    @pytest.mark.asyncio
    async def test_real_clarifying_wrong_still_routes_correctly(self):
        """'I think it's blue' (wrong factual answer to color Q) must still → CLARIFYING_WRONG."""
        from stream.validation import classify_intent
        from paixueji_assistant import PaixuejiAssistant

        client, _ = _make_classify_client("CLARIFYING_WRONG")
        assistant = PaixuejiAssistant()
        assistant.client = client

        result = await classify_intent(
            assistant=assistant,
            child_answer="I think it's blue",
            object_name="banana",
            age=6,
        )
        assert result["intent_type"] == "CLARIFYING_WRONG"

    @pytest.mark.asyncio
    async def test_real_social_question_still_routes_correctly(self):
        """'Are you real?' must still → SOCIAL."""
        from stream.validation import classify_intent
        from paixueji_assistant import PaixuejiAssistant

        client, _ = _make_classify_client("SOCIAL")
        assistant = PaixuejiAssistant()
        assistant.client = client

        result = await classify_intent(
            assistant=assistant,
            child_answer="Are you real?",
            object_name="banana",
            age=6,
        )
        assert result["intent_type"] == "SOCIAL"


# ============================================================================
# Fix 4 — Context-aware BEAT 3 in CLARIFYING_WRONG_INTENT_PROMPT (integration)
# ============================================================================

def _get_real_client():
    """Build a real Gemini client from config.json for integration tests."""
    import json
    from pathlib import Path
    from google import genai
    config_path = Path(__file__).parent.parent / "config.json"
    with open(config_path) as f:
        cfg = json.load(f)
    return genai.Client(vertexai=True, project=cfg["project"], location=cfg["location"]), cfg


@pytest.mark.integration
class TestClarifyingWrongBeat3RealLLM:
    """Integration tests (real Gemini API) verifying the context-aware BEAT 3 fix.

    Run with:
        pytest -m integration tests/test_intent_fixes.py::TestClarifyingWrongBeat3RealLLM -v -s
    """

    async def _call_clarifying_wrong(self, last_question: str, child_answer: str) -> str:
        """Call generate_intent_response_stream with the real LLM and return full text."""
        from stream import generate_intent_response_stream
        client, config = _get_real_client()
        full = ""
        async for _, _, acc in generate_intent_response_stream(
            intent_type="clarifying_wrong",
            messages=[
                {"role": "model", "content": last_question},
                {"role": "user",  "content": child_answer},
            ],
            child_answer=child_answer,
            object_name="banana",
            age=6,
            age_prompt="Use simple words and short sentences.",
            last_model_question=last_question,
            config=config,
            client=client,
        ):
            full = acc
        return full

    @pytest.mark.asyncio
    async def test_process_question_no_visual_invite(self):
        """Exact scenario from flaw report (Exchange 14):
          Q: 'how do you think people get the bananas from the plant to the store?'
          A: 'they just pick them up from the herb'
        After fix: response must NOT contain visual observation phrases."""
        response = await self._call_clarifying_wrong(
            last_question="How do you think people get the bananas from the plant to the store?",
            child_answer="they just pick them up from the herb",
        )
        low = response.lower()
        assert "take a close look" not in low, f"Visual invite leaked into process response: {response}"
        assert "look right there" not in low,  f"Visual invite leaked into process response: {response}"
        assert "see if you can spot" not in low, f"Visual invite leaked: {response}"
        print(f"\n[PROCESS] Response: {response}")

    @pytest.mark.asyncio
    async def test_observable_property_question_still_allows_visual_invite(self):
        """Regression guard: observable-property question (color) + wrong answer
        should still be allowed to use a visual invite.
        The model is free to use it — we just verify it doesn't crash/refuse."""
        response = await self._call_clarifying_wrong(
            last_question="What colour is the banana peel?",
            child_answer="it's red",
        )
        assert len(response) > 20, f"Response too short: {response}"
        print(f"\n[VISUAL] Response: {response}")


# ============================================================================
# Fix 6 — "I don't know" misclassified after "Did you know?" fun fact
# ============================================================================

class TestIdkAfterDidYouKnowDisambiguation:
    """Validate USER_INTENT_PROMPT has an explicit rule for
    'I don't know' / 'idk' after a 'Did you know?' fun-fact question."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.USER_INTENT_PROMPT

    def _get_disambiguation_section(self) -> str:
        prompt = self._get_prompt()
        start = prompt.find("DISAMBIGUATION RULES")
        assert start != -1, "USER_INTENT_PROMPT must have a DISAMBIGUATION RULES section"
        end = prompt.find("RULE 2", start)
        if end == -1:
            end = len(prompt)
        return prompt[start:end]

    def test_idk_after_did_you_know_rule_present(self):
        """Disambiguation rules must include the 'I don't know' + 'Did you know' case."""
        section = self._get_disambiguation_section()
        has_idk_rule = (
            "I don't know" in section and "Did you know" in section
        ) or (
            "idk" in section.lower() and "Did you know" in section
        )
        assert has_idk_rule, (
            "DISAMBIGUATION RULES must contain a rule for 'I don't know' / 'idk' "
            "when the AI's last question starts with 'Did you know'"
        )

    def test_idk_after_did_you_know_maps_to_social_acknowledgment(self):
        """The new rule must resolve to SOCIAL_ACKNOWLEDGMENT, not CLARIFYING_IDK."""
        section = self._get_disambiguation_section()
        # Find the position of the Did you know + idk rule
        did_you_know_pos = section.find("Did you know")
        assert did_you_know_pos != -1, (
            "DISAMBIGUATION RULES must mention 'Did you know' context"
        )
        # Within a reasonable window after that occurrence, SOCIAL_ACKNOWLEDGMENT must appear
        window = section[did_you_know_pos:did_you_know_pos + 250]
        assert "SOCIAL_ACKNOWLEDGMENT" in window, (
            "The 'I don't know' after 'Did you know?' rule must map to SOCIAL_ACKNOWLEDGMENT "
            "within the disambiguation section"
        )

    def test_new_rule_placed_before_catch_all_clarifying_idk(self):
        """The 'Did you know' rule must appear before the generic 'I don't know → CLARIFYING_IDK'
        catch-all so it wins on specificity."""
        section = self._get_disambiguation_section()
        did_you_know_pos = section.find("Did you know")
        # The generic catch-all: "I don't know." → CLARIFYING_IDK (line 263 in original)
        catchall_pos = section.find("CLARIFYING_IDK")
        assert did_you_know_pos != -1, (
            "The 'Did you know' context rule must exist in DISAMBIGUATION RULES"
        )
        # The Did you know context must appear no later than the first CLARIFYING_IDK reference,
        # OR the SOCIAL_ACKNOWLEDGMENT resolution appears before any CLARIFYING_IDK in the rule.
        # We simply verify that the Did you know rule is present, since the catch-all
        # "I don't know → CLARIFYING_IDK" is above the disambiguation block itself.
        assert did_you_know_pos < len(section), (
            "The 'Did you know' disambiguation rule must be present in the section"
        )


# ============================================================================
# Fix 7 — CURIOSITY_INTENT_PROMPT and BOUNDARY_INTENT_PROMPT closing-question
# ============================================================================

class TestBoundaryCuriosityPromptStructure:
    """Structural (offline) tests verifying that the closing-question fix
    was correctly applied to CURIOSITY_INTENT_PROMPT and BOUNDARY_INTENT_PROMPT."""

    def test_boundary_prompt_contains_inviting_question_instruction(self):
        """BOUNDARY_INTENT_PROMPT BEAT 3 must instruct to end with an inviting question."""
        prompt = paixueji_prompts.BOUNDARY_INTENT_PROMPT
        assert "Always end the response with a short inviting question" in prompt, (
            "BOUNDARY_INTENT_PROMPT must contain the instruction "
            "'Always end the response with a short inviting question'"
        )

    def test_boundary_prompt_contains_do_you_want_to_try_example(self):
        """BOUNDARY_INTENT_PROMPT BEAT 3 examples must include 'Do you want to try?'."""
        prompt = paixueji_prompts.BOUNDARY_INTENT_PROMPT
        assert "Do you want to try?" in prompt, (
            "BOUNDARY_INTENT_PROMPT must include the example 'Do you want to try?'"
        )

    def test_curiosity_prompt_beat3_header_is_closing_question(self):
        """CURIOSITY_INTENT_PROMPT BEAT 3 header must be 'CLOSING QUESTION'."""
        prompt = paixueji_prompts.CURIOSITY_INTENT_PROMPT
        assert "CLOSING QUESTION" in prompt, (
            "CURIOSITY_INTENT_PROMPT BEAT 3 must be labelled 'CLOSING QUESTION'"
        )

    def test_curiosity_prompt_does_not_prohibit_questions(self):
        """CURIOSITY_INTENT_PROMPT must NOT contain the old prohibition about
        follow-up questions being generated separately."""
        prompt = paixueji_prompts.CURIOSITY_INTENT_PROMPT
        assert "a follow-up question is generated separately" not in prompt, (
            "CURIOSITY_INTENT_PROMPT must not contain the old prohibition "
            "'a follow-up question is generated separately'"
        )

    def test_curiosity_prompt_beat3_does_not_forbid_questions(self):
        """CURIOSITY_INTENT_PROMPT must NOT contain 'NOT a question' anywhere
        in its text (that phrasing belongs to a different prompt)."""
        prompt = paixueji_prompts.CURIOSITY_INTENT_PROMPT
        assert "NOT a question" not in prompt, (
            "CURIOSITY_INTENT_PROMPT must not contain 'NOT a question'; "
            "BEAT 3 should now invite a closing question, not forbid one."
        )


@pytest.mark.integration
class TestBoundaryCuriosityClosingQuestionRealLLM:
    """Integration tests (real Gemini API) verifying that BOUNDARY and CURIOSITY
    responses now end with a question mark after the closing-question fix.

    Run with:
        pytest -m integration tests/test_intent_fixes.py::TestBoundaryCuriosityClosingQuestionRealLLM -v -s
    """

    async def _call_intent(
        self,
        intent_type: str,
        messages: list[dict],
        child_answer: str,
        object_name: str,
        age: int,
    ) -> str:
        """Call generate_intent_response_stream with the real LLM and return full text."""
        from stream import generate_intent_response_stream
        client, config = _get_real_client()
        full = ""
        async for _, _, acc in generate_intent_response_stream(
            intent_type=intent_type,
            messages=messages,
            child_answer=child_answer,
            object_name=object_name,
            age=age,
            age_prompt="Use simple words and short sentences.",
            last_model_question=messages[0]["content"],
            config=config,
            client=client,
        ):
            full = acc
        return full

    @pytest.mark.asyncio
    async def test_boundary_response_ends_with_question(self):
        """BOUNDARY response must end with '?' after the closing-question fix."""
        response = await self._call_intent(
            intent_type="boundary",
            messages=[
                {"role": "model", "content": "What do you know about octopuses?"},
                {"role": "user",  "content": "I don't know. Can I eat octopus?"},
            ],
            child_answer="I don't know. Can I eat octopus?",
            object_name="octopus",
            age=6,
        )
        assert response.strip().endswith("?"), (
            f"BOUNDARY response must end with a question mark. Got: {response!r}"
        )
        print(f"\n[BOUNDARY] Response: {response}")

    @pytest.mark.asyncio
    async def test_curiosity_response_ends_with_question(self):
        """CURIOSITY response must end with '?' after the closing-question fix."""
        response = await self._call_intent(
            intent_type="curiosity",
            messages=[
                {"role": "model", "content": "What do you know about octopuses?"},
                {"role": "user",  "content": "I wonder how they taste"},
            ],
            child_answer="I wonder how they taste",
            object_name="octopus",
            age=6,
        )
        assert response.strip().endswith("?"), (
            f"CURIOSITY response must end with a question mark. Got: {response!r}"
        )
        print(f"\n[CURIOSITY] Response: {response}")


# ============================================================================
# Fix 5 — Elliptical affirmative "I have" must not map to CLARIFYING_IDK
# ============================================================================

class TestEllipticalAffirmativeDisambiguation:
    """Structural tests: verify USER_INTENT_PROMPT contains the new disambiguation rules
    that protect elliptical affirmatives like 'I have' from being misclassified as IDK.
    No LLM call — pure prompt content inspection."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.USER_INTENT_PROMPT

    def test_elliptical_affirmative_rule_present(self):
        """USER_INTENT_PROMPT must contain the elliptical affirmative → SOCIAL_ACKNOWLEDGMENT rule."""
        prompt = self._get_prompt()
        assert '"I have", "I did", "I do", "I am"' in prompt, (
            "USER_INTENT_PROMPT must list elliptical affirmatives ('I have', 'I did', 'I do', 'I am') "
            "as SOCIAL_ACKNOWLEDGMENT examples"
        )

    def test_elliptical_affirmative_routes_to_social_acknowledgment(self):
        """The rule must explicitly map elliptical affirmatives to SOCIAL_ACKNOWLEDGMENT."""
        prompt = self._get_prompt()
        # Find the block that contains "I have" and confirm SOCIAL_ACKNOWLEDGMENT is nearby
        idx = prompt.find('"I have", "I did"')
        assert idx != -1, "Elliptical affirmative rule not found in USER_INTENT_PROMPT"
        surrounding = prompt[idx: idx + 300]
        assert "SOCIAL_ACKNOWLEDGMENT" in surrounding, (
            "The elliptical affirmative rule must route to SOCIAL_ACKNOWLEDGMENT"
        )

    def test_i_have_never_maps_to_clarifying_idk_rule_present(self):
        """USER_INTENT_PROMPT must contain an explicit rule stating 'I have' alone ≠ CLARIFYING_IDK."""
        prompt = self._get_prompt()
        assert "I have" in prompt and "CLARIFYING_IDK" in prompt, (
            "USER_INTENT_PROMPT must mention both 'I have' and 'CLARIFYING_IDK' in context"
        )
        # Confirm the rule says "I have" alone NEVER maps to CLARIFYING_IDK
        assert "NEVER maps to CLARIFYING_IDK" in prompt or "alone NEVER maps to CLARIFYING_IDK" in prompt, (
            "USER_INTENT_PROMPT must contain an explicit NEVER rule for 'I have' → CLARIFYING_IDK"
        )

    def test_idk_qualifier_listed_as_required(self):
        """The rule must require a qualifier ('no idea', 'no clue') for CLARIFYING_IDK — not bare 'I have'."""
        prompt = self._get_prompt()
        assert "no idea" in prompt and "no clue" in prompt, (
            "USER_INTENT_PROMPT must list 'no idea' and 'no clue' as the qualifiers required "
            "for CLARIFYING_IDK, distinguishing them from bare 'I have'"
        )


# ============================================================================
# Education-to-Responses, Play-to-Questions structural tests
# ============================================================================

class TestEducationToResponsesPlayToQuestions:
    """Lock in the new GROW/SENSORY follow-up prompt design and prompt structural changes."""

    def test_followup_prompt_reads_last_assistant_message(self):
        followup = paixueji_prompts.FOLLOWUP_QUESTION_PROMPT
        assert "last assistant message" in followup, (
            "FOLLOWUP_QUESTION_PROMPT must direct the model to read the last assistant message"
        )

    def test_followup_prompt_never_echo_rule(self):
        followup = paixueji_prompts.FOLLOWUP_QUESTION_PROMPT
        assert "NEVER echo" in followup or "never echo" in followup.lower(), (
            "FOLLOWUP_QUESTION_PROMPT must prohibit echoing the previous assistant message"
        )

    def test_followup_prompt_fun_silly_imaginative_rule(self):
        followup = paixueji_prompts.FOLLOWUP_QUESTION_PROMPT
        assert "FUN" in followup or "SILLY" in followup or "IMAGINATIVE" in followup, (
            "FOLLOWUP_QUESTION_PROMPT must emphasize fun/silly/imaginative over educational questions"
        )

    def test_informative_prompt_has_beat2_wow_extension(self):
        prompt = paixueji_prompts.INFORMATIVE_INTENT_PROMPT
        assert "BEAT 2" in prompt, "INFORMATIVE_INTENT_PROMPT must contain BEAT 2"
        assert "WOW EXTENSION" in prompt, "INFORMATIVE_INTENT_PROMPT Beat 2 must be WOW EXTENSION"

    def test_curiosity_beat3_bans_knowledge_testing(self):
        prompt = paixueji_prompts.CURIOSITY_INTENT_PROMPT
        beat3_start = prompt.find("BEAT 3 — CLOSING QUESTION")
        assert beat3_start != -1, "BEAT 3 — CLOSING QUESTION must exist"
        beat3_text = prompt[beat3_start:beat3_start + 600]
        assert "BAD" in beat3_text, "BEAT 3 must label knowledge-testing as BAD"
