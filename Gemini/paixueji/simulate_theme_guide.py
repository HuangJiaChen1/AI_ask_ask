"""
Simulation test for Theme Guide feature.
"""
import asyncio
import os
import json
from google import genai
from loguru import logger
from paixueji_assistant import PaixuejiAssistant
from stream.main import call_paixueji_stream

async def simulate_conversation():
    # Setup assistant
    assistant = PaixuejiAssistant()
    assistant.age = 6
    assistant.object_name = "Daffodils"
    assistant.character = "teacher"
    
    # Enable Theme Guide
    # Ensure you have 'seasons' in themes.json or use a valid ID
    if not assistant.start_theme_guide("indoor_activities"):
        print("Error: Theme 'seasons' not found in themes.json")
        return
    
    config = assistant.config
    
    client = assistant.client
    
    # Initialize with System Prompt (Critical for consistent persona)
    messages = [
        {"role": "system", "content": assistant.prompts['system_prompt']}
    ]
    
    print(f"\n=== THEME GUIDE SIMULATION: {assistant.target_theme['name']} ===\n")
    print(f"Goal Description: {assistant.target_theme.get('description', 'N/A')}")
    print(f"Starting with object: {assistant.object_name}\n")
    print("(Type 'exit' or 'quit' to stop the simulation)\n")

    user_input = f"Start conversation about {assistant.object_name}"
    first_turn = True
    i = 0
    
    while True:
        if not first_turn:
            try:
                user_input = input("USER: ")
                if user_input.lower() in ["exit", "quit", "q"]:
                    break
                if not user_input.strip():
                    continue
            except EOFError:
                break
        else:
            print(f"[System] Triggering start with: {user_input}")

        print("AI: ", end="", flush=True)
        full_response = ""
        
        async for chunk in call_paixueji_stream(
            age=6,
            messages=messages,
            content=user_input,
            status="normal",
            session_id="sim_session",
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
        print("-" * 50)
        if hasattr(assistant, 'last_navigation_state') and assistant.last_navigation_state:
            nav = assistant.last_navigation_state
            print(f"🧠 [NAVIGATOR'S HIDDEN THOUGHTS]")
            print(f"   Status:    {nav.get('status', 'N/A')}")
            print(f"   Strategy:  {nav.get('strategy', 'N/A')}")
            print(f"   Reasoning: {nav.get('reasoning', 'N/A')}")
            print(f"   Instruct:  {nav.get('instruction', 'N/A')}")
        else:
            print("🧠 [NAVIGATOR] (No state available)")
        print("-" * 50)
        # ---------------------------------------------
        
        messages.append({"role": "assistant", "content": full_response})
        
        i += 1
        first_turn = False
        
        if not assistant.guide_mode:
            print("\nTheme Guide COMPLETED!")
            break

if __name__ == "__main__":
    asyncio.run(simulate_conversation())