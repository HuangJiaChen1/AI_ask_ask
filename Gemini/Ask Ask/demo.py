"""
Interactive demo for the Ask Ask assistant.
Children ask questions and get age-appropriate answers with follow-up questions.
"""

from ask_ask_assistant import AskAskAssistant


def safe_print(message):
    """Print message with fallback for encoding errors."""
    try:
        print(message)
    except UnicodeEncodeError:
        # Fallback: encode to ascii with replacement
        print(message.encode('ascii', 'replace').decode('ascii'))


def main():
    """Run the interactive demo."""
    print("=" * 60)
    print("Ask Ask - Curiosity-Driven Learning Assistant")
    print("=" * 60)
    print("\nWelcome! In this demo, YOU ask the questions!")
    print("The assistant will answer and help you keep exploring.")
    print("\nCommands:")
    print("  - Ask any question about anything!")
    print("  - Type 'restart' to begin again")
    print("  - Type 'quit' to exit")
    print("=" * 60)

    try:
        # Initialize the assistant
        assistant = AskAskAssistant()
        print("[OK] Assistant initialized successfully!\n")

    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        return
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        print("\nPlease update the config.json file with your Gemini API key.")
        return

    while True:
        # Get child's age
        print("\n" + "-" * 60)
        age_input = input("Enter child's age (3-8, or press Enter to skip): ").strip()
        age = None
        if age_input:
            try:
                age = int(age_input)
                if age < 3 or age > 8:
                    print("[WARNING] Age should be between 3-8. Using default prompting.")
                    age = None
            except ValueError:
                print("[WARNING] Invalid age. Using default prompting.")
                age = None

        # Start conversation with introduction
        try:
            print("\n" + "=" * 60)
            print("Starting conversation...")
            print("=" * 60)

            introduction = assistant.start_conversation(age=age)
            safe_print(f"\n🤖 Assistant: {introduction}")

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            continue

        # Conversation loop
        while True:
            print("\n" + "-" * 60)
            child_input = input("Your question (or 'restart'/'quit'): ").strip()

            if child_input.lower() == 'quit':
                print("\nThank you for your curiosity! Keep asking questions!")
                return

            if child_input.lower() == 'restart':
                assistant.reset()
                break

            if not child_input:
                print("Please ask a question or type a command.")
                continue

            # Get assistant's response
            try:
                response, audio_output = assistant.continue_conversation(child_input)
                safe_print(f"\n🤖 Assistant: {response}")

            except Exception as e:
                print(f"\n[ERROR] {e}")
                import traceback
                traceback.print_exc()
                continue


if __name__ == "__main__":
    main()
