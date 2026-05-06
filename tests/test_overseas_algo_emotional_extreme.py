import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask\.worktrees\overseas-algo-alignment")
import paixueji_prompts as pp

def test_emotional_has_extreme_tier():
    prompts = pp.get_prompts()
    text = prompts.get("emotional_intent_prompt", "")
    assert "STRONG/EXTREME" in text or "EXTREME" in text, "Missing extreme emotion tier"
    assert "REAL-WORLD SUPPORT" in text
    assert "trusted person" in text or "grown-up you trust" in text
    assert "Do NOT try to fix the emotion within the system" in text
