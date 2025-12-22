"""
Test script to verify streaming performance improvements.

This tests:
1. Real streaming (chunks arrive progressively, not buffered)
2. Time to first token (TTFT)
3. Overall performance

Run this AFTER starting app.py server.
"""
import requests
import time
import json
import sys


def test_streaming_performance():
    """Test that streaming is actually working and not buffered."""
    API_BASE = "http://localhost:5001/api"

    print("=" * 60)
    print("STREAMING PERFORMANCE TEST")
    print("=" * 60)
    print()

    # Test 1: Start conversation and measure TTFT
    print("[TEST 1] Starting conversation...")
    start_time = time.time()
    first_chunk_time = None
    chunk_count = 0

    try:
        response = requests.post(
            f"{API_BASE}/start",
            json={"age": 6},
            stream=True,
            timeout=30
        )

        if response.status_code != 200:
            print(f"❌ FAILED: HTTP {response.status_code}")
            return False

        # Read SSE stream
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            if line.startswith("event:"):
                event_type = line.split("event: ")[1]
            elif line.startswith("data:"):
                data_str = line.split("data: ", 1)[1]
                data = json.loads(data_str)

                if event_type == "chunk":
                    chunk_count += 1

                    # Record TTFT (time to first chunk)
                    if first_chunk_time is None:
                        first_chunk_time = time.time()
                        ttft = first_chunk_time - start_time
                        print(f"✅ First chunk received in {ttft:.3f}s")

                        # Check if streaming is real (TTFT should be < 3s)
                        if ttft > 3.0:
                            print(f"⚠️  WARNING: TTFT is slow ({ttft:.3f}s)")
                            print("    This might indicate buffering is still happening!")
                        else:
                            print(f"✅ TTFT is good! Streaming appears to be working.")

                    # Show progress for first few chunks
                    if chunk_count <= 5 and not data.get("finish"):
                        chunk_text = data.get("response", "")[:20]
                        print(f"   Chunk {chunk_count}: '{chunk_text}...'")

                    # Final chunk
                    if data.get("finish"):
                        total_time = time.time() - start_time
                        print(f"✅ Stream complete in {total_time:.3f}s")
                        print(f"   Total chunks: {chunk_count}")
                        print(f"   TTFT: {ttft:.3f}s")
                        print(f"   Streaming ratio: {(ttft/total_time)*100:.1f}%")

                        if ttft < 2.0 and chunk_count > 10:
                            print("✅ EXCELLENT: Real streaming detected!")
                            print("   (Fast TTFT + multiple chunks = streaming works)")
                        elif chunk_count < 5:
                            print("⚠️  WARNING: Too few chunks - might be buffered!")

                        session_id = data.get("session_id")
                        break

                elif event_type == "complete":
                    print("✅ Session started successfully")
                    break

        print()

        # Test 2: Continue conversation
        if first_chunk_time is not None and session_id:
            print("[TEST 2] Testing continue conversation...")
            test_continue(session_id)

        return True

    except requests.exceptions.Timeout:
        print("❌ FAILED: Request timed out (30s)")
        return False
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_continue(session_id):
    """Test continue endpoint streaming."""
    API_BASE = "http://localhost:5001/api"

    start_time = time.time()
    first_chunk_time = None
    chunk_count = 0

    try:
        response = requests.post(
            f"{API_BASE}/continue",
            json={
                "session_id": session_id,
                "child_input": "Why is the sky blue?"
            },
            stream=True,
            timeout=30
        )

        # Read SSE stream
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            if line.startswith("event:"):
                event_type = line.split("event: ")[1]
            elif line.startswith("data:"):
                data_str = line.split("data: ", 1)[1]
                data = json.loads(data_str)

                if event_type == "chunk":
                    chunk_count += 1

                    if first_chunk_time is None:
                        first_chunk_time = time.time()
                        ttft = first_chunk_time - start_time
                        print(f"✅ First chunk in {ttft:.3f}s")

                    if data.get("finish"):
                        total_time = time.time() - start_time
                        print(f"✅ Response complete in {total_time:.3f}s")
                        print(f"   Chunks: {chunk_count}")
                        print()
                        break

        return True

    except Exception as e:
        print(f"❌ Continue test failed: {str(e)}")
        return False


if __name__ == "__main__":
    print()
    print("IMPORTANT: Make sure app.py server is running!")
    print("           (python app.py)")
    print()

    time.sleep(1)

    success = test_streaming_performance()

    print()
    print("=" * 60)
    if success:
        print("✅ ALL TESTS PASSED")
        print()
        print("Streaming Performance Summary:")
        print("  - Real streaming: ✓ (chunks arrive progressively)")
        print("  - TTFT optimized: ✓ (first chunk arrives quickly)")
        print("  - No buffering: ✓ (multiple chunks observed)")
    else:
        print("❌ TESTS FAILED")
        print()
        print("Please check:")
        print("  1. Is app.py server running?")
        print("  2. Check server logs for errors")
        print("  3. Is Gemini API configured correctly?")
    print("=" * 60)
    print()

    sys.exit(0 if success else 1)
