from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    """Generic standard API response wrapper.

    This class wraps all API responses with a consistent structure including
    status codes, messages, and data payloads.

    Response Structure:
    - code: HTTP status code or custom business code
    - msg: Human-readable response message
    - data: Response payload (varies by endpoint)
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
                },
            },
            "example_error": {
                "code": 400,
                "msg": "Invalid input provided",
                "data": None,
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


class CallAskAskRequest(BaseModel):
    """Request model for calling Ask Ask agent.

    In Ask Ask, children ask questions and the AI provides age-appropriate answers.
    Unlike the picture book assistant, there's no book context - just free-form Q&A.
    """

    age: int | None = Field(None, description="Child's age (3-8) for age-appropriate responses")
    messages: list[dict[str, Any]] = Field(..., description="Conversation message history")
    content: str = Field(..., description="Child's question or input")
    status: str = Field(default="normal", description="Current conversation status (normal/over)")
    session_id: str = Field(..., description="Session ID for tracking")


class StreamChunk(BaseModel):
    """Model representing a single streaming response chunk.

    This model defines the unified format for streaming responses from the
    Ask Ask assistant. Each chunk contains content and metadata about the
    session state.

    Attributes
    ----------
        response: The actual response content (text chunk or full response).
        session_finished: Boolean indicating if the session has concluded.
        duration: Time taken to generate the response for this turn.
        token_usage: Token usage information for this API call.
        finish: Boolean indicating if this is the final chunk in the stream.
        sequence_number: Sequential number of this chunk in the stream (1-based).
        timestamp: Timestamp when this chunk was generated (Unix timestamp).
        session_id: Session identifier matching the request session_id.
        request_id: Unique identifier for this specific request (to distinguish concurrent streams).
        is_stuck: Boolean indicating if child is stuck and needs topic suggestions.

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
        description="Token usage information for this API call (only in final chunk).",
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
    request_id: str
    response_type: str | None = None
    is_stuck: bool = False
    correct_answer_count: int = 0
    conversation_complete: bool = False

    # Intent classification (9-node architecture)
    intent_type: str | None = None

    # Fun fact state
    fun_fact: Optional[str] = None
    fun_fact_hook: Optional[str] = None
    fun_fact_question: Optional[str] = None
    real_facts: Optional[str] = None

    # IB PYP Theme info
    ibpyp_theme: Optional[str] = None
    ibpyp_theme_name: Optional[str] = None
    theme_classification_reason: Optional[str] = None
    
    # Theme Guide info
    guide_phase: Optional[str] = None  # "active", "success", "hint", "exit"
    key_concept: Optional[str] = None
    bridge_question: Optional[str] = None
    is_guide_success: Optional[bool] = None

    # Multi-turn guide state (Navigator/Driver integration)
    guide_turn_count: Optional[int] = None  # Current turn in guide (1-based)
    guide_max_turns: Optional[int] = None   # Maximum turns before timeout
    guide_status: Optional[str] = None      # ON_TRACK, DRIFTING, STUCK, COMPLETED
    guide_strategy: Optional[str] = None    # ADVANCE, PIVOT, SCAFFOLD, COMPLETE
    scaffold_level: Optional[int] = None    # 1-4, progressive hint levels (only if SCAFFOLD)

    # Topic switching fields:
    new_object_name: str | None = None
    detected_object_name: str | None = None  # Object AI detected but didn't switch to

    # Object selection mode:
    object_selection_mode: bool = False  # True if presenting object choices
    suggested_objects: list[str] | None = None  # Objects to choose from

    # Node execution tracing (for critique reports)
    nodes_executed: list[dict] | None = None  # Passed through final chunk
