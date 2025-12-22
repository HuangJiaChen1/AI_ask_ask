import asyncio
import copy
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncGenerator, List

import jieba
import yaml
from dashscope import Generation
from dotenv import load_dotenv
from loguru import logger

from schema import SessionTerminationReason, StreamChunk, TokenUsage

load_dotenv()

# Load streaming configuration
_config_path = Path(__file__).parent / "config.yaml"
try:
    with open(_config_path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    STANDARD_DELAY = _config["streaming"]["delays"]["STANDARD_DELAY"]
    FAST_DELAY = _config["streaming"]["delays"]["FAST_DELAY"]
    logger.info(f"Loaded streaming config | STANDARD_DELAY={STANDARD_DELAY}s, FAST_DELAY={FAST_DELAY}s")
except Exception as e:
    logger.warning(f"Failed to load config.yaml, using default delays | error={str(e)}")
    STANDARD_DELAY = 0.1
    FAST_DELAY = 0.05

# Configure loguru for production
logger.add(
    "logs/agent_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    backtrace=True,
    diagnose=True,
)

jieba.initialize()

# Performance thresholds for warnings (in seconds)
SLOW_LLM_CALL_THRESHOLD = 5.0
SLOW_CLASSIFICATION_THRESHOLD = 3.0


def clean_messages_for_api(messages: list[dict]) -> list[dict]:
    """
    Remove count and boolean flag fields from messages before sending to API.

    Args:
        messages: List of message dicts that may contain count/flag fields

    Returns:
        Cleaned list of messages with only standard fields (role, content, etc.)
    """
    cleaned = []
    for msg in messages:
        # Create a copy without the count and flag fields
        cleaned_msg = {
            k: v
            for k, v in msg.items()
            if k not in ["no_relevant_count", "relevant_question_count", "not_relevant", "relevant_question"]
        }
        cleaned.append(cleaned_msg)
    return cleaned


def calculate_session_counts(messages: list[dict]) -> tuple[int, int]:
    """
    Calculate session state counts by looping through message history.

    Counts assistant messages that have the boolean flags set to True.

    Args:
        messages: List of message dicts (conversation history)

    Returns:
        Tuple of (not_relevant_count, relevant_question_count)
    """
    not_relevant_count = sum(1 for msg in messages if msg.get("role") == "assistant" and msg.get("not_relevant", False))
    relevant_question_count = sum(
        1 for msg in messages if msg.get("role") == "assistant" and msg.get("relevant_question", False)
    )
    return not_relevant_count, relevant_question_count


def prepare_messages_for_streaming(messages: list[dict], new_system_content: str) -> list[dict]:
    """
    Safely prepare messages for streaming API calls without mutating the original list.

    This function:
    1. Creates a deep copy of the messages list
    2. Removes count fields from the first message (if present)
    3. Updates the system message content

    Args:
        messages: Original message list (will not be modified)
        new_system_content: New content for the system message

    Returns:
        New cleaned message list ready for API calls
    """
    # Create deep copy to avoid mutating original
    messages_copy = copy.deepcopy(messages)

    # Remove first message if it contains only count fields (no role/content)
    if messages_copy and not messages_copy[0].get("role"):
        messages_copy.pop(0)

    # Update system message content
    if messages_copy and messages_copy[0].get("role") == "system":
        messages_copy[0]["content"] = new_system_content

    # Clean any remaining count fields
    return clean_messages_for_api(messages_copy)


def chunk_text(text: str, max_chunk_size: int = 4) -> List[str]:
    """
    Split Chinese text into natural chunks using jieba for sentence segmentation.

    Args:
        text: Input Chinese text to chunk
        max_chunk_size: Maximum number of characters per chunk

    Returns:
        List of text chunks split at natural boundaries
    """
    if not text or text.strip() == "":
        return []

    seg_list = list(jieba.cut(text))

    chunks = []
    current_chunk = ""

    for i in range(0, len(seg_list), 2):
        seg = seg_list[i]
        delimiter = seg_list[i + 1] if i + 1 < len(seg_list) else ""

        seg_with_delimiter = seg + delimiter

        # If adding this sentence exceeds max_chunk_size and current_chunk is not empty,
        # yield current_chunk and start a new one
        if len(current_chunk) + len(seg_with_delimiter) > max_chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = seg_with_delimiter
        else:
            current_chunk += seg_with_delimiter

    # Add remaining chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # If no chunks were created (no delimiters found), split by character count
    if not chunks and text.strip():
        for i in range(0, len(text), max_chunk_size):
            chunks.append(text[i : i + max_chunk_size])

    return chunks


def concatenate_contents(data):
    pages = data["pages"]
    contents = [page.get("content", "") for page in pages]
    if any(not page.get("content") for page in pages):
        logger.warning("Some pages have missing or empty 'content' fields in concatenate_contents")
    concatenated_string = "".join(contents)

    return concatenated_string


def get_content_by_index(book_data, page_id):
    pages = book_data["pages"]
    for page in pages:
        if page["page_id"] == page_id:
            content = page.get("content", "")
            if not content:
                logger.warning(f"Page {page_id} has missing or empty 'content' field")
            return content
    logger.warning(f"Page with page_id={page_id} not found in book_data")
    return ""  # Return empty string instead of None


def call_flash(system_content, content):
    messages = [{"role": "system", "content": system_content}, {"role": "user", "content": content}]
    start_time = time.time()

    try:
        logger.debug(f"Calling qwen-flash | content_length={len(content)}")
        response = Generation.call(
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            model="qwen-flash",
            messages=messages,
            seed=127,
            result_format="message",
            max_tokens=128,
        )
        duration = time.time() - start_time

        if response.status_code == 200:
            result = response.output.choices[0].message.content
            logger.info(f"qwen-flash call successful | duration={duration:.3f}s, result_length={len(result)}")
            if duration > SLOW_LLM_CALL_THRESHOLD:
                logger.warning(
                    f"Slow qwen-flash call | duration={duration:.3f}s exceeded threshold {SLOW_LLM_CALL_THRESHOLD}s"
                )
            return result
        else:
            logger.error(f"qwen-flash call failed | status_code={response.status_code}, duration={duration:.3f}s")
            return None
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"qwen-flash call exception | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        return None


def call_plus(system_content, content):
    messages = [{"role": "system", "content": system_content}, {"role": "user", "content": content}]
    start_time = time.time()

    try:
        logger.debug(f"Calling qwen3-30b | content_length={len(content)}")
        response = Generation.call(
            # model='qwen-plus',
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            model="qwen3-30b-a3b-instruct-2507",
            messages=messages,
            seed=127,
            result_format="message",
            max_tokens=128,
        )
        duration = time.time() - start_time

        if response.status_code == 200:
            result = response.output.choices[0].message.content
            logger.info(f"qwen3-30b call successful | duration={duration:.3f}s, result_length={len(result)}")
            if duration > SLOW_LLM_CALL_THRESHOLD:
                logger.warning(
                    f"Slow qwen3-30b call | duration={duration:.3f}s exceeded threshold {SLOW_LLM_CALL_THRESHOLD}s"
                )
            return result
        else:
            logger.error(f"qwen3-30b call failed | status_code={response.status_code}, duration={duration:.3f}s")
            return None
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"qwen3-30b call exception | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        return None


def call_qwen3(system_content, content):
    messages = [{"role": "system", "content": system_content}, {"role": "user", "content": content}]
    start_time = time.time()

    try:
        logger.debug(f"Calling qwen3-30b | content_length={len(content)}")
        response = Generation.call(
            # model='qwen-plus',
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            model="qwen3-30b-a3b-instruct-2507",
            messages=messages,
            seed=127,
            result_format="message",
            max_tokens=128,
        )
        duration = time.time() - start_time

        if response.status_code == 200:
            result = response.output.choices[0].message.content
            logger.info(f"qwen3-30b call successful | duration={duration:.3f}s, result_length={len(result)}")
            if duration > SLOW_LLM_CALL_THRESHOLD:
                logger.warning(
                    f"Slow qwen3-30b call | duration={duration:.3f}s exceeded threshold {SLOW_LLM_CALL_THRESHOLD}s"
                )
            return result
        else:
            logger.error(f"qwen3-30b call failed | status_code={response.status_code}, duration={duration:.3f}s")
            return None
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"qwen3-30b call exception | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        return None


# 异步包装器 - 在单独的线程中运行同步函数
async def async_call_flash(system_content, content):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(pool, call_flash, system_content, content)


async def async_call_plus(system_content, content):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(pool, call_plus, system_content, content)


async def async_call_qwen3(system_content, content):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(pool, call_qwen3, system_content, content)


# 异步版本的story_relevant函数
async def async_story_relevant(story_data, page_id, content):
    # 获取故事内容（假设这些是同步函数）
    whole_story = concatenate_contents(story_data)
    page_content = get_content_by_index(story_data, page_id)

    system_content = f"""
    全篇故事内容：{whole_story}
    =====================================
    当前页故事内容：{page_content}
    =====================================
    你需要判断用户的回复是否和故事里的内容相关？
    =====================================
    规则：你的返回只能为"是"或者"否"
    """

    max_retries = 0
    attempt = 0

    while attempt <= max_retries:
        try:
            # 使用异步包装器调用同步API
            response_content = await async_call_flash(system_content, content)
            # response_content = await async_call_plus(system_content, content)
            if response_content:
                result = response_content.strip()
                if result in ["是", "否"]:
                    return True if result == "是" else False
                elif attempt < max_retries:
                    logger.warning(f"Invalid response on attempt {attempt + 1}: '{result}', retrying...")
                else:
                    logger.warning(f"Max retries reached with invalid response: '{result}', defaulting to 'no' (否)")
                    return False
            else:
                logger.error("API call returned None")

        except Exception as e:
            logger.error(f"Error during API call: {e}", exc_info=True)

        attempt += 1
    return False


# 异步检查函数
async def check_sensitive(content):
    system_content = """你是一个AI语言检查助手，你需要判断收到的内容是否为敏感内容，攻击性的内容或者辱骂性的内容。
    当回复包含污言秽语、诽谤、仇恨言论、性暗示语言、人身攻击，或整体语气带有敌意、攻击性或不妥内容，你的判断为"是"
    当回复内容无不良信息，且语气保持中立或积极，你的判断为"否"
    ================================
    要求：你的回复只能为"是"或者"否"。
    """
    reply = await async_call_qwen3(system_content, content)
    return "over_chat" if reply is None or reply == "是" else "continue"


async def check_question(content):
    system_content = """你是一个AI语言检查助手，你需要判断收到的内容是否为问句。
    当收到的回复为问句时，你的判断为"是"
    其余所有情况，你的判断为"否"
    ================================
    要求：你的回复只能为"是"或者"否"。"""
    reply = await async_call_flash(system_content, content)
    return "question" if reply == "是" else "not_question"


async def check_refuse(content):
    system_content = """你是一个判断对话状态的助手，你需要判断接下来的对话是否要继续。
    一位绘本读者之前正在和小朋友关于绘本聊天，他上一句刚刚问了小朋友是否还有问题，你需要就小朋友的回复，判断是否要继续回复。
    当回复包含明显的拒绝对话意思时，或者要求他继续读绘本的时候，你的判断为"否"，例如："我没有问题了。"，"不要"，"继续讲故事吧"。
    其余所有情况，你的判断均为"是"。
    ================================
    要求：你的回复只能为"是"或者"否"。"""
    reply = await async_call_flash(system_content, content)
    return "reply" if reply == "是" else "no_reply"


# 主调用函数
async def main_checks(content, story_data, page_id):
    # 同时发起四个异步任务
    reply_task = asyncio.create_task(check_refuse(content))  ###判断小朋友是否没有问题了
    sensitive_task = asyncio.create_task(check_sensitive(content))  # 判断是否有敏感攻击性内容
    question_task = asyncio.create_task(check_question(content))
    story_task = asyncio.create_task(async_story_relevant(story_data, page_id, content))

    # 等待所有任务完成
    results = await asyncio.gather(reply_task, sensitive_task, question_task, story_task, return_exceptions=True)

    # 处理结果（三个字符串变量）
    reply_result, sensitive_result, question_result, relevant_result = results

    # 返回三个结果
    return reply_result, sensitive_result, question_result, relevant_result


async def check_all(story_data, page_id, content):
    # 直接调用main_checks并解包结果
    start_time = time.time()

    logger.info(f"Starting parallel classification checks | page_id={page_id}, content_length={len(content)}")

    reply_result, sensitive_result, question_result, story_result = await main_checks(content, story_data, page_id)

    end_time = time.time()
    elapsed_time = end_time - start_time

    logger.info(
        f"Classification checks completed | "
        f"reply={reply_result}, sensitive={sensitive_result}, "
        f"question={question_result}, story_relevant={story_result}, "
        f"duration={elapsed_time:.3f}s"
    )

    if elapsed_time > SLOW_CLASSIFICATION_THRESHOLD:
        logger.warning(
            f"Slow classification | duration={elapsed_time:.3f}s exceeded threshold {SLOW_CLASSIFICATION_THRESHOLD}s"
        )

    logger.debug(
        f"Classification results summary | "
        f"continue_check={reply_result}, sensitive_check={sensitive_result}, "
        f"question_check={question_result}, story_relevant_check={story_result}, "
        f"total_duration={elapsed_time:.4f}s"
    )

    return reply_result, sensitive_result, question_result, story_result


async def relevant_question_stream(messages, page_id, story_data):
    """
    Stream version of relevant_question that yields text chunks and token usage.

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_reply_so_far)
    """
    start_time = time.time()
    logger.info(f"relevant_question_stream started | page_id={page_id}, message_count={len(messages)}")

    whole_story = concatenate_contents(story_data)
    page_content = get_content_by_index(story_data, page_id)

    new_system_content = f"""全篇故事内容：{whole_story}
    ====================================
    你是一位充满智慧的小狮子莱纳德,你的责任是指导小朋友读故事绘本,你需要根据故事内容，非常精简地回答一位小朋友的问题
    ====================================
    当前页面的故事内容为：{page_content}
    ====================================
    要求：用陈述句回答小朋友，不要对小朋友进行提问。
    """

    # Prepare clean copy of messages without mutating original
    clean_messages = prepare_messages_for_streaming(messages, new_system_content)
    logger.debug(f"Messages to call LLM: {clean_messages}")

    praise_list = [
        "问得真好呀！",
        "你好会提问呀！",
        "真会动脑筋！",
        "好聪明的问题！",
        "问得太棒啦！",
        "真是一个好问题！",
        "你真是个好奇宝宝！",
    ]
    praise = random.choice(praise_list)

    question_list = [
        "还想问点啥呀？",
        "还有问题要问吗？",
        "接下来还想知道啥？",
        "还有什么好奇吗？",
        "有新问题诞生了吗？",
    ]
    follow_up_question = random.choice(question_list)

    # Buffer praise chunks (don't yield yet - wait for first LLM chunk)
    praise_chunks = chunk_text(praise)
    buffered_praise_chunks = list(praise_chunks)

    # Stream from LLM and yield chunks
    full_llm_reply = ""
    token_usage = None
    first_llm_chunk = True

    try:
        logger.debug(f"Sending {len(clean_messages)} messages to API")

        response = Generation.call(
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            model="qwen-flash",
            messages=clean_messages,
            seed=127,
            result_format="message",
            stream=True,
            incremental_output=True,
            max_tokens=128,
        )

        for chunk in response:
            if chunk.status_code == 200:
                content_chunk = chunk.output.choices[0].message.content

                # On first LLM chunk, flush all buffered praise chunks
                if first_llm_chunk:
                    for buffered_chunk in buffered_praise_chunks:
                        yield (buffered_chunk, None, "")
                        await asyncio.sleep(STANDARD_DELAY)

                    first_llm_chunk = False

                # Then yield the LLM chunk
                full_llm_reply += content_chunk
                yield (content_chunk, None, praise + full_llm_reply)

                # Check if this is the last chunk (has usage info)
                if hasattr(chunk, "usage") and chunk.usage:
                    token_usage = TokenUsage(
                        input_tokens=chunk.usage.input_tokens,
                        output_tokens=chunk.usage.output_tokens,
                        total_tokens=chunk.usage.input_tokens + chunk.usage.output_tokens,
                    )
            else:
                logger.error(f"Stream chunk failed | status_code={chunk.status_code}")
                break

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"relevant_question_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        return

    # Chunk the follow-up question and yield chunks
    question_chunks = chunk_text(follow_up_question)
    for chunk in question_chunks:
        yield (chunk, None, praise + full_llm_reply + follow_up_question)
        await asyncio.sleep(STANDARD_DELAY)

    # Final yield with token usage
    qwen_reply = praise + full_llm_reply + follow_up_question
    # messages.append({"role": "assistant", "content": qwen_reply})

    duration = time.time() - start_time
    logger.info(
        f"relevant_question_stream completed | "
        f"duration={duration:.3f}s, reply_length={len(qwen_reply)}, "
        f"token_usage={token_usage.model_dump() if token_usage else 'N/A'}"
    )

    yield ("", token_usage, qwen_reply)


async def relevant_not_question_stream(messages, page_id, story_data):
    """
    Stream version of relevant_not_question that yields text chunks and token usage.

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_reply_so_far)
    """
    start_time = time.time()
    logger.info(f"relevant_not_question_stream started | page_id={page_id}, message_count={len(messages)}")

    whole_story = concatenate_contents(story_data)
    page_content = get_content_by_index(story_data, page_id)

    new_system_content = f"""全篇故事内容：{whole_story}
    ====================================
    你是一位充满智慧的小狮子莱纳德,你的责任是指导小朋友读故事绘本,你需要根据故事内容，非常精简地回答一位小朋友
    ====================================
    当前页面的故事内容为：{page_content}
    ====================================
    要求：用陈述句回答小朋友，不要对小朋友进行提问。
    """

    # Prepare clean copy of messages without mutating original
    clean_messages = prepare_messages_for_streaming(messages, new_system_content)
    logger.debug(f"Messages to call LLM: {clean_messages}")

    # Stream from LLM and yield chunks
    full_llm_reply = ""
    token_usage = None

    try:
        logger.debug(f"Sending {len(clean_messages)} messages to API")

        response = Generation.call(
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            model="qwen-flash",
            messages=clean_messages,
            seed=127,
            result_format="message",
            stream=True,
            incremental_output=True,
            max_tokens=128,
        )

        for chunk in response:
            if chunk.status_code == 200:
                content_chunk = chunk.output.choices[0].message.content
                full_llm_reply += content_chunk
                yield (content_chunk, None, full_llm_reply)
                await asyncio.sleep(FAST_DELAY)

                # Check if this is the last chunk (has usage info)
                if hasattr(chunk, "usage") and chunk.usage:
                    token_usage = TokenUsage(
                        input_tokens=chunk.usage.input_tokens,
                        output_tokens=chunk.usage.output_tokens,
                        total_tokens=chunk.usage.input_tokens + chunk.usage.output_tokens,
                    )
            else:
                logger.error(f"Stream chunk failed | status_code={chunk.status_code}")
                break

    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            f"relevant_not_question_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True
        )
        return

    duration = time.time() - start_time
    logger.info(
        f"relevant_not_question_stream completed | "
        f"duration={duration:.3f}s, reply_length={len(full_llm_reply)}, "
        f"token_usage={token_usage.model_dump() if token_usage else 'N/A'}"
    )

    yield ("", token_usage, full_llm_reply)


async def not_relevant_stream(content):
    """
    Stream version of no_relevant that yields text chunks and token usage.

    Yields:
        Tuple of (text_chunk, token_usage_or_None, full_reply_so_far)
    """
    start_time = time.time()
    logger.info(f"no_relevant_stream started | content_length={len(content)}")

    system_content = """你是一位充满智慧的小狮子玩偶莱纳德,你需要非常精简地回答一位小朋友的问题,如果你不知道答案,就委婉地说不知道。
    ==============================================
    要求：用陈述句回答小朋友，不要对小朋友进行提问。
    """
    temporary_messages = [{"role": "system", "content": system_content}, {"role": "user", "content": content}]

    # Stream from LLM and yield chunks
    full_reply = ""
    token_usage = None

    try:
        response = Generation.call(
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            model="qwen3-30b-a3b-instruct-2507",
            messages=temporary_messages,
            seed=127,
            result_format="message",
            stream=True,
            incremental_output=True,
            max_tokens=128,
        )

        for chunk in response:
            if chunk.status_code == 200:
                content_chunk = chunk.output.choices[0].message.content
                full_reply += content_chunk
                yield (content_chunk, None, full_reply)
                await asyncio.sleep(FAST_DELAY)

                # Check if this is the last chunk (has usage info)
                if hasattr(chunk, "usage") and chunk.usage:
                    token_usage = TokenUsage(
                        input_tokens=chunk.usage.input_tokens,
                        output_tokens=chunk.usage.output_tokens,
                        total_tokens=chunk.usage.input_tokens + chunk.usage.output_tokens,
                    )
                    logger.debug(f"Token usage: {chunk.usage}")
            else:
                logger.error(f"Stream chunk failed | status_code={chunk.status_code}")
                break

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"no_relevant_stream LLM error | error={str(e)}, duration={duration:.3f}s", exc_info=True)
        return

    duration = time.time() - start_time
    logger.info(
        f"no_relevant_stream completed | "
        f"duration={duration:.3f}s, reply_length={len(full_reply)}, "
        f"token_usage={token_usage.model_dump() if token_usage else 'N/A'}"
    )

    yield ("", token_usage, full_reply)


async def sentive_chat_stream():
    """
    Stream version of sentive_chat that yields text chunks.

    Yields:
        Tuple of (text_chunk, None, full_reply)
    """
    replies = ["我是你的读书小助手。", "我的魔法是帮你读故事。", "我不太明白。"]
    reply = random.choice(replies)

    # Chunk the reply and yield
    reply_chunks = chunk_text(reply)
    for chunk in reply_chunks:
        yield (chunk, None, reply)
        await asyncio.sleep(STANDARD_DELAY)

    # message.append({"role": "assistant", "content": reply})
    # Final yield
    yield ("", None, reply)


async def no_reply_chat_stream():
    """
    Stream version of no_reply_chat that yields text chunks.

    Yields:
        Tuple of (text_chunk, None, full_reply)
    """
    replies = [
        "好的。",
        "好呀。",
        "没问题。",
    ]
    reply = random.choice(replies)

    # Chunk the reply and yield
    reply_chunks = chunk_text(reply)
    for chunk in reply_chunks:
        yield (chunk, None, reply)
        await asyncio.sleep(STANDARD_DELAY)

    # message.append({"role": "assistant", "content": reply})
    # Final yield
    yield ("", None, reply)


async def call_Leonard_stream(
    book_data,
    page_id,
    messages,
    content,
    status,
    session_id,
) -> AsyncGenerator[StreamChunk, None]:
    """
    Streaming version of call_Leonard that yields StreamChunk objects.

    Args:
        book_data: Book content data
        page_index: Current page index
        messages: Conversation message history
        content: User's input
        status: Current conversation status
        session_id: Session identifier
        turn_number: Turn number in conversation

    Yields:
        StreamChunk objects containing response chunks and metadata
    """
    start_time = time.time()

    # Calculate session counts from message history
    no_relevant_count, relevant_question_count = calculate_session_counts(messages)

    logger.info(
        f"[{session_id}] call_Leonard_stream started | "
        f"session_id={session_id}, page_id={page_id}, "
        f"status={status}, no_relevant_count={no_relevant_count}, "
        f"relevant_question_count={relevant_question_count}, "
        f"content_length={len(content)}, message_history={len(messages)}"
    )

    messages.append({"role": "user", "content": content})

    # Run all checks in parallel
    reply_result, sensitive_result, question_result, story_result = await check_all(book_data, page_id, content)

    # Build router_result dict
    router_result = {
        "reply_result": reply_result,
        "sensitive_result": sensitive_result,
        "question_result": question_result,
        "story_result": story_result,
    }

    logger.info(
        f"[{session_id}] Router decision | "
        f"reply={reply_result}, sensitive={sensitive_result}, "
        f"question={question_result}, story={story_result}"
    )

    # Track sequence number and token usage
    sequence_number = 0
    token_usage = None
    full_reply = ""

    # Track termination reason
    termination_reason = None

    # Track current turn's boolean flags
    current_not_relevant = False
    current_relevant_question = False

    # Determine which streaming function to use
    stream_generator = None
    response_type = None

    if sensitive_result == "over_chat":
        stream_generator = sentive_chat_stream()
        status = "over"
        termination_reason = SessionTerminationReason.SENSITIVE_CONTENT
        response_type = "sensitive_chat"
        logger.info(f"[{session_id}] Routing to sensitive_chat (offensive content detected)")
    else:
        if reply_result != "reply":
            stream_generator = no_reply_chat_stream()
            status = "over"
            termination_reason = SessionTerminationReason.USER_DECLINED
            response_type = "no_reply_chat"
            logger.info(f"[{session_id}] Routing to no_reply_chat (user declined to continue)")
        else:
            if sensitive_result == "continue" and question_result == "question" and story_result:
                stream_generator = relevant_question_stream(messages, page_id, book_data)
                relevant_question_count += 1
                current_relevant_question = True
                response_type = "relevant_question"
                logger.info(
                    f"[{session_id}] Routing to relevant_question | "
                    f"relevant_question_count={relevant_question_count}"
                )
                if relevant_question_count >= 20:
                    status = "over"
                    termination_reason = SessionTerminationReason.RELEVANT_QUESTION_LIMIT
                    logger.warning(f"[{session_id}] Relevant question limit reached (20), setting status=over")

            elif sensitive_result == "continue" and question_result == "not_question" and story_result:
                stream_generator = relevant_not_question_stream(messages, page_id, book_data)
                relevant_question_count += 1
                current_relevant_question = True
                response_type = "relevant_not_question"
                logger.info(
                    f"[{session_id}] Routing to relevant_not_question | "
                    f"relevant_question_count={relevant_question_count}"
                )
                if relevant_question_count >= 20:
                    status = "over"
                    termination_reason = SessionTerminationReason.RELEVANT_QUESTION_LIMIT
                    logger.warning(f"[{session_id}] Relevant question limit reached (20), setting status=over")

            else:
                stream_generator = not_relevant_stream(content)
                no_relevant_count += 1
                current_not_relevant = True
                response_type = "no_relevant"
                logger.info(
                    f"[{session_id}] Routing to no_relevant (off-topic) | " f"no_relevant_count={no_relevant_count}"
                )
                if no_relevant_count >= 3:
                    status = "over"
                    termination_reason = SessionTerminationReason.OFF_TOPIC_LIMIT
                    logger.warning(f"[{session_id}] Off-topic limit reached (3), setting status=over")

    # Stream chunks from the selected generator
    if stream_generator:
        async for chunked_text, chunk_token_usage, full_text in stream_generator:
            if chunk_token_usage:
                token_usage = chunk_token_usage

            full_reply = full_text

            # Only yield non-empty text chunks (skip the final empty yield from stream functions)
            if chunked_text:
                sequence_number += 1
                chunk = StreamChunk(
                    response=chunked_text,
                    # router_result=router_result,
                    session_finished=(status == "over"),
                    duration=0.0,  # Will be set in final chunk
                    token_usage=None,  # Only in final chunk
                    finish=False,
                    sequence_number=sequence_number,
                    timestamp=time.time(),
                    session_id=session_id,
                    not_relevant=current_not_relevant,
                    relevant_question=current_relevant_question,
                    termination_reason=termination_reason,
                )
                yield chunk

    # Handle "over" status - append closing message
    if status == "over":
        over_replies = [
            "我们现在快回到书里的世界吧。",
            "我们的书本大冒险，继续出发吧！",
            "书里的角色还在等着我们，我们快回去吧！",
        ]
        over_reply = random.choice(over_replies)
        full_reply += over_reply

        logger.info(f"[{session_id}] Session ending | appending closing message: {over_reply}")

        # Chunk and stream the closing message
        over_chunks = chunk_text(over_reply)
        for chunked_text in over_chunks:
            sequence_number += 1
            chunk = StreamChunk(
                response=chunked_text,
                # router_result=router_result,
                session_finished=True,
                duration=0.0,
                token_usage=None,
                finish=False,
                sequence_number=sequence_number,
                timestamp=time.time(),
                session_id=session_id,
                not_relevant=current_not_relevant,
                relevant_question=current_relevant_question,
                termination_reason=termination_reason,
            )
            yield chunk

    # Calculate total duration
    end_time = time.time()
    elapsed_time = end_time - start_time

    logger.info(
        f"[{session_id}] call_Leonard_stream completed | "
        f"response_type={response_type}, duration={elapsed_time:.3f}s, "
        f"total_chunks={sequence_number}, reply_length={len(full_reply)}, "
        f"session_finished={status == 'over'}, "
        f"final_no_relevant_count={no_relevant_count}, "
        f"final_relevant_question_count={relevant_question_count}, "
        f"token_usage={token_usage.model_dump() if token_usage else 'N/A'}"
    )

    logger.debug(f"Full reply: {full_reply}")

    # Yield final chunk with token usage and duration
    sequence_number += 1
    final_chunk = StreamChunk(
        response=full_reply,
        # router_result=router_result,
        session_finished=(status == "over"),
        duration=elapsed_time,
        token_usage=token_usage,
        finish=True,
        sequence_number=sequence_number,
        timestamp=time.time(),
        session_id=session_id,
        not_relevant=current_not_relevant,
        relevant_question=current_relevant_question,
        termination_reason=termination_reason,
    )
    yield final_chunk
