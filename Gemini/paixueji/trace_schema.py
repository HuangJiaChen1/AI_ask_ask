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
from pydantic import BaseModel, Field
from datetime import datetime


class CulpritType(str, Enum):
    NODE = "NODE"
    ROUTER = "ROUTER"
    VALIDATOR = "VALIDATOR"
    NAVIGATOR = "NAVIGATOR"
    DRIVER = "DRIVER"
    PROMPT = "PROMPT"
    UNKNOWN = "UNKNOWN"


class NodeTrace(BaseModel):
    """Enriched trace entry for a single node or router execution."""
    node: str
    time_ms: float
    changes: dict = Field(default_factory=dict)
    state_before: dict = Field(default_factory=dict)
    validation_result: Optional[dict] = None
    navigation_result: Optional[dict] = None


class CulpritIdentification(BaseModel):
    """Identifies the component most likely responsible for the failure."""
    culprit_type: CulpritType
    culprit_name: str
    confidence: float = Field(ge=0, le=1)
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


def identify_culprit(
    critique: HumanCritique,
    execution_path: list[NodeTrace],
    exchange: ExchangeContext,
    validation_result: Optional[dict] = None,
    navigation_result: Optional[dict] = None,
) -> CulpritIdentification:
    """
    Heuristic to identify the most likely culprit component.

    Decision tree:
      1. Validator said correct but human says wrong → VALIDATOR
      2. Validator said not engaged but human disagrees → VALIDATOR
      3. Wrong topic switch → VALIDATOR
      4. Guide mode, wrong strategy → NAVIGATOR
      5. Guide mode, strategy OK but output bad → DRIVER
      6. Only question problematic → NODE (generate_question)
      7. Only response problematic → NODE (generate_response)
      8. Both problematic → ROUTER
      9. Fallback → last content-generating node
    """
    has_question_problem = bool(critique.model_question_problem.strip())
    has_response_problem = bool(critique.model_response_problem.strip())
    is_guide = exchange.mode == "guide"

    # Extract validation info from the execution path if not passed directly
    if validation_result is None:
        for entry in execution_path:
            if entry.validation_result:
                validation_result = entry.validation_result
                break

    if navigation_result is None:
        for entry in execution_path:
            if entry.navigation_result:
                navigation_result = entry.navigation_result
                break

    # 1. Validator said correct but human says the response is wrong
    if validation_result:
        val_correct = validation_result.get("is_factually_correct")
        if val_correct is True and has_response_problem:
            return CulpritIdentification(
                culprit_type=CulpritType.VALIDATOR,
                culprit_name="node_analyze_input",
                confidence=0.8,
                reasoning="Validator judged answer correct, but human identified response problem",
            )

        # 2. Validator said not engaged but human disagrees
        val_engaged = validation_result.get("is_engaged")
        if val_engaged is False and not has_response_problem and not has_question_problem:
            return CulpritIdentification(
                culprit_type=CulpritType.VALIDATOR,
                culprit_name="node_analyze_input",
                confidence=0.7,
                reasoning="Validator marked child as not engaged, but human found no problem",
            )

        # 3. Wrong topic switch
        new_object = validation_result.get("new_object")
        if new_object and has_question_problem:
            return CulpritIdentification(
                culprit_type=CulpritType.VALIDATOR,
                culprit_name="node_analyze_input",
                confidence=0.75,
                reasoning=f"Validator triggered topic switch to '{new_object}', but question was problematic",
            )

    # 4. Guide mode, wrong strategy → NAVIGATOR
    if is_guide and navigation_result:
        strategy = navigation_result.get("strategy", "")
        if has_response_problem and has_question_problem:
            return CulpritIdentification(
                culprit_type=CulpritType.NAVIGATOR,
                culprit_name="node_guide_navigator",
                confidence=0.7,
                reasoning=f"Guide mode with strategy '{strategy}': both question and response problematic, suggesting wrong strategic direction",
            )

        # 5. Guide mode, strategy OK but output bad → DRIVER
        if has_response_problem and not has_question_problem:
            return CulpritIdentification(
                culprit_type=CulpritType.DRIVER,
                culprit_name="node_guide_driver",
                confidence=0.7,
                reasoning=f"Guide mode with strategy '{strategy}': strategy direction seems OK but response execution was poor",
            )

    # 6. Only question problematic → NODE (generate_question)
    if has_question_problem and not has_response_problem:
        return CulpritIdentification(
            culprit_type=CulpritType.NODE,
            culprit_name="generate_question",
            confidence=0.7,
            reasoning="Only the question was problematic, pointing to question generation",
        )

    # 7. Only response problematic → NODE (generate_response)
    if has_response_problem and not has_question_problem:
        # Try to identify the prompt template used
        prompt_name = None
        for entry in reversed(execution_path):
            if entry.node == "generate_response":
                response_type = entry.changes.get("response_type") or entry.state_before.get("response_type")
                if response_type:
                    prompt_name = f"{response_type}_prompt"
                break

        return CulpritIdentification(
            culprit_type=CulpritType.NODE,
            culprit_name="generate_response",
            confidence=0.7,
            reasoning="Only the response was problematic, pointing to response generation",
            prompt_template_name=prompt_name,
        )

    # 8. Both problematic → ROUTER
    if has_question_problem and has_response_problem:
        return CulpritIdentification(
            culprit_type=CulpritType.ROUTER,
            culprit_name="route_after_response",
            confidence=0.6,
            reasoning="Both question and response problematic, suggesting wrong routing decision",
        )

    # 9. Fallback → last content-generating node
    content_nodes = {"generate_response", "generate_question", "guide_driver", "guide_hint", "guide_exit"}
    for entry in reversed(execution_path):
        if entry.node in content_nodes:
            return CulpritIdentification(
                culprit_type=CulpritType.NODE,
                culprit_name=entry.node,
                confidence=0.4,
                reasoning=f"Fallback: last content-generating node was '{entry.node}'",
            )

    return CulpritIdentification(
        culprit_type=CulpritType.UNKNOWN,
        culprit_name="unknown",
        confidence=0.1,
        reasoning="Could not identify culprit from available trace data",
    )
