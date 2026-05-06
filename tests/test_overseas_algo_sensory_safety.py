import paixueji_prompts as pp

def test_sensory_safety_rules_constant_exists():
    assert hasattr(pp, "SENSORY_SAFETY_RULES"), "SENSORY_SAFETY_RULES not found"
    assert "Do NOT invite the child to TOUCH" in pp.SENSORY_SAFETY_RULES
    assert "only voices and stretches" in pp.SENSORY_SAFETY_RULES

def test_sensory_safety_injected_into_explanation_response():
    prompts = pp.get_prompts()
    text = prompts.get("explanation_response_prompt", "")
    assert "{sensory_safety_rules}" in text, "SENSORY_SAFETY_RULES placeholder not found in EXPLANATION_RESPONSE_PROMPT"

def test_sensory_safety_injected_into_followup_question():
    prompts = pp.get_prompts()
    text = prompts.get("followup_question_prompt", "")
    assert "{sensory_safety_rules}" in text, "SENSORY_SAFETY_RULES placeholder not found in FOLLOWUP_QUESTION_PROMPT"

def test_sensory_safety_injected_into_attribute_intro():
    prompts = pp.get_prompts()
    text = prompts.get("attribute_intro_prompt", "")
    assert "{sensory_safety_rules}" in text, "SENSORY_SAFETY_RULES placeholder not found in ATTRIBUTE_INTRO_PROMPT"

def test_sensory_safety_injected_into_attribute_soft_guide():
    prompts = pp.get_prompts()
    text = prompts.get("attribute_soft_guide", "")
    assert "{sensory_safety_rules}" in text, "SENSORY_SAFETY_RULES placeholder not found in ATTRIBUTE_SOFT_GUIDE"
