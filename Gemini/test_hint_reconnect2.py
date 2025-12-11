"""
Test script for hint reconnection system - Better test case
Simulates proper flow with appropriate hint answer
"""

import sys
import io

# Fix Windows console encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from child_learning_assistant import ChildLearningAssistant
import database
import prompts

print("=" * 80)
print("Testing Hint Reconnection System - Proper Flow")
print("=" * 80)

# Initialize
database.init_db()
prompts_dict = prompts.get_prompts()
system_prompt = prompts_dict['system_prompt']
user_prompt_template = prompts_dict['user_prompt']

assistant = ChildLearningAssistant()

# Start conversation
print("\n[Step 1] Starting conversation about onion...")
response = assistant.start_new_object(
    "onion",
    "vegetable",
    system_prompt,
    user_prompt_template,
    age=5,
    level2_category="fresh_ingredients"
)
print(f"\nAssistant: {response}")
print(f"State: {assistant.state.value}")

# First response: "I don't know" - should give first hint
print("\n" + "=" * 80)
print("[Step 2] Child says 'I don't know' - should give hint...")
response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation("I don't know")
print(f"\nAssistant (HINT): {response}")
print(f"State: {assistant.state.value}")
print(f"Original question saved: '{assistant.question_before_hint}'")

# Answer the hint question with a proper answer
print("\n" + "=" * 80)
print("[Step 3] Child answers the hint question appropriately...")
print("(Looking at hint to determine appropriate answer...)")

# The hint question should be about something that makes eyes cry/water
# Let's answer appropriately: "they cry" or "they get watery"
hint_answer = "they cry"
print(f"Child's answer to hint: '{hint_answer}'")

response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation(hint_answer)
print(f"\nAssistant (RECONNECT): {response}")
print(f"State: {assistant.state.value}")
print(f"Is neutral (no emoji): {is_neutral}")

# Check if it reconnected properly
success_keywords = ["eye", "onion", "cry", "tear", "water"]
found_keywords = [kw for kw in success_keywords if kw in response.lower()]
print(f"\nKeywords found in reconnect response: {found_keywords}")

if len(found_keywords) >= 2:
    print("SUCCESS: Response reconnected back to original question about onions and eyes!")
else:
    print("WARNING: Reconnection may not have fully bridged back to original question")

# Fourth response: Answer the original question
print("\n" + "=" * 80)
print("[Step 4] Child answers the original question...")
response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation("it makes them cry")
print(f"\nAssistant: {response}")
print(f"State: {assistant.state.value}")
print(f"Is correct: {is_correct}")
print(f"Correct count: {assistant.correct_count}")

print("\n" + "=" * 80)
print("Test complete!")
print("=" * 80)
