"""
Test streaming with a longer prompt to see if we get multiple chunks.
"""
import json
import time
from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig


def test_long_streaming():
    """Test streaming with a longer response to see chunk patterns."""

    # Load config
    with open("config.json", 'r') as f:
        config = json.load(f)

    # Initialize client
    client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1")
    )

    print("=" * 80)
    print("LONG STREAMING TEST - Detailed Chunk Analysis")
    print("=" * 80)
    print("\nPrompt: Tell me a story about a cat (at least 5 sentences)")
    print("\n" + "-" * 80)

    start_time = time.time()

    try:
        # Configure streaming request with higher max tokens
        gen_config = GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=500
        )

        # Stream response
        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents="Tell me a story about a cat. Make it at least 5 sentences long.",
            config=gen_config
        )

        chunk_number = 0
        total_content = ""
        content_chunks = []

        print("Streaming chunks as they arrive:")
        print("-" * 80)

        for chunk in stream:
            if chunk.text:
                chunk_number += 1
                elapsed = time.time() - start_time

                # Display chunk immediately
                print(f"[{chunk_number}] {elapsed:.3f}s: {repr(chunk.text[:60])}")

                content_chunks.append({
                    'time': elapsed,
                    'content': chunk.text,
                    'length': len(chunk.text)
                })
                total_content += chunk.text

        elapsed = time.time() - start_time

        print("\n" + "=" * 80)
        print("RESULTS:")
        print("=" * 80)
        print(f"Total chunks: {chunk_number}")
        print(f"Total time: {elapsed:.3f}s")
        print(f"Total characters: {len(total_content)}")

        if content_chunks:
            avg_chunk_size = sum(c['length'] for c in content_chunks) / len(content_chunks)
            print(f"Average chunk size: {avg_chunk_size:.1f} characters")

            if len(content_chunks) > 1:
                time_between = [(content_chunks[i]['time'] - content_chunks[i-1]['time'])
                               for i in range(1, len(content_chunks))]
                avg_gap = sum(time_between) / len(time_between)
                print(f"Average time between chunks: {avg_gap:.3f}s")

            print("\n" + "=" * 80)
            print("VERDICT:")
            print("=" * 80)
            if len(content_chunks) == 1:
                print("[X] FAIL - Only 1 chunk (no streaming)")
            elif len(content_chunks) < 5:
                print(f"[!] POOR - Only {len(content_chunks)} chunks (heavy buffering)")
            elif avg_chunk_size < 10:
                print(f"[OK] GOOD - {len(content_chunks)} chunks, avg {avg_chunk_size:.1f} chars (real streaming)")
            else:
                print(f"[~] MODERATE - {len(content_chunks)} chunks, avg {avg_chunk_size:.1f} chars (some buffering)")

            print("\n" + "=" * 80)
            print("FULL STORY:")
            print("=" * 80)
            print(total_content)
            print("=" * 80)

        return True

    except Exception as e:
        print(f"\n[X] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_long_streaming()
