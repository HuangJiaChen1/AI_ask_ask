import paixueji_prompts


def test_emotional_extreme_prompt_requires_trusted_grownup():
    """Type C emotional response MUST suggest talking to a trusted grown-up."""
    prompt = paixueji_prompts.EMOTIONAL_INTENT_PROMPT
    # Check that the prompt uses mandatory language for the trusted person suggestion
    assert "MUST include" in prompt or "both of these" in prompt, (
        "Prompt should make trusted-grown-up suggestion mandatory, not optional"
    )
    assert "grown-up you trust" in prompt
