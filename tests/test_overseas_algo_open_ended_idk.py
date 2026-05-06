import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask\.worktrees\overseas-algo-alignment")
import paixueji_prompts as pp

def test_open_ended_idk_no_beat3():
    prompts = pp.get_prompts()
    text = prompts.get("give_answer_open_ended_idk_intent_prompt", "")
    assert "BEAT 3" not in text, "Should drop BEAT 3 entirely"
    assert "LIGHT RE-OPEN" not in text
    assert "2 beats" in text or "2–2 beats" in text, "Should state 2 beats"
