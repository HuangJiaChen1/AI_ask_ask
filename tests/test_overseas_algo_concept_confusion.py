import paixueji_prompts as pp

def test_concept_confusion_no_reask_prohibition():
    prompts = pp.get_prompts()
    text = prompts.get("concept_confusion_intent_prompt", "")
    assert "Do NOT skip Beat 3" not in text, "Should remove the old 'must not skip' prohibition"
    assert "DO NOT RE-ASK" in text or "do not re-ask" in text.lower(), "Should add no-re-ask rule"

def test_concept_confusion_has_validate_questioning():
    prompts = pp.get_prompts()
    text = prompts.get("concept_confusion_intent_prompt", "")
    assert "VALIDATE THE QUESTIONING SPIRIT" in text
    assert "self-verify" in text.lower() or "re-verify" in text.lower()
