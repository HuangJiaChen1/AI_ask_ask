import pytest
from unittest.mock import AsyncMock, MagicMock
from stream.verification_guided_conversation import (
    VerificationItem,
    build_verification_context,
    classify_verification,
    check_probe_needed,
)


def test_verification_item_dataclass():
    item = VerificationItem(
        property="has_polka_dots",
        question="Does it have polka dots?",
        for_activity_id="polka_dot_patrol",
    )
    assert item.property == "has_polka_dots"
    assert item.status == "pending"


def test_build_verification_context_with_pending_items():
    items = [
        VerificationItem(property="has_spots", question="Does the cat have spots?", for_activity_id="polka_dot_patrol"),
    ]
    ctx = build_verification_context(items)
    assert "[VERIFICATION NEEDED]" in ctx
    assert "has_spots" in ctx
    assert "Does the cat have spots?" in ctx


def test_build_verification_context_empty():
    ctx = build_verification_context([])
    assert ctx == ""


def test_check_probe_needed_true_after_two_turns():
    items = [
        VerificationItem(property="has_spots", question="...", for_activity_id="a", pending_turns=2),
    ]
    assert check_probe_needed(items) is True


def test_check_probe_needed_false_at_zero():
    items = [
        VerificationItem(property="has_spots", question="...", for_activity_id="a", pending_turns=0),
    ]
    assert check_probe_needed(items) is False


@pytest.mark.asyncio
async def test_classify_verification_confirm():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"verdict": "confirm", "confidence": "high", "reason": "Child said yes"}'
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    result = await classify_verification(
        child_input="Yes it does!",
        property="has_spots",
        conversation_context="We are talking about a cat.",
        client=mock_client,
        config={"model_name": "gemini-2.0-flash-lite"},
    )
    assert result["verdict"] == "confirm"


@pytest.mark.asyncio
async def test_classify_verification_keyword_fast_path():
    """Keywords like 'yes', 'yeah', 'yep' should bypass LLM."""
    result = await classify_verification(
        child_input="Yeah it has spots",
        property="has_spots",
        conversation_context="",
        client=None,
        config=None,
    )
    assert result["verdict"] == "confirm"
    assert result["source"] == "keyword"
