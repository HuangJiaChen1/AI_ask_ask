"""
Test TTFT (Time To First Token) and identify bottlenecks.
"""
import json
import time
from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig


def test_ttft_simple():
    """Test TTFT with minimal prompt."""
    with open("config.json", 'r') as f:
        config = json.load(f)

    client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1")
    )

    print("=" * 80)
    print("TTFT TEST - Minimal Prompt")
    print("=" * 80)

    # Test 1: Minimal prompt
    print("\n[Test 1] Minimal prompt: 'Hi!'")
    start = time.time()

    gen_config = GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=50
    )

    stream = client.models.generate_content_stream(
        model=config["model_name"],
        contents="Hi!",
        config=gen_config
    )

    first_chunk_time = None
    for i, chunk in enumerate(stream):
        if chunk.text and first_chunk_time is None:
            first_chunk_time = time.time() - start
            print(f"  TTFT: {first_chunk_time:.3f}s")
            preview = chunk.text[:50].encode('utf-8', errors='ignore').decode('utf-8')
            print(f"  First chunk: {len(chunk.text)} chars")
            break

    print("\n" + "-" * 80)

    # Test 2: Medium system prompt
    print("\n[Test 2] With system instruction (similar to app)")
    start = time.time()

    system_instruction = """You are a helpful assistant for children.
Be warm and friendly. Use simple language."""

    gen_config = GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=100,
        system_instruction=system_instruction
    )

    stream = client.models.generate_content_stream(
        model=config["model_name"],
        contents="Say a friendly hello!",
        config=gen_config
    )

    first_chunk_time = None
    for i, chunk in enumerate(stream):
        if chunk.text and first_chunk_time is None:
            first_chunk_time = time.time() - start
            print(f"  TTFT: {first_chunk_time:.3f}s")
            preview = chunk.text[:50].encode('utf-8', errors='ignore').decode('utf-8')
            print(f"  First chunk: {len(chunk.text)} chars")
            break

    print("\n" + "-" * 80)

    # Test 3: Full app-like prompt
    print("\n[Test 3] Full app-like system prompt + introduction request")
    start = time.time()

    system_instruction = """You are a curious and enthusiastic learning companion for young children!
Your job is to answer children's questions in a fun, educational, and age-appropriate way.

YOUR PERSONALITY:
- Warm, playful, and encouraging
- Use simple, clear language
- Sound excited about learning!

STYLE:
- Short, simple, exciting sentences
- Use emojis to make it fun!

AGE-SPECIFIC GUIDANCE:
Focus on WHAT and HOW questions. Ask about properties, features, processes, and actions."""

    introduction_prompt = """Generate a warm, exciting introduction for a curious child.

Your introduction should:
1. Greet the child warmly
2. Explain that they can ask ANY question
3. Give 2-3 example topics
4. Invite them to ask their first question

Keep it SHORT (2-3 sentences) and EXCITING!"""

    gen_config = GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=150,
        system_instruction=system_instruction
    )

    stream = client.models.generate_content_stream(
        model=config["model_name"],
        contents=introduction_prompt,
        config=gen_config
    )

    first_chunk_time = None
    total_chunks = 0
    for i, chunk in enumerate(stream):
        if chunk.text:
            total_chunks += 1
            if first_chunk_time is None:
                first_chunk_time = time.time() - start
                print(f"  TTFT: {first_chunk_time:.3f}s")
                print(f"  First chunk: {repr(chunk.text[:50])}")

    print(f"  Total chunks: {total_chunks}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("Baseline TTFT should be 1-3 seconds for Gemini Flash")
    print("If TTFT > 3s, consider:")
    print("  - Shorter system prompts")
    print("  - Lower max_output_tokens")
    print("  - Temperature closer to 0")
    print("=" * 80)


if __name__ == "__main__":
    test_ttft_simple()
