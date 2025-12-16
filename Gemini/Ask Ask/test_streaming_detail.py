"""
Detailed streaming diagnostic - see exactly what chunks arrive and when.
This will reveal if we're truly streaming or receiving batches.
"""
import requests
import json
import time


def test_streaming_detail():
    """Test streaming with detailed timing and chunk analysis."""

    # Load config
    with open("config.json", 'r') as f:
        config = json.load(f)

    headers = {
        "Authorization": f"Bearer {config['gemini_api_key']}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": config["model_name"],
        "messages": [
            {"role": "user", "content": "Write a short poem about cats (2 lines)"}
        ],
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 100
    }

    print("=" * 80)
    print("DETAILED STREAMING ANALYSIS")
    print("=" * 80)
    print("\nSending request at:", time.strftime("%H:%M:%S"))
    print("Question: Write a short poem about cats (2 lines)")
    print("\n" + "-" * 80)
    print("CHUNKS RECEIVED:")
    print("-" * 80)

    start_time = time.time()

    try:
        response = requests.post(
            config["api_base_url"],
            headers=headers,
            json=payload,
            stream=True,
            timeout=30
        )
        response.raise_for_status()

        chunk_number = 0
        total_content = ""
        content_chunks = []

        for line in response.iter_lines():
            if line:
                chunk_number += 1
                elapsed = time.time() - start_time
                decoded = line.decode('utf-8')

                print(f"\n[Chunk {chunk_number}] at {elapsed:.3f}s:")

                if decoded.startswith("data: "):
                    data_str = decoded[6:]

                    if data_str == "[DONE]":
                        print("  Type: [DONE] marker")
                        break

                    try:
                        chunk_data = json.loads(data_str)

                        if "choices" in chunk_data:
                            delta = chunk_data["choices"][0].get("delta", {})
                            content = delta.get("content", "")

                            if content:
                                content_chunks.append({
                                    'time': elapsed,
                                    'content': content,
                                    'length': len(content)
                                })
                                total_content += content

                                print(f"  Content: '{content}'")
                                print(f"  Length: {len(content)} characters")
                                print(f"  Type: {'word' if ' ' in content or len(content) > 3 else 'token/char'}")
                            else:
                                print(f"  Empty content chunk")
                        else:
                            print(f"  No choices in chunk")

                    except json.JSONDecodeError as e:
                        print(f"  JSON decode error: {e}")

        print("\n" + "=" * 80)
        print("ANALYSIS RESULTS:")
        print("=" * 80)
        print(f"\nTotal chunks received: {chunk_number}")
        print(f"Content chunks: {len(content_chunks)}")
        print(f"Total time: {elapsed:.3f}s")

        if content_chunks:
            print(f"\nChunk sizes:")
            for i, chunk in enumerate(content_chunks, 1):
                print(f"  Chunk {i}: {chunk['length']} chars at {chunk['time']:.3f}s - '{chunk['content'][:50]}...'")

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
                print("❌ NOT STREAMING - Received entire response in ONE chunk")
                print("   This is just a regular API call, not true streaming")
            elif avg_chunk_size > 50:
                print("⚠️  BATCHED STREAMING - Large chunks (avg {:.0f} chars)".format(avg_chunk_size))
                print("   API sends in batches, not token-by-token")
            elif avg_chunk_size < 5:
                print("✅ TRUE STREAMING - Small chunks (avg {:.0f} chars)".format(avg_chunk_size))
                print("   Real token-by-token or word-by-word streaming!")
            else:
                print("~ MODERATE STREAMING - Medium chunks (avg {:.0f} chars)".format(avg_chunk_size))
                print("   Streaming with some buffering")

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_streaming_detail()
