Refactoring "Tone" to "Character" (`Teacher` vs `Buddy`).

I will implement the following changes:

1.  **Rename & Refactor**: Replace all instances of `tone` with `character` across the codebase (Backend, Frontend, Configs).
2.  **Define Characters (`paixueji_prompts.py`)**:
    *   **Teacher**: "Educational and structured. Your goal is to guide learning by asking questions (Socratic method)."
    *   **Buddy**: "Playful and conversational. Your goal is to be a friend. Chat naturally, share fun facts, and react to the user. Do NOT feel pressured to ask a question every turn."
3.  **Logic Update (`stream/main.py`)**:
    *   Currently, the system *always* generates a "Follow-up Question" after every response.
    *   I will modify this to support a "Conversation Turn" which can be a question (Teacher) or a chat/comment (Buddy).
    *   I will update the prompts to allow the "Buddy" character to just comment or share excitement without interrogating the user.
4.  **Frontend**: Update the UI to select "Assistant Character" (Teacher/Buddy) instead of "Tone".

Ready to proceed?