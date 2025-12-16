"""
Test real streaming with official Google Gemini SDK.
This will verify we get true token-by-token streaming, not batched responses.
"""
import json
import time
from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig


def test_official_streaming():
    """Test streaming with official SDK - detailed timing and chunk analysis."""

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
    print("OFFICIAL SDK STREAMING TEST")
    print("=" * 80)
    print(f"\nProject: {config['project']}")
    print(f"Location: {config['location']}")
    print(f"Model: {config['model_name']}")
    print("\nSending request at:", time.strftime("%H:%M:%S"))
    print("Question: Write a short poem about cats (2 lines)")
    print("\n" + "-" * 80)
    print("CHUNKS RECEIVED:")
    print("-" * 80)

    start_time = time.time()

    try:
        # Configure streaming request
        gen_config = GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=100
        )

        # Stream response
        stream = client.models.generate_content_stream(
            model=config["model_name"],
            contents="Write a short poem about cats (2 lines)",
            config=gen_config
        )

        chunk_number = 0
        total_content = ""
        content_chunks = []

        for chunk in stream:
            if chunk.text:
                chunk_number += 1
                elapsed = time.time() - start_time

                print(f"\n[Chunk {chunk_number}] at {elapsed:.3f}s:")
                print(f"  Content: '{chunk.text}'")
                print(f"  Length: {len(chunk.text)} characters")

                content_chunks.append({
                    'time': elapsed,
                    'content': chunk.text,
                    'length': len(chunk.text)
                })
                total_content += chunk.text

        elapsed = time.time() - start_time

        print("\n" + "=" * 80)
        print("ANALYSIS RESULTS:")
        print("=" * 80)
        print(f"\nTotal chunks received: {chunk_number}")
        print(f"Content chunks: {len(content_chunks)}")
        print(f"Total time: {elapsed:.3f}s")

        if content_chunks:
            print(f"\nChunk sizes:")
            for i, chunk in enumerate(content_chunks, 1):
                content_preview = chunk['content'].replace('\n', '\\n')[:50]
                print(f"  Chunk {i}: {chunk['length']} chars at {chunk['time']:.3f}s - '{content_preview}...'")

            avg_chunk_size = sum(c['length'] for c in content_chunks) / len(content_chunks)
            print(f"\nAverage chunk size: {avg_chunk_size:.1f} characters")

            if len(content_chunks) > 1:
                time_between = [(content_chunks[i]['time'] - content_chunks[i-1]['time'])
                               for i in range(1, len(content_chunks))]
                avg_gap = sum(time_between) / len(time_between)
                print(f"Average time between chunks: {avg_gap:.3f}s")

            print(f"\n{'='*80}")
            print("FULL RESPONSE:")
            print("=" * 80)
            print(total_content)
            print("=" * 80)

            # Determine streaming type
            print("\nSTREAMING TYPE ANALYSIS:")
            if len(content_chunks) == 1:
                print("[X] NOT STREAMING - Received entire response in ONE chunk")
                print("   This is just a regular API call, not true streaming")
            elif avg_chunk_size > 50:
                print("[!] BATCHED STREAMING - Large chunks (avg {:.0f} chars)".format(avg_chunk_size))
                print("   API sends in batches, not token-by-token")
            elif avg_chunk_size < 5:
                print("[OK] TRUE STREAMING - Small chunks (avg {:.0f} chars)".format(avg_chunk_size))
                print("   Real token-by-token or word-by-word streaming!")
            else:
                print("[~] MODERATE STREAMING - Medium chunks (avg {:.0f} chars)".format(avg_chunk_size))
                print("   Streaming with some buffering")

        return True

    except Exception as e:
        print(f"\n[X] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_official_streaming()
    if success:
        print("\n" + "=" * 80)
        print("[SUCCESS] Official SDK streaming test completed")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print("[FAIL] Official SDK streaming test failed")
        print("=" * 80)
