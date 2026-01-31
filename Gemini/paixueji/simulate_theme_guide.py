"""
Simulation test for Pathway Guide feature.

This script demonstrates the new pathway-based conversation system using
WonderLens educational data. It allows testing pathway guides with objects
from objects.yaml and age-appropriate pathways.

Usage:
    python simulate_theme_guide.py
    python simulate_theme_guide.py --object Dog --age 6
    python simulate_theme_guide.py --list-objects
"""
import asyncio
import argparse
from google import genai
from loguru import logger
from paixueji_assistant import PaixuejiAssistant
from stream.main import call_paixueji_stream
from wonderlens_data import get_wonderlens_data, WonderlensData


def list_available_objects():
    """List all available objects from WonderLens data."""
    wonderlens = get_wonderlens_data()
    objects = wonderlens.list_all_object_names()

    print("\n=== Available Objects ===")
    print("Objects that can be used with pathway guides:\n")

    # Group by category
    categories = {}
    for obj_id, obj_data in wonderlens.objects.items():
        cat = obj_data.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(obj_data.name)

    for category, names in sorted(categories.items()):
        print(f"  {category.upper()}:")
        for name in sorted(names):
            print(f"    - {name}")
        print()


async def simulate_conversation(object_name: str, age: int):
    """Run a simulated pathway-guided conversation."""
    # Setup assistant
    assistant = PaixuejiAssistant()
    assistant.age = age
    assistant.character = "teacher"

    # Enable Pathway Guide using the new API
    print(f"\n=== Starting Pathway Guide for '{object_name}' (age {age}) ===\n")

    if not assistant.start_pathway_guide(object_name, age):
        print(f"Error: Could not start pathway guide for '{object_name}'")
        print("\nTip: Use --list-objects to see available objects")
        return

    # Display pathway info
    progress = assistant.get_pathway_progress()
    if progress:
        print(f"Pathway: {progress['pathway_id']}")
        print(f"Total rounds: {progress['total_rounds']}")
        print(f"Age tier: {progress['age_tier']}")
        print()

    config = assistant.config
    client = assistant.client

    # Initialize with System Prompt
    messages = [
        {"role": "system", "content": assistant.prompts['system_prompt']}
    ]

    print(f"Starting with object: {assistant.object_name}")
    print("(Type 'exit' or 'quit' to stop the simulation)\n")
    print("-" * 60)

    user_input = f"Start conversation about {assistant.object_name}"
    first_turn = True
    i = 0

    while True:
        if not first_turn:
            try:
                user_input = input("\nUSER: ")
                if user_input.lower() in ["exit", "quit", "q"]:
                    break
                if not user_input.strip():
                    continue
            except EOFError:
                break
        else:
            print(f"[System] Triggering start with: {user_input}")

        print("\nAI: ", end="", flush=True)
        full_response = ""

        async for chunk in call_paixueji_stream(
            age=age,
            messages=messages,
            content=user_input,
            status="normal",
            session_id="sim_pathway_session",
            request_id=f"req_{i}",
            config=config,
            client=client,
            assistant=assistant,
            object_name=assistant.object_name,
            character_prompt=assistant.get_character_prompt("teacher")
        ):
            if not chunk.finish:
                full_response += chunk.response
                print(chunk.response, end="", flush=True)

        print("\n")

        # --- VISUALIZE NAVIGATOR'S HIDDEN THOUGHTS ---
        print("-" * 60)
        if hasattr(assistant, 'last_navigation_state') and assistant.last_navigation_state:
            nav = assistant.last_navigation_state
            print(f"[NAVIGATOR'S HIDDEN THOUGHTS]")
            print(f"   Status:    {nav.get('status', 'N/A')}")
            print(f"   Strategy:  {nav.get('strategy', 'N/A')}")
            print(f"   Reasoning: {nav.get('reasoning', 'N/A')}")
            if nav.get('feedback'):
                print(f"   Feedback:  {nav.get('feedback', 'N/A')}")
            if nav.get('hint'):
                print(f"   Hint:      {nav.get('hint', 'N/A')}")
            print(f"   Advance:   {nav.get('should_advance', False)}")
        else:
            print("[NAVIGATOR] (No state available)")

        # Show pathway progress
        progress = assistant.get_pathway_progress()
        if progress and not progress['is_complete']:
            print(f"\n[PATHWAY PROGRESS] Round {progress['current_round']}/{progress['total_rounds']}")
        print("-" * 60)

        messages.append({"role": "user", "content": user_input})
        messages.append({"role": "assistant", "content": full_response})

        i += 1
        first_turn = False

        # Check if pathway completed
        if not assistant.pathway_mode:
            print("\n=== Pathway Guide COMPLETED! ===")
            break


def main():
    parser = argparse.ArgumentParser(
        description="Simulate pathway-guided conversations with WonderLens data"
    )
    parser.add_argument(
        "--object", "-o",
        type=str,
        default="Dog",
        help="Object name to use for pathway (default: Dog)"
    )
    parser.add_argument(
        "--age", "-a",
        type=int,
        default=6,
        help="Child's age for tier selection (default: 6)"
    )
    parser.add_argument(
        "--list-objects", "-l",
        action="store_true",
        help="List all available objects and exit"
    )

    args = parser.parse_args()

    if args.list_objects:
        list_available_objects()
        return

    asyncio.run(simulate_conversation(args.object, args.age))


if __name__ == "__main__":
    main()
