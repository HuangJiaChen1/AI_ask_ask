import paixueji_prompts as pp

def test_user_intent_prompt_has_action_subtype():
    prompts = pp.get_prompts()
    text = prompts.get("user_intent_prompt", "")
    assert "ACTION_SUBTYPE" in text
    assert "A — REPEAT REQUEST" in text
    assert "B — NEW ACTIVITY REQUEST" in text
    assert "C — VAGUE OR META REQUEST" in text
    assert "D — REQUEST FOR UNRELATED SPECIFIC TOPIC" in text
