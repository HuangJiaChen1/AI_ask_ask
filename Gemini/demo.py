"""
Interactive demo for the Child Learning Assistant (Gemini Version)
This script simulates a conversation between the AI assistant and a child.
"""

from child_learning_assistant import ChildLearningAssistant
import database
import prompts
import object_classifier


def main():
    """Run the interactive demo."""
    print("=" * 60)
    print("Child Learning Assistant - Interactive Demo (Gemini)")
    print("=" * 60)
    print("\nThis assistant helps young children learn through questions!")
    print("The child can respond, and the assistant will continue the conversation.")
    print("\nCommands:")
    print("  - Type 'new' to start with a new object")
    print("  - Type 'quit' to exit")
    print("=" * 60)

    try:
        # Initialize the database (for sessions only)
        database.init_db()
        print("\n[OK] Database initialized")

        # Load hardcoded prompts
        prompts_dict = prompts.get_prompts()
        system_prompt = prompts_dict['system_prompt']
        user_prompt_template = prompts_dict['user_prompt']
        print("[OK] Prompts loaded (hardcoded, age-flexible)")

        # Initialize the assistant
        assistant = ChildLearningAssistant()
        print("[OK] Assistant initialized successfully!\n")

    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        return
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        print("\nPlease update the config.json file with your Gemini API key.")
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

            # Classify the object using LLM
            print(f"\n🔍 Classifying '{object_name}'...")
            recommended_category = object_classifier.classify_object(object_name)

            # Get child's age
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

            # Get category hierarchy (simplified - only need level 2)
            print("\nEnter object category:")
            print("  Available Level 2 categories:")
            print("    Foods: fresh_ingredients, processed_foods, beverages_drinks")
            print("    Animals: vertebrates, invertebrates, human_raised_animals")
            print("    Plants: ornamental_plants, useful_plants, wild_natural_plants")
            print("  Note: Level 1 category will be auto-detected from Level 2")

            level2_category = None

            # Show recommendation if classification succeeded
            if recommended_category:
                category_display = object_classifier.get_category_display_name(recommended_category)
                print(f"\n💡 We think '{object_name}' belongs to the '{category_display}' category ({recommended_category})")
                use_recommendation = input("Use this category? (y/n, or press Enter for yes): ").strip().lower()

                if use_recommendation in ['', 'y', 'yes']:
                    level2_category = recommended_category
                    print(f"✓ Using recommended category: {recommended_category}")
                else:
                    print("Please enter your preferred category:")
                    level2_category = input("Level 2 category (or Enter to skip): ").strip() or None
            else:
                print("\n⚠️  Could not automatically classify the object.")
                level2_category = input("Level 2 category (or Enter to skip): ").strip() or None

            level3_category = input("Level 3 category (optional, for display only): ").strip() or None

            # Derive category from the most specific level provided
            category = level3_category or level2_category or "object"

            print(f"\n🎯 Starting learning session about: {object_name}")
            print(f"   Category: {category}")
            if age:
                print(f"   Age: {age} years old")
            if level2_category:
                print(f"   Using category: {level2_category} (Level 1 will be auto-detected)")
            print("-" * 60)

            # Start the conversation
            try:
                response = assistant.start_new_object(
                    object_name,
                    category,
                    system_prompt,
                    user_prompt_template,
                    age=age,
                    level1_category=None,  # Will be auto-detected from level2
                    level2_category=level2_category,
                    level3_category=level3_category
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
                response, mastery_achieved, is_correct, is_neutral, audio_output = assistant.continue_conversation(child_response)

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
