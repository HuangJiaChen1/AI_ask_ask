
import sys
import logging
from unittest.mock import MagicMock

# Configure logging
logging.basicConfig(level=logging.INFO)

# Mock schema and dependencies
sys.modules['schema'] = MagicMock()
sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()

# Import the function to test
# We need to mock imports inside paixueji_stream before importing it
from unittest.mock import patch

with patch('paixueji_stream.logger') as mock_logger:
    from paixueji_stream import decide_topic_switch_with_validation

# Mock Assistant
class MockAssistant:
    def __init__(self):
        self.conversation_history = [
            {"role": "assistant", "content": "Would you like to talk about Apple, Banana, or Car?"}
        ]
        self.client = MagicMock()
        self.config = {"model": "gemini-2.0-flash-exp"}

# Mock Gemini Response
def mock_gemini_response(*args, **kwargs):
    prompt = kwargs.get('contents', '')
    print(f"\n--- SENT PROMPT ---\n{prompt}\n-------------------\n")
    
    # Simulate the current behavior: I don't know -> Stuck -> CONTINUE
    return MagicMock(text='''
    {
        "decision": "CONTINUE",
        "new_object": null,
        "switching_reasoning": "Child said they don't know, so we stay on current topic.",
        "is_engaged": false,
        "is_factually_correct": false,
        "correctness_reasoning": "Child did not answer."
    }
    ''')

# Run Test
def run_test():
    assistant = MockAssistant()
    assistant.client.models.generate_content.side_effect = mock_gemini_response
    
    print("Testing 'I don't know' response to topic switch proposal...")
    result = decide_topic_switch_with_validation(
        assistant=assistant,
        child_answer="I don't know",
        object_name="PreviousObject",
        age=6,
        focus_mode="depth"
    )
    
    print("\n--- RESULT ---")
    print(result)
    
    if result['decision'] == 'CONTINUE':
        print("\n[CONFIRMED] Issue reproduced: System decided to CONTINUE on old object despite indecision on switch.")
    else:
        print("\n[FAILED] Issue not reproduced.")

if __name__ == "__main__":
    run_test()
