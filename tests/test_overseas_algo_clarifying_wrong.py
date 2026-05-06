import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask\.worktrees\overseas-algo-alignment")
import paixueji_prompts as pp

def test_clarifying_wrong_has_named_styles():
    prompts = pp.get_prompts()
    text = prompts.get("clarifying_wrong_intent_prompt", "")
    assert "Interesting Observation" in text
    assert "So Close" in text
    assert "Playful Pivot" in text
    assert "ACKNOWLEDGE THE EFFORT" in text
    assert 'NEVER use "no" or "wrong"' in text
    assert "MIRROR THEIR LOGIC" in text
