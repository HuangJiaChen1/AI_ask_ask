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
    Scenario,
    ScenarioSetup,
    ScenarioEvaluation,
    ScenarioExchange,
    ConversationCritique,
    ExchangeCritique,
    PedagogicalContext,
    MultiTurnPattern,
)
from .pedagogical_analyzer import PedagogicalAnalyzer
from .expert_critic import ExpertCritic
from .critique_report import compile_conversation_critique, CritiqueReportGenerator


class PedagogicalCritiquePipeline:
    """
    Main pipeline for critiquing pedagogical effectiveness.

    This pipeline can:
    1. Critique a pre-recorded transcript
    2. Run a scenario through the real system, then critique it
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

    async def run_and_critique(self, scenario: Scenario) -> ConversationCritique:
        """
        Run a scenario through the real Paixueji system, then critique it.

        This is a convenience method that combines:
        1. ScenarioRunner.run_scenario() - execute the scenario
        2. critique_scenario() - analyze the responses

        Args:
            scenario: The test scenario to run and critique

        Returns:
            Full conversation critique with effectiveness analysis
        """
        from .scenario_runner import ScenarioRunner

        # Step 1: Run scenario through real system
        runner = ScenarioRunner(self.client)
        model_responses = await runner.run_scenario(scenario)

        # Step 2: Critique the captured responses
        return await self.critique_scenario(scenario, model_responses)

    async def critique_scenario(
        self,
        scenario: Scenario,
        model_responses: list[str],
    ) -> ConversationCritique:
        """
        Critique a scenario with provided model responses.

        The scenario defines the conversation structure (model questions,
        child responses), and model_responses provides what the model
        actually said after each child response.

        Args:
            scenario: The test scenario
            model_responses: List of model's actual responses after child turns

        Returns:
            Full conversation critique
        """
        exchange_critiques = []
        turn_number = 0

        # Find exchanges where we have: model_question → child_response → model_actual
        exchanges = self._extract_exchanges(scenario, model_responses)

        for model_question, child_response, model_actual in exchanges:
            turn_number += 1

            # Extract pedagogical context
            context = await self.analyzer.analyze(
                model_utterance=model_question,
                child_response=child_response,
                setup=scenario.setup,
            )

            # Run expert critic
            critique = await self.critic.critique(
                turn_number=turn_number,
                model_question=model_question,
                child_response=child_response,
                model_actual_response=model_actual,
                context=context,
                setup=scenario.setup,
                evaluation=scenario.evaluation,
            )

            exchange_critiques.append(critique)

        return compile_conversation_critique(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            exchange_critiques=exchange_critiques,
        )

    def _extract_exchanges(
        self,
        scenario: Scenario,
        model_responses: list[str],
    ) -> list[tuple[str, str, str]]:
        """
        Extract (model_question, child_response, model_actual) tuples.

        The scenario conversation defines the setup, and model_responses
        contains what the model actually said in response.
        """
        exchanges = []
        conversation = scenario.conversation
        response_idx = 0

        i = 0
        while i < len(conversation) - 1:
            # Find model → child pairs
            if (conversation[i].role == "model" and
                i + 1 < len(conversation) and
                conversation[i + 1].role == "child"):

                model_question = conversation[i].content
                child_response = conversation[i + 1].content

                # Get the actual model response
                if response_idx < len(model_responses):
                    model_actual = model_responses[response_idx]
                    response_idx += 1
                else:
                    # No more responses provided
                    break

                exchanges.append((model_question, child_response, model_actual))
                i += 2
            else:
                i += 1

        return exchanges

    async def critique_transcript(
        self,
        transcript: list[dict],
        object_name: str,
        key_concept: str,
        age: int = 5,
    ) -> ConversationCritique:
        """
        Critique a raw conversation transcript.

        Args:
            transcript: List of {"role": "model"|"child", "content": "..."}
            object_name: Object being discussed
            key_concept: Key concept being taught
            age: Child's age

        Returns:
            Full conversation critique
        """
        setup = ScenarioSetup(
            object_name=object_name,
            key_concept=key_concept,
            age=age,
        )
        evaluation = ScenarioEvaluation(
            must_do=["Advance the child's understanding"],
            must_not_do=["Rephrase questions without adding information"],
        )

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

                exchange_critiques.append(critique)
                i += 2  # Move past child response, next iteration starts from model_actual
            else:
                i += 1

        return compile_conversation_critique(
            scenario_id="transcript",
            scenario_name="Raw Transcript Analysis",
            exchange_critiques=exchange_critiques,
        )

class ScenarioLoader:
    """Loads test scenarios from YAML files."""

    def __init__(self, scenarios_dir: str | Path):
        """
        Initialize the loader.

        Args:
            scenarios_dir: Directory containing scenario YAML files
        """
        self.scenarios_dir = Path(scenarios_dir)

    def load_scenario(self, scenario_id: str) -> Scenario:
        """
        Load a specific scenario by ID.

        Searches all YAML files in the scenarios directory.
        """
        for yaml_file in self.scenarios_dir.glob("*.yaml"):
            scenarios = self._load_yaml(yaml_file)
            for scenario in scenarios:
                if scenario.id == scenario_id:
                    return scenario

        raise ValueError(f"Scenario not found: {scenario_id}")

    def load_all(self) -> list[Scenario]:
        """Load all scenarios from all YAML files."""
        all_scenarios = []
        for yaml_file in self.scenarios_dir.glob("*.yaml"):
            all_scenarios.extend(self._load_yaml(yaml_file))
        return all_scenarios

    def _load_yaml(self, path: Path) -> list[Scenario]:
        """Load scenarios from a single YAML file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        scenarios = []
        for scenario_data in data.get("scenarios", []):
            # Parse setup
            setup = ScenarioSetup(**scenario_data["setup"])

            # Parse conversation (may be empty for SIMULATED mode)
            conversation = [
                ScenarioExchange(**exchange)
                for exchange in scenario_data.get("conversation", [])
            ]

            # Parse evaluation
            evaluation = ScenarioEvaluation(**scenario_data.get("evaluation", {}))

            scenarios.append(Scenario(
                id=scenario_data["id"],
                name=scenario_data["name"],
                description=scenario_data["description"],
                setup=setup,
                conversation=conversation,
                evaluation=evaluation,
            ))

        return scenarios


async def run_critique_pipeline(
    client: genai.Client,
    scenario: Scenario,
    model_responses: list[str],
    output_path: str | Path | None = None,
    output_format: str = "markdown",
) -> ConversationCritique:
    """
    Convenience function to run the full critique pipeline.

    Args:
        client: Google GenAI client
        scenario: Test scenario
        model_responses: Model's actual responses
        output_path: Optional path to save report
        output_format: "json", "markdown", or "html"

    Returns:
        The conversation critique
    """
    pipeline = PedagogicalCritiquePipeline(client)
    critique = await pipeline.critique_scenario(scenario, model_responses)

    if output_path:
        CritiqueReportGenerator.save_report(critique, output_path, output_format)

    return critique
