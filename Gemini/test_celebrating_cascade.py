"""
Test that CELEBRATING state properly cascades to hint when child says "I don't know"
"""

import sys
import io

# Fix Windows console encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from child_learning_assistant import ChildLearningAssistant
import database
import prompts

print("=" * 80)
print("Testing CELEBRATING → AWAITING_ANSWER → GIVING_HINT_1 Cascade")
print("=" * 80)

# Initialize
database.init_db()
prompts_dict = prompts.get_prompts()
system_prompt = prompts_dict['system_prompt']
user_prompt_template = prompts_dict['user_prompt']

assistant = ChildLearningAssistant()

# Start conversation
print("\n[Step 1] Starting conversation about apple...")
response = assistant.start_new_object(
    "apple",
    "fruit",
    system_prompt,
    user_prompt_template,
    age=5,
    level2_category="fresh_ingredients"
)
print(f"State: {assistant.state.value}")

# Answer correctly to get to CELEBRATING
print("\n[Step 2] Answer correctly to reach CELEBRATING state...")
response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation("it's red")
print(f"State: {assistant.state.value}")
print(f"Is correct: {is_correct}")

# Check if we're in CELEBRATING
if assistant.state.value == "celebrating":
    print("✅ Reached CELEBRATING state")
else:
    print(f"❌ Expected CELEBRATING, got {assistant.state.value}")

# Now say "I don't know" - should cascade to GIVING_HINT_1
print("\n[Step 3] Say 'I don't know' from CELEBRATING state...")
print(f"State BEFORE: {assistant.state.value}, stuck_count: {assistant.stuck_count}")

response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation("I don't know")

print(f"State AFTER: {assistant.state.value}, stuck_count: {assistant.stuck_count}")
print(f"Response: {response[:150]}...")

# Verify we're in GIVING_HINT_1
if assistant.state.value == "hint1":
    print("\n✅ SUCCESS: Properly cascaded from CELEBRATING → AWAITING_ANSWER → GIVING_HINT_1")
    print("✅ Generated proper hint (not fallback message)")
else:
    print(f"\n❌ FAILURE: Expected hint1, got {assistant.state.value}")

# Check the response isn't the fallback
if "Let me ask you something else" in response:
    print("❌ FAILURE: Got fallback JSON parsing message")
elif "Can you make a guess?" in response:
    print("❌ FAILURE: Got hint generation fallback message")
else:
    print("✅ Response looks good (no fallback messages)")

print("\n" + "=" * 80)
print("Test complete!")
print("=" * 80)
