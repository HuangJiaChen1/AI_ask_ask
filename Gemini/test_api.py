"""
Test script for the Child Learning Assistant API (Gemini Version)
Demonstrates how to interact with the Flask web service
"""

import requests
import json

BASE_URL = 'http://localhost:5000'


def test_health_check():
    """Test the health check endpoint"""
    print("\n" + "=" * 60)
    print("Testing Health Check")
    print("=" * 60)

    response = requests.get(f'{BASE_URL}/api/health')
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200


def test_start_conversation(object_name, category):
    """Test starting a new conversation"""
    print("\n" + "=" * 60)
    print(f"Starting Conversation: {object_name} ({category})")
    print("=" * 60)

    response = requests.post(f'{BASE_URL}/api/start', json={
        'object_name': object_name,
        'category': category
    })

    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")

    if data.get('success'):
        print(f"\n🤖 Curious Fox: {data['response']}")
        return data['session_id']
    else:
        print(f"\n❌ Error: {data.get('error')}")
        return None


def test_continue_conversation(session_id, child_response):
    """Test continuing a conversation"""
    print("\n" + "=" * 60)
    print(f"Continuing Conversation")
    print("=" * 60)
    print(f"👦 Child says: {child_response}")

    response = requests.post(f'{BASE_URL}/api/continue', json={
        'session_id': session_id,
        'child_response': child_response
    })

    print(f"Status Code: {response.status_code}")
    data = response.json()

    if data.get('success'):
        print(f"\n🤖 Curious Fox: {data['response']}")
        return True
    else:
        print(f"\n❌ Error: {data.get('error')}")
        return False


def test_get_history(session_id):
    """Test getting conversation history"""
    print("\n" + "=" * 60)
    print("Getting Conversation History")
    print("=" * 60)

    response = requests.get(f'{BASE_URL}/api/history/{session_id}')
    print(f"Status Code: {response.status_code}")
    data = response.json()

    if data.get('success'):
        print(f"Object: {data['object']}")
        print(f"Category: {data['category']}")
        print(f"Total messages: {len(data['history'])}")
        return True
    else:
        print(f"❌ Error: {data.get('error')}")
        return False


def test_list_sessions():
    """Test listing all active sessions"""
    print("\n" + "=" * 60)
    print("Listing Active Sessions")
    print("=" * 60)

    response = requests.get(f'{BASE_URL}/api/sessions')
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")
    return data.get('success', False)


def test_reset_session(session_id):
    """Test resetting a session"""
    print("\n" + "=" * 60)
    print("Resetting Session")
    print("=" * 60)

    response = requests.post(f'{BASE_URL}/api/reset', json={
        'session_id': session_id
    })

    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")
    return data.get('success', False)


def run_full_conversation_test():
    """Run a complete conversation flow"""
    print("\n" + "🌟" * 30)
    print("FULL CONVERSATION TEST (Gemini)")
    print("🌟" * 30)

    # 1. Health check
    if not test_health_check():
        print("❌ Health check failed. Is the server running?")
        return

    # 2. Start conversation
    session_id = test_start_conversation("Apple", "Fruit")
    if not session_id:
        print("❌ Failed to start conversation")
        return

    # 3. Continue conversation multiple times
    responses = [
        "I don't know",
        "Red and green",
        "On trees?",
        "We can eat it!",
        "No, tell me!"
    ]

    for child_response in responses:
        if not test_continue_conversation(session_id, child_response):
            print("❌ Conversation failed")
            break
        print("\n" + "-" * 60)

    # 4. Get history
    test_get_history(session_id)

    # 5. List sessions
    test_list_sessions()

    # 6. Reset session
    test_reset_session(session_id)

    print("\n" + "🌟" * 30)
    print("TEST COMPLETED")
    print("🌟" * 30)


if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║   Child Learning Assistant - API Test Suite (Gemini)    ║
    ║                                                          ║
    ║   Make sure the Flask server is running:                ║
    ║   python app.py                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    try:
        run_full_conversation_test()
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to the server.")
        print("Make sure the Flask server is running on http://localhost:5000")
        print("Run: python app.py")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
