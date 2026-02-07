from google import genai
import json
import os

try:
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    client = genai.Client(
        vertexai=True, 
        project=config['project'], 
        location=config['location']
    )
    
    print("Available Models:")
    for model in client.models.list():
        print(f"- {model.name}")
except Exception as e:
    print(f"Error: {e}")
