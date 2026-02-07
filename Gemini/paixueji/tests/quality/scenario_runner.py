"""
Scenario Runner for Pedagogical Quality Testing.

Runs test scenarios through the real Paixueji system to capture
actual model responses for critique. This allows automated
batch testing of pedagogical effectiveness.

Flow:
    Scenario YAML -> Build State -> Run paixueji_graph -> Capture Response -> JSON
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from google import genai

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph import paixueji_graph, PaixuejiState
from paixueji_assistant import PaixuejiAssistant
from schema import StreamChunk

from .schema import Scenario


class ResponseCapture:
    """
    Captures streaming responses from the Paixueji graph.

    Collects all chunks and provides the final full response text.
    """

    def __init__(self):
        self.chunks: list[StreamChunk] = []
        self.full_response: str = ""
        self.response_type: str | None = None

    async def callback(self, chunk: StreamChunk):
        """Callback function for stream_callback in PaixuejiState."""
        self.chunks.append(chunk)

        # The final chunk contains the full response
        if chunk.finish:
            self.full_response = chunk.response
            self.response_type = chunk.response_type

    def get_response_text(self) -> str:
        """Get the captured response text."""
        # If we have a finish chunk, use its full response
        if self.full_response:
            return self.full_response

        # Otherwise concatenate all chunk responses
        return "".join(c.response for c in self.chunks if c.response)


class ScenarioRunner:
    """
    Runs pedagogical scenarios through the real Paixueji system.

    This class creates a PaixuejiAssistant, builds the appropriate state,
    and invokes the paixueji_graph to capture actual model responses.
    """

    def __init__(self, client: genai.Client, config: dict | None = None):
        """
        Initialize the scenario runner.

        Args:
            client: Google GenAI client (Vertex AI configured)
            config: Optional config dict. If not provided, loads from config.json
        """
        self.client = client
        self.config = config or self._load_config()

    def _load_config(self) -> dict:
        """Load config from the project's config.json."""
        config_path = Path(__file__).parent.parent.parent / "config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            raise FileNotFoundError(f"Config not found: {config_path}")

    async def run_scenario(self, scenario: Scenario) -> list[str]:
        """
        Execute a scenario and capture model responses.

        The scenario defines:
        - Setup (object, age, concept)
        - Conversation (model questions, child responses)

        This method:
        1. Creates a PaixuejiAssistant with scenario setup
        2. For each child response in the scenario:
           - Builds state from conversation history
           - Invokes paixueji_graph
           - Captures the model's actual response
        3. Returns list of model responses

        Args:
            scenario: The test scenario to run

        Returns:
            List of model's actual responses (one per child turn)
        """
        # Create a fresh assistant for this scenario
        assistant = PaixuejiAssistant(client=self.client, system_managed=False)

        # Set up assistant with scenario context
        assistant.age = scenario.setup.age
        assistant.object_name = scenario.setup.object_name

        # Build conversation history from scenario
        messages: list[dict] = []
        model_responses: list[str] = []

        # Process the conversation
        for i, exchange in enumerate(scenario.conversation):
            if exchange.role == "model":
                # Add model's scripted question to history
                messages.append({
                    "role": "assistant",
                    "content": exchange.content
                })
                # Also add to assistant's history
                assistant.conversation_history.append({
                    "role": "assistant",
                    "content": exchange.content
                })

            elif exchange.role == "child":
                # This is the child's response - run it through the graph
                child_input = exchange.content

                # Add child input to messages
                messages.append({
                    "role": "user",
                    "content": child_input
                })
                assistant.conversation_history.append({
                    "role": "user",
                    "content": child_input
                })

                # Build state for graph invocation
                state = self._build_state(
                    assistant=assistant,
                    messages=messages.copy(),
                    child_input=child_input,
                    scenario=scenario,
                )

                # Create response capture
                capture = ResponseCapture()
                state["stream_callback"] = capture.callback

                # Invoke the graph
                try:
                    await paixueji_graph.ainvoke(state)
                except Exception as e:
                    print(f"Graph error: {e}")
                    model_responses.append(f"[ERROR: {e}]")
                    continue

                # Get the response
                response_text = capture.get_response_text()
                model_responses.append(response_text)

                # Add model's response to history for next turn
                if response_text:
                    messages.append({
                        "role": "assistant",
                        "content": response_text
                    })
                    assistant.conversation_history.append({
                        "role": "assistant",
                        "content": response_text
                    })

                    # Increment correct count if the exchange was marked correct
                    if exchange.response_type and exchange.response_type.value == "ANSWER":
                        assistant.correct_answer_count += 1

        return model_responses

    def _build_state(
        self,
        assistant: PaixuejiAssistant,
        messages: list[dict],
        child_input: str,
        scenario: Scenario,
    ) -> dict:
        """
        Build PaixuejiState dict for graph invocation.

        Args:
            assistant: The PaixuejiAssistant instance
            messages: Current conversation history
            child_input: The child's current input
            scenario: The test scenario

        Returns:
            State dict compatible with paixueji_graph.ainvoke()
        """
        # Get prompts from assistant
        age_prompt = assistant.get_age_prompt(scenario.setup.age)
        category_prompt = assistant.get_category_prompt(
            assistant.level1_category,
            assistant.level2_category,
            assistant.level3_category
        )
        character_prompt = assistant.get_character_prompt("friendly")  # Default character
        focus_prompt = assistant.get_focus_prompt("depth")  # Default focus

        # Determine response type
        # If no assistant messages yet, it's introduction
        has_assistant_messages = any(m.get("role") == "assistant" for m in messages)
        response_type = None if has_assistant_messages else "introduction"

        # Build the state
        state: dict[str, Any] = {
            # Inputs
            "age": scenario.setup.age,
            "messages": messages,
            "content": child_input,
            "status": "normal",
            "session_id": f"scenario-{scenario.id}",
            "request_id": f"req-{scenario.id}-{int(time.time())}",
            "config": self.config,
            "client": self.client,
            "assistant": assistant,

            # Context
            "object_name": scenario.setup.object_name,
            "level1_category": assistant.level1_category,
            "level2_category": assistant.level2_category,
            "level3_category": assistant.level3_category,
            "correct_answer_count": assistant.correct_answer_count,

            # Prompts
            "age_prompt": age_prompt,
            "character_prompt": character_prompt,
            "category_prompt": category_prompt,
            "focus_prompt": focus_prompt,

            # Flow control
            "focus_mode": "depth",
            "validation_result": None,
            "is_engaged": None,
            "is_factually_correct": None,
            "correctness_reasoning": None,
            "switch_decision_reasoning": None,
            "new_object_name": None,
            "detected_object_name": None,
            "response_type": response_type,
            "suggested_objects": None,
            "natural_topic_completion": False,

            # Guide state (from scenario setup)
            "guide_phase": scenario.setup.guide_phase if hasattr(scenario.setup, 'guide_phase') else None,
            "guide_status": None,
            "guide_strategy": None,
            "guide_turn_count": None,
            "scaffold_level": None,
            "last_navigation_state": None,

            # Fun fact (not used in scenarios)
            "fun_fact": None,
            "fun_fact_hook": None,
            "fun_fact_question": None,
            "real_facts": None,

            # Output accumulation
            "full_response_text": "",
            "full_question_text": "",
            "sequence_number": 0,

            # Internal
            "stream_callback": None,  # Set by caller
            "start_time": time.time(),
        }

        return state


async def run_scenario_to_json(
    client: genai.Client,
    scenario: Scenario,
    output_path: Path | str | None = None,
) -> dict:
    """
    Convenience function to run a scenario and optionally save to JSON.

    Args:
        client: Google GenAI client
        scenario: The scenario to run
        output_path: Optional path to save the JSON output

    Returns:
        Dict with scenario ID and captured responses
    """
    runner = ScenarioRunner(client)
    responses = await runner.run_scenario(scenario)

    result = {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "object_name": scenario.setup.object_name,
        "age": scenario.setup.age,
        "responses": responses,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result
