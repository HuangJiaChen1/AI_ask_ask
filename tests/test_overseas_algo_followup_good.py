import paixueji_prompts as pp

def test_followup_good_no_sniff_tap_hold():
    prompts = pp.get_prompts()
    text = prompts.get("followup_question_prompt", "")
    assert "sniff" not in text.lower(), "FOLLOWUP still mentions sniff"
    assert "tap" not in text.lower(), "FOLLOWUP still mentions tap"
    assert "hold" not in text.lower(), "FOLLOWUP still mentions hold"
    assert "try having a little sniff" not in text.lower()

def test_followup_good_has_visual_examples():
    prompts = pp.get_prompts()
    text = prompts.get("followup_question_prompt", "")
    assert "Is it shiny or dull?" in text
    assert "Which part looks the biggest?" in text
    assert "Do you think it's smooth or bumpy?" in text or "smooth or bumpy" in text
