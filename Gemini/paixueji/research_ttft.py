
import time
import asyncio
import json
import os
from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig

# Setup
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except:
    print("Config not found")
    exit()

client = genai.Client(
    vertexai=True,
    project=config["project"],
    location=config["location"],
    http_options=HttpOptions(api_version="v1")
)

# Warmup
print("Warming up...")
client.models.generate_content(model=config["model_name"], contents="hi")

async def run_baseline():
    print("\n--- BASELINE: Pipeline Approach ---")
    start_total = time.time()
    
    # 1. Validation Step
    val_prompt = """You are an educational AI.
    CONTEXT: Object='banana', Question='Color?', Answer='Yellow'
    TASK: Evaluate.
    RESPOND WITH JSON: {\"is_correct\": true, \"decision\": \"CONTINUE\"}
    """
    
    t0 = time.time()
    val_resp = client.models.generate_content(
        model=config["model_name"],
        contents=val_prompt,
        config={"response_mime_type": "application/json", "max_output_tokens": 100}
    )
    t_val = time.time() - t0
    print(f"Validation Time: {t_val:.4f}s")
    
    # 2. Response Generation Step
    # Assuming we parsed JSON and decided to give Feedback
    gen_prompt = """User answered 'Yellow' correctly about Banana.
    Task: Celebrate enthusiasticly. Short.
    """
    
    t0 = time.time()
    stream = client.models.generate_content_stream(
        model=config["model_name"],
        contents=gen_prompt,
        config={"max_output_tokens": 200}
    )
    
    first_token_time = None
    full_text = ""
    for chunk in stream:
        if first_token_time is None:
            first_token_time = time.time()
        if chunk.text:
            full_text += chunk.text
            
    t_gen_ttft = first_token_time - t0
    print(f"Generation TTFT: {t_gen_ttft:.4f}s")
    
    total_ttft = t_val + t_gen_ttft
    print(f"TOTAL TTFT (User Wait): {total_ttft:.4f}s")
    return total_ttft

async def run_single_pass():
    print("\n--- EXPERIMENTAL: Single Pass Approach ---")
    start_total = time.time()
    
    # Combined Prompt
    # Instruction: Respond FIRST, then validate.
    combined_prompt = """You are an educational AI.
    CONTEXT: Object='banana', Question='Color?', Answer='Yellow'
    
    TASK:
    1. Respond to the child immediately.
       - If correct: Celebrate.
       - If wrong: Gently correct.
       - If unrelated: Address it.
    2. AFTER the response, output a separator "---JSON---" followed by validation JSON: {\"is_correct\": bool, \"decision\": \"...\"}
    
    Start response immediately:
    """
    
    t0 = time.time()
    stream = client.models.generate_content_stream(
        model=config["model_name"],
        contents=combined_prompt,
        config={"max_output_tokens": 300}
    )
    
    first_token_time = None
    full_text = ""
    json_part = ""
    
    for chunk in stream:
        if first_token_time is None:
            first_token_time = time.time()
        if chunk.text:
            full_text += chunk.text
    
    t_ttft = first_token_time - t0
    print(f"TOTAL TTFT (User Wait): {t_ttft:.4f}s")
    print(f"Full Output Preview: {full_text[:50]}... ...{full_text[-50:]}")
    return t_ttft

async def main():
    baseline_time = await run_baseline()
    single_pass_time = await run_single_pass()
    
    improvement = baseline_time - single_pass_time
    percent = (improvement / baseline_time) * 100
    print(f"\nImprovement: {improvement:.4f}s ({percent:.1f}%)")

if __name__ == "__main__":
    asyncio.run(main())
