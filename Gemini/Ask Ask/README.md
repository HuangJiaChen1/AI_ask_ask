# Ask Ask - Curiosity-Driven Learning Assistant

A conversational learning assistant where **children ask questions** and the LLM provides age-appropriate answers with follow-up questions to keep the conversation engaging.

## Overview

Unlike the main Child Learning Assistant (where the assistant asks questions about objects), **Ask Ask** reverses the dynamic:

1. **LLM starts with introduction** - Greets the child and invites them to ask any question
2. **Child asks questions** - About anything they're curious about (not limited to objects)
3. **LLM answers** - Provides age-appropriate answers based on the child's age
4. **LLM expands** - Adds a fun fact and asks a related follow-up question to continue learning
5. **Conversation flows naturally** - Child can keep asking questions or follow the LLM's prompts

## Key Features

- **Age-Adaptive Responses**: Uses the same age-based prompting system (3-4, 5-6, 7-8) to adjust vocabulary and explanation depth
- **Free-Flowing Conversation**: No mastery tracking or scoring - just pure curiosity-driven learning
- **Stuck Detection**: When child doesn't know what to ask, LLM suggests interesting topics
- **Text-Based**: Clean text interface (emojis included in responses but handled gracefully on all platforms)

## Architecture

### Core Components

**1. AskAskAssistant** (`ask_ask_assistant.py`)
- Main conversation engine
- Simplified state machine:
  - `INTRODUCTION`: Initial greeting
  - `AWAITING_QUESTION`: Waiting for child's question
  - `ANSWERING`: Answering child's question
  - `SUGGESTING_TOPICS`: Suggesting topics when child is stuck

**2. Prompts** (`ask_ask_prompts.py`)
- `SYSTEM_PROMPT`: Defines assistant personality and behavior
- `INTRODUCTION_PROMPT`: Generates the opening greeting
- `ANSWER_QUESTION_PROMPT`: Structures answers with follow-up questions
- `SUGGEST_TOPICS_PROMPT`: Provides topic suggestions when child is stuck

**3. Demo** (`demo.py`)
- Interactive CLI for testing
- Supports age input (3-8) for age-appropriate responses
- Restart and quit commands

### Conversation Flow

```
┌─────────────────────────────────────────────┐
│  1. Demo starts                             │
│     - User enters child's age (optional)    │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  2. LLM introduces itself                   │
│     - Warm greeting                         │
│     - Invites child to ask anything         │
│     - Gives example topics                  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  3. Child asks a question                   │
│     (or says "I don't know")                │
└──────────────────┬──────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
         ▼                   ▼
┌──────────────┐    ┌──────────────────┐
│ Child stuck? │    │ Child has        │
│              │    │ question?        │
└──────┬───────┘    └────────┬─────────┘
       │                     │
       ▼                     ▼
┌──────────────┐    ┌──────────────────┐
│ Suggest      │    │ Answer question  │
│ topics       │    │ + fun fact       │
│              │    │ + follow-up      │
└──────┬───────┘    └────────┬─────────┘
       │                     │
       └──────────┬──────────┘
                  │
                  ▼
         ┌─────────────────┐
         │ Loop continues  │
         └─────────────────┘
```

## Differences from Main System

| Feature | Main Child Learning Assistant | Ask Ask |
|---------|------------------------------|---------|
| **Who asks questions?** | LLM asks, child answers | Child asks, LLM answers |
| **Topic scope** | Specific objects/categories | Any topic child is curious about |
| **Mastery tracking** | Tracks correct answers, celebrates mastery | No tracking, free-flowing |
| **Stuck handling** | Progressive hints (hint1 → hint2 → reveal) | Topic suggestions |
| **State machine** | 7 states with hint system | 4 simple states |
| **Conversation start** | Requires object name + category | Just age (optional) |

## Usage

### Running the Demo

```bash
cd "Ask Ask"
python demo.py
```

**Demo Flow:**
1. Enter child's age (3-8) or press Enter to skip
2. LLM introduces itself and invites questions
3. Type your questions as the child would ask them
4. Type `restart` to begin a new session
5. Type `quit` to exit

### Example Session

```
Enter child's age (3-8, or press Enter to skip): 6

🤖 Assistant: Hello, super scientist! 🌟 You can ask me anything
you're wondering about! Maybe how a caterpillar turns into a
butterfly 🦋 or how a big truck works? 🚛 What's the first big
question on your mind?

Your question (or 'restart'/'quit'): Why is the sky blue?

🤖 Assistant: Wow, what a super smart question! ☀️ The sky looks
blue because the sun's light, which has all the colors of the
rainbow in it, shines through our air. The air grabs the blue
color and scatters it all around for us to see! 🌈 A fun fact is
that when the sun is setting, we get to see the other colors,
like red and orange, making a beautiful sunset! 🌅 What do you
think happens to the color of the sky when it gets dark at night?

Your question (or 'restart'/'quit'): How do birds fly?
...
```

## Configuration

Uses the same `config.json` as the main system:
- `gemini_api_key`: Your Gemini API key
- `model_name`: "gemini-2.5-pro"
- `api_base_url`: Gemini API endpoint
- `temperature`: 0.7
- `max_tokens`: 2000

## Age-Based Prompting

The system uses `age_prompts.json` to adjust responses:

- **Age 3-4**: Simple vocabulary, short answers, concrete examples
- **Age 5-6**: Medium complexity, introduce processes and actions
- **Age 7-8**: Advanced vocabulary, deeper explanations, encourage reasoning

## Implementation Notes

### Stuck Detection

The system detects when a child is stuck using:
- **Question detection**: If input starts with "why/what/how" or ends with "?", it's a question
- **Stuck phrases**: "I don't know", "dunno", "help me", etc.
- **Single-word stuck**: Short responses like "huh", "what" (without context)

If child is stuck → LLM suggests 2-3 interesting topics to explore

### Encoding Handling

The code includes `safe_print()` function to handle emoji encoding issues on Windows:
- Tries to print normally
- Falls back to ASCII with replacement if Unicode encoding fails
- Ensures demo works on all platforms

### JSON Response Structure

**Introduction:**
```json
{
  "introduction": "Greeting with emojis and invitation",
  "audio_output": "Same text without emojis for TTS"
}
```

**Answer:**
```json
{
  "answer": "Age-appropriate answer to question",
  "fun_fact": "Interesting related detail",
  "follow_up_question": "Related question to continue",
  "full_response": "Complete response with emojis",
  "audio_output": "Full response without emojis"
}
```

**Topic Suggestions:**
```json
{
  "encouragement": "Encouraging message",
  "topic_suggestions": "2-3 topic ideas",
  "full_response": "Complete response with emojis",
  "audio_output": "Full response without emojis"
}
```

## Files

- `ask_ask_assistant.py` - Main conversation engine
- `ask_ask_prompts.py` - Prompt templates
- `demo.py` - Interactive CLI demo
- `config.json` - API configuration (copied from parent)
- `age_prompts.json` - Age-based prompting rules (copied from parent)
- `README.md` - This file

## Future Enhancements

Potential improvements:
- Add conversation history persistence (SQLite database)
- Implement Flask API for web/mobile integration
- Add TTS (text-to-speech) support using `audio_output` field
- Track question quality/curiosity metrics (without mastery scoring)
- Support multi-turn question clarification
- Add topic categories for better follow-up suggestions

## Testing

The demo has been tested with:
- Age-appropriate responses for ages 3-4, 5-6, 7-8
- Question answering flow (why/what/how questions)
- Stuck detection and topic suggestions
- Emoji encoding on Windows platforms
- JSON parsing with proper escape handling

## Credits

Built as a companion to the Child Learning Assistant (Gemini version), sharing the same:
- Age-based prompting system
- Gemini API integration
- Configuration structure
- Utility functions (emoji removal, JSON extraction)
