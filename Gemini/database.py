import sqlite3
import json
from child_learning_assistant import ChildLearningAssistant

DATABASE_NAME = 'sessions.db'


def get_db_connection():
    """Establishes and returns a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create sessions table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            current_object TEXT,
            current_category TEXT,
            conversation_history TEXT,
            state TEXT DEFAULT 'initial',
            stuck_count INTEGER DEFAULT 0,
            question_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            current_main_question TEXT,
            expected_answer TEXT,
            question_before_hint TEXT,
            answer_before_hint TEXT,
            last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Migrate existing sessions table if needed (add new columns)
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'state' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN state TEXT DEFAULT "initial"')
    if 'stuck_count' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN stuck_count INTEGER DEFAULT 0')
    if 'question_count' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN question_count INTEGER DEFAULT 0')
    if 'correct_count' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN correct_count INTEGER DEFAULT 0')
    if 'current_main_question' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN current_main_question TEXT')
    if 'expected_answer' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN expected_answer TEXT')
    if 'question_before_hint' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN question_before_hint TEXT')
    if 'answer_before_hint' not in columns:
        conn.execute('ALTER TABLE sessions ADD COLUMN answer_before_hint TEXT')

    conn.commit()
    conn.close()


def load_session(session_id):
    """Loads a single session from the database and returns a ChildLearningAssistant object."""
    conn = get_db_connection()
    session_row = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    conn.close()

    if session_row is None:
        return None

    # Convert Row to dict for easier access
    session_data = dict(session_row)

    from child_learning_assistant import ConversationState

    assistant = ChildLearningAssistant()
    assistant.current_object = session_data['current_object']
    assistant.current_category = session_data['current_category']
    assistant.conversation_history = json.loads(session_data['conversation_history'])

    # Restore state machine values
    state_value = session_data.get('state', 'initial')
    assistant.state = ConversationState(state_value) if state_value else ConversationState.INITIAL_QUESTION
    assistant.stuck_count = session_data.get('stuck_count', 0) or 0
    assistant.question_count = session_data.get('question_count', 0) or 0
    assistant.correct_count = session_data.get('correct_count', 0) or 0

    # Restore question tracking for hint system
    assistant.current_main_question = session_data.get('current_main_question')
    assistant.expected_answer = session_data.get('expected_answer')
    assistant.question_before_hint = session_data.get('question_before_hint')
    assistant.answer_before_hint = session_data.get('answer_before_hint')

    return assistant


def save_session(session_id, assistant):
    """Saves a session to the database (inserts or updates)."""
    conn = get_db_connection()
    history_json = json.dumps(assistant.get_conversation_history())

    # Get state value (enum to string)
    state_value = assistant.state.value if hasattr(assistant, 'state') else 'initial'
    stuck_count = getattr(assistant, 'stuck_count', 0)
    question_count = getattr(assistant, 'question_count', 0)
    correct_count = getattr(assistant, 'correct_count', 0)

    # Get question tracking fields for hint system
    current_main_question = getattr(assistant, 'current_main_question', None)
    expected_answer = getattr(assistant, 'expected_answer', None)
    question_before_hint = getattr(assistant, 'question_before_hint', None)
    answer_before_hint = getattr(assistant, 'answer_before_hint', None)

    conn.execute('''
        INSERT OR REPLACE INTO sessions (
            id, current_object, current_category, conversation_history,
            state, stuck_count, question_count, correct_count,
            current_main_question, expected_answer, question_before_hint, answer_before_hint,
            last_modified
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (session_id, assistant.current_object, assistant.current_category, history_json,
          state_value, stuck_count, question_count, correct_count,
          current_main_question, expected_answer, question_before_hint, answer_before_hint))

    conn.commit()
    conn.close()


def delete_session(session_id):
    """Deletes a session from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
    conn.commit()
    deleted_rows = cursor.rowcount
    conn.close()
    return deleted_rows > 0


def list_all_sessions():
    """Lists key information for all sessions from the database."""
    conn = get_db_connection()
    sessions_raw = conn.execute('SELECT id, current_object, current_category FROM sessions ORDER BY last_modified DESC').fetchall()
    conn.close()
    return [dict(row) for row in sessions_raw]
