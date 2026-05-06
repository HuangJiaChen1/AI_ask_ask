import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask\.worktrees\overseas-algo-alignment")
import paixueji_prompts as pp

def test_explanation_open_ended_offers_1_to_2_suggestions():
    """EXPLANATION_RESPONSE_PROMPT should ask for 1-2 suggestions, not 2-3."""
    prompts = pp.get_prompts()
    text = prompts.get("explanation_response_prompt", "")
    assert "1-2 fun suggestions" in text, "EXPLANATION_RESPONSE_PROMPT should say '1-2 fun suggestions'"
    assert "2-3 fun suggestions" not in text, "EXPLANATION_RESPONSE_PROMPT still says '2-3 fun suggestions'"

def test_curiosity_beat_2_anchor_constraint():
    """CURIOSITY_ATTRIBUTE_RESPONSE_PROMPT BEAT 2 must amplify the child's specific question."""
    prompts = pp.get_prompts()
    text = prompts.get("curiosity_attribute_response_prompt", "")
    # The ANCHOR CHECK must contain the strong constraint language
    assert "Your WOW detail MUST amplify the answer to *that question*" in text, (
        "CURIOSITY BEAT 2 anchor constraint missing"
    )
