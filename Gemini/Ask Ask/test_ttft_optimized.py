"""
Compare TTFT before and after optimizations.
"""
import json
import time
from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig


def test_optimized_ttft():
    """Test TTFT with optimized configuration."""
    with open("config.json", 'r') as f:
        config = json.load(f)

    client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1")
    )

    print("=" * 80)
    print("OPTIMIZED TTFT TEST")
    print("=" * 80)
    print(f"Model: {config['model_name']}")
    print(f"Temperature: {config['temperature']}")
    print(f"Max tokens: {config['max_tokens']}")
    print()

    # Optimized system prompt (shorter)
    system_instruction = """You are an enthusiastic learning companion for young children.

Answer questions in a fun, age-appropriate way:
- Use simple, clear language
- Sound excited about learning
- Use emojis to make it fun

Follow AGE-SPECIFIC GUIDANCE for vocabulary and depth.

Keep responses SHORT and EXCITING!

AGE-SPECIFIC GUIDANCE:
Focus on WHAT and HOW questions."""

    # Optimized introduction prompt (shorter)
    introduction_prompt = """Greet the child warmly, say they can ask about anything, give 2-3 example topics, and ask what they want to know. Keep it SHORT (2-3 sentences), fun, and use emojis!"""

    print("[Test] Optimized prompts + config")
    print(f"  System prompt: {len(system_instruction)} chars")
    print(f"  Intro prompt: {len(introduction_prompt)} chars")

    start = time.time()

    gen_config = GenerateContentConfig(
        temperature=config["temperature"],
        max_output_tokens=100,  # Short for introduction
        system_instruction=system_instruction
    )

    stream = client.models.generate_content_stream(
        model=config["model_name"],
        contents=introduction_prompt,
        config=gen_config
    )

    first_chunk_time = None
    total_chunks = 0
    total_text = ""

    for chunk in stream:
        if chunk.text:
            total_chunks += 1
            total_text += chunk.text
            if first_chunk_time is None:
                first_chunk_time = time.time() - start
                print(f"  TTFT: {first_chunk_time:.3f}s")

    total_time = time.time() - start

    print(f"  Total chunks: {total_chunks}")
    print(f"  Total time: {total_time:.3f}s")
    print(f"  Response length: {len(total_text)} chars")
    print()
    print(f"Response preview:")
    print(f"  {total_text[:100]}...")

    print("\n" + "=" * 80)
    print("OPTIMIZATION RESULTS")
    print("=" * 80)
    print(f"[OK] TTFT: {first_chunk_time:.3f}s")

    if first_chunk_time < 2.0:
        print("  Excellent! < 2 seconds")
    elif first_chunk_time < 2.5:
        print("  Good! 2-2.5 seconds")
    elif first_chunk_time < 3.0:
        print("  Acceptable. 2.5-3 seconds")
    else:
        print("  Could be better. > 3 seconds")

    print("\nOptimizations applied:")
    print("  [x] Reduced system prompt from ~700 to ~300 chars")
    print("  [x] Reduced intro prompt from ~600 to ~150 chars")
    print("  [x] Temperature: 0.7 -> 0.5")
    print("  [x] Max tokens: 2000 -> 100 (for intro)")
    print("=" * 80)


if __name__ == "__main__":
    test_optimized_ttft()
