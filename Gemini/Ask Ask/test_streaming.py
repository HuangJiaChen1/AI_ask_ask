"""
Test script to verify if the Gemini API supports streaming mode.
This MUST be run first before implementing streaming functionality.
"""
import requests
import json
import sys


def test_streaming_support():
    """Test if the Gemini API supports streaming."""
    print("=" * 60)
    print("TESTING API STREAMING SUPPORT")
    print("=" * 60)

    # Load config
    try:
        with open("config.json", 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print("[X] ERROR: config.json not found")
        return False
    except json.JSONDecodeError:
        print("[X] ERROR: config.json is not valid JSON")
        return False

    # Validate config
    if "gemini_api_key" not in config:
        print("[X] ERROR: gemini_api_key not found in config.json")
        return False

    if config.get("gemini_api_key") == "YOUR_GEMINI_API_KEY_HERE":
        print("[X] ERROR: Please set your API key in config.json")
        return False

    headers = {
        "Authorization": f"Bearer {config['gemini_api_key']}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": config.get("model_name", "gemini-2.5-pro"),
        "messages": [
            {"role": "user", "content": "Count from 1 to 5, one number per line."}
        ],
        "stream": True,  # Enable streaming
        "temperature": 0.7,
        "max_tokens": 100
    }

    print(f"\nTesting API endpoint: {config.get('api_base_url', 'N/A')}")
    print(f"Model: {config.get('model_name', 'N/A')}")
    print(f"Streaming enabled: True")
    print("-" * 60)

    try:
        print("\nSending streaming request...")
        response = requests.post(
            config["api_base_url"],
            headers=headers,
            json=payload,
            stream=True,  # Important: Enable streaming in requests
            timeout=30
        )

        print(f"Response status: {response.status_code}")

        if response.status_code != 200:
            print(f"[X] ERROR: HTTP {response.status_code}")
            print(f"Response body: {response.text[:500]}")
            return False

        print("[OK] API accepted streaming request\n")
        print("Receiving chunks:")
        print("-" * 60)

        chunk_count = 0
        content_received = False

        for line in response.iter_lines():
            if line:
                chunk_count += 1
                decoded = line.decode('utf-8')

                # Show first few chunks for debugging
                if chunk_count <= 5:
                    print(f"Chunk {chunk_count}: {decoded[:100]}...")

                # Check if it's SSE format
                if decoded.startswith("data: "):
                    data_str = decoded[6:]  # Remove "data: " prefix

                    if data_str == "[DONE]":
                        print(f"\n[OK] Received [DONE] marker at chunk {chunk_count}")
                        break

                    try:
                        chunk_data = json.loads(data_str)
                        if "choices" in chunk_data:
                            delta = chunk_data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                content_received = True
                                if chunk_count <= 5:
                                    print(f"  -> Content: '{content}'")
                    except json.JSONDecodeError:
                        # Not JSON, could be plain text streaming
                        if chunk_count <= 5:
                            print(f"  -> Not JSON: {data_str[:50]}")

        print("-" * 60)
        print(f"\n[OK] Streaming works! Received {chunk_count} chunks")

        if content_received:
            print("[OK] Successfully received streaming content")
        else:
            print("[WARNING] No content chunks received (might still work)")

        return True

    except requests.exceptions.Timeout:
        print(f"\n[X] ERROR: Request timed out after 30 seconds")
        return False
    except requests.exceptions.RequestException as e:
        print(f"\n[X] ERROR: Request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Status: {e.response.status_code}")
            print(f"Body: {e.response.text[:500]}")
        return False
    except Exception as e:
        print(f"\n[X] ERROR: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point."""
    success = test_streaming_support()

    print("\n" + "=" * 60)
    if not success:
        print("[FAIL] STREAMING NOT SUPPORTED")
        print("=" * 60)
        print("\nThe Gemini API endpoint does not support streaming mode.")
        print("Cannot proceed with streaming implementation.")
        print("\nPossible reasons:")
        print("  1. API endpoint doesn't support 'stream: true' parameter")
        print("  2. API key is invalid or expired")
        print("  3. Network/firewall issues")
        print("  4. API endpoint URL is incorrect")
        print("\nPlease check your config.json and API documentation.")
        sys.exit(1)
    else:
        print("[SUCCESS] STREAMING SUPPORTED - PROCEED WITH IMPLEMENTATION")
        print("=" * 60)
        print("\nThe API supports streaming mode!")
        print("You can now proceed with implementing the streaming chatbot.")
        sys.exit(0)


if __name__ == "__main__":
    main()
