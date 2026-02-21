"""
TraceObject Pydantic models for structured self-evolution traces.

Each TraceObject captures the full context of a failed exchange:
  1. input_state  — the graph's input state before failure
  2. execution_path — the exact node/router path taken
  3. culprit — identified responsible component
  4. critique — the human's feedback

These JSON-serializable objects power the automated optimization pipeline.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field  # Field still used by NodeTrace and TraceObject
from datetime import datetime


class CulpritType(str, Enum):
    NODE = "NODE"
    ROUTER = "ROUTER"
    VALIDATOR = "VALIDATOR"
    NAVIGATOR = "NAVIGATOR"
    DRIVER = "DRIVER"
    PROMPT = "PROMPT"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    CONFIDENT = "CONFIDENT"
    VERY_CONFIDENT = "VERY_CONFIDENT"


class NodeTrace(BaseModel):
    """Enriched trace entry for a single node or router execution."""
    node: str
    time_ms: float
    changes: dict = Field(default_factory=dict)
    state_before: dict = Field(default_factory=dict)
    validation_result: Optional[dict] = None
    navigation_result: Optional[dict] = None
    phase: str = "response"   # "question" | "response"


class CulpritIdentification(BaseModel):
    """Identifies the component most likely responsible for the failure."""
    culprit_type: CulpritType
    culprit_name: str
    confidence_level: ConfidenceLevel
    reasoning: str
    prompt_template_name: Optional[str] = None


class HumanCritique(BaseModel):
    """Human feedback on a specific exchange."""
    exchange_index: int
    model_question_expected: str = ""
    model_question_problem: str = ""
    model_response_expected: str = ""
    model_response_problem: str = ""
    conclusion: str = ""


class ExchangeContext(BaseModel):
    """The model→child→model triplet that was critiqued."""
    model_question: str
    child_response: str
    model_response: str
    mode: str = "chat"


class TraceObject(BaseModel):
    """Top-level trace capturing the full context of a critiqued exchange."""
    trace_id: str
    session_id: str
    timestamp: str
    object_name: str
    age: Optional[int] = None
    key_concept: Optional[str] = None
    ibpyp_theme_name: Optional[str] = None

    input_state: dict = Field(default_factory=dict)
    execution_path: list[NodeTrace] = Field(default_factory=list)
    culprit: CulpritIdentification
    critique: HumanCritique
    exchange: ExchangeContext

    validation_result: Optional[dict] = None
    navigation_result: Optional[dict] = None

    exchange_index: int
    conversation_length: int = 0
    total_execution_time_ms: float = 0
