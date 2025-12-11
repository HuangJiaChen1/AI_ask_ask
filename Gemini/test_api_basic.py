"""
Basic API test to verify Gemini API is working
"""
import requests
import json
import sys
import io

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

API_KEY = config['gemini_api_key']
BASE_URL = config['api_base_url']
MODEL = config['model_name']

print("=" * 60)
print("Testing Gemini API Connection")
print("=" * 60)
print(f"API URL: {BASE_URL}")
print(f"Model: {MODEL}")
print(f"API Key: {API_KEY[:20]}..." if len(API_KEY) > 20 else API_KEY)
print("=" * 60)

# Test 1: Simple API call
print("\n[Test 1] Simple API call...")
try:
    response = requests.post(
        BASE_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "Say 'Hello World'"}]
        }
    )

    print(f"Status Code: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"Response keys: {data.keys()}")
        print(f"Full response:\n{json.dumps(data, indent=2)}")

        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
            print(f"\n✅ SUCCESS! Response: {content}")
        else:
            print(f"\n❌ ERROR: No 'choices' in response")
    else:
        print(f"❌ ERROR: Status {response.status_code}")
        print(f"Response: {response.text}")

except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

# Test 2: JSON mode request
print("\n" + "=" * 60)
print("[Test 2] JSON mode request...")
try:
    response = requests.post(
        BASE_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "user", "content": 'Respond with JSON: {"greeting": "hello", "number": 42}. IMPORTANT: Respond with ONLY valid JSON.'}
            ]
        }
    )

    print(f"Status Code: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
            print(f"\n✅ Response: {content}")

            # Try to parse as JSON
            try:
                parsed = json.loads(content)
                print(f"✅ Valid JSON! Parsed: {parsed}")
            except:
                print(f"⚠️  Response is not pure JSON, attempting extraction...")
                # Try to find JSON in the response
                import re
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        print(f"✅ Extracted JSON: {parsed}")
                    except:
                        print(f"❌ Could not parse extracted JSON")
        else:
            print(f"\n❌ ERROR: No 'choices' in response")
    else:
        print(f"❌ ERROR: Status {response.status_code}")
        print(f"Response: {response.text}")

except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Tests Complete")
print("=" * 60)
