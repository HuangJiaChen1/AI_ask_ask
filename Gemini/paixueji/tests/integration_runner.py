#!/usr/bin/env python3
"""
Real-LLM integration test runner for fix-flaw verification.

Replays a conversation history through the live LangGraph pipeline and prints
the model's final response to stdout.  Used by the /fix-flaw skill's Phase 5
integration test step.

Usage:
  python tests/integration_runner.py /tmp/paixueji_integration.json

Input JSON schema:
  {
    "child_name": str,        # optional, cosmetic only
    "age": int,               # optional (3-8), defaults to None
    "object_name": str,       # required — object being discussed
    "history": [              # prior turns (role: "user" | "assistant")
      {"role": "user",      "content": "..."},
      {"role": "assistant", "content": "..."},
      ...
    ],
    "user_input": str         # the exact triggering input to test
  }

Output:
  The model's response text on stdout.
  Error messages go to stderr; exits with code 1 on failure.
"""

import asyncio
import json
import os
import sys
import time
import uuid

# Add project root to Python path so imports resolve correctly when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google import genai
from google.genai.types import HttpOptions

from graph import paixueji_graph
from paixueji_assistant import PaixuejiAssistant


# ---------------------------------------------------------------------------
# Async helpers (mirrors stream_graph_execution in paixueji_app.py)
# ---------------------------------------------------------------------------

async def _stream_graph_execution(initial_state):
    """Run the LangGraph workflow and yield StreamChunks as produced."""
    queue = asyncio.Queue()

    async def stream_callback(chunk):
        await queue.put(chunk)

    initial_state["stream_callback"] = stream_callback
    initial_state["start_time"] = time.time()

    task = asyncio.create_task(paixueji_graph.ainvoke(initial_state))

    while True:
        get_chunk = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait([get_chunk, task], return_when=asyncio.FIRST_COMPLETED)

        if get_chunk in done:
            yield get_chunk.result()

        if task in done:
            if not get_chunk.done():
                get_chunk.cancel()
                try:
                    await get_chunk
                except asyncio.CancelledError:
                    pass

            if task.exception():
                raise task.exception()

            while not queue.empty():
                yield await queue.get()

            break


async def _run_turn(assistant, user_input, session_id, request_id):
    """Drive one conversation turn through the graph; return the final response text."""
    age_prompt = assistant.get_age_prompt(assistant.age) if assistant.age else ""
    category_prompt = assistant.get_category_prompt(
        assistant.level1_category,
        assistant.level2_category,
        assistant.level3_category,
    )

    current_messages = assistant.conversation_history.copy()
    current_messages.append({"role": "user", "content": user_input})

    initial_state = {
        "age": assistant.age,
        "messages": current_messages,
        "content": user_input,
        "status": "normal",
        "session_id": session_id,
        "request_id": request_id,
        "config": assistant.config,
        "client": assistant.client,
        "assistant": assistant,
        "age_prompt": age_prompt,
        "object_name": assistant.object_name,
        "level1_category": assistant.level1_category,
        "level2_category": assistant.level2_category,
        "level3_category": assistant.level3_category,
        "correct_answer_count": assistant.correct_answer_count,
        "category_prompt": category_prompt,
        # Initialise output fields required by PaixuejiState
        "full_response_text": "",
        "full_question_text": "",
        "sequence_number": 0,
        "intent_type": None,
        "new_object_name": None,
        "detected_object_name": None,
        "response_type": None,
        "fun_fact": "",
        "fun_fact_hook": "",
        "fun_fact_question": "",
        "real_facts": "",
        "nodes_executed": [],
        "_input_state_snapshot": {
            "object_name": assistant.object_name,
            "age": assistant.age,
            "correct_answer_count": assistant.correct_answer_count,
            "content": user_input,
            "conversation_state": assistant.state.value,
            "guide_phase": assistant.guide_phase,
            "guide_turn_count": assistant.guide_turn_count,
            "scaffold_level": assistant.scaffold_level,
            "hint_given": assistant.hint_given,
            "ibpyp_theme_name": assistant.ibpyp_theme_name,
            "key_concept": assistant.key_concept,
            "level1_category": assistant.level1_category,
            "level2_category": assistant.level2_category,
            "level3_category": assistant.level3_category,
        },
    }

    final_response = ""
    async for chunk in _stream_graph_execution(initial_state):
        if chunk.finish:
            final_response = chunk.response
            # Mirror paixueji_app.py: update conversation_history on completion
            assistant.conversation_history.append({"role": "user", "content": user_input})
            assistant.conversation_history.append({
                "role": "assistant",
                "content": chunk.response,
                "nodes_executed": chunk.nodes_executed or [],
                "mode": "guide" if chunk.guide_phase else "chat",
            })

    return final_response


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python tests/integration_runner.py <input.json>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]

    # Require Vertex AI credentials
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print(
            "ERROR: GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.\n"
            "Run:   export GOOGLE_APPLICATION_CREDENTIALS='path/to/credentials.json'",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load input JSON
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"ERROR: Cannot read input file '{input_path}': {exc}", file=sys.stderr)
        sys.exit(1)

    object_name = data.get("object_name", "apple")
    user_input = data.get("user_input")
    if not user_input:
        print("ERROR: 'user_input' field is required in the input JSON.", file=sys.stderr)
        sys.exit(1)

    age = data.get("age")
    if age is not None:
        try:
            age = int(age)
        except (ValueError, TypeError):
            age = None

    history = data.get("history", [])

    # Load config.json (project root, one level above tests/)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except Exception as exc:
        print(f"ERROR: Cannot read config.json: {exc}", file=sys.stderr)
        sys.exit(1)

    # Build real Gemini client (no mocking)
    client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1"),
    )

    # Create assistant and set session state
    assistant = PaixuejiAssistant(client=client)
    assistant.age = age
    assistant.object_name = object_name

    # Build system prompt (same logic as paixueji_app.py start_conversation)
    system_prompt = assistant.prompts["system_prompt"]
    if age:
        age_prompt = assistant.get_age_prompt(age)
        if age_prompt:
            system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"

    # Seed conversation_history with system prompt, then replay prior turns.
    # We insert history turns directly — no graph call needed — because the graph's
    # only lasting side-effect is appending to this list.
    assistant.conversation_history = [{"role": "system", "content": system_prompt}]
    for turn in history:
        assistant.conversation_history.append({
            "role": turn["role"],
            "content": turn["content"],
        })

    # Run the triggering input through the live pipeline
    session_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    response = asyncio.run(
        _run_turn(assistant, user_input, session_id, request_id)
    )

    print(response)


if __name__ == "__main__":
    main()
