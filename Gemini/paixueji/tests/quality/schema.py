"""
Schema definitions for the Pedagogical Quality Critique System.

Defines the data structures for:
- Pedagogical context extraction
- Failure classification
- Exchange and conversation critiques
- Test scenarios
"""

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


# ============================================================================
# Enums for Classification
# ============================================================================

class QuestionType(str, Enum):
    """Types of pedagogical questions."""
    WHY = "WHY"          # Causation, reasoning
    WHAT = "WHAT"        # Description, identification
    HOW = "HOW"          # Process, mechanism
    WHERE = "WHERE"      # Location, spatial
    WHEN = "WHEN"        # Temporal
    WHICH = "WHICH"      # Selection, comparison
    OPEN = "OPEN"        # Open-ended exploration
    STATEMENT = "STATEMENT"  # Not a question


class ResponseType(str, Enum):
    """Types of child responses."""
    ANSWER = "ANSWER"           # Attempted answer (right or wrong)
    PARTIAL = "PARTIAL"         # Partially correct or incomplete
    CONFUSED = "CONFUSED"       # Shows confusion or misunderstanding
    DONT_KNOW = "DONT_KNOW"     # Explicit "I don't know"
    OFF_TOPIC = "OFF_TOPIC"     # Unrelated response
    QUESTION = "QUESTION"       # Child asks a question back
    ENGAGEMENT = "ENGAGEMENT"   # Shows interest but no answer


class FailureType(str, Enum):
    """Types of pedagogical failures."""
    # Single-turn failures
    SAME_QUESTION_REPHRASED = "SAME_QUESTION_REPHRASED"
    MISSED_SCAFFOLD = "MISSED_SCAFFOLD"
    WRONG_QUESTION_TYPE = "WRONG_QUESTION_TYPE"
    NO_NEW_INFO = "NO_NEW_INFO"
    ABANDONED_INTENT = "ABANDONED_INTENT"
    IGNORED_CONFUSION = "IGNORED_CONFUSION"
    TOO_COMPLEX = "TOO_COMPLEX"
    TOO_SIMPLE = "TOO_SIMPLE"
    MISSED_TEACHABLE_MOMENT = "MISSED_TEACHABLE_MOMENT"
    OTHER = "OTHER"

    # Multi-turn failures (detected over multiple exchanges)
    REPEATED_SCAFFOLD_FAILURE = "REPEATED_SCAFFOLD_FAILURE"  # Same scaffold approach 2+ times
    STUCK_LOOP = "STUCK_LOOP"  # Conversation circles without progress
    PREMATURE_ADVANCEMENT = "PREMATURE_ADVANCEMENT"  # Moves on when child still confused
    ENGAGEMENT_DECLINE = "ENGAGEMENT_DECLINE"  # Child responses getting shorter/less engaged
    LOST_THREAD = "LOST_THREAD"  # Abandoned original learning goal


class Severity(str, Enum):
    """Severity of pedagogical failures."""
    CRITICAL = "CRITICAL"  # Fundamentally breaks learning
    MAJOR = "MAJOR"        # Significantly impairs learning
    MINOR = "MINOR"        # Small missed opportunity


# ============================================================================
# Multi-Turn Pattern Analysis (kept for real conversation analysis)
# ============================================================================

class MultiTurnPattern(BaseModel):
    """A pattern detected across multiple conversation turns."""
    pattern_type: FailureType = Field(
        description="Type of multi-turn pattern detected"
    )
    severity: Severity = Field(
        description="Severity of the pattern"
    )
    turns_affected: list[int] = Field(
        description="Which turn numbers exhibit this pattern"
    )
    description: str = Field(
        description="Human-readable description of the pattern"
    )
    evidence: str = Field(
        description="Specific examples from the conversation showing the pattern"
    )


# ============================================================================
# Pedagogical Context (extracted by analyzer)
# ============================================================================

class PedagogicalContext(BaseModel):
    """Extracted pedagogical context for each exchange."""

    # What the model asked
    question_type: QuestionType = Field(
        description="The type of question asked (WHY, WHAT, HOW, etc.)"
    )
    question_intent: str = Field(
        description="What the model is trying to get the child to understand"
    )
    target_knowledge: str = Field(
        description="The specific knowledge/concept being taught"
    )

    # What the child responded
    child_response_type: ResponseType = Field(
        description="How the child responded (ANSWER, DONT_KNOW, etc.)"
    )
    knowledge_gap: str = Field(
        description="What the child's response reveals they don't understand"
    )

    # What the model should do
    ideal_next_action: str = Field(
        description="What the model should do to advance learning"
    )
    acceptable_actions: list[str] = Field(
        default_factory=list,
        description="Alternative acceptable approaches"
    )
    unacceptable_actions: list[str] = Field(
        default_factory=list,
        description="Actions that would fail pedagogically"
    )


# ============================================================================
# Critique Results
# ============================================================================

class Failure(BaseModel):
    """A specific pedagogical failure identified by the critic."""
    type: FailureType = Field(description="Category of failure")
    description: str = Field(description="Specific description of the failure")
    evidence: str = Field(description="Exact text showing the problem")
    severity: Severity = Field(description="How serious this failure is")


class ExpectedVsActual(BaseModel):
    """Comparison of expected vs actual response."""
    i_expected: str = Field(
        description="What a good pedagogical response would do"
    )
    but_got: str = Field(
        description="What the model actually did"
    )
    this_is_problematic_because: str = Field(
        description="Why the actual response fails pedagogically"
    )


class ExchangeCritique(BaseModel):
    """Critique of a single exchange in a conversation."""
    turn_number: int = Field(description="Which turn in the conversation")
    model_question: str = Field(description="What the model asked")
    child_response: str = Field(description="What the child said")
    model_actual: str = Field(description="How the model responded")

    # Node execution trace for debugging
    nodes_executed: list[dict] = Field(
        default_factory=list,
        description="Node execution trace for this exchange [{'node': str, 'time_ms': float, 'changes': dict}]"
    )

    # Pedagogical context
    context: PedagogicalContext = Field(
        description="Extracted pedagogical context"
    )

    # Scores
    advances_learning: bool = Field(
        description="Whether the response advances the child's understanding"
    )
    addresses_knowledge_gap: bool = Field(
        description="Whether the response addresses the identified gap"
    )
    effectiveness_score: int = Field(
        ge=1, le=10,
        description="Overall effectiveness (1-10)"
    )

    # Failures
    failures: list[Failure] = Field(
        default_factory=list,
        description="Identified pedagogical failures"
    )

    # The key insight
    expected_vs_actual: ExpectedVsActual | None = Field(
        default=None,
        description="Expected vs actual comparison (if there were failures)"
    )

    # What should have happened
    ideal_response: str = Field(
        description="What an ideal response would look like"
    )

    # Suggestions
    improvements: list[str] = Field(
        default_factory=list,
        description="Specific improvement suggestions"
    )
    picky_observations: list[str] = Field(
        default_factory=list,
        description="Detailed observations from the picky critic"
    )


class ConversationCritique(BaseModel):
    """Full critique of a conversation."""
    scenario_id: str = Field(description="Scenario identifier")
    scenario_name: str = Field(description="Human-readable scenario name")

    # Overall metrics
    overall_effectiveness: float = Field(
        ge=0, le=100,
        description="Overall effectiveness percentage"
    )
    total_exchanges: int = Field(description="Number of exchanges analyzed")
    failed_exchanges: int = Field(
        description="Number of exchanges with failures"
    )

    # Failure breakdown
    failure_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Count of each failure type"
    )

    # Per-exchange critiques
    exchange_critiques: list[ExchangeCritique] = Field(
        default_factory=list,
        description="Detailed critique of each exchange"
    )

    # Summary
    critical_failures: list[str] = Field(
        default_factory=list,
        description="Most important problems found"
    )
    improvement_priorities: list[str] = Field(
        default_factory=list,
        description="Ordered list of what to fix first"
    )


# ============================================================================
# Scenario Definition
# ============================================================================

class ScenarioExchange(BaseModel):
    """A single exchange in a test scenario."""
    role: Literal["model", "child"] = Field(description="Who is speaking")
    content: str = Field(description="What they said")

    # Optional metadata for model turns
    pedagogical_intent: str | None = Field(
        default=None,
        description="What the model is trying to teach"
    )
    question_type: QuestionType | None = Field(
        default=None,
        description="Type of question asked"
    )
    target_knowledge: str | None = Field(
        default=None,
        description="Knowledge being targeted"
    )

    # Optional metadata for child turns
    response_type: ResponseType | None = Field(
        default=None,
        description="Type of child response"
    )
    knowledge_gap: str | None = Field(
        default=None,
        description="Gap revealed by the response"
    )


class ScenarioEvaluation(BaseModel):
    """Evaluation criteria for a scenario."""
    must_do: list[str] = Field(
        default_factory=list,
        description="Actions the model MUST take"
    )
    must_not_do: list[str] = Field(
        default_factory=list,
        description="Actions the model must NOT take"
    )
    ideal_response_pattern: str | None = Field(
        default=None,
        description="Regex pattern for an ideal response"
    )


class ScenarioSetup(BaseModel):
    """Setup context for a scenario."""
    object_name: str = Field(description="Object being discussed")
    key_concept: str = Field(description="Key concept being taught")
    age: int = Field(ge=3, le=12, description="Child's age")
    guide_phase: str = Field(
        default="active",
        description="Current phase of the conversation"
    )


class Scenario(BaseModel):
    """A complete pedagogical test scenario."""
    id: str = Field(description="Unique scenario identifier")
    name: str = Field(description="Human-readable scenario name")
    description: str = Field(description="What this scenario tests")

    setup: ScenarioSetup = Field(description="Scenario context")
    conversation: list[ScenarioExchange] = Field(
        default_factory=list,
        description="The conversation exchanges"
    )
    evaluation: ScenarioEvaluation = Field(
        description="How to evaluate responses"
    )
