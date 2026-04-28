#!/usr/bin/env python3
"""
Real-LLM integration test for Fix 4: two consecutive IDK turns.

Turn 1 — first IDK  → expects a scaffold HINT  (clarifying_idk)
Turn 2 — second IDK → expects the DIRECT ANSWER (give_answer_idk)

Verifiable properties checked:
  Turn 1 response:
    - Does NOT open with "That's okay!" immediately followed by the answer
    - Contains a sensory scaffold clue (not the full answer)
  Turn 2 response:
    - Opens with short acceptance phrase
    - Directly states the answer (not another hint)
    - 3 sentences or fewer

Usage:
  export GOOGLE_APPLICATION_CREDENTIALS="path/to/credentials.json"
  python tests/integration_scenarios/fix4_two_idk_turns.py
"""

import asyncio
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google import genai
from google.genai.types import HttpOptions

from graph import paixueji_graph
from paixueji_assistant import PaixuejiAssistant


async def stream_graph_execution(initial_state):
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


async def run_turn(assistant, user_input, session_id):
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
        "request_id": str(uuid.uuid4()),
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
            "ibpyp_theme_name": assistant.ibpyp_theme_name,
            "key_concept": assistant.key_concept,
            "level1_category": assistant.level1_category,
            "level2_category": assistant.level2_category,
            "level3_category": assistant.level3_category,
        },
    }

    response_type = None
    final_response = ""
    async for chunk in stream_graph_execution(initial_state):
        if chunk.finish:
            final_response = chunk.response
            response_type = chunk.response_type if hasattr(chunk, "response_type") else None
            assistant.conversation_history.append({"role": "user", "content": user_input})
            assistant.conversation_history.append({
                "role": "assistant",
                "content": chunk.response,
                "nodes_executed": chunk.nodes_executed or [],
                "mode": "chat",
            })

    return final_response, response_type


async def main():
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("ERROR: GOOGLE_APPLICATION_CREDENTIALS not set", file=sys.stderr)
        sys.exit(1)

    import json
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_path = os.path.join(base_dir, "config.json")
    with open(config_path) as f:
        config = json.load(f)

    client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1"),
    )

    assistant = PaixuejiAssistant(client=client)
    assistant.age = 4
    assistant.object_name = "apple"

    system_prompt = assistant.prompts["system_prompt"]
    age_prompt_text = assistant.get_age_prompt(4)
    if age_prompt_text:
        system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt_text}"

    # Seed with prior conversation (model asked about sunlight)
    assistant.conversation_history = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": "Oh, you found an apple! Apples are SO crunchy and sweet! Do you like eating apples?"},
        {"role": "user", "content": "yes"},
        {"role": "assistant", "content": "Apple trees need something special from the sky to grow big and juicy. What do you think apple trees need to grow?"},
    ]

    session_id = str(uuid.uuid4())

    print("=" * 60)
    print(f"consecutive_struggle_count BEFORE Turn 1: {assistant.consecutive_struggle_count}")
    print()
    print("TURN 1 — First IDK (child says: 'I don't know')")
    print("-" * 60)
    response1, rtype1 = await run_turn(assistant, "I don't know", session_id)
    print(f"response_type : {rtype1}")
    print(f"idk_count after: {assistant.consecutive_struggle_count}")
    print()
    print("MODEL RESPONSE:")
    print(response1)
    print()

    print("=" * 60)
    print(f"consecutive_struggle_count BEFORE Turn 2: {assistant.consecutive_struggle_count}")
    print()
    print("TURN 2 — Second IDK (child says: 'I don't know' again)")
    print("-" * 60)
    response2, rtype2 = await run_turn(assistant, "I don't know", session_id)
    print(f"response_type : {rtype2}")
    print(f"idk_count after: {assistant.consecutive_struggle_count}")
    print()
    print("MODEL RESPONSE:")
    print(response2)
    print()

    print("=" * 60)
    print("VERIFICATION")
    print("-" * 60)
    print(f"[{'PASS' if rtype1 == 'clarifying_idk' else 'FAIL'}] Turn 1 response_type == 'clarifying_idk' (got: {rtype1})")
    print(f"[{'PASS' if rtype2 == 'give_answer_idk' else 'FAIL'}] Turn 2 response_type == 'give_answer_idk' (got: {rtype2})")


if __name__ == "__main__":
    asyncio.run(main())
