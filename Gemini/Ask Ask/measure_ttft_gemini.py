"""
Measure true TTFT (Time To First Stream Chunk) for Gemini streaming,
including cold start vs warm start behavior.
"""

import time
from statistics import mean

from google import genai
from google.genai.types import HttpOptions


PROJECT_ID = "elaborate-baton-480304-r8"
REGION = "us-central1"
MODEL = "gemini-2.5-flash-lite"

import logging
import http.client as http_client

http_client.HTTPConnection.debuglevel = 1

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)
logging.getLogger("google").setLevel(logging.DEBUG)
def create_client():
    return genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=REGION,
        http_options=HttpOptions(api_version="v1"),
    )


def measure_ttft(client, prompt: str) -> float:
    """
    Returns TTFT in seconds (time to first stream chunk).
    """
    start = time.perf_counter()

    for chunk in client.models.generate_content_stream(
        model=MODEL,
        contents=prompt,
    ):
        # first chunk arrival
        return time.perf_counter() - start

    raise RuntimeError("No chunks received")


def warmup(client, rounds: int = 1):
    """
    Warm up auth, connection, and backend.
    """
    for _ in range(rounds):
        _ = client.models.generate_content(
            model=MODEL,
            contents="hi",
        )


def main():
    client = create_client()

    prompt = "Tell me a story in 300 words."

    print("=== Cold TTFT (no warmup) ===")
    cold_ttft = measure_ttft(client, prompt)
    print(f"Cold TTFT: {cold_ttft:.3f}s\n")

    print("=== Warmup ===")
    warmup(client, rounds=1)
    print("Warmup done\n")

    print("=== Warm TTFT (multiple runs) ===")
    warm_tts = []
    for i in range(5):
        ttft = measure_ttft(client, prompt)
        warm_tts.append(ttft)
        print(f"Run {i+1}: {ttft:.3f}s")

    print("\n=== Summary ===")
    print(f"Cold TTFT : {cold_ttft:.3f}s")
    print(f"Warm Avg  : {mean(warm_tts):.3f}s")
    print(f"Warm Min  : {min(warm_tts):.3f}s")
    print(f"Warm Max  : {max(warm_tts):.3f}s")


if __name__ == "__main__":
    main()
