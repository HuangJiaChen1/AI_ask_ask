"""
Pedagogical Quality Critique System for Paixueji.

This module provides tools to evaluate the pedagogical effectiveness
of AI-child conversations, going beyond simple checklist compliance
to analyze whether responses actually advance children's learning.
"""

from .schema import (
    # Enums
    QuestionType,
    ResponseType,
    FailureType,
    Severity,
    # Context/Critique models
    PedagogicalContext,
    Failure,
    ExpectedVsActual,
    ExchangeCritique,
    ConversationCritique,
    ScenarioEvaluation,
    ScenarioSetup,
    # Multi-turn pattern model
    MultiTurnPattern,
)
from .pedagogical_analyzer import PedagogicalAnalyzer
from .expert_critic import ExpertCritic
from .critique_report import CritiqueReportGenerator
from .pipeline import PedagogicalCritiquePipeline

__all__ = [
    # Enums
    "QuestionType",
    "ResponseType",
    "FailureType",
    "Severity",
    # Models
    "PedagogicalContext",
    "Failure",
    "ExpectedVsActual",
    "ExchangeCritique",
    "ConversationCritique",
    "ScenarioEvaluation",
    "ScenarioSetup",
    # Multi-turn pattern model
    "MultiTurnPattern",
    # Components
    "PedagogicalAnalyzer",
    "ExpertCritic",
    "CritiqueReportGenerator",
    "PedagogicalCritiquePipeline",
]