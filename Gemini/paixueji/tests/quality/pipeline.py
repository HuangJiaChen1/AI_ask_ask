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


INTENT_EVALUATION_CRITERIA = {
    "curiosity": ScenarioEvaluation(
        must_do=["Give a simple, age-appropriate answer", "Expand with 1 interesting detail",
                 "Suggest one concrete action or observation"],
        must_not_do=["Lecture or summarize", "Ask a question that ignores their curiosity"]
    ),
    "clarifying": ScenarioEvaluation(
        must_do=["Acknowledge the child's effort positively",
                 "Gently provide the correct answer", "Encourage the child to try or observe"],
        must_not_do=["Ignore the wrong guess", "Simply repeat the question without help"]
    ),
    "informative": ScenarioEvaluation(
        must_do=["Affirm and give space to the child's sharing",
                 "React with a social/non-knowledge question (e.g. 'How did you learn that?')"],
        must_not_do=["Lecture on top of what the child shared", "Evaluate correctness of their claim"]
    ),
    "play": ScenarioEvaluation(
        must_do=["Play along with the child's imagination",
                 "Add one playful question or action suggestion"],
        must_not_do=["Correct the child's imaginative reframe", "Ignore the playfulness"]
    ),
    "emotional": ScenarioEvaluation(
        must_do=["Acknowledge the child's emotion first (before anything else)",
                 "Offer a gentle alternative action or topic"],
        must_not_do=["Dismiss or minimize the feeling", "Immediately pivot without empathy"]
    ),
    "avoidance": ScenarioEvaluation(
        must_do=["Acknowledge the child's reluctance without pushback",
                 "Offer a re-hook or change of topic gently"],
        must_not_do=["Ask the same question again", "Force engagement on the avoided topic"]
    ),
    "boundary": ScenarioEvaluation(
        must_do=["Show understanding of the child's curiosity",
                 "Clearly but gently deny the risky action",
                 "Suggest a safe alternative (e.g., take a photo)"],
        must_not_do=["Encourage or joke about unsafe behavior",
                     "Suggest other direct physical interaction"]
    ),
    "action": ScenarioEvaluation(
        must_do=["Respond directly to the command or request",
                 "Pivot gracefully if the command is a topic change"],
        must_not_do=["Ignore the child's command", "Go into deep conversation about the command itself"]
    ),
    "social": ScenarioEvaluation(
        must_do=["Respond warmly and directly to the personal question",
                 "Keep the answer brief and age-appropriate"],
        must_not_do=["Avoid the question", "Give a long or abstract answer"]
    ),
}


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

                # Detect intent node from nodes_executed for per-intent evaluation criteria
                _intent_node_names = {
                    "curiosity", "clarifying", "informative", "play", "emotional",
                    "avoidance", "boundary", "action", "social"
                }
                detected_intent = next(
                    (n.get("node") for n in nodes_executed if n.get("node") in _intent_node_names),
                    None
                )
                if mode == "chat" and detected_intent:
                    evaluation = INTENT_EVALUATION_CRITERIA.get(detected_intent, evaluation)

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
