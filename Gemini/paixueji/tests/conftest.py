import pytest
from unittest.mock import MagicMock, AsyncMock
import json
import asyncio

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