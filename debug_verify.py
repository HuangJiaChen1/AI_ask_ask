"""Probe script to verify hypotheses for the diagnose skill.
Run: python debug_verify.py
"""
import sys
sys.path.insert(0, r"C:\Users\123\Documents\GitHub\AI_ask_ask")

import asyncio
from stream.verification_guided_conversation import (
    classify_verification,
    _CONFIRM_KEYWORDS,
    _DENY_KEYWORDS,
)
from stream.cares_handoff import (
    AttributeInterestRecord,
    compute_attribute_interest_score_breakdown,
    compute_attribute_interest_score,
    evaluate_handoff,
    HandoffDecision,
    MIN_INTEREST_FOR_HANDOFF,
)

# ── Probe 1: H1/H2 — keyword fast-path behavior ──
print("=" * 60)
print("PROBE 1: keyword fast-path with 'it has wings' on polka_dots")
print("=" * 60)

async def probe1():
    # Simulate the exact bug scenario
    result = await classify_verification(
        child_input="it has wings",
        property="polka_dots",
        conversation_context="We are talking about a bug.",
        client=None,
        config=None,
    )
    print(f"  Input: 'it has wings'")
    print(f"  Property: 'polka_dots'")
    print(f"  Result: {result}")
    print(f"  [H1-VALID] verdict == 'confirm'? {result['verdict'] == 'confirm'}")
    print()

    # Test more edge cases
    test_cases = [
        ("it has legs", "polka_dots"),
        ("it has spots", "polka_dots"),
        ("yes", "polka_dots"),
        ("it does fly", "polka_dots"),
        ("no", "polka_dots"),
        ("it has wings", "has_wings"),  # If property is actually about wings
    ]
    print("  Edge cases:")
    for inp, prop in test_cases:
        r = await classify_verification(
            child_input=inp,
            property=prop,
            conversation_context="",
            client=None,
            config=None,
        )
        print(f"    '{inp}' / '{prop}' -> {r['verdict']} (source={r['source']})")
    print()

asyncio.run(probe1())

# ── Probe 2: H3/H4 — interest score after 1 turn ──
print("=" * 60)
print("PROBE 2: interest score after 1 turn with CORRECT_ANSWER")
print("=" * 60)

record = AttributeInterestRecord(attribute_id="activity.polka_dot_patrol")
record.turns_explored = 1
record.intent_history = ["CORRECT_ANSWER"]

breakdown = compute_attribute_interest_score_breakdown(record)
score = compute_attribute_interest_score(record)
print(f"  turns_explored=1, intent_history=['CORRECT_ANSWER']")
print(f"  Breakdown: {breakdown}")
print(f"  Total score: {score}")
print(f"  Threshold: {MIN_INTEREST_FOR_HANDOFF}")
print(f"  [H3-VALID] score >= threshold? {score >= MIN_INTEREST_FOR_HANDOFF}")
print()

# What if CORRECT_ANSWER is NOT in positive_intents?
print("  What if CORRECT_ANSWER were removed from positive intents?")
# Manually recalculate
positive_intents = {"INFORMATIVE", "CURIOSITY", "PLAY", "EMOTIONAL"}  # without CORRECT_ANSWER
positive = sum(1 for it in record.intent_history if it in positive_intents)
base = (positive / record.turns_explored) * 60
streak = min(record.turns_explored * 5, 20)
total_without_correct = base + streak
print(f"  New base={base}, streak={streak}, total={total_without_correct}")
print(f"  [H4-VALID] Would still exceed threshold? {total_without_correct >= MIN_INTEREST_FOR_HANDOFF}")
print()

# What about 2 turns with mixed intents?
print("  What about 2 turns with CORRECT_ANSWER + INFORMATIVE?")
record2 = AttributeInterestRecord(attribute_id="activity.polka_dot_patrol")
record2.turns_explored = 2
record2.intent_history = ["CORRECT_ANSWER", "INFORMATIVE"]
breakdown2 = compute_attribute_interest_score_breakdown(record2)
print(f"  Breakdown: {breakdown2}")
print()

# ── Probe 3: Full handoff evaluation with bug state ──
print("=" * 60)
print("PROBE 3: evaluate_handoff with falsely-verified property")
print("=" * 60)

from types import SimpleNamespace
from stream.verification_guided_conversation import VerificationItem

# Build mock assistant with the exact bug state from the report
assistant = SimpleNamespace()
assistant.consecutive_struggle_count = 0

state = SimpleNamespace()
state.profile = SimpleNamespace(attribute_id="activity.polka_dot_patrol")
state.turn_count = 1
state.primary_activity = SimpleNamespace(
    activity_id="polka_dot_patrol",
    name="Find three polka-dotted things!",
    observation_angle="pattern",
)
# Bug: polka_dots was incorrectly verified
state.verification_queue = [
    VerificationItem(
        property="polka_dots",
        question="Does your bug have any spots or polka dots on its back?",
        for_activity_id="polka_dot_patrol",
        status="verified",
    ),
]
state.explored_angle_ids = []
state.angle_records = []
assistant.attribute_state = state

# Interest record after 1 turn
assistant.attribute_interest_records = {
    "activity.polka_dot_patrol": AttributeInterestRecord(
        attribute_id="activity.polka_dot_patrol",
        turns_explored=1,
        intent_history=["CORRECT_ANSWER"],
        is_current=True,
    ),
}

switch = SimpleNamespace(should_switch=False, target_attribute_id=None)

decision, reason, meta = evaluate_handoff(assistant, switch)
print(f"  Decision: {decision.value}")
print(f"  Reason: {reason}")
print(f"  Meta: {meta}")
print(f"  [BUG-CONFIRMED] decision == HANDOFF_NOW? {decision == HandoffDecision.HANDOFF_NOW}")
print()

# What if the property was NOT verified (correct behavior)?
print("  What if property was still pending (correct behavior)?")
state2 = SimpleNamespace()
state2.profile = SimpleNamespace(attribute_id="activity.polka_dot_patrol")
state2.turn_count = 1
state2.primary_activity = SimpleNamespace(
    activity_id="polka_dot_patrol",
    name="Find three polka-dotted things!",
    observation_angle="pattern",
)
state2.verification_queue = [
    VerificationItem(
        property="polka_dots",
        question="Does your bug have any spots or polka dots on its back?",
        for_activity_id="polka_dot_patrol",
        status="pending",
    ),
]
state2.explored_angle_ids = []
state2.angle_records = []
assistant2 = SimpleNamespace()
assistant2.consecutive_struggle_count = 0
assistant2.attribute_state = state2
assistant2.attribute_interest_records = assistant.attribute_interest_records

decision2, reason2, meta2 = evaluate_handoff(assistant2, switch)
print(f"  Decision: {decision2.value}")
print(f"  Reason: {reason2}")
print(f"  [COUNTERFACTUAL] Would block handoff? {decision2 != HandoffDecision.HANDOFF_NOW}")
print()

# ── Probe 4: Confirm keyword list contents ──
print("=" * 60)
print("PROBE 4: _CONFIRM_KEYWORDS contents")
print("=" * 60)
print(f"  _CONFIRM_KEYWORDS = {_CONFIRM_KEYWORDS}")
print(f"  'has' in confirm? {'has' in _CONFIRM_KEYWORDS}")
print(f"  'does' in confirm? {'does' in _CONFIRM_KEYWORDS}")
print()

# ── Probe 5: What inputs would correctly use keyword path? ──
print("=" * 60)
print("PROBE 5: Inputs that keyword path is MEANT for")
print("=" * 60)
keyword_test_inputs = [
    "yes",
    "yeah it has spots",
    "it has wings",
    "it does fly",
    "right",
    "correct",
]
for inp in keyword_test_inputs:
    words = set(__import__('re').findall(r"[a-z']+", inp.lower()))
    has_confirm = bool(words & _CONFIRM_KEYWORDS)
    has_deny = bool(words & _DENY_KEYWORDS)
    short = len(inp.split()) <= 6
    would_confirm = has_confirm and not has_deny and short
    print(f"  '{inp}' -> confirm_keywords={has_confirm}, deny_keywords={has_deny}, short={short} => would_confirm={would_confirm}")
print()

print("=" * 60)
print("PROBE COMPLETE")
print("=" * 60)
