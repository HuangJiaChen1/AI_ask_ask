"""
Pedagogical Critique Pipeline.

Orchestrates the analysis and critique of conversations:
1. Load scenarios
2. Run conversations through the real system (optional)
3. Extract pedagogical context for each exchange
4. Run the expert critic on each exchange
5. Compile into a full critique report
"""

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

import yaml
from google import genai

from .schema import (
    ScenarioSetup,
    ScenarioEvaluation,
    ConversationCritique,
    ExchangeCritique,
    PedagogicalContext,
)
from .pedagogical_analyzer import PedagogicalAnalyzer
from .expert_critic import ExpertCritic
from .critique_report import compile_conversation_critique


class PedagogicalCritiquePipeline:
    """
    Main pipeline for critiquing pedagogical effectiveness.

    This pipeline focuses on critiquing conversation transcripts
    to provide pedagogical analysis and feedback.
    """

    def __init__(
        self,
        client: genai.Client,
        analyzer_model: str = "gemini-2.5-pro",
        critic_model: str = "gemini-2.5-pro",
    ):
        """
        Initialize the pipeline.

        Args:
            client: Google GenAI client
            analyzer_model: Model for pedagogical analysis (can be fast)
            critic_model: Model for expert critique (should be strong)
        """
        self.client = client
        self.analyzer = PedagogicalAnalyzer(client, analyzer_model)
        self.critic = ExpertCritic(client, critic_model)

    async def critique_transcript(
        self,
        transcript: list[dict],
        object_name: str,
        key_concept: str,
        age: int = 5,
        mode: str = "chat",
    ) -> ConversationCritique:
        """
        Critique a raw conversation transcript.

        Args:
            transcript: List of {"role": "model"|"child", "content": "..."}
            object_name: Object being discussed
            key_concept: Key concept being taught
            age: Child's age
            mode: "chat" or "guide" — determines evaluation criteria

        Returns:
            Full conversation critique
        """
        if mode == "guide":
            setup = ScenarioSetup(
                object_name=object_name,
                key_concept=key_concept,
                age=age,
                guide_phase="active",
            )
            evaluation = ScenarioEvaluation(
                must_do=[
                    "Advance understanding toward the key concept",
                    "Scaffold when child is stuck",
                ],
                must_not_do=[
                    "Rephrase without adding information",
                    "Abandon the key concept",
                ],
            )
            scenario_name = "Guide Phase Analysis"
        else:
            setup = ScenarioSetup(
                object_name=object_name,
                key_concept=f"general knowledge about {object_name}",
                age=age,
                guide_phase="chat",
            )
            evaluation = ScenarioEvaluation(
                must_do=[
                    "Engage curiosity",
                    "Ask age-appropriate questions",
                    "Respond with encouragement and new information",
                ],
                must_not_do=[
                    "Rephrase without adding information",
                    "Ignore the child's responses",
                ],
            )
            scenario_name = "Chat Phase Analysis"

        exchange_critiques = []
        turn_number = 0

        # Find triplets: model → child → model
        i = 0
        while i < len(transcript) - 2:
            if (transcript[i].get("role") == "model" and
                transcript[i + 1].get("role") == "child" and
                transcript[i + 2].get("role") == "model"):

                turn_number += 1

                model_question = transcript[i]["content"]
                child_response = transcript[i + 1]["content"]
                model_actual = transcript[i + 2]["content"]
                # Extract node execution trace from the model's response
                nodes_executed = transcript[i + 2].get("nodes_executed", [])

                # Extract context
                context = await self.analyzer.analyze(
                    model_utterance=model_question,
                    child_response=child_response,
                    setup=setup,
                )

                # Critique
                critique = await self.critic.critique(
                    turn_number=turn_number,
                    model_question=model_question,
                    child_response=child_response,
                    model_actual_response=model_actual,
                    context=context,
                    setup=setup,
                    evaluation=evaluation,
                )

                # Attach node execution trace and mode to the critique
                critique.nodes_executed = nodes_executed
                critique.mode = mode

                exchange_critiques.append(critique)
                i += 2  # Move past child response, next iteration starts from model_actual
            else:
                i += 1

        return compile_conversation_critique(
            scenario_id="transcript",
            scenario_name=scenario_name,
            exchange_critiques=exchange_critiques,
        )
