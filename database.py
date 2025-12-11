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
    
    # Create prompts table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY,
            system_prompt TEXT,
            user_prompt TEXT,
            initial_question_prompt TEXT,
            hint_prompt TEXT,
            reveal_prompt TEXT,
            state_instructions_json TEXT
        )
    ''')

    # Migrate existing prompts table if needed (add new columns)
    cursor.execute("PRAGMA table_info(prompts)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'initial_question_prompt' not in columns:
        conn.execute('ALTER TABLE prompts ADD COLUMN initial_question_prompt TEXT')
    if 'hint_prompt' not in columns:
        conn.execute('ALTER TABLE prompts ADD COLUMN hint_prompt TEXT')
    if 'reveal_prompt' not in columns:
        conn.execute('ALTER TABLE prompts ADD COLUMN reveal_prompt TEXT')
    if 'state_instructions_json' not in columns:
        conn.execute('ALTER TABLE prompts ADD COLUMN state_instructions_json TEXT')

    # Seed or update the prompts table with default values
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(id) FROM prompts WHERE id = 1")
    needs_insert = cursor.fetchone()[0] == 0

    # Check if existing row needs update (has NULL in new columns)
    if not needs_insert:
        cursor.execute("SELECT initial_question_prompt FROM prompts WHERE id = 1")
        row = cursor.fetchone()
        needs_update = row is None or row[0] is None
    else:
        needs_update = False

    if needs_insert or needs_update:
        default_system_prompt = """You are a playful learning buddy for kids aged 4–8!
Your job is to help children explore objects through fun questions.
Always sound joyful, warm, and super excited!

CRITICAL: Ask questions with SIMPLE, 1-3 WORD answers!

Good question types:
✓ "What color is it?" → "red", "yellow"
✓ "What shape is it?" → "round", "oval"
✓ "Where does it grow?" → "on trees", "underground"
✓ "What sound does it make?" → "crunch", "meow"
✓ "How does it feel?" → "soft", "rough"

Avoid complex questions:
✗ "Why does...?" (requires explanation)
✗ "How does it work?" (requires process)
✗ "What makes...?" (requires causal explanation)

STYLE:
- Short, simple, exciting sentences
- Lots of "Wow!", "Ooh!", "Amazing!"
- Always build on what the child just said
- Celebrate every answer with big cheers!

When child answers correctly:
- Big celebration: "YES! WOW! AMAZING!"
- Acknowledge what they said
- Ask the next simple question

When child says "I don't know":
- This is handled by dedicated hint system
- You will NOT see "I don't know" responses"""
        default_user_prompt = """The child wants to learn about: {object_name} (Category: {category})

REMEMBER: Ask questions with SIMPLE, 1-3 WORD answers!

Good questions about {object_name}:
✓ "What color is a {object_name}?"
✓ "What shape is a {object_name}?"
✓ "Where does a {object_name} grow/live?"
✓ "What sound does a {object_name} make?"
✓ "How does a {object_name} feel?"

Your task:
1. Ask ONE simple question about a property of {object_name}
2. Make it fun and exciting with emojis!
3. Give example answers to help them

Example question format:
"🍎 Ooh! Let's think about apples! What COLOR is an apple? Is it red? Green? Yellow? What color do YOU think?"

CRITICAL: Only ask about ONE property at a time, and it should have a SIMPLE answer!

Begin now with your first exciting question about {object_name}!
"""

        default_initial_question_prompt = """Generate an exciting first question about {object_name} for a child aged 4-8.

CRITICAL: Ask questions with SIMPLE, SINGLE-WORD answers that are easy for children!

Good question types (simple answers):
✓ "What color is a {object_name}?" (answer: "red", "yellow", etc.)
✓ "What shape is a {object_name}?" (answer: "round", "oval", etc.)
✓ "Where does a {object_name} grow?" (answer: "on trees", "underground", etc.)
✓ "What sound does a {object_name} make?" (answer: "crunch", "squeak", etc.)

Avoid complex questions (multiple answers or explanations):
✗ "Why does it...?" (requires explanation)
✗ "How does it...?" (requires process explanation)
✗ "What makes it...?" (requires causal explanation)

You MUST respond in this JSON format:
{{
  "main_question": "The core question you're asking (simple, clear, one sentence)",
  "expected_answer": "ONE SIMPLE answer (1-3 words max - like 'red', 'round', 'on trees')",
  "full_response": "Your full decorated response with emojis, context, examples - ENDING WITH THE QUESTION"
}}

Example:
{{
  "main_question": "What color is an apple?",
  "expected_answer": "red",
  "full_response": "🍎 WOW! Apples are amazing! They come in so many colors! What color do YOU think an apple is? Red? Green? Yellow?"
}}

CRITICAL RULES for full_response:
✗ DO NOT answer your own question (no "YES! Red!")
✗ DO NOT celebrate yet (no "WOW! AMAZING!" at the end)
✓ DO end with the question
✓ DO give example answers to help them (like "Red? Green? Yellow?")
✓ DO wait for the child to respond before celebrating

The main_question should ask about ONE SIMPLE property (color, shape, location, sound, texture).
The expected_answer should be 1-3 words max.
The full_response should ONLY ask the question, NOT answer it!"""

        default_hint_prompt = """The child is stuck on this question:
Original question: "{original_question}"
The answer we're looking for: "{answer}"

Your task: Ask a DIFFERENT, easier question that has the SAME answer "{answer}".

The new question should be {difficulty_instruction}.

EXAMPLES of good hint questions:
- Original: "What color is an apple?" (answer: red) → Hint: "What color is a fire truck?" ✓
- Original: "Where do apples grow?" (answer: on trees) → Hint: "Where do birds like to make their nests?" ✓
- Original: "What shape is a ball?" (answer: round) → Hint: "What shape is the sun in the sky?" ✓

FORMAT your response as:
1. Brief encouragement: "That's okay! Let me help you think..."
2. Your DIFFERENT, easier question
3. Optional: A tiny hint like "Think about things you see every day..."

Keep it very short (2-3 sentences) and playful!"""

        default_reveal_prompt = """The child was asked: "{last_question}"
They said "I don't know" 3 times.

Your task:
1. Say "That's okay! Let me tell you..."
2. Give them the answer in an exciting, positive way (1 sentence)
3. Immediately ask a NEW question about a different aspect of the object

Keep it short (2-3 sentences total). Be cheerful and move forward!"""

        default_state_instructions = json.dumps({
            "base_format": """
You must respond in this EXACT JSON format:
{
  "reaction": "Your immediate reaction to what the child said (celebration/encouragement)",
  "next_question": "Your next question to continue learning",
  "main_question": "The PRIMARY question you're asking (simple, one sentence - NOT rhetorical examples)",
  "expected_answer": "The answer you're looking for (1-3 words max)",
  "is_correct": "Whether the child's answer is similar to your expected answer." (True or False)
}

CRITICAL: Ask questions with SIMPLE, SINGLE answers!

Good question types (simple answers):
✓ "What color...?" (answer: "red", "yellow")
✓ "What shape...?" (answer: "round", "oval")
✓ "Where does...?" (answer: "on trees", "underground")
✓ "What sound...?" (answer: "crunch", "meow")
✓ "How does it feel?" (answer: "soft", "rough")

Avoid complex questions:
✗ "Why does...?" (requires explanation)
✗ "How does...?" (requires process)
✗ "What makes...?" (requires causal chain)

IMPORTANT about main_question:
- Ask about ONE SIMPLE property (color, shape, location, sound, texture)
- NOT rhetorical examples like "Is it red? Blue?"
- Example: "What color is an apple?" NOT "Why is an apple red?"

IMPORTANT about expected_answer:
- Must be 1-3 words MAXIMUM
- One clear, simple answer
- Examples: "red", "on trees", "round", "crunch", "soft"
- NOT complex: "because it has pigments" ✗

IMPORTANT about is_correct:
- Set to true ONLY if the child's answer is correct or mostly correct
- Set to false if: answer is wrong or you're correcting them
""",
            "initial_question": "🎯 STATE: Initial question - Just ask your exciting first question.",
            "awaiting_answer": """🎯 STATE: Awaiting answer - The child just answered.
- Evaluate if their answer is correct or not (set is_correct accordingly)
- Respond with celebration if correct, or gentle correction if wrong
- Ask your next question to continue learning""",
            "celebrating": """🎯 STATE: CELEBRATING - Child figured it out or gave a good answer!
- Big celebration! "YES! WOW! AMAZING!"
- Acknowledge what they said specifically
- Immediately ask the next exciting question about a different aspect of the object"""
        })

        conn.execute('''
            INSERT OR REPLACE INTO prompts (id, system_prompt, user_prompt, initial_question_prompt, hint_prompt, reveal_prompt, state_instructions_json)
            VALUES (1, ?, ?, ?, ?, ?, ?)
        ''', (default_system_prompt, default_user_prompt, default_initial_question_prompt, default_hint_prompt, default_reveal_prompt, default_state_instructions))

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

    conn.execute('''
        INSERT OR REPLACE INTO sessions (id, current_object, current_category, conversation_history, state, stuck_count, question_count, correct_count, last_modified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (session_id, assistant.current_object, assistant.current_category, history_json, state_value, stuck_count, question_count, correct_count))

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


def get_prompts():
    """Retrieves the current production prompts from the database."""
    conn = get_db_connection()
    prompts_row = conn.execute('''
        SELECT system_prompt, user_prompt, initial_question_prompt, hint_prompt, reveal_prompt, state_instructions_json
        FROM prompts WHERE id = 1
    ''').fetchone()
    conn.close()

    if prompts_row is None:
        return None

    return {
        'system_prompt': prompts_row['system_prompt'],
        'user_prompt': prompts_row['user_prompt'],
        'initial_question_prompt': prompts_row['initial_question_prompt'],
        'hint_prompt': prompts_row['hint_prompt'],
        'reveal_prompt': prompts_row['reveal_prompt'],
        'state_instructions_json': prompts_row['state_instructions_json']
    }


def update_prompts(system_prompt=None, user_prompt=None, initial_question_prompt=None,
                   hint_prompt=None, reveal_prompt=None, state_instructions_json=None):
    """Updates the production prompts in the database. Only updates provided fields."""
    conn = get_db_connection()

    # Get current prompts
    current = conn.execute('SELECT * FROM prompts WHERE id = 1').fetchone()

    # Update only provided fields
    system_prompt = system_prompt if system_prompt is not None else current['system_prompt']
    user_prompt = user_prompt if user_prompt is not None else current['user_prompt']
    initial_question_prompt = initial_question_prompt if initial_question_prompt is not None else current['initial_question_prompt']
    hint_prompt = hint_prompt if hint_prompt is not None else current['hint_prompt']
    reveal_prompt = reveal_prompt if reveal_prompt is not None else current['reveal_prompt']
    state_instructions_json = state_instructions_json if state_instructions_json is not None else current['state_instructions_json']

    conn.execute('''
        INSERT OR REPLACE INTO prompts (id, system_prompt, user_prompt, initial_question_prompt, hint_prompt, reveal_prompt, state_instructions_json)
        VALUES (1, ?, ?, ?, ?, ?, ?)
    ''', (system_prompt, user_prompt, initial_question_prompt, hint_prompt, reveal_prompt, state_instructions_json))
    conn.commit()
    conn.close()
