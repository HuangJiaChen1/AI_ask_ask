from google import genai
from google.genai.types import HttpOptions

client = genai.Client(
    vertexai=True,
    project="elaborate-baton-480304-r8",
    location="us-central1",   # IMPORTANT: this is a REGION, not a path
    http_options=HttpOptions(api_version="v1"),
)

for chunk in client.models.generate_content_stream(
    model='gemini-2.5-flash', contents='Tell me a story in 300 words.'
):
    print(chunk.text, end='//n')
