import paixueji_prompts


def test_introduction_prompt_has_sensory_safety_placeholder():
    assert "{sensory_safety_rules}" in paixueji_prompts.INTRODUCTION_PROMPT
