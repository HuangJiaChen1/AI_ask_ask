"""
Quick test to verify the state machine logic without requiring API calls (Gemini Version)
"""
from child_learning_assistant import ConversationState

def test_state_machine():
    """Test the state machine transitions"""
    print("=" * 60)
    print("Testing State Machine Logic (Gemini)")
    print("=" * 60)

    # Test 1: Initial state
    state = ConversationState.INITIAL_QUESTION
    print(f"\n[OK] Initial state: {state.value}")
    assert state == ConversationState.INITIAL_QUESTION

    # Test 2: State values
    print("\n[OK] All state values:")
    for s in ConversationState:
        print(f"  - {s.value}")

    # Test 3: Enum comparison
    state2 = ConversationState("initial")
    print(f"\n[OK] Can recreate from value: {state2.value}")
    assert state2 == ConversationState.INITIAL_QUESTION

    print("\n" + "=" * 60)
    print("[OK] All state machine tests passed!")
    print("=" * 60)


def test_database_migration():
    """Test database migration adds new columns"""
    import database
    import os

    print("\n" + "=" * 60)
    print("Testing Database Migration (Gemini)")
    print("=" * 60)

    # Create/migrate database
    database.init_db()

    # Check if columns exist
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in cursor.fetchall()]
    conn.close()

    print(f"\n[OK] Session table columns: {columns}")

    required_columns = ['state', 'stuck_count', 'question_count', 'correct_count']
    for col in required_columns:
        if col in columns:
            print(f"  [OK] Column '{col}' exists")
        else:
            print(f"  [FAIL] Column '{col}' MISSING!")
            return False

    print("\n" + "=" * 60)
    print("[OK] Database migration successful!")
    print("=" * 60)
    return True


if __name__ == '__main__':
    try:
        test_state_machine()
        test_database_migration()

        print("\n" + "=" * 30)
        print("ALL TESTS PASSED!")
        print("=" * 30)

    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
