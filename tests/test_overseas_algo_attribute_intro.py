import paixueji_prompts as pp


def test_attribute_intro_has_hook_placeholder():
    prompts = pp.get_prompts()
    text = prompts.get("attribute_intro_prompt", "")
    assert "{hook_type_section}" in text, "ATTRIBUTE_INTRO should accept hook_type_section"


def test_attribute_intro_has_fallback_path():
    prompts = pp.get_prompts()
    text = prompts.get("attribute_intro_prompt", "")
    assert "FALLBACK" in text, "ATTRIBUTE_INTRO must have a FALLBACK path"
    assert "{hook_type_section}" in text, "FALLBACK should reference hook_type_section"
