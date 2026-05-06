import json
import os

HOOK_TYPES_PATH = os.path.join(os.path.dirname(__file__), "..", "hook_types.json")

def test_hook_types_count():
    with open(HOOK_TYPES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 10, f"Expected 10 hooks, got {len(data)}"

def test_imitation_hook_present():
    with open(HOOK_TYPES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "模仿引导" in data
    hook = data["模仿引导"]
    assert hook["safety_constraint"] == "voices_and_motions_only"
    assert any("bark like a puppy" in ex for ex in hook["examples"])
    assert any("stretch together like sunflowers" in ex for ex in hook["examples"])

def test_silly_twist_hook_present():
    with open(HOOK_TYPES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "轻搞怪/无厘头" in data
    hook = data["轻搞怪/无厘头"]
    assert any("dance party" in ex for ex in hook["examples"])
    assert any("chocolate bar" in ex for ex in hook["examples"])
