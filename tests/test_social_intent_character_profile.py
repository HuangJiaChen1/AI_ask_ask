import inspect
from stream.response_generators import generate_intent_response_stream


def test_generate_intent_response_stream_accepts_character_profile():
    sig = inspect.signature(generate_intent_response_stream)
    assert "character_profile" in sig.parameters, (
        "generate_intent_response_stream must accept character_profile parameter"
    )
