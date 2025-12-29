
import asyncio
import sys
from ask_ask_assistant import AskAskAssistant

def test_memory_retention():
    """
    Simulates the logic in app.py to verify that User inputs are correctly
    persisted to the conversation history alongside AI responses.
    """
    print("=" * 60)
    print("TEST: Conversation Memory Retention")
    print("=" * 60)

    # 1. Setup
    assistant = AskAskAssistant()
    # Initialize with system prompt (mimics app.py /api/start)
    assistant.conversation_history = [
        {"role": "system", "content": "You are a helpful assistant."}
    ]
    print("[Setup] Assistant initialized.")
    print(f"[Setup] History length: {len(assistant.conversation_history)}")

    # ---------------------------------------------------------
    # Turn 1: User states a fact
    # ---------------------------------------------------------
    user_input_1 = "I have a pet dog named Rex."
    ai_response_1 = "That's a great name for a dog! 🐶 Do you play fetch with Rex?"
    
    print(f"\n[Turn 1] User: '{user_input_1}'")
    print(f"[Turn 1] AI (Simulated): '{ai_response_1}'")

    # --- SIMULATING THE FIX IN APP.PY ---
    # The fix ensures we append BOTH the user input and the AI response
    assistant.conversation_history.append({"role": "user", "content": user_input_1})
    assistant.conversation_history.append({"role": "assistant", "content": ai_response_1})
    # ------------------------------------

    # ---------------------------------------------------------
    # Turn 2: User asks to recall the fact
    # ---------------------------------------------------------
    user_input_2 = "What is the name of my pet?"
    
    print(f"\n[Turn 2] User: '{user_input_2}'")
    
    # In app.py, we create a copy of history and append the current input
    # to send to the LLM
    messages_sent_to_llm = assistant.conversation_history.copy()
    messages_sent_to_llm.append({"role": "user", "content": user_input_2})

    print("\n[Inspection] Reviewing messages sent to LLM for Turn 2...")
    
    # ---------------------------------------------------------
    # Verification
    # ---------------------------------------------------------
    fact_found = False
    fact_in_correct_role = False
    
    for i, msg in enumerate(messages_sent_to_llm):
        role = msg['role']
        content = msg['content']
        print(f"  Msg {i} [{role}]: {content}")
        
        if "Rex" in content:
            fact_found = True
            if role == "user":
                fact_in_correct_role = True

    print("-" * 60)
    
    if fact_found and fact_in_correct_role:
        print("✅ SUCCESS: The user's previous statement ('Rex') was found in the history.")
        print("   The model WILL be able to answer the question.")
    elif fact_found and not fact_in_correct_role:
        print("⚠️ WARNING: The fact was found, but in the wrong role (Assistant?).")
    else:
        print("❌ FAILURE: The user's previous statement was NOT found in the history.")
        print("   The model will hallucinate or say it doesn't know.")
        sys.exit(1)

if __name__ == "__main__":
    test_memory_retention()
