from stream.utils import HIGH_IMAGINATION_HOOKS, select_hook_type
from graph import OPEN_ENDED_QUESTION_HOOKS, CONCRETE_QUESTION_HOOKS

def test_silly_twist_in_high_imagination():
    assert "轻搞怪/无厘头" in HIGH_IMAGINATION_HOOKS, "Silly twist should be high-imagination"

def test_imitation_not_in_high_imagination():
    assert "模仿引导" not in HIGH_IMAGINATION_HOOKS, "Imitation should NOT be high-imagination"
