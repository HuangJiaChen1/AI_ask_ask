"""
Utility functions for stream processing.

This module contains helper functions for message preparation,
format conversion, and other utilities used across stream modules.
"""
import random
from loguru import logger

# Configure loguru for this module
logger.add(
    "logs/paixueji_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    backtrace=True,
    diagnose=True,
)

# Performance thresholds for warnings (in seconds)
SLOW_LLM_CALL_THRESHOLD = 5.0
HIGH_IMAGINATION_HOOKS = {"想象导向", "情绪投射", "角色代入", "创意改造"}


def safe_print(message):
    """Print message with fallback for encoding errors."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('ascii', 'replace').decode('ascii'))


def clean_messages_for_api(messages: list[dict]) -> list[dict]:
    """
    Remove internal tracking fields from messages before sending to API.

    Args:
        messages: List of message dicts that may contain internal fields

    Returns:
        Cleaned list of messages with only standard fields (role, content)
    """
    cleaned = []
    for msg in messages:
        cleaned_msg = {
            k: v
            for k, v in msg.items()
            if k in ["role", "content"]  # Only keep standard fields
        }
        cleaned.append(cleaned_msg)
    return cleaned


def prepare_messages_for_streaming(messages: list[dict], age_prompt: str = "") -> list[dict]:
    """
    Safely prepare messages for streaming API calls without mutating the original list.

    This function:
    1. Creates a shallow copy of the messages list (10-100x faster than deep copy)
    2. Cleans messages to only include role/content
    3. Optionally appends age-specific guidance to system message

    Args:
        messages: Original message list (will not be modified)
        age_prompt: Optional age-specific guidance to append to system message

    Returns:
        New cleaned message list ready for API calls
    """
    # Shallow copy is sufficient - we only modify the list structure, not the dicts
    # This is 10-100x faster than deep copy for long conversation histories
    messages_copy = messages.copy()

    # Clean messages
    messages_copy = clean_messages_for_api(messages_copy)

    # Append age guidance to system message if provided
    if age_prompt and messages_copy and messages_copy[0].get("role") == "system":
        # Need to copy the first dict since we're modifying its content
        messages_copy[0] = messages_copy[0].copy()
        messages_copy[0]["content"] += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"

    return messages_copy


def convert_messages_to_gemini_format(messages: list[dict]) -> tuple[str, list[dict]]:
    """
    Convert OpenAI-style messages to Gemini format.

    OpenAI format: [{"role": "system"/"user"/"assistant", "content": "..."}]
    Gemini format: (system_instruction, contents_array)

    Returns:
        tuple: (system_instruction_str, contents_array)
    """
    system_instruction = ""
    contents = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "system":
            # System messages become system_instruction
            system_instruction += content + "\n"
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            # Convert "assistant" to "model" for Gemini
            contents.append({"role": "model", "parts": [{"text": content}]})

    return system_instruction.strip(), contents


def select_hook_type(age: int, messages: list, hook_types: dict) -> tuple[str, str]:
    """
    Select a hook type for the introduction question using age-weighted random sampling.

    Args:
        age: Child's age (3-8)
        messages: Current conversation history (used to check history length)
        hook_types: Dict loaded from hook_types.json

    Returns:
        (hook_type_name, hook_type_section_string) — the selected hook name and
        a formatted block ready to inject into the INTRODUCTION_PROMPT.
    """
    resolved_age = min(max(age or 5, 3), 8)
    age_str = str(resolved_age)  # clamp to supported range; default 5 if None

    pool = []
    weights = []

    for name, hook in hook_types.items():
        # Exclude hooks that need conversation context when not enough history exists
        if hook.get("requires_history", False) and len(messages) < 4:
            continue

        base_weight = hook.get("age_weights", {}).get(age_str, 1)

        # 意图好奇 is best for child-created objects; penalise in general sessions
        if name == "意图好奇":
            base_weight *= 0.5

        pool.append(name)
        weights.append(base_weight)

    # Younger children default to concrete openings. If any low-imagination hooks
    # are available, remove the high-imagination ones from the intro pool.
    if resolved_age <= 6:
        filtered = [
            (name, weight)
            for name, weight in zip(pool, weights)
            if name not in HIGH_IMAGINATION_HOOKS
        ]
        if filtered:
            pool = [name for name, _ in filtered]
            weights = [weight for _, weight in filtered]

    if not pool:
        # Fallback: pick any hook that doesn't require history
        for name, hook in hook_types.items():
            if not hook.get("requires_history", False):
                pool.append(name)
                weights.append(1.0)

    selected_name = random.choices(pool, weights=weights, k=1)[0]
    hook = hook_types[selected_name]

    examples_text = "\n".join(f'    "{ex}"' for ex in hook.get("examples", []))
    section = (
        f"Hook style: {hook['name']}\n"
        f"  Concept: {hook['concept']}\n"
        f"  Examples:\n{examples_text}"
    )

    logger.debug(f"select_hook_type | age={age}, selected={selected_name}, pool_size={len(pool)}")
    return selected_name, section


def extract_previous_response(messages: list[dict]) -> str:
    """
    Extract the last full response by the assistant from conversation history.

    This looks for the most recent assistant message and returns it.
    The assistant turn contains the full combined response text (explanation,
    wow detail, and closing question), not just the question alone.
    Used to provide rich context when the child reacts to any part of the
    previous turn (fun fact, explanation, question, etc.).

    Args:
        messages: Conversation history (list of role/content dicts)

    Returns:
        The last assistant message, or a fallback string if not found
    """
    # Walk backwards through messages to find last assistant message
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            # Return the full content (response + question combined)
            return content

    # Fallback if no assistant message found (shouldn't happen in practice)
    return "the previous response"
