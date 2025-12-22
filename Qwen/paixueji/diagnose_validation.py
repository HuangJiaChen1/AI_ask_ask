"""
Diagnostic script to test validation with a simulated conversation
"""
import sys
import io

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from child_learning_assistant import ChildLearningAssistant
import database

# Initialize database
database.init_db()

# Load production prompts
prompts = database.get_prompts()
if not prompts:
    print("[ERROR] No prompts in database. Run app.py first.")
    exit(1)

system_prompt = prompts['system_prompt']
user_prompt_template = prompts['user_prompt']

# Create assistant
assistant = ChildLearningAssistant()

print("="*80)
print("HINT GENERATION DIAGNOSTIC TEST")
print("="*80)
print("\nNEW APPROACH: Dedicated hint prompts (no complex validation!)")
print("\nWatch for:")
print("  - [Generated subtle hint for] - Hint 1 generation")
print("  - [Generated stronger hint for] - Hint 2 generation")
print("  - [Revealed answer for] - Final answer reveal")
print("  - State transitions: initial → awaiting → hint1 → hint2 → reveal")
print("="*80)

# Start conversation
print("\n\nSTARTING: Apple conversation")
print("-"*80)
response = assistant.start_new_object("Apple", "Fruit", system_prompt, user_prompt_template)
print(f"\n🤖 First Question: {response}\n")

# Simulate "I don't know" - should trigger GIVING_HINT_1
print("\n\nCHILD RESPONDS: 'I don't know'")
print("-"*80)
print(f"Current state BEFORE: {assistant.state.value}")
print(f"Stuck count BEFORE: {assistant.stuck_count}")

response, mastery = assistant.continue_conversation("I don't know")

print(f"\nCurrent state AFTER: {assistant.state.value}")
print(f"Stuck count AFTER: {assistant.stuck_count}")
print(f"\n🤖 Assistant response:\n{response}\n")

# Second "I don't know" - should trigger GIVING_HINT_2
print("\n\nCHILD RESPONDS: 'I don't know' (2nd time)")
print("-"*80)
print(f"Current state BEFORE: {assistant.state.value}")
print(f"Stuck count BEFORE: {assistant.stuck_count}")

response, mastery = assistant.continue_conversation("I don't know")

print(f"\nCurrent state AFTER: {assistant.state.value}")
print(f"Stuck count AFTER: {assistant.stuck_count}")
print(f"\n🤖 Assistant response:\n{response}\n")

# Third "I don't know" - should trigger REVEALING_ANSWER
print("\n\nCHILD RESPONDS: 'I don't know' (3rd time)")
print("-"*80)
print(f"Current state BEFORE: {assistant.state.value}")
print(f"Stuck count BEFORE: {assistant.stuck_count}")

response, mastery = assistant.continue_conversation("I don't know")

print(f"\nCurrent state AFTER: {assistant.state.value}")
print(f"Stuck count AFTER: {assistant.stuck_count}")
print(f"\n🤖 Assistant response:\n{response}\n")

print("\n" + "="*80)
print("DIAGNOSTIC COMPLETE")
print("="*80)
print("\nWhat you should see:")
print("1. First 'I don't know' → State: hint1 → [Generated subtle hint]")
print("2. Second 'I don't know' → State: hint2 → [Generated stronger hint]")
print("3. Third 'I don't know' → State: reveal → [Revealed answer]")
print("\nNO MORE COMPLEX JSON VALIDATION!")
print("Each state uses a dedicated, focused prompt.")
