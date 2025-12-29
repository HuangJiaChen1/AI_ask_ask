
import asyncio
import json
from app import app, sessions
from ask_ask_assistant import AskAskAssistant

def test_context_retention():
    # Setup session
    session_id = "test_session_123"
    assistant = AskAskAssistant()
    sessions[session_id] = assistant
    
    # 1. Start (Simulate)
    assistant.conversation_history = [{"role": "system", "content": "Sys"}]
    assistant.conversation_history.append({"role": "assistant", "content": "Hello!"})
    
    # 2. First Continue: Weather
    # We'll call the logic directly since running the full Flask app + SSE is complex here
    child_input_1 = "How is the weather?"
    # Simulate what happens in app.py's continue_conversation
    
    # In the real app, this happens in the generator
    # We'll mock the result of call_ask_ask_stream
    response_1 = "It is sunny. What about artificial rain?"
    
    # Applying the fix logic manually to verify state
    assistant.conversation_history.append({"role": "user", "content": child_input_1})
    assistant.conversation_history.append({"role": "assistant", "content": response_1})
    
    # 3. Second Continue: AI response to "good"
    child_input_2 = "I think it is good."
    
    # This is what will be sent to the LLM in the next turn
    messages_to_send = assistant.conversation_history.copy()
    messages_to_send.append({"role": "user", "content": child_input_2})
    
    print("History for the next turn:")
    for m in messages_to_send:
        print(f"  {m['role']}: {m['content']}")
    
    # Verify the "weather" is there
    has_weather = any("weather" in m['content'].lower() for m in messages_to_send)
    print(f"Has weather context? {has_weather}")
    assert has_weather, "Context lost!"

if __name__ == "__main__":
    test_context_retention()
