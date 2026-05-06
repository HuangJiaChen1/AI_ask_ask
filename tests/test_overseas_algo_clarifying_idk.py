import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask\.worktrees\overseas-algo-alignment")
import paixueji_prompts as pp

def test_clarifying_idk_single_clue_language():
    prompts = pp.get_prompts()
    text = prompts.get("clarifying_idk_intent_prompt", "")
    assert "THIS IS YOUR ONLY CHANCE TO HINT" in text, "Missing single-clue cap instruction"
    assert "After this turn, the system will reveal the answer" in text
