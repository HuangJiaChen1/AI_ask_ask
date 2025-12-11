"""
Test that session persistence preserves question tracking fields
"""

import sys
import io
import uuid

# Fix Windows console encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from child_learning_assistant import ChildLearningAssistant
import database
import prompts

print("=" * 80)
print("Testing Session Persistence for Question Tracking")
print("=" * 80)

# Initialize
database.init_db()
prompts_dict = prompts.get_prompts()
system_prompt = prompts_dict['system_prompt']
user_prompt_template = prompts_dict['user_prompt']

# Create a new session
session_id = str(uuid.uuid4())
print(f"\n[Step 1] Creating new session: {session_id[:8]}...")

assistant = ChildLearningAssistant()
response = assistant.start_new_object(
    "banana",
    "fruit",
    system_prompt,
    user_prompt_template,
    age=5,
    level2_category="fresh_ingredients"
)

print(f"Assistant: {response[:100]}...")
print(f"current_main_question: {assistant.current_main_question[:50] if assistant.current_main_question else 'None'}")
print(f"expected_answer: {assistant.expected_answer[:50] if assistant.expected_answer else 'None'}")

# Save to database
print(f"\n[Step 2] Saving session to database...")
database.save_session(session_id, assistant)
print(f"Session saved")

# Load from database
print(f"\n[Step 3] Loading session from database...")
loaded_assistant = database.load_session(session_id)
print(f"Session loaded")
print(f"current_main_question: {loaded_assistant.current_main_question[:50] if loaded_assistant.current_main_question else 'None'}")
print(f"expected_answer: {loaded_assistant.expected_answer[:50] if loaded_assistant.expected_answer else 'None'}")

# Verify fields are preserved
if loaded_assistant.current_main_question and loaded_assistant.expected_answer:
    print("\n✅ SUCCESS: Question tracking fields preserved across save/load!")
else:
    print(f"\n❌ FAILURE: Fields not preserved")
    print(f"   current_main_question: {repr(loaded_assistant.current_main_question)}")
    print(f"   expected_answer: {repr(loaded_assistant.expected_answer)}")

# Test hint generation with loaded session
print(f"\n[Step 4] Testing hint generation with loaded session...")
try:
    response, mastery, is_correct, is_neutral, audio = loaded_assistant.continue_conversation("I don't know")
    print(f"State: {loaded_assistant.state.value}")
    print(f"Response: {response[:100]}...")

    if "Can you make a guess?" in response:
        print("❌ FAILURE: Still returning fallback message!")
    else:
        print("✅ SUCCESS: Proper hint generated!")
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

# Cleanup
database.delete_session(session_id)
print(f"\n[Cleanup] Deleted test session")

print("\n" + "=" * 80)
print("Test complete!")
print("=" * 80)
