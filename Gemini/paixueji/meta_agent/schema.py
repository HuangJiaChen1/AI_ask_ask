"""
Schema definitions for the Meta-Agent Evolution System.

Defines all Pydantic models for:
- Stage 1: Report Analysis (parsed reports + LLM analysis)
- Stage 2: Architecture Diagnosis (root causes + proposed changes)
- Stage 3: Verification Loop (attempts, results, evolution history)
"""

from enum import Enum
from pydantic import BaseModel, Field


# ============================================================================
# Report Parsing (input to Stage 1)
# ============================================================================

class ParsedExchange(BaseModel):
    """A single exchange extracted from a critic report."""
    turn_number: int
    model_question: str
    child_response: str
    model_response: str
    effectiveness_score: int | None = None  # 1-10, AIF only
    advances_learning: bool | None = None
    addresses_knowledge_gap: bool | None = None
    failures: list[dict] = Field(default_factory=list)
    # e.g. [{"type": "MISSED_TEACHABLE_MOMENT", "severity": "MAJOR", "description": "...", "evidence": "..."}]
    node_trace: list[dict] = Field(default_factory=list)
    # e.g. [{"node": "analyze_input", "time_ms": 1372, "changes": {"response_type": "explanation"}}]
    improvements: list[str] = Field(default_factory=list)
    expected_vs_actual: dict | None = None
    # e.g. {"expected": "...", "got": "...", "problematic_because": "..."}
    ideal_response: str | None = None
    picky_observations: list[str] = Field(default_factory=list)

    # HF-specific
    human_critique: str | None = None


class ParsedReport(BaseModel):
    """Structured data extracted from a critic report markdown file."""
    source: str  # "AIF" or "HF"
    object_name: str = ""
    session_id: str = ""
    age: int = 6
    date: str = ""
    key_concept: str | None = None

    # AIF summary fields
    overall_effectiveness: float | None = None  # 0-100
    total_exchanges: int = 0
    failed_exchanges: int = 0
    failure_breakdown: dict[str, int] = Field(default_factory=dict)
    critical_failures: list[str] = Field(default_factory=list)
    improvement_priorities: list[str] = Field(default_factory=list)

    # Exchanges
    exchanges: list[ParsedExchange] = Field(default_factory=list)

    # HF-specific
    feedback_type: str | None = None
    exchanges_critiqued_count: int | None = None
    exchanges_total_count: int | None = None


# ============================================================================
# Stage 1: Report Analysis (LLM output)
# ============================================================================

class SuspectedNode(BaseModel):
    """A graph node suspected of contributing to pedagogical failures."""
    node_name: str = Field(description="e.g. 'generate_response'")
    response_types: list[str] = Field(
        default_factory=list,
        description="e.g. ['explanation', 'gentle_correction']"
    )
    failure_count: int
    failure_types: list[str] = Field(description="e.g. ['MISSED_TEACHABLE_MOMENT', 'ABANDONED_INTENT']")
    evidence_turns: list[int] = Field(description="Turn numbers where this node failed")
    confidence: str = Field(description="'high', 'medium', or 'low'")


class FailureGroup(BaseModel):
    """A group of related failures across exchanges."""
    category: str = Field(description="Failure category name")
    description: str
    failure_types: list[str]
    affected_turns: list[int]
    severity: str  # "critical", "major", "minor"


class ReportAnalysis(BaseModel):
    """Stage 1 output: analyzed report with node blame attribution."""
    report_source: str  # "AIF" or "HF"
    overall_effectiveness: float | None = None  # 0-100, AIF only
    total_exchanges: int
    failed_exchanges: int
    suspected_nodes: list[SuspectedNode] = Field(
        default_factory=list,
        description="Ordered by confidence (highest first)"
    )
    failure_groups: list[FailureGroup] = Field(default_factory=list)
    consolidated_improvements: list[str] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    severity_assessment: str = Field(description="'critical', 'moderate', or 'minor'")
    summary: str


# ============================================================================
# Stage 2: Architecture Diagnosis (LLM output)
# ============================================================================

class ChangeType(str, Enum):
    """Types of architectural changes the meta-agent can propose."""
    MODIFY_PROMPT = "MODIFY_PROMPT"
    CREATE_NODE = "CREATE_NODE"
    DELETE_NODE = "DELETE_NODE"
    UPDATE_NODE = "UPDATE_NODE"
    MODIFY_ROUTER = "MODIFY_ROUTER"
    MODIFY_STATE = "MODIFY_STATE"


class ProposedChange(BaseModel):
    """A specific architectural change proposed by the diagnostician."""
    change_type: ChangeType
    target: str = Field(description="Prompt name / node name / router name")
    description: str
    rationale: str = Field(description="WHY this fixes the root cause")
    priority: int = Field(ge=1, le=5, description="1 (highest) to 5 (lowest)")
    risk_level: str = Field(description="'low', 'medium', or 'high'")

    # MODIFY_PROMPT specific
    prompt_key: str | None = Field(default=None, description="Key in get_prompts()")
    prompt_current_excerpt: str | None = Field(default=None, description="Relevant excerpt of current prompt")
    prompt_proposed: str | None = Field(default=None, description="Full proposed replacement text")

    # CREATE_NODE specific
    node_inputs: list[str] | None = None
    node_outputs: list[str] | None = None
    graph_position: str | None = Field(default=None, description="e.g. 'after generate_response, before generate_question'")

    # MODIFY_ROUTER specific
    router_conditions: str | None = None


class RootCause(BaseModel):
    """A diagnosed root cause of pedagogical failures."""
    description: str
    mechanism: str = Field(description="HOW the architecture produces this failure")
    affected_nodes: list[str]
    affected_prompts: list[str]


class ArchitectureDiagnosis(BaseModel):
    """Stage 2 output: root cause diagnosis with proposed changes."""
    root_causes: list[RootCause]
    proposed_changes: list[ProposedChange]
    summary: str
    estimated_impact: str


# ============================================================================
# Stage 3: Verification Loop
# ============================================================================

class VerificationConfig(BaseModel):
    """Configuration for the verification loop."""
    max_iterations: int = 3
    improvement_threshold: float = 5.0  # Min effectiveness gain to accept
    batch_changes: bool = False  # True = apply all prompt changes at once


class AttemptResult(BaseModel):
    """Result of a single verification attempt."""
    iteration: int
    change_applied: ProposedChange
    old_effectiveness: float
    new_effectiveness: float
    new_failures: list[str] = Field(default_factory=list)
    rejection_reason: str = ""


class EvolutionHistory(BaseModel):
    """History of previous failed attempts for a prompt target."""
    target_prompt: str
    attempts: list[AttemptResult] = Field(default_factory=list)


class VerifiedChange(BaseModel):
    """A change that has been tested and proven to improve effectiveness."""
    change: ProposedChange
    old_effectiveness: float
    new_effectiveness: float
    delta: float
    iterations_needed: int


class EvolutionResult(BaseModel):
    """Final output of the meta-agent evolution loop."""
    verified_changes: list[VerifiedChange] = Field(default_factory=list)
    unverified_proposals: list[ProposedChange] = Field(default_factory=list)
    rejected_attempts: list[AttemptResult] = Field(default_factory=list)
    final_effectiveness: float | None = None
    summary: str
