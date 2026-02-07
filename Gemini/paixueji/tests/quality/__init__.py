"""
Pedagogical Quality Critique System for Paixueji.

This module provides tools to evaluate the pedagogical effectiveness
of AI-child conversations, going beyond simple checklist compliance
to analyze whether responses actually advance children's learning.

Key capabilities:
- Single-turn critique: Analyze individual exchanges for pedagogical failures
- Pattern detection: Identify multi-turn issues like repeated scaffold failures
"""

from .schema import (
    # Enums
    QuestionType,
    ResponseType,
    FailureType,
    Severity,
    # Single-turn models
    PedagogicalContext,
    Failure,
    ExpectedVsActual,
    ExchangeCritique,
    ConversationCritique,
    ScenarioExchange,
    ScenarioEvaluation,
    Scenario,
    # Multi-turn pattern model
    MultiTurnPattern,
)
from .pedagogical_analyzer import PedagogicalAnalyzer
from .expert_critic import ExpertCritic
from .critique_report import CritiqueReportGenerator
from .pipeline import PedagogicalCritiquePipeline
from .scenario_runner import ScenarioRunner, run_scenario_to_json

__all__ = [
    # Enums
    "QuestionType",
    "ResponseType",
    "FailureType",
    "Severity",
    # Single-turn models
    "PedagogicalContext",
    "Failure",
    "ExpectedVsActual",
    "ExchangeCritique",
    "ConversationCritique",
    "ScenarioExchange",
    "ScenarioEvaluation",
    "Scenario",
    # Multi-turn pattern model
    "MultiTurnPattern",
    # Components
    "PedagogicalAnalyzer",
    "ExpertCritic",
    "CritiqueReportGenerator",
    "PedagogicalCritiquePipeline",
    # Scenario Runner
    "ScenarioRunner",
    "run_scenario_to_json",
]
