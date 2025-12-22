## Project Overview

This project is a **Child Learning Assistant**, an interactive educational chatbot designed for young children (ages 4-8). It uses the Qwen AI model via an OpenAI-compatible API to ask engaging questions about everyday objects, encouraging curiosity and learning.

The application is architected as a Python-based web service using the **Flask** framework. It maintains conversation state using a **SQLite** database (`sessions.db`), allowing for stateful, multi-turn conversations.

The core logic is encapsulated in the `ChildLearningAssistant` class, which implements a state machine to manage the flow of the conversation. This state machine adapts to the child's responses, providing hints or revealing answers if the child gets stuck. A key feature is its use of the LLM to classify user input (e.g., to detect if a child is "stuck"), making the interaction more robust and natural.

Prompts, which are crucial for guiding the AI's behavior, are stored in the database and can be updated via an API endpoint, allowing for dynamic control over the assistant's personality and questioning style.

## Building and Running

### 1. Install Dependencies

Install the required Python packages using pip:

```bash
pip install -r requirements.txt
```

### 2. Configure API Key

The application uses the Qwen AI model. You need to configure your API key in the `config.json` file.

```json
{
  "qwen_api_key": "YOUR_QWEN_API_KEY",
  "model_name": "qwen-plus",
  "api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "temperature": 0.7,
  "max_tokens": 1000
}
```

### 3. Running the Application

There are two ways to run the application:

**A) As an interactive command-line demo:**

```bash
python demo.py
```

**B) As a Flask web service:**

```bash
python app.py
```

This will start the API server on `http://localhost:5001`.

### 4. Running Tests

The project includes API tests that can be run as follows:

```bash
python test_api.py
```

## Development Conventions

*   **State Management**: The application's core is a state machine implemented in the `ChildLearningAssistant` class. Conversation state is persisted in a SQLite database to handle multi-turn dialogues over a stateless API.
*   **Database-Driven Prompts**: All system and user prompts are stored in the `prompts` table in the `sessions.db` SQLite database. This allows for easy modification of the assistant's behavior without code changes. The `database.init_db()` function seeds the initial prompts.
*   **Structured AI Responses**: The system is designed to work with an AI model that can return structured JSON, which includes fields like `main_question`, `expected_answer`, `is_correct`, etc. This makes the logic for handling responses more reliable.
*   **Modular Design**: The project is well-structured, with distinct modules for the Flask application (`app.py`), core assistant logic (`child_learning_assistant.py`), and database interaction (`database.py`).
*   **API**: The application exposes a RESTful API for integration with web or mobile frontends. Key endpoints include `/api/start`, `/api/continue`, and `/api/history`. See `API_DOCUMENTATION.md` for more details.
