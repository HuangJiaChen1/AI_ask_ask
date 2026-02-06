"""
Test script for IB PYP Theme Guide Flow.
Simulates the transition from normal conversation to Theme Guide.
"""
import asyncio
import logging
from paixueji_assistant import PaixuejiAssistant
from graph import paixueji_graph

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_guide_flow():
    print("=" * 70)
    print("TEST: IB PYP Theme Guide Flow")
    print("=" * 70)

    # 1. Setup Assistant with Pre-classified Theme Info
    assistant = PaixuejiAssistant()
    
    # Simulate background classification result
    assistant.ibpyp_theme = "Category_Nature_And_Physics"
    assistant.ibpyp_theme_name = "How the World Works"
    assistant.key_concept = "Function"
    assistant.bridge_question = "How do these wheels help the bike move?"
    
    print("[SETUP] Assistant classified object: Bike -> How the World Works (Function)")
    
    # 2. Simulate Turn 4 (Trigger Turn)
    # User answers correctly, bringing count from 3 -> 4
    print("\n[STEP 1] User answers 4th question correctly...")
    
    # Mock Client
    class MockResponse:
        def __init__(self, text):
            self.text = text

    class MockModels:
        def generate_content(self, model, contents, config=None):
            # Check content to determine response
            if "CONFIRM" in contents: # It's the intent check prompt
                return MockResponse('{"intent": "CONFIRM"}')
            return MockResponse('{}')

    class MockClient:
        def __init__(self):
            self.models = MockModels()

    mock_client = MockClient()

    # Mock loop for async generator
    initial_state = {
        "messages": [],
        "content": "It has wheels!",
        "session_id": "test_session",
        "assistant": assistant,
        "object_name": "Bike",
        
        # Critical state for triggering
        "correct_answer_count": 3, # Will become 4
        "is_factually_correct": True, # Current answer is correct
        
        # Required fields default
        "age": 6,
        "request_id": "req_1",
        "config": {"model_name": "mock-model"}, # Mock config
        "client": mock_client, # Mock client
        "validation_result": {"is_factually_correct": True}, # Simulating validation success
        
        # Mock other fields to avoid validation errors
        "age_prompt": "", "character_prompt": "", "category_prompt": "", "focus_prompt": "",
        "level1_category": "transport", "level2_category": "", "level3_category": "",
        "status": "normal",
        "focus_mode": "depth"
    }

    # Run graph for Turn 1
    # We expect it to route to 'start_guide' instead of 'generate_question'
    print("  Running graph...")
    final_state = await paixueji_graph.ainvoke(initial_state)
    
    # CHECK 1: Did we enter guide phase?
    guide_phase = final_state.get("guide_phase")
    question = final_state.get("full_question_text") or final_state.get("bridge_question")
    
    if guide_phase == "bridge":
        print(f"  [PASS] Entered Guide Phase: 'bridge'")
        print(f"  [PASS] Bridge Question: {question}")
    else:
        print(f"  [FAIL] Did not enter guide phase. Phase: {guide_phase}")
        return

    # 3. Simulate Turn 5 (Commit Turn)
    # User responds to bridge question
    print("\n[STEP 2] User responds to bridge question ('Because they roll')...")
    
    turn_2_state = {
        **initial_state,
        "guide_phase": "bridge", # Carry over
        "content": "Because they roll on the ground", # User input
        "correct_answer_count": 4, # Updated count
    }
    
    print("  Running graph...")
    final_state_2 = await paixueji_graph.ainvoke(turn_2_state)
    
    # CHECK 2: Did we succeed?
    is_success = final_state_2.get("is_guide_success")
    
    if is_success:
        print(f"  [PASS] Guide Success! User intent confirmed.")
    else:
        print(f"  [FAIL] Guide Failed. State: {final_state_2}")

if __name__ == "__main__":
    asyncio.run(test_guide_flow())
