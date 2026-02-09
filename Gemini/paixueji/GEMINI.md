# Paixueji Educational Assistant - Gemini Context

## Project Overview

**Paixueji** ("Pat the Learner" or similar phonetic) is a Flask-based educational chatbot designed to engage children (ages 3-8) in conversations about objects. It acts as a friendly teacher/companion, asking questions to encourage observation and critical thinking.

**Key Technologies:**
*   **Backend:** Python, Flask (Sync) with `asyncio` bridge for streaming.
*   **AI:** Google Gemini API (Vertex AI / Google Gen AI SDK).
*   **Streaming:** Server-Sent Events (SSE) for real-time text delivery.
*   **Frontend:** HTML/JavaScript (served statically from `static/`).

## Getting Started

### Prerequisites
*   Python 3.8+
*   Google Cloud Platform project with Vertex AI/Gemini API enabled.
*   `GOOGLE_APPLICATION_CREDENTIALS` JSON file.

### Installation

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configuration:**
    *   Ensure `config.json` exists in the root directory (containing `project`, `location`, `model_name`, etc.).
    *   Set the environment variable for authentication:
        *   **Windows (PowerShell):** `$env:GOOGLE_APPLICATION_CREDENTIALS="path\to\credentials.json"`
        *   **Linux/Mac:** `export GOOGLE_APPLICATION_CREDENTIALS="path/to/credentials.json"`

### Running the Application

Start the Flask server:

```bash
python paixueji_app.py
```

*   The server runs on **http://localhost:5001**.
*   Access the web interface at `http://localhost:5001/`.
*   API endpoints are available at `/api/*`.

## Project Structure

*   `paixueji_app.py`: Main entry point. Initializes Flask, handles API routes (`/api/start`, `/api/continue`), and manages the `asyncio` event loop bridge.
*   `paixueji_assistant.py`: Core logic class (`PaixuejiAssistant`). Manages session state, conversation history, and prompts.
*   `paixueji_stream.py`: Handles the interaction with the Gemini API, specifically the streaming logic for questions and feedback.
*   `theme_classifier.py`: Logic for classifying objects into IB PYP themes.
*   `config.json`: Configuration settings for the AI model and project.
*   `requirements.txt`: Python dependencies.
*   `static/`: Frontend assets (HTML, CSS, JS).
*   `tests/`: Test suite (Pytest).
*   `docs/`: Documentation, including architecture diagrams (`chat_flow.mermaid`).
*   `OPERATIONAL_ARCHITECTURE.md`: **Critical** document detailing system topology, data flow, and known issues (leaks, orphans).

## Development Workflow

### Running Tests

The project uses `pytest` for testing. A `conftest.py` file is provided to mock the Gemini API client, allowing for offline testing of the flow.

```bash
pytest
```

### Architecture Notes

*   **Concurrency:** The app uses a hybrid sync/async model. Flask runs synchronously, but creates a new `asyncio` event loop for each request to handle the async Gemini streaming calls. This is bridged using `async_gen_to_sync` in `paixueji_app.py`.
*   **State Management:** Sessions are stored **in-memory** in a global `sessions` dictionary in `paixueji_app.py`. **Warning:** All session data is lost if the server restarts.
*   **Streaming:** Responses are sent using Server-Sent Events (SSE). The frontend listens for `chunk` events to display text in real-time.

### Logging

*   Uses `loguru` for structured logging.
*   Console output is used for immediate feedback.
*   Logs are stored in the `logs/` directory.

## Key Commands

| Action | Command |
| :--- | :--- |
| **Run App** | `python paixueji_app.py` |
| **Run Tests** | `pytest` |
| **Install Deps** | `pip install -r requirements.txt` |
