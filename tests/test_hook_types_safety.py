import json
import pytest


def load_hook_types():
    with open("hook_types.json", encoding="utf-8") as f:
        return json.load(f)


def test_detail_discovery_no_touch_invitation():
    """细节发现 hook examples must not invite physical touch."""
    hooks = load_hook_types()
    detail = hooks["细节发现"]
    for ex in detail["examples"]:
        assert "touch" not in ex.lower(), f"Example invites touch: {ex}"
        assert "feel" not in ex.lower() or "look" in ex.lower(), f"Example may invite touch: {ex}"
