import pytest
from unittest.mock import AsyncMock, MagicMock
from activities import ActivityDefinition
from stream.activity_discovery import (
    ActivityDiscoveryResult,
    _build_activity_block,
    discover_talkable_activities,
)


def test_build_activity_block_formats_activity():
    a = ActivityDefinition(
        activity_id="polka_dot_patrol",
        name="Polka Dot Patrol",
        description="Find spotted things",
        focal_attribute="polka_dots",
        observation_angle="pattern",
    )
    block = _build_activity_block(a)
    assert "polka_dot_patrol" in block
    assert "pattern" in block
    assert "polka_dots" in block


def test_activity_discovery_result_dataclass():
    result = ActivityDiscoveryResult(
        primary_activity_id="test",
        proceed=True,
    )
    assert result.primary_activity_id == "test"
    assert result.proceed is True
    assert result.verification_queue == []


@pytest.mark.asyncio
async def test_discover_talkable_activities_returns_result():
    """Mock LLM call returns a valid JSON response."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '''
    {
      "primary": {"activity_id": "polka_dot_patrol", "category": "ready", "certainty": "high", "why": "Cat has spots"},
      "secondary": [],
      "verification_queue": [],
      "assessment": "Strong match",
      "proceed": true
    }
    '''
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    eligible = [
        ActivityDefinition(
            activity_id="polka_dot_patrol",
            name="Polka Dot Patrol",
            description="Find spotted things",
            attributes=("polka_dots",),
            preview_prompt="You noticed the polka dots!",
            tier_range_span=("T1",),
            tier_support={"T1": True},
        )
    ]

    result, debug = await discover_talkable_activities(
        eligible_activities=eligible,
        object_name="spotted cat",
        anchor_name="cat",
        age=6,
        client=mock_client,
        config={"model_name": "gemini-2.0-flash-lite"},
    )
    assert result.proceed is True
    assert result.primary_activity_id == "polka_dot_patrol"
