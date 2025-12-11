"""
Test script for hint reconnection system
Simulates: Question → "I don't know" → Hint → Answer hint → Should reconnect to original
"""

import sys
import io

# Fix Windows console encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from child_learning_assistant import ChildLearningAssistant
import database
import prompts

print("=" * 60)
print("Testing Hint Reconnection System")
print("=" * 60)

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
print(f"\n🤖 Assistant: {response[:200]}...")

# First response: "I don't know" - should give first hint
print("\n[Step 2] Child says 'I don't know' - should transition to GIVING_HINT_1...")
response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation("I don't know")
print(f"State: {assistant.state.value}")
print(f"🤖 Assistant (Hint 1): {response[:200]}...")
print(f"Original question saved: {assistant.question_before_hint[:50] if assistant.question_before_hint else 'None'}...")

# Second response: Answer the hint question
print("\n[Step 3] Child answers the hint question...")
hint_answer = "because its yummy"
response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation(hint_answer)
print(f"State: {assistant.state.value}")
print(f"Is neutral (no emoji): {is_neutral}")
print(f"🤖 Assistant (Reconnect): {response}")

# Check if it reconnected
if "layer" in response.lower():
    print("\n✅ SUCCESS: Response mentions 'layer' - reconnected to original question!")
else:
    print("\n⚠️  WARNING: Response may not have reconnected to original question about layers")

# Fourth response: Should be asking the original question again
print("\n[Step 4] Child answers after reconnection...")
response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation("to protect it")
print(f"State: {assistant.state.value}")
print(f"Is neutral: {is_neutral}")
print(f"🤖 Assistant: {response[:200]}...")

print("\n" + "=" * 60)
print("Test complete!")
print("=" * 60)
