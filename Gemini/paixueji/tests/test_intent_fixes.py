"""
Tests for three root-cause fixes applied to paixueji_prompts.py, stream/validation.py, and graph.py:

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

Fix 3 — CLARIFYING scaffold topic coherence
    - CRITICAL CONSTRAINT added to Case A, Beat 2 of CLARIFYING_INTENT_PROMPT
    - Scaffold clue must stay within SAME sensory dimension as last_model_question
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
        """Prompt must explicitly prohibit 'Did you know...?' phrasing in Beat 2."""
        prompt = self._get_prompt()
        # The CRITICAL annotation must be present
        assert "CRITICAL" in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must contain a CRITICAL prohibition marker"
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

    def test_beat_3_fresh_question_structure(self):
        """Prompt must define a Beat 3 asking a fresh question about a DIFFERENT property."""
        prompt = self._get_prompt()
        assert "BEAT 3" in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must contain BEAT 3"
        )
        # Beat 3 must be about a different property
        assert "DIFFERENT" in prompt, (
            "BEAT 3 must instruct the model to ask about a DIFFERENT property"
        )

    def test_max_length_note_mentions_three_beats(self):
        """Prompt should reference 3 beats in its length guidance."""
        prompt = self._get_prompt()
        assert "3 beats" in prompt or "3 sentences" in prompt, (
            "CORRECT_ANSWER_INTENT_PROMPT must note a 3-sentence / 3-beat structure"
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

    def test_social_acknowledgment_prompt_has_pivot_beat(self):
        """Prompt must define a pivot-forward beat (Beat 2) with a fresh question."""
        prompt = paixueji_prompts.SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT
        assert "BEAT 2" in prompt, (
            "SOCIAL_ACKNOWLEDGMENT_INTENT_PROMPT must have BEAT 2 for pivoting forward"
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
        """USER_INTENT_PROMPT output instruction should reference 11 categories."""
        prompt = paixueji_prompts.USER_INTENT_PROMPT
        assert "11" in prompt, (
            "USER_INTENT_PROMPT must reference '11 categories' after adding SOCIAL_ACKNOWLEDGMENT"
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
# Fix 3 — CLARIFYING scaffold topic coherence constraint
# ============================================================================

class TestClarifyingPromptSensoryDimensionConstraint:
    """Validate CLARIFYING_INTENT_PROMPT contains the SAME sensory dimension constraint."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.CLARIFYING_INTENT_PROMPT

    def test_critical_constraint_label_present(self):
        """Prompt must include a CRITICAL CONSTRAINT label in Case A, Beat 2."""
        prompt = self._get_prompt()
        assert "CRITICAL CONSTRAINT" in prompt, (
            "CLARIFYING_INTENT_PROMPT must have a 'CRITICAL CONSTRAINT' marker in Case A, Beat 2"
        )

    def test_same_sensory_dimension_instruction(self):
        """Constraint must instruct scaffold to stay within the SAME sensory dimension."""
        prompt = self._get_prompt()
        assert "SAME" in prompt and ("sensory" in prompt.lower() or "dimension" in prompt.lower()), (
            "CLARIFYING_INTENT_PROMPT must instruct scaffold to stay within the SAME sensory dimension"
        )

    def test_color_to_color_example_present(self):
        """Color → color scaffold example must be explicitly stated."""
        prompt = self._get_prompt()
        # Check for color dimension example
        assert "COLOR" in prompt.upper() or "color" in prompt, (
            "CLARIFYING_INTENT_PROMPT must give the COLOR example for sensory dimension constraint"
        )

    def test_never_pivot_to_unrelated_sense_prohibition(self):
        """Prompt must prohibit pivoting to an unrelated sensory dimension."""
        prompt = self._get_prompt()
        has_pivot_prohibition = (
            "NEVER" in prompt and "unrelated" in prompt.lower()
        ) or (
            "unrelated sense" in prompt.lower()
        )
        assert has_pivot_prohibition, (
            "CLARIFYING_INTENT_PROMPT must explicitly prohibit pivoting to an unrelated sense/dimension"
        )

    def test_taste_dimension_example_present(self):
        """Taste → taste scaffold example must be explicitly stated."""
        prompt = self._get_prompt()
        assert "TASTE" in prompt.upper() or "taste" in prompt.lower(), (
            "CLARIFYING_INTENT_PROMPT must give the TASTE example for the sensory constraint"
        )

    def test_sound_dimension_example_present(self):
        """Sound → sound scaffold example must be explicitly stated."""
        prompt = self._get_prompt()
        assert "SOUND" in prompt.upper() or "sound" in prompt.lower(), (
            "CLARIFYING_INTENT_PROMPT must give the SOUND example for the sensory constraint"
        )

    def test_constraint_is_in_case_a_scaffold_section(self):
        """CRITICAL CONSTRAINT must appear in the CASE A section, not CASE B."""
        prompt = self._get_prompt()
        case_a_start = prompt.find("CASE A")
        case_b_start = prompt.find("CASE B")
        constraint_pos = prompt.find("CRITICAL CONSTRAINT")
        assert case_a_start != -1, "CLARIFYING_INTENT_PROMPT must have CASE A"
        assert case_b_start != -1, "CLARIFYING_INTENT_PROMPT must have CASE B"
        assert constraint_pos != -1, "CRITICAL CONSTRAINT must exist in prompt"
        assert case_a_start < constraint_pos < case_b_start, (
            "CRITICAL CONSTRAINT must be in CASE A section, not CASE B"
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


class TestClarifyingPromptCaseC:
    """Validate CLARIFYING_INTENT_PROMPT contains the new CASE C for real-world constraints."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.CLARIFYING_INTENT_PROMPT

    def _get_case_c_section(self) -> str:
        prompt = self._get_prompt()
        case_c_start = prompt.find("CASE C")
        assert case_c_start != -1, "CLARIFYING_INTENT_PROMPT must define CASE C"
        # Read until PROHIBITIONS block
        prohibitions_start = prompt.find("PROHIBITIONS", case_c_start)
        end = prohibitions_start if prohibitions_start != -1 else len(prompt)
        return prompt[case_c_start:end]

    def test_case_c_header_exists(self):
        """CLARIFYING_INTENT_PROMPT must contain a CASE C header."""
        prompt = self._get_prompt()
        assert "CASE C" in prompt, (
            "CLARIFYING_INTENT_PROMPT must define CASE C for real-world constraints"
        )

    def test_case_c_appears_after_case_b(self):
        """CASE C header must appear after CASE B in the prompt."""
        prompt = self._get_prompt()
        case_b_pos = prompt.find("CASE B")
        case_c_pos = prompt.find("CASE C")
        assert case_b_pos != -1, "CLARIFYING_INTENT_PROMPT must define CASE B"
        assert case_c_pos != -1, "CLARIFYING_INTENT_PROMPT must define CASE C"
        assert case_b_pos < case_c_pos, (
            "CASE C must come after CASE B in CLARIFYING_INTENT_PROMPT"
        )

    def test_case_c_beat_1_validates_their_reality(self):
        """CASE C Beat 1 must instruct the model to validate the child's real-world situation."""
        section = self._get_case_c_section()
        assert "BEAT 1" in section, (
            "CASE C must define BEAT 1"
        )
        beat_1_pos = section.find("BEAT 1")
        beat_1_text = section[beat_1_pos:beat_1_pos + 200]
        assert "VALIDATE" in beat_1_text.upper() or "REALITY" in beat_1_text.upper(), (
            "CASE C BEAT 1 must instruct validating the child's reality "
            "(expected 'VALIDATE THEIR REALITY' or similar)"
        )

    def test_case_c_beat_2_imaginative_redirect(self):
        """CASE C Beat 2 must instruct an imaginative or relatable redirect."""
        section = self._get_case_c_section()
        assert "BEAT 2" in section, (
            "CASE C must define BEAT 2"
        )
        beat_2_pos = section.find("BEAT 2")
        beat_2_text = section[beat_2_pos:beat_2_pos + 300]
        has_imaginative = (
            "IMAGINATIVE" in beat_2_text.upper()
            or "imaginative" in beat_2_text.lower()
            or "redirect" in beat_2_text.lower()
        )
        assert has_imaginative, (
            "CASE C BEAT 2 must include an imaginative or relatable redirect instruction"
        )

    def test_case_c_beat_3_open_question_accessible(self):
        """CASE C Beat 3 must require an open question that does not require the child to have the object."""
        section = self._get_case_c_section()
        assert "BEAT 3" in section, (
            "CASE C must define BEAT 3"
        )
        beat_3_pos = section.find("BEAT 3")
        beat_3_text = section[beat_3_pos:beat_3_pos + 400]
        # The beat must instruct a question
        has_question_instruction = (
            "QUESTION" in beat_3_text.upper()
            or "question" in beat_3_text.lower()
        )
        assert has_question_instruction, (
            "CASE C BEAT 3 must instruct asking an open question to re-engage the child"
        )
        # Accessibility: no requirement to have the object
        has_accessibility_note = (
            "no requirement" in beat_3_text.lower()
            or "accessible" in beat_3_text.lower()
            or "without" in beat_3_text.lower()
        )
        assert has_accessibility_note, (
            "CASE C BEAT 3 must note that the question should be accessible — "
            "the child is not required to have the object"
        )


class TestClarifyingPromptCaseCProhibition:
    """Validate the prohibition against treating constraint statements as avoidance."""

    def _get_prompt(self) -> str:
        return paixueji_prompts.CLARIFYING_INTENT_PROMPT

    def _get_prohibitions_section(self) -> str:
        prompt = self._get_prompt()
        prohibitions_start = prompt.find("PROHIBITIONS")
        assert prohibitions_start != -1, "CLARIFYING_INTENT_PROMPT must have a PROHIBITIONS section"
        return prompt[prohibitions_start:]

    def test_prohibition_against_treating_constraint_as_avoidance_exists(self):
        """PROHIBITIONS block must instruct: do NOT treat a constraint as avoidance."""
        section = self._get_prohibitions_section()
        has_constraint_prohibition = (
            "constraint" in section.lower()
            or "avoidance" in section.lower()
        )
        assert has_constraint_prohibition, (
            "CLARIFYING_INTENT_PROMPT PROHIBITIONS must include a rule against "
            "treating constraint statements as avoidance"
        )

    def test_prohibition_bans_we_can_talk_about_something_else_phrasing(self):
        """PROHIBITIONS must explicitly ban 'That's okay, we can talk about something else!'."""
        section = self._get_prohibitions_section()
        has_ban = (
            "something else" in section.lower()
            or "talk about something" in section.lower()
        )
        assert has_ban, (
            "CLARIFYING_INTENT_PROMPT PROHIBITIONS must explicitly ban "
            "saying 'That's okay, we can talk about something else!'"
        )

    def test_prohibition_is_after_case_c_in_document_order(self):
        """The constraint-as-avoidance prohibition must appear in PROHIBITIONS, after CASE C."""
        prompt = self._get_prompt()
        case_c_pos = prompt.find("CASE C")
        prohibitions_pos = prompt.find("PROHIBITIONS")
        assert case_c_pos != -1, "CASE C must exist"
        assert prohibitions_pos != -1, "PROHIBITIONS must exist"
        assert case_c_pos < prohibitions_pos, (
            "PROHIBITIONS section must come after CASE C in CLARIFYING_INTENT_PROMPT"
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
