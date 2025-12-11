"""
Interactive demo for the Child Learning Assistant
This script simulates a conversation between the AI assistant and a child.
"""

from child_learning_assistant import ChildLearningAssistant
import database


def main():
    """Run the interactive demo."""
    print("=" * 60)
    print("Child Learning Assistant - Interactive Demo")
    print("=" * 60)
    print("\nThis assistant helps young children learn through questions!")
    print("The child can respond, and the assistant will continue the conversation.")
    print("\nCommands:")
    print("  - Type 'new' to start with a new object")
    print("  - Type 'quit' to exit")
    print("=" * 60)

    try:
        # Initialize the database
        database.init_db()
        print("\n[OK] Database initialized")

        # Load production prompts
        prompts = database.get_prompts()
        if not prompts:
            print("\n[ERROR] Production prompts not found in database!")
            print("Please run app.py first to initialize default prompts.")
            return

        system_prompt = prompts['system_prompt']
        user_prompt_template = prompts['user_prompt']
        print("[OK] Prompts loaded from database")

        # Initialize the assistant
        assistant = ChildLearningAssistant()
        print("[OK] Assistant initialized successfully!\n")

    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        return
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        print("\nPlease update the config.json file with your Qwen API key.")
        return

    in_conversation = False

    while True:
        if not in_conversation:
            # Get object information from user
            print("\n" + "-" * 60)
            object_name = input("\nEnter object name (or 'quit' to exit): ").strip()

            if object_name.lower() == 'quit':
                print("\nThank you for using Child Learning Assistant!")
                break

            if not object_name:
                print("Please enter a valid object name.")
                continue

            category = input("Enter object category: ").strip()

            if not category:
                print("Please enter a valid category.")
                continue

            print(f"\n🎯 Starting learning session about: {object_name} ({category})")
            print("-" * 60)

            # Start the conversation
            try:
                response = assistant.start_new_object(
                    object_name,
                    category,
                    system_prompt,
                    user_prompt_template
                )
                print(f"\n🤖 Assistant: {response}")
                in_conversation = True

            except Exception as e:
                print(f"\n[ERROR] {e}")
                import traceback
                traceback.print_exc()
                continue

        else:
            # Continue the conversation
            print("\n" + "-" * 60)
            child_response = input("👦 Child's response (or 'new' for new object, 'quit' to exit): ").strip()

            if child_response.lower() == 'quit':
                print("\nThank you for using Child Learning Assistant!")
                break

            if child_response.lower() == 'new':
                assistant.reset()
                in_conversation = False
                continue

            if not child_response:
                print("Please enter a response.")
                continue

            # Get assistant's response
            try:
                response, mastery_achieved, is_correct, is_neutral = assistant.continue_conversation(child_response)

                emoji_response = response
                # Add emoji only if it's a direct answer, not a hint or the final mastery message
                if not is_neutral and not mastery_achieved:
                    if is_correct:
                        emoji_response = f"✅ {response}"
                    else:
                        emoji_response = f"❌ {response}"

                print(f"\n🤖 Assistant: {emoji_response}")

                if mastery_achieved:
                    print(f"\n{'='*60}")
                    print("🎉 MASTERY ACHIEVED! 🎉")
                    print(f"Correct answers: {assistant.correct_count}")
                    print(f"{'='*60}\n")

            except Exception as e:
                print(f"\n[ERROR] {e}")
                import traceback
                traceback.print_exc()
                continue


if __name__ == "__main__":
    main()
