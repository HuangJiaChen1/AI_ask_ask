"Streaming functions for Paixueji assistant.

This module provides async streaming responses for the Paixueji assistant,
where the LLM asks questions about objects and children answer.
"
import asyncio
import copy
import json
import os
import time
from typing import AsyncGenerator

from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig
from loguru import logger

from schema import StreamChunk, TokenUsage
import paixueji_prompts

# Configure loguru
logger.add(
    "logs/paixueji_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
)

# Performance thresholds
SLOW_LLM_CALL_THRESHOLD = 5.0

def clean_messages_for_api(messages: list[dict]) -> list[dict]:
    """Clean messages to only include role/content."""
    return [{"role": m["role"], "content": m["content"]} for m in messages if "role" in m and "content" in m]

def convert_messages_to_gemini_format(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert OpenAI-style messages to Gemini format."""
    system_instruction = ""
    contents = []
    for msg in messages:
        if msg["role"] == "system":
            system_instruction += msg["content"] + "\n"
        else:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    return system_instruction.strip(), contents

async def call_gemini_stream_raw(client: genai.Client, model: str, system_instruction: str, contents: list, config: dict):
    """Low-level wrapper for Gemini streaming."""
    gen_config = GenerateContentConfig(
        temperature=config.get("temperature", 0.3),
        max_output_tokens=config.get("max_tokens", 2000),
        system_instruction=system_instruction if system_instruction else None
    )
    return client.models.generate_content_stream(model=model, contents=contents, config=gen_config)

async def ask_introduction_question_stream(
    messages: list[dict], object_name: str, category_prompt: str, age_prompt: str, age: int, config: dict, client: genai.Client, level3_category: str = "", focus_prompt: str = ""
) -> AsyncGenerator[tuple[str, None, str, dict], None]:
    """Stream first question (Monolithic)."""
    prompts = paixueji_prompts.get_prompts()
    prompt = prompts['introduction_prompt'].format(object_name=object_name, category_prompt=category_prompt, age_prompt=age_prompt, age=age, focus_prompt=focus_prompt)
    sys_inst, contents = convert_messages_to_gemini_format(clean_messages_for_api(messages + [{"role": "user", "content": prompt}]))
    
    full_response = ""
    stream = await call_gemini_stream_raw(client, config["model_name"], sys_inst, contents, config)
    decision_info = {'new_object_name': None, 'detected_object_name': None, 'switch_decision_reasoning': None}
    
    for chunk in stream:
        if chunk.text:
            full_response += chunk.text
            yield (chunk.text, None, full_response, decision_info)

async def orchestrate_dual_stream(
    messages: list[dict], response_prompt: str, followup_prompt: str, config: dict, client: genai.Client, decision_info: dict
) -> AsyncGenerator[tuple[str, None, str, dict], None]:
    """Parallel generation, Serial consumption."""
    sys_inst_res, contents_res = convert_messages_to_gemini_format(clean_messages_for_api(messages + [{"role": "user", "content": response_prompt}]))
    sys_inst_fol, contents_fol = convert_messages_to_gemini_format(clean_messages_for_api(messages + [{"role": "user", "content": followup_prompt}]))

    # Start both streams in parallel
    res_stream_task = asyncio.create_task(call_gemini_stream_raw(client, config["model_name"], sys_inst_res, contents_res, config))
    fol_stream_task = asyncio.create_task(call_gemini_stream_raw(client, config["model_name"], sys_inst_fol, contents_fol, config))

    full_response = ""
    
    # 1. Stream the Response (Feedback/Explanation/Correction)
    res_stream = await res_stream_task
    for chunk in res_stream:
        if chunk.text:
            full_response += chunk.text
            yield (chunk.text, None, full_response, decision_info)

    # 2. Add bridge newline if needed
    if full_response and not full_response.endswith('\n\n'):
        bridge = "\n\n"
        full_response += bridge
        yield (bridge, None, full_response, decision_info)

    # 3. Stream the Follow-up Question
    fol_stream = await fol_stream_task
    for chunk in fol_stream:
        if chunk.text:
            full_response += chunk.text
            yield (chunk.text, None, full_response, decision_info)

def decide_topic_switch_with_validation(assistant, child_answer: str, object_name: str, age: int, focus_mode: str | None = None):
    """Unified AI validation logic (JSON)."""
    conversation_history = assistant.conversation_history
    last_model_question = next((msg['content'] for msg in reversed(conversation_history) if msg['role'] == 'assistant'), "Unknown")

    decision_prompt = f"""Evaluate the child's answer:
- Current Topic: {object_name}
- Last Question: "{last_model_question}"
- Child's Answer: "{child_answer}"
- Age: {age}

Respond in JSON with:
{{
    "decision": "SWITCH" or "CONTINUE",
    "new_object": "Name" or null,
    "switching_reasoning": "...",
    "is_engaged": true/false,
    "is_factually_correct": true/false,
    "correctness_reasoning": "..."
}}"""

    response = assistant.client.models.generate_content(
        model=assistant.config.get("model", "gemini-2.0-flash-exp"),
        contents=decision_prompt,
        config={"response_mime_type": "application/json", "temperature": 0.1, "max_output_tokens": 200}
    )
    return json.loads(response.text)

async def ask_followup_question_stream(
    messages: list[dict], child_answer: str, assistant, object_name: str, correct_count: int, category_prompt: str, age_prompt: str, age: int, config: dict, client: genai.Client, level3_category: str = "", focus_prompt: str = "", focus_mode: str | None = None, precomputed_decision: dict | None = None
) -> AsyncGenerator[tuple[str, None, str, dict], None]:
    """Dual-stream follow-up or topic switch."""
    decision = precomputed_decision or decide_topic_switch_with_validation(assistant, child_answer, object_name, age, focus_mode)
    prompts = paixueji_prompts.get_prompts()
    
    decision_info = {'new_object_name': None, 'detected_object_name': None, 'switch_decision_reasoning': decision.get('switching_reasoning')}
    
    if decision['decision'] == 'SWITCH':
        if decision['new_object']:
            # Handle object switch
            prev_obj = object_name
            object_name = decision['new_object']
            assistant.object_name = object_name
            decision_info['new_object_name'] = object_name
            
            # Sync classification
            assistant.classify_object_sync(object_name)
            cat_prompt = assistant.get_category_prompt(assistant.level1_category, assistant.level2_category, assistant.level3_category)
            
            res_prompt = prompts['topic_switch_response_prompt'].format(new_object=object_name, previous_object=prev_obj, age=age)
            fol_prompt = prompts['followup_question_prompt'].format(object_name=object_name, age=age, focus_prompt=focus_prompt, category_prompt=cat_prompt, age_prompt=age_prompt)
        else:
            # Generic switch request
            res_prompt = f"Warmly agree to switch from {object_name} to something else. Age {age}."
            fol_prompt = f"Ask the child what they would like to talk about next. Age {age}."
    else:
        # Normal follow-up
        res_prompt = prompts['feedback_response_prompt'].format(child_answer=child_answer, object_name=object_name, age=age)
        fol_prompt = prompts['followup_question_prompt'].format(object_name=object_name, age=age, focus_prompt=focus_prompt, category_prompt=category_prompt, age_prompt=age_prompt)

    return orchestrate_dual_stream(messages, res_prompt, fol_prompt, config, client, decision_info)

async def ask_explanation_question_stream(
    messages: list[dict], child_answer: str, assistant, object_name: str, correct_count: int, category_prompt: str, age_prompt: str, age: int, config: dict, client: genai.Client, level3_category: str = "", focus_prompt: str = "", focus_mode: str | None = None
) -> AsyncGenerator[tuple[str, None, str, dict], None]:
    """Dual-stream explanation."""
    prompts = paixueji_prompts.get_prompts()
    prev_q = next((msg['content'] for msg in reversed(messages) if msg['role'] == 'assistant'), "the last question")
    
    res_prompt = prompts['explanation_response_prompt'].format(child_answer=child_answer, object_name=object_name, age=age, previous_question=prev_q)
    fol_prompt = prompts['followup_question_prompt'].format(object_name=object_name, age=age, focus_prompt=focus_prompt, category_prompt=category_prompt, age_prompt=age_prompt)
    
    decision_info = {'new_object_name': None, 'detected_object_name': None, 'switch_decision_reasoning': None}
    return orchestrate_dual_stream(messages, res_prompt, fol_prompt, config, client, decision_info)

async def ask_gentle_correction_stream(
    messages: list[dict], child_answer: str, assistant, object_name: str, correct_count: int, category_prompt: str, age_prompt: str, age: int, config: dict, client: genai.Client, correctness_reasoning: str, level3_category: str = "", focus_prompt: str = "", focus_mode: str | None = None
) -> AsyncGenerator[tuple[str, None, str, dict], None]:
    """Dual-stream correction."""
    prompts = paixueji_prompts.get_prompts()
    
    res_prompt = prompts['correction_response_prompt'].format(child_answer=child_answer, object_name=object_name, age=age, correctness_reasoning=correctness_reasoning)
    fol_prompt = prompts['followup_question_prompt'].format(object_name=object_name, age=age, focus_prompt=focus_prompt, category_prompt=category_prompt, age_prompt=age_prompt)
    
    decision_info = {'new_object_name': None, 'detected_object_name': None, 'switch_decision_reasoning': None}
    return orchestrate_dual_stream(messages, res_prompt, fol_prompt, config, client, decision_info)

async def call_paixueji_stream(
    age: int | None, messages: list[dict], content: str, status: str, session_id: str, request_id: str, config: dict, client: genai.Client, assistant, age_prompt: str = "", object_name: str = "", level1_category: str = "", level2_category: str = "", level3_category: str = "", correct_answer_count: int = 0, category_prompt: str = "", focus_prompt: str = "", focus_mode: str | None = None
) -> AsyncGenerator[StreamChunk, None]:
    """Main entry point."""
    messages.append({"role": "user", "content": content})
    has_asked = any(m["role"] == "assistant" for m in messages)

    if correct_answer_count == 0 and not has_asked:
        stream_gen = ask_introduction_question_stream(messages, object_name, category_prompt, age_prompt, age or 6, config, client, level3_category, focus_prompt)
        res_type = "introduction"
    else:
        val = decide_topic_switch_with_validation(assistant, content, object_name, age or 6, focus_mode)
        is_engaged = val['is_engaged']
        is_factually_correct = val['is_factually_correct']
        should_switch = val['decision'] == 'SWITCH'

        if not is_engaged and not should_switch:
            stream_gen = await ask_explanation_question_stream(messages, content, assistant, object_name, correct_answer_count, category_prompt, age_prompt, age or 6, config, client, level3_category, focus_prompt, focus_mode)
            res_type = "explanation"
        elif is_factually_correct or should_switch:
            stream_gen = await ask_followup_question_stream(messages, content, assistant, object_name, correct_answer_count, category_prompt, age_prompt, age or 6, config, client, level3_category, focus_prompt, focus_mode, precomputed_decision=val)
            res_type = "followup"
        else:
            stream_gen = await ask_gentle_correction_stream(messages, content, assistant, object_name, correct_answer_count, category_prompt, age_prompt, age or 6, config, client, val['correctness_reasoning'], level3_category, focus_prompt, focus_mode)
            res_type = "gentle_correction"

    full_response = ""
    seq = 0
    async for chunk_text, _, full_text, d_info in stream_gen:
        seq += 1
        full_response = full_text
        yield StreamChunk(
            response=chunk_text, session_finished=False, duration=0.0, token_usage=None, finish=False, sequence_number=seq, timestamp=time.time(), session_id=session_id, request_id=request_id, correct_answer_count=correct_answer_count, conversation_complete=False, focus_mode=focus_mode, is_engaged=val['is_engaged'] if 'val' in locals() else True, is_factually_correct=val['is_factually_correct'] if 'val' in locals() else True, new_object_name=d_info['new_object_name'], detected_object_name=d_info['detected_object_name'], switch_decision_reasoning=d_info['switch_decision_reasoning']
        )

    yield StreamChunk(
        response=full_response, session_finished=False, duration=0.0, token_usage=None, finish=True, sequence_number=seq+1, timestamp=time.time(), session_id=session_id, request_id=request_id, correct_answer_count=correct_answer_count, conversation_complete=False, focus_mode=focus_mode, finish_reason="stop"
    )