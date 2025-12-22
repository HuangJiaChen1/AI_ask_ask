from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    """Generic standard API response wrapper.

    This class wraps all API responses with a consistent structure including
    status codes, messages, and data payloads. For chat endpoints, additional
    tracking fields are included in the data payload.

    Response Structure:
    - code: HTTP status code or custom business code
    - msg: Human-readable response message
    - data: Response payload (varies by endpoint)

    Chat Endpoint Extensions:
    For chat endpoints (consolidate_chat, enhance_chat), the data payload
    includes additional tracking fields:
    - content_id: Unique ID for system's response (session_id_N+1)

    Session Start Extensions:
    For session start endpoints, the data payload includes:
    - session_id: Unique session identifier for subsequent requests
    """

    code: int = Field(..., description="HTTP status code or custom business code")
    msg: str = Field(..., description="Response message")
    data: T | None = Field(None, description="Response data payload, null on error")
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="ISO timestamp of response",
    )

    model_config = ConfigDict(
        exclude_none=True,
        populate_by_name=True,
        json_schema_extra={
            "example_success": {
                "code": 200,
                "msg": "success",
                "data": {
                    "some_key": "some_value",
                    "content_id": "session_123_2",
                },
            },
            "example_error": {
                "code": 400,
                "msg": "Invalid input provided",
                "data": None,
            },
            "example_session_start": {
                "code": 200,
                "msg": "Session started successfully",
                "data": {
                    "session_id": "session_abc-123",
                    "message": "Session started at 2024-01-01 12:00:00",
                    "first_question": "Hi there! What is your name?",
                },
            },
        },
    )


class TokenUsage(BaseModel):
    """Model representing token usage information for the current API call.

    This represents the token consumption for the current turn/request only,
    not the cumulative usage across the entire session.

    Attributes
    ----------
        input_tokens: Number of input tokens used in this API call.
        output_tokens: Number of output tokens generated in this API call.
        total_tokens: Total number of tokens for this API call (input + output).

    """

    input_tokens: int = Field(..., description="Number of input tokens used in this API call.")
    output_tokens: int = Field(..., description="Number of output tokens generated in this API call.")
    total_tokens: int = Field(
        ...,
        description="Total number of tokens for this API call (input + output).",
    )


class CallLeonardRequest(BaseModel):
    """Request model for calling Leonard agent."""

    book_data: dict[str, Any] = Field(..., description="Book data with content and pages")
    page_id: int = Field(..., description="Current page index")
    messages: list[dict[str, Any]] = Field(..., description="Conversation message history")
    content: str = Field(..., description="User's input content")
    status: str = Field(default="normal", description="Current conversation status")
    session_id: str = Field(..., description="Session ID for content_id generation")
    # turn_number: int = Field(..., description="Turn number in the conversation")


class SessionTerminationReason(str, Enum):
    """Enumeration of possible session termination reasons.

    Attributes
    ----------
        SENSITIVE_CONTENT: Session ended due to offensive/inappropriate content detection.
        USER_DECLINED: Session ended because user indicated no more questions.
        RELEVANT_QUESTION_LIMIT: Session ended after reaching 20 relevant exchanges.
        OFF_TOPIC_LIMIT: Session ended after 3 off-topic responses.
    """

    SENSITIVE_CONTENT = "sensitive_content"
    USER_DECLINED = "user_declined"
    RELEVANT_QUESTION_LIMIT = "relevant_question_limit"
    OFF_TOPIC_LIMIT = "off_topic_limit"


class StreamChunk(BaseModel):
    """Model representing a single streaming response chunk.

    This model defines the unified format for streaming responses from both
    consolidation and enhancement sessions. Each chunk contains content and
    metadata about the session state. The structure matches the non-streaming
    API response format.

    Attributes
    ----------
        response: The actual response content (text chunk or full response).
        router_result: Results of routing logic or internal state information.
        session_finished: Boolean indicating if the session has concluded.
        duration: Time taken to generate the response for this turn.
        token_usage: Token usage information for this API call.
        finish: Boolean indicating if this is the final chunk in the stream.
        not_relevant: Boolean indicating if current turn is off-topic.
        relevant_question: Boolean indicating if current turn is a relevant question.
        termination_reason: Reason for session termination (only set when session_finished=True).

    """

    response: str = Field(
        ...,
        description="The response content chunk or full response.",
    )
    session_finished: bool = Field(
        ...,
        description="Boolean indicating if the session has concluded.",
    )
    duration: float = Field(
        ...,
        description="Time taken (in seconds) to generate the response for this turn.",
    )
    token_usage: TokenUsage | None = Field(
        None,
        description="Token usage information for this API call (API calls only).",
    )
    finish: bool = Field(
        ...,
        description="Boolean indicating if this is the final chunk in the stream.",
    )
    sequence_number: int = Field(
        ...,
        description="Sequential number of this chunk in the stream (1-based).",
    )
    timestamp: float = Field(
        ...,
        description="Timestamp when this chunk was generated (Unix timestamp).",
    )
    session_id: str = Field(
        ...,
        description="Session identifier matching the request session_id.",
    )
    not_relevant: bool = Field(
        ...,
        description="Boolean indicating if current turn is off-topic.",
    )
    relevant_question: bool = Field(
        ...,
        description="Boolean indicating if current turn is a relevant question.",
    )
    termination_reason: SessionTerminationReason | None = Field(
        None,
        description="Reason for session termination (only set when session_finished=True).",
    )
