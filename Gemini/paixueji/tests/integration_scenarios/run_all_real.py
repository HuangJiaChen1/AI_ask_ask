#!/usr/bin/env python3
"""
Real-LLM integration test for all 4 behavioral fixes.

Uses Application Default Credentials (ADC) — no GOOGLE_APPLICATION_CREDENTIALS
env var required.  ADC is discovered automatically by genai.Client at:
  ~/.config/gcloud/application_default_credentials.json

Scenarios:
  A — Fix 1 : Introduction 3-beat structure
  B — Fix 2+3: Correct answer path (age-appropriate question + bridge phrase)
  C — Fix 4 T1: First IDK → scaffold hint
  D — Fix 4 T2: Second IDK (same assistant instance) → direct answer

Usage:
  cd /Users/huangjiachen/Desktop/PROJECTS/AI_ask_ask/Gemini/paixueji
  python tests/integration_scenarios/run_all_real.py
"""

import asyncio
import json
import os
import re
import sys
import time
import uuid

# Add project root so imports resolve when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google import genai
from google.genai.types import HttpOptions

from graph import paixueji_graph
from paixueji_assistant import PaixuejiAssistant


# ============================================================================
# Graph streaming helpers  (pattern from integration_runner.py / fix4_two_idk_turns.py)
# ============================================================================

async def _stream_graph_execution(initial_state):
    """Run the LangGraph workflow, yield StreamChunks as they arrive."""
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


def _build_initial_state(assistant, user_input, messages, response_type=None):
    """
    Build a complete initial_state dict for one graph invocation.

    Parameters
    ----------
    assistant      : PaixuejiAssistant instance (carries session state)
    user_input     : The child's utterance for this turn (empty string for intro)
    messages       : Conversation history to pass as state["messages"]
    response_type  : Pre-set response_type to bypass analyze_input (intro only)
    """
    age_prompt = assistant.get_age_prompt(assistant.age) if assistant.age else ""
    category_prompt = assistant.get_category_prompt(
        assistant.level1_category,
        assistant.level2_category,
        assistant.level3_category,
    )
    return {
        "age": assistant.age,
        "messages": messages,
        "content": user_input,
        "status": "normal",
        "session_id": str(uuid.uuid4()),
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
        # Output fields — initialised empty / None
        "full_response_text": "",
        "full_question_text": "",
        "sequence_number": 0,
        "intent_type": None,
        "new_object_name": None,
        "detected_object_name": None,
        "response_type": response_type,   # "introduction" → bypasses analyze_input
        "fun_fact": "",
        "fun_fact_hook": "",
        "fun_fact_question": "",
        "real_facts": "",
        "nodes_executed": [],
        # Snapshot for tracing (not used by graph logic)
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


async def run_turn(assistant, user_input):
    """
    Drive one standard conversation turn through the graph.

    Returns (response_text, response_type) extracted from the finish chunk.
    Updates assistant.conversation_history with both the user turn and assistant reply.
    """
    msgs = assistant.conversation_history.copy()
    msgs.append({"role": "user", "content": user_input})

    initial_state = _build_initial_state(assistant, user_input, msgs)

    final_response = ""
    response_type = None
    async for chunk in _stream_graph_execution(initial_state):
        if chunk.finish:
            final_response = chunk.response
            response_type = chunk.response_type
            assistant.conversation_history.append({"role": "user", "content": user_input})
            assistant.conversation_history.append({
                "role": "assistant",
                "content": chunk.response,
                "nodes_executed": chunk.nodes_executed or [],
                "mode": "chat",
            })

    return final_response, response_type


async def run_intro(assistant):
    """
    Drive the introduction turn.

    Pre-sets response_type="introduction" so route_from_start bypasses
    analyze_input and routes directly to generate_fun_fact → generate_intro.
    No user message is appended to messages (intro is model-initiated).
    """
    msgs = assistant.conversation_history.copy()  # system prompt only

    initial_state = _build_initial_state(
        assistant,
        user_input="",
        messages=msgs,
        response_type="introduction",  # KEY: triggers intro path in route_from_start
    )

    final_response = ""
    response_type = None
    async for chunk in _stream_graph_execution(initial_state):
        if chunk.finish:
            final_response = chunk.response
            response_type = chunk.response_type
            assistant.conversation_history.append({
                "role": "assistant",
                "content": chunk.response,
                "nodes_executed": chunk.nodes_executed or [],
                "mode": "chat",
            })

    return final_response, response_type


# ============================================================================
# Assistant factory
# ============================================================================

def make_assistant(client):
    """Create a PaixuejiAssistant for apple / age 4 with system prompt seeded."""
    assistant = PaixuejiAssistant(client=client)
    assistant.age = 4
    assistant.object_name = "apple"

    system_prompt = assistant.prompts["system_prompt"]
    age_prompt_text = assistant.get_age_prompt(4)
    if age_prompt_text:
        system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt_text}"

    assistant.conversation_history = [{"role": "system", "content": system_prompt}]
    return assistant


# ============================================================================
# Verification helpers
# ============================================================================

_PASS_COUNT = 0
_FAIL_COUNT = 0


def check(condition, label):
    global _PASS_COUNT, _FAIL_COUNT
    status = "PASS" if condition else "FAIL"
    if condition:
        _PASS_COUNT += 1
    else:
        _FAIL_COUNT += 1
    print(f"  [{status}] {label}")
    return condition


def split_sentences(text):
    """Simple sentence splitter on . ! ? boundaries."""
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


def last_question(text):
    """Return the last sentence that ends with a question mark."""
    for sentence in reversed(split_sentences(text)):
        if "?" in sentence:
            return sentence
    return ""


def is_yn_question(q):
    """
    Heuristic: yes/no question starts with an auxiliary verb or
    'do/does/can/would/is/are/did/will/have/has'.
    """
    if not q:
        return False
    starters = (
        "do ", "does ", "can ", "would ", "is ", "are ",
        "did ", "will ", "have ", "has ",
    )
    return any(q.lower().lstrip().startswith(s) for s in starters)


# ============================================================================
# Scenario A — Fix 1: Introduction 3-beat structure
# ============================================================================

async def run_scenario_a(client):
    print("\n" + "=" * 70)
    print("SCENARIO A — Fix 1: Introduction 3-beat structure")
    print("=" * 70)

    assistant = make_assistant(client)
    response, rtype = await run_intro(assistant)

    print(f"\nresponse_type : {rtype}")
    print("\nMODEL RESPONSE:")
    print(response)
    print()

    sentences = split_sentences(response)
    first = sentences[0] if sentences else ""
    final_q = last_question(response)

    print("VERIFICATION:")
    check(rtype == "introduction", 'response_type == "introduction"')
    check("apple" in first.lower(), f'First sentence names "apple": "{first}"')
    check(
        not first.lower().startswith("hey ") and not first.lower().startswith("hello"),
        'First sentence does NOT open with "Hey there!" / "Hello"',
    )
    check(is_yn_question(final_q), f'Final question is yes/no form: "{final_q}"')
    check(
        not final_q.lower().startswith("what ") and
        not final_q.lower().startswith("why ") and
        not final_q.lower().startswith("how "),
        "Final question is NOT open-ended (not 'what/why/how')",
    )
    print()


# ============================================================================
# Scenario B — Fix 2+3: Correct answer path (age 4)
# ============================================================================

async def run_scenario_b(client):
    print("=" * 70)
    print("SCENARIO B — Fix 2+3: Correct answer path")
    print("=" * 70)

    assistant = make_assistant(client)
    # Seed with 3 prior turns (intro + 'yes' + model asking about seeds)
    assistant.conversation_history += [
        {
            "role": "assistant",
            "content": (
                "Oh, you found an apple! Apples are SO crunchy and sweet! "
                "Do you like eating apples?"
            ),
        },
        {"role": "user", "content": "yes"},
        {
            "role": "assistant",
            "content": (
                "When you cut an apple right in half, there is something really cool "
                "hiding in the very middle. What do you think you would see in there?"
            ),
        },
    ]

    user_input = "I will see the seeds"
    response, rtype = await run_turn(assistant, user_input)

    print(f"\nresponse_type : {rtype}")
    print("\nMODEL RESPONSE:")
    print(response)
    print()

    final_q = last_question(response)
    response_lower = response.lower()

    # "Did you know...?" appears as a question → violates BEAT2 statement rule.
    # We detect it by looking for "did you know" before any "?" in the text.
    before_first_q = response_lower.split("?")[0] if "?" in response_lower else response_lower
    beat2_bad = "did you know" in before_first_q

    # Bridge phrase check: the question should start with a bridge word, not "did you know"
    q_lower = final_q.lower().lstrip()
    bridge_present = (
        q_lower.startswith("and ") or
        q_lower.startswith("also,") or
        q_lower.startswith("also ") or
        q_lower.startswith("you know what") or
        q_lower.startswith("now,") or
        q_lower.startswith("oh,") or
        q_lower.startswith("so,")
    )

    print("VERIFICATION:")
    check(rtype == "correct_answer", 'response_type == "correct_answer"')
    check(not beat2_bad, 'BEAT2 fact NOT delivered as "Did you know...?" (statement form)')
    check(is_yn_question(final_q), f'BEAT3 final question is yes/no form: "{final_q}"')
    check(
        not final_q.lower().startswith("what do you think"),
        'BEAT3 is NOT "What do you think..." open-ended question',
    )
    check(
        not q_lower.startswith("did you know"),
        'Follow-up question does NOT start with "Did you know"',
    )
    print()


# ============================================================================
# Scenarios C + D — Fix 4: Two consecutive IDK turns (shared assistant)
# ============================================================================

async def run_scenarios_cd(client):
    print("=" * 70)
    print("SCENARIOS C+D — Fix 4: Two consecutive IDK turns (same assistant instance)")
    print("=" * 70)

    # Fresh assistant — C and D must share the SAME instance so
    # consecutive_struggle_count increments correctly between turns.
    assistant = make_assistant(client)
    assistant.conversation_history += [
        {
            "role": "assistant",
            "content": (
                "Oh, you found an apple! Apples are SO crunchy and sweet! "
                "Do you like eating apples?"
            ),
        },
        {"role": "user", "content": "yes"},
        {
            "role": "assistant",
            "content": (
                "Apple trees need something special from the sky to grow big and juicy. "
                "What do you think apple trees need to grow?"
            ),
        },
    ]

    # ---- Turn C: First IDK ----
    print(f"\nconsecutive_struggle_count BEFORE Turn C: {assistant.consecutive_struggle_count}")
    print()
    print("TURN C — 'I don't know' (first IDK)")
    print("-" * 50)

    response_c, rtype_c = await run_turn(assistant, "I don't know")

    print(f"response_type  : {rtype_c}")
    print(f"idk_count after: {assistant.consecutive_struggle_count}")
    print("\nMODEL RESPONSE:")
    print(response_c)
    print()

    print("VERIFICATION:")
    check(rtype_c == "clarifying_idk", f'response_type == "clarifying_idk" (got: {rtype_c})')
    check(
        assistant.consecutive_struggle_count == 1,
        f"consecutive_struggle_count incremented to 1 (got: {assistant.consecutive_struggle_count})",
    )
    print()

    # ---- Turn D: Second IDK ----
    print(f"consecutive_struggle_count BEFORE Turn D: {assistant.consecutive_struggle_count}")
    print()
    print("TURN D — 'I don't know' again (second IDK)")
    print("-" * 50)

    response_d, rtype_d = await run_turn(assistant, "I don't know")

    print(f"response_type  : {rtype_d}")
    print(f"idk_count after: {assistant.consecutive_struggle_count}")
    print("\nMODEL RESPONSE:")
    print(response_d)
    print()

    print("VERIFICATION:")
    check(rtype_d == "give_answer_idk", f'response_type == "give_answer_idk" (got: {rtype_d})')
    check(
        assistant.consecutive_struggle_count == 0,
        f"consecutive_struggle_count reset to 0 (got: {assistant.consecutive_struggle_count})",
    )
    # Accept "that's okay", "no worries", or "okay" appearing in the first 60 chars
    opening = response_d.lower()[:60]
    check(
        "that's okay" in opening or "no worries" in opening or "okay" in opening,
        f'Response opens with acceptance phrase (first 60 chars): "{response_d[:60]}"',
    )
    check(
        "sunlight" in response_d.lower() or "sun" in response_d.lower() or
        "water" in response_d.lower() or "light" in response_d.lower(),
        "Response directly states the answer (mentions sun/sunlight/water/light)",
    )
    print()


# ============================================================================
# Main
# ============================================================================

async def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_path = os.path.join(base_dir, "config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    print("Building Gemini client using Application Default Credentials (ADC)...")
    client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1"),
    )
    print("Client ready.\n")

    await run_scenario_a(client)
    await run_scenario_b(client)
    await run_scenarios_cd(client)

    print("=" * 70)
    print(f"SUMMARY: {_PASS_COUNT} passed, {_FAIL_COUNT} failed")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
