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


class ActivationTransitionBeforeState(BaseModel):
    activation_handoff_ready_before: bool | None = None
    activation_last_question_before: str | None = None
    activation_last_question_kb_item_before: dict | None = None
    activation_last_question_validation_source_before: str | None = None
    activation_last_question_validation_confidence_before: str | None = None
    activation_last_question_validation_reason_before: str | None = None
    activation_last_question_continuity_anchor_before: str | None = None
    bridge_phase_before: str | None = None
    activation_turn_count_before: int | None = None


class ActivationTransitionQuestionValidation(BaseModel):
    source: str | None = None
    confidence: str | None = None
    reason: str | None = None
    kb_backed_question: bool | None = None
    handoff_ready_question: bool | None = None
    kb_item: dict | None = None
    activation_last_question_after: str | None = None
    activation_last_question_kb_item_after: dict | None = None
    activation_last_question_continuity_anchor_after: str | None = None


class ActivationTransitionAnswerValidation(BaseModel):
    handoff_check_attempted: bool | None = None
    source: str | None = None
    reason: str | None = None
    answered_previous_question: bool | None = None
    answered_previous_kb_question: bool | None = None
    answer_polarity: str | None = None


class ActivationTransitionOutcome(BaseModel):
    handoff_result: str | None = None
    handoff_block_reason: str | None = None
    bridge_success: bool | None = None


class ActivationTransitionTurnInterpretation(BaseModel):
    activation_child_reply_type: str | None = None
    counted_turn: bool | None = None
    counted_turn_reason: str | None = None


class ActivationTransitionContinuity(BaseModel):
    continuity_anchor_before: str | None = None
    continuity_anchor_after: str | None = None
    continuity_preserved: bool | None = None
    continuity_break_reason: str | None = None


class ActivationTransitionDebugInfo(BaseModel):
    before_state: ActivationTransitionBeforeState | None = None
    question_validation: ActivationTransitionQuestionValidation | None = None
    answer_validation: ActivationTransitionAnswerValidation | None = None
    outcome: ActivationTransitionOutcome | None = None
    turn_interpretation: ActivationTransitionTurnInterpretation | None = None
    continuity: ActivationTransitionContinuity | None = None


class BridgeDebugInfo(BaseModel):
    surface_object_name: str | None = None
    anchor_object_name: str | None = None
    anchor_status: str | None = None
    anchor_relation: str | None = None
    anchor_confidence_band: str | None = None
    bridge_profile: dict | None = None
    bridge_profile_status: str | None = None
    bridge_profile_reason: str | None = None
    intro_mode: str | None = None
    learning_anchor_active_before: bool | None = None
    learning_anchor_active_after: bool | None = None
    bridge_attempt_count_before: int | None = None
    bridge_attempt_count_after: int | None = None
    pre_anchor_handler_entered: bool = False
    bridge_followed: bool | None = None
    bridge_follow_reason: str | None = None
    decision: str | None = None
    decision_reason: str | None = None
    response_type: str | None = None
    kb_mode: str | None = None
    bridge_context_summary: str | None = None
    activation_grounding_mode: str | None = None
    activation_grounding_summary: str | None = None
    bridge_phase_before: str | None = None
    bridge_phase_after: str | None = None
    activation_turn_count_before: int | None = None
    activation_turn_count_after: int | None = None
    activation_handoff_ready_after: bool | None = None
    activation_last_question: str | None = None
    activation_last_question_kb_item: dict | None = None
    activation_transition: ActivationTransitionDebugInfo | None = None
    bridge_visible_in_response: bool | None = None
    bridge_visibility_reason: str | None = None
    pre_anchor_reply_type: str | None = None
    support_action: str | None = None
    pre_anchor_support_count_before: int | None = None
    pre_anchor_support_count_after: int | None = None


class ResolutionDebugInfo(BaseModel):
    surface_object_name: str | None = None
    decision_source: str | None = None
    decision_reason: str | None = None
    candidate_anchors: list[str] | None = None
    model_attempted: bool | None = None
    raw_model_response: str | None = None
    raw_model_payload_kind: str | None = None
    json_recovery_applied: bool = False
    parsed_anchor_raw: str | None = None
    parsed_relation_raw: str | None = None
    parsed_confidence_raw: str | None = None
    anchor_object_name: str | None = None
    anchor_status: str | None = None
    unresolved_surface_only_mode: bool = False


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
    current_object_name: str | None = None
    surface_object_name: str | None = None
    anchor_object_name: str | None = None
    anchor_status: str | None = None
    anchor_relation: str | None = None
    anchor_confidence_band: str | None = None
    anchor_confirmation_needed: bool = False
    learning_anchor_active: bool = False
    bridge_phase: str | None = None
    bridge_attempt_count: int = 0
    pre_anchor_support_count: int = 0
    activation_turn_count: int = 0
    activation_handoff_ready: bool = False
    activation_child_reply_type: str | None = None
    counted_turn: bool | None = None
    counted_turn_reason: str | None = None
    attribute_pipeline_enabled: bool = False
    attribute_lane_active: bool = False
    attribute_debug: dict | None = None
    activity_ready: bool = False
    activity_target: dict | None = None

    # Node execution tracing (for critique reports)
    nodes_executed: list[dict] | None = None  # Passed through final chunk
    bridge_debug: BridgeDebugInfo | None = None
    resolution_debug: ResolutionDebugInfo | None = None

    # Chat phase completion signal (one-shot, sent on the threshold correct answer turn)
    chat_phase_complete: Optional[bool] = None

    # Hook type selected for this session (set on introduction, null otherwise)
    selected_hook_type: Optional[str] = None
    question_style: Optional[str] = None

    # Ordinary-chat KB debug info
    used_kb_item: dict | None = None
    kb_mapping_status: str | None = None
