"""
Test real-world TTFT by calling the Flask API.
"""
import requests
import time
import json


def test_real_ttft():
    """Test TTFT via the actual Flask API endpoint."""
    print("=" * 80)
    print("REAL-WORLD TTFT TEST (via Flask API)")
    print("=" * 80)

    url = "http://localhost:5001/api/start"
    payload = {"age": 6}

    print(f"Calling: POST {url}")
    print(f"Payload: {payload}")
    print()

    start_time = time.time()
    first_chunk_time = None
    metadata_time = None
    chunk_count = 0
    text_chunks = []

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=30
        )

        if response.status_code != 200:
            print(f"[ERROR] HTTP {response.status_code}")
            print(response.text)
            return

        buffer = ""
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                buffer += decoded + "\n"

                # Check if we have a complete event
                if "\n\n" in buffer or not line:
                    parts = buffer.split("\n")
                    event_type = None
                    data_json = None

                    for part in parts:
                        if part.startswith("event: "):
                            event_type = part[7:]
                        elif part.startswith("data: "):
                            data_json = part[6:]

                    if event_type and data_json:
                        elapsed = time.time() - start_time
                        data = json.loads(data_json)

                        if event_type == "metadata":
                            if metadata_time is None:
                                metadata_time = elapsed
                                print(f"[{elapsed:.3f}s] metadata: {data}")

                        elif event_type == "text_chunk":
                            chunk_count += 1
                            text = data.get("text", "")
                            text_chunks.append(text)

                            if first_chunk_time is None:
                                first_chunk_time = elapsed
                                print(f"[{elapsed:.3f}s] FIRST TEXT CHUNK!")
                                print(f"           Text: {text[:50]}...")

                        elif event_type == "complete":
                            total_time = elapsed
                            print(f"[{elapsed:.3f}s] complete: stream ended")

                        buffer = ""

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return

    # Results
    total_text = "".join(text_chunks)

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    if metadata_time:
        print(f"Metadata received: {metadata_time:.3f}s")
    if first_chunk_time:
        print(f"TTFT (Time To First Token): {first_chunk_time:.3f}s")
    else:
        print("No text chunks received!")
    print(f"Total chunks: {chunk_count}")
    print(f"Total response length: {len(total_text)} chars")
    print()
    print(f"Full response:")
    print(f"  {total_text}")

    print("\n" + "=" * 80)
    if first_chunk_time:
        if first_chunk_time < 2.0:
            print("[EXCELLENT] TTFT < 2s")
        elif first_chunk_time < 2.5:
            print("[GOOD] TTFT 2-2.5s")
        elif first_chunk_time < 3.0:
            print("[OK] TTFT 2.5-3s")
        else:
            print("[SLOW] TTFT > 3s - needs more optimization")
    print("=" * 80)


if __name__ == "__main__":
    test_real_ttft()
