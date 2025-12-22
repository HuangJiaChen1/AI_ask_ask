"""
Test the LLM-based stuck detection system
"""
from child_learning_assistant import ChildLearningAssistant

def test_stuck_detection():
    """Test various child responses to see if stuck detection works"""
    print("=" * 60)
    print("Testing LLM-Based Stuck Detection")
    print("=" * 60)

    try:
        assistant = ChildLearningAssistant()
        print("[OK] Assistant initialized\n")
    except Exception as e:
        print(f"[ERROR] Failed to initialize: {e}")
        return

    # Test cases: (response, expected_stuck)
    test_cases = [
        # Stuck responses
        ("I don't know", True),
        ("idk", True),
        ("dunno", True),
        ("what?", True),
        ("huh?", True),
        ("Nope", True),
        ("no idea", True),
        ("help!", True),
        ("?", True),
        ("what does that mean", True),
        ("I dont get it", True),

        # Attempting to answer
        ("red", False),
        ("on trees", False),
        ("it flies", False),
        ("5", False),
        ("yes", False),
        ("no", False),
        ("in the sky", False),
        ("maybe it's blue?", False),
        ("I think it's round", False),
    ]

    print("Testing stuck detection:")
    print("-" * 60)

    correct = 0
    total = len(test_cases)

    for response, expected_stuck in test_cases:
        is_stuck = assistant._is_child_stuck(response)
        status = "[OK]" if is_stuck == expected_stuck else "[FAIL]"
        stuck_str = "STUCK" if is_stuck else "ATTEMPTING"
        expected_str = "STUCK" if expected_stuck else "ATTEMPTING"

        print(f"{status} '{response}' -> {stuck_str} (expected: {expected_str})")

        if is_stuck == expected_stuck:
            correct += 1

    print("-" * 60)
    print(f"\nResults: {correct}/{total} correct ({100*correct/total:.1f}%)")

    if correct == total:
        print("\n[SUCCESS] All tests passed!")
    elif correct >= total * 0.8:
        print("\n[PARTIAL] Most tests passed (80%+)")
    else:
        print("\n[FAIL] Too many failures")

    print("=" * 60)


if __name__ == '__main__':
    test_stuck_detection()
