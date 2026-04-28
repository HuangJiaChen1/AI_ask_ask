import pytest
from unittest.mock import MagicMock, AsyncMock
import json
import asyncio
import sys
import types

if "flask_cors" not in sys.modules:
    flask_cors_module = types.ModuleType("flask_cors")

    def CORS(*args, **kwargs):
        return None

    flask_cors_module.CORS = CORS
    sys.modules["flask_cors"] = flask_cors_module

if "loguru" not in sys.modules:
    loguru_module = types.ModuleType("loguru")
    loguru_module.logger = MagicMock()
    sys.modules["loguru"] = loguru_module

google_module = sys.modules.get("google")
if google_module is None:
    google_module = types.ModuleType("google")
    sys.modules["google"] = google_module

genai_module = types.ModuleType("google.genai")
genai_types_module = types.ModuleType("google.genai.types")


class HttpOptions:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class GenerateContentConfig:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class Tool:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class GoogleSearch:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


genai_types_module.HttpOptions = HttpOptions
genai_types_module.GenerateContentConfig = GenerateContentConfig
genai_types_module.Tool = Tool
genai_types_module.GoogleSearch = GoogleSearch
genai_module.types = genai_types_module
genai_module.Client = MagicMock
google_module.genai = genai_module
sys.modules["google.genai"] = genai_module
sys.modules["google.genai.types"] = genai_types_module

# Mock classes to simulate Gemini API behavior

class MockChunk:
    def __init__(self, text):
        self.text = text

class MockStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        for chunk in self.chunks:
            yield chunk
            
    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

class MockGeminiModels:
    def __init__(self, is_async=False):
        if is_async:
            self.generate_content = AsyncMock()
            self.generate_content_stream = AsyncMock()
        else:
            self.generate_content = MagicMock()
            self.generate_content_stream = MagicMock()

class MockGeminiClient:
    def __init__(self, *args, **kwargs):
        self.models = MockGeminiModels(is_async=False)
        self.aio = MagicMock()
        self.aio.models = MockGeminiModels(is_async=True)

@pytest.fixture
def mock_gemini_client(monkeypatch):
    """Mocks the global Gemini client in paixueji_app and PaixuejiAssistant."""
    client = MockGeminiClient()
    
    # Common response text
    default_text = "Mock response from Gemini."
    
    # --- Sync Mock Configuration ---
    mock_response_sync = MagicMock()
    # Return a valid JSON string for classification or generic text
    mock_response_sync.text = json.dumps({
        "theme_id": "nature",
        "theme_name": "Nature",
        "reason": "Test",
        "key_concept": "Change",
        "bridge_question": "How does it change?",
        "thinking": "Test"
    })
    client.models.generate_content.return_value = mock_response_sync

    # --- Async Mock Configuration (aio) ---
    mock_response_async = MagicMock()
    # classify_intent() parses plain-text with INTENT:/NEW_OBJECT:/REASONING: regex
    mock_response_async.text = "INTENT: CLARIFYING_IDK\nNEW_OBJECT: null\nREASONING: Mock classification"
    client.aio.models.generate_content.return_value = mock_response_async

    def side_effect_stream(model, contents, config=None):
        response_text = "Hello! Let's talk about the object. What color is it?"
        chunks = [MockChunk(word + " ") for word in response_text.split()]
        return MockStream(chunks)

    client.models.generate_content_stream.side_effect = side_effect_stream
    client.aio.models.generate_content_stream.side_effect = side_effect_stream

    # Patch the global client in the app
    import paixueji_app
    monkeypatch.setattr(paixueji_app, "GLOBAL_GEMINI_CLIENT", client)
    
    return client

@pytest.fixture
def client(mock_gemini_client):
    """Flask test client with mocked Gemini."""
    from paixueji_app import app
    app.config['TESTING'] = True
    # We must reset the sessions for each test to ensure isolation
    import paixueji_app
    paixueji_app.sessions = {}
    with app.test_client() as client:
        yield client
