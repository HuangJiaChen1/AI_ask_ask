import pytest
from unittest.mock import MagicMock, AsyncMock
import json
import asyncio
from google.genai.types import GenerateContentResponse

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

class MockGeminiModels:
    def __init__(self):
        self.generate_content = MagicMock()
        self.generate_content_stream = MagicMock()

class MockGeminiClient:
    def __init__(self, *args, **kwargs):
        self.models = MockGeminiModels()

@pytest.fixture
def mock_gemini_client(monkeypatch):
    """Mocks the global Gemini client in paixueji_app and PaixuejiAssistant."""
    client = MockGeminiClient()
    
    # Configure generate_content (sync) for classification
    mock_response_classification = MagicMock()
    mock_response_classification.text = "level2_category_key" 
    client.models.generate_content.return_value = mock_response_classification

    # Configure generate_content_stream (sync iterator in current impl, handled by async wrapper)
    # The real client returns a synchronous iterator for stream, which is wrapped in async generators in stream/*.py
    # wait, stream/*.py uses `client.models.generate_content_stream` which returns an iterator.
    # We can mock it to return a list of MockChunks.
    
    def side_effect_stream(model, contents, config=None):
        # Determine response based on content (simple keyword matching)
        content_str = str(contents)
        
        response_text = "Mock response"
        if "introduction" in content_str.lower() or "start conversation" in content_str.lower():
            response_text = "Hello! Let's talk about the apple. What color is it?"
        elif "feedback" in content_str.lower():
            response_text = "Great job! That is correct."
        elif "followup" in content_str.lower():
            response_text = " What shape is it?"
        elif "correction" in content_str.lower():
            response_text = "Actually, apples are usually red. "
        elif "explanation" in content_str.lower():
            response_text = "Apples are a type of fruit. "
            
        chunks = [MockChunk(word + " ") for word in response_text.split()]
        return MockStream(chunks)

    client.models.generate_content_stream.side_effect = side_effect_stream

    # Patch where it's used
    import paixueji_app
    monkeypatch.setattr(paixueji_app, "GLOBAL_GEMINI_CLIENT", client)
    
    # Also patch PaixuejiAssistant's default client init if needed, 
    # but since GLOBAL_GEMINI_CLIENT is passed, it should be enough if app uses it.
    # However, PaixuejiAssistant might create its own if not passed.
    # Let's verify usage in app.py: it passes `client=GLOBAL_GEMINI_CLIENT`.
    
    return client

@pytest.fixture
def client(mock_gemini_client):
    """Flask test client with mocked Gemini."""
    from paixueji_app import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client
