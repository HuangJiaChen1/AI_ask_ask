"""
Test that None handling is fixed
"""

import sys
import io

# Fix Windows console encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from child_learning_assistant import ChildLearningAssistant
import database
import prompts

print("=" * 80)
print("Testing None Handling Fix")
print("=" * 80)

# Initialize
database.init_db()
prompts_dict = prompts.get_prompts()
system_prompt = prompts_dict['system_prompt']
user_prompt_template = prompts_dict['user_prompt']

assistant = ChildLearningAssistant()

# Start conversation
print("\n[Step 1] Starting conversation about instant noodle...")
try:
    response = assistant.start_new_object(
        "instant noodle",
        "processed_foods",
        system_prompt,
        user_prompt_template,
        age=8,
        level2_category="processed_foods"
    )
    print(f"Assistant: {response[:150]}...")
    print(f"State: {assistant.state.value}")
    print(f"current_main_question: {assistant.current_main_question[:50] if assistant.current_main_question else 'None'}")
except Exception as e:
    print(f"ERROR in start: {e}")
    import traceback
    traceback.print_exc()

# Try saying "I don't know" - this should not crash anymore
print("\n[Step 2] Child says 'I don't know'...")
try:
    response, mastery, is_correct, is_neutral, audio = assistant.continue_conversation("I don't know")
    print(f"SUCCESS! No crash occurred")
    print(f"Assistant: {response[:150]}...")
    print(f"State: {assistant.state.value}")
except TypeError as e:
    print(f"ERROR (TypeError): {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"ERROR (Other): {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("Test complete!")
print("=" * 80)
