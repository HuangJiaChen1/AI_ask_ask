import paixueji_prompts as pp

def test_character_profile_constant_exists():
    assert hasattr(pp, "CHARACTER_PROFILE"), "CHARACTER_PROFILE not found"
    assert "Age:" in pp.CHARACTER_PROFILE
    assert "Hobbies:" in pp.CHARACTER_PROFILE

def test_social_prompt_has_character_profile():
    prompts = pp.get_prompts()
    text = prompts.get("social_intent_prompt", "")
    assert "CHARACTER_PROFILE" in text or "character_profile" in text.lower()
