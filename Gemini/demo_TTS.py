"""
Interactive demo for the Child Learning Assistant with Text-to-Speech (Gemini Version)
This script simulates a conversation between the AI assistant and a child with voice output.
"""

from child_learning_assistant import ChildLearningAssistant
import database
import requests
import os
from io import BytesIO
import pygame


# Deepgram API configuration
DEEPGRAM_API_KEY = "271fd6a37dbf97e935f03c1ec32f2ac7ed6756ef"
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"


def text_to_speech(text, voice_model="aura-2-luna-en"):
    """
    Convert text to speech using Deepgram TTS API and play it.

    Args:
        text: The text to convert to speech
        voice_model: Deepgram voice model to use (default: aura-2-stella-en - bright, energetic voice perfect for a playful red panda)
                     Other cute options: aura-2-luna-en (gentle), aura-2-asteria-en (warm), aura-2-arcas-en (young male)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "text": text
        }

        # Make request to Deepgram TTS API
        response = requests.post(
            f"{DEEPGRAM_TTS_URL}?model={voice_model}",
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code == 200:
            # Get audio data
            audio_data = BytesIO(response.content)

            # Initialize pygame mixer if not already initialized
            if not pygame.mixer.get_init():
                pygame.mixer.init()

            # Load and play audio
            pygame.mixer.music.load(audio_data, 'mp3')
            pygame.mixer.music.play()

            # Wait for playback to finish
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)

            return True
        else:
            print(f"\n[TTS Error] Status code: {response.status_code}")
            print(f"[TTS Error] Response: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"\n[TTS Error] Failed to generate speech: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run the interactive demo with TTS."""
    print("=" * 60)
    print("Child Learning Assistant - Interactive Demo with TTS (Gemini)")
    print("=" * 60)
    print("\nThis assistant helps young children learn through questions!")
    print("The child can respond, and the assistant will continue the conversation.")
    print("\nNEW: The assistant's responses will be spoken aloud!")
    print("\nCommands:")
    print("  - Type 'new' to start with a new object")
    print("  - Type 'quit' to exit")
    print("=" * 60)

    try:
        # Initialize pygame for audio playback
        pygame.mixer.init()
        print("\n[OK] Audio system initialized")

        # Initialize the database
        database.init_db()
        print("[OK] Database initialized")

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
        print("\nPlease update the config.json file with your Gemini API key.")
        return
    except Exception as e:
        print(f"\n[ERROR] Failed to initialize: {e}")
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

                # Convert to speech using clean audio output
                print("[Playing audio...]")
                audio_text = assistant.last_audio_output if assistant.last_audio_output else response
                text_to_speech(audio_text)

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

                # Convert to speech using clean audio output (without emojis)
                print("[Playing audio...]")
                text_to_speech(audio_output)

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
