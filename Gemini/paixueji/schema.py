from typing import Optional

from pydantic import BaseModel, Field


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
    classification_status: str | None = None
    classification_failure_reason: str | None = None

    # Fun fact state
    fun_fact: Optional[str] = None
    fun_fact_hook: Optional[str] = None
    fun_fact_question: Optional[str] = None
    real_facts: Optional[str] = None

    # IB PYP Theme info
    ibpyp_theme: Optional[str] = None
    ibpyp_theme_name: Optional[str] = None
    theme_classification_reason: Optional[str] = None
    key_concept: Optional[str] = None

    # Topic switching fields:
    new_object_name: str | None = None
    detected_object_name: str | None = None  # Object AI detected but didn't switch to

    # Node execution tracing (for critique reports)
    nodes_executed: list[dict] | None = None  # Passed through final chunk

    # Chat phase completion signal (one-shot, sent on the threshold correct answer turn)
    chat_phase_complete: Optional[bool] = None

    # Hook type selected for this session (set on introduction, null otherwise)
    selected_hook_type: Optional[str] = None

    # Ordinary-chat KB debug info
    used_kb_item: dict | None = None
    kb_mapping_status: str | None = None
