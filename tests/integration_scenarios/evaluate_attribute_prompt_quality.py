#!/usr/bin/env python3
"""
End-to-end quality evaluation for attribute pipeline intent prompts.

Runs each of the 14 attribute intents through the full pipeline:
  classify_intent -> generate_attribute_activation_response_stream
  -> ask_followup_question_stream (where applicable)

Saves raw outputs to JSON and Markdown for manual audit.

Usage:
  cd /path/to/repo
  python tests/integration_scenarios/evaluate_attribute_prompt_quality.py

Environment:
  Uses Application Default Credentials (ADC) — no GOOGLE_APPLICATION_CREDENTIALS
  env var required. ADC is discovered automatically by genai.Client at:
    ~/.config/gcloud/application_default_credentials.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Add project root so imports resolve when run as a script
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google import genai
from google.genai.types import HttpOptions

import paixueji_prompts
from graph import INTENTS_WITHOUT_FOLLOWUP
from stream.validation import classify_intent
from stream.response_generators import generate_attribute_activation_response_stream
from stream.question_generators import ask_followup_question_stream
from stream.utils import prepare_messages_for_streaming


# ============================================================================
# Configuration
# ============================================================================

OBJECT_NAME = "fluffy cat"
OBSERVATION_ANGLE = "texture"
ACTIVITY_TARGET = "Describe how the cat's fur feels when you touch it"
AGE = 6

# Age prompt for 5-6 year olds (from age_prompts.json)
AGE_PROMPT = (
    "Focus on WHAT and HOW questions. Ask about properties, features, processes, "
    "and actions. Examples: 'What does it do?', 'How does it move?', 'How does it grow?', "
    "'What happens when...?', 'How do we use it?'. Introduce simple cause-and-effect "
    "relationships. Use vocabulary appropriate for 5-6 year olds. Encourage understanding "
    "of processes and sequences."
)


# ============================================================================
# Test scenarios — one per attribute intent
# ============================================================================

@dataclass
class TestScenario:
    intent: str
    description: str
    history: list[dict]
    child_input: str
    expected_strategy: str


# Shared opening turn for all scenarios
_OPENING = {"role": "assistant", "content": "Hey there! Look at this fluffy cat. What do you notice about how its fur feels?"}

ALL_SCENARIOS: list[TestScenario] = [
    TestScenario(
        intent="curiosity",
        description="Child asks why the fur is fluffy",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! What else do you feel when you pet it?"},
            {"role": "user", "content": "It's warm and fluffy!"},
            {"role": "assistant", "content": "Warm and fluffy — nice! Do you think all cats feel the same?"},
        ],
        child_input="Why is the fur so fluffy?",
        expected_strategy="Honor curiosity about texture, invite observation, closing question about texture",
    ),
    TestScenario(
        intent="concept_confusion",
        description="Child asks meaning of a word the model just used",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! The fur is also very fuzzy."},
            {"role": "user", "content": "Fuzzy!"},
            {"role": "assistant", "content": "Can you find something fuzzy at home?"},
        ],
        child_input="What does fuzzy mean?",
        expected_strategy="Honor observation, do NOT defend with facts, re-ask observationally about texture",
    ),
    TestScenario(
        intent="clarifying_idk",
        description="Child says they don't know",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! What about the tail — does it feel the same?"},
            {"role": "user", "content": "I don't know"},
            {"role": "assistant", "content": "That's okay! Can you guess what the tail might feel like?"},
        ],
        child_input="Um...",
        expected_strategy="Accept, scaffold hint about texture, low-pressure question",
    ),
    TestScenario(
        intent="clarifying_wrong",
        description="Child gives a wrong answer about texture",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! Is the fur smooth or bumpy?"},
            {"role": "user", "content": "Smooth!"},
            {"role": "assistant", "content": "Smooth! What else do you feel?"},
        ],
        child_input="It feels like sandpaper!",
        expected_strategy="Warm acknowledgment, reframe (NOT correct), re-engagement question about texture",
    ),
    TestScenario(
        intent="clarifying_constraint",
        description="Child describes a real-world constraint",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! Can you touch it and tell me more?"},
            {"role": "user", "content": "It's fluffy!"},
            {"role": "assistant", "content": "Fluffy! Can you compare it to your shirt?"},
        ],
        child_input="I don't have a cat at home",
        expected_strategy="Validate constraint, redirect to texture, open question",
    ),
    TestScenario(
        intent="correct_answer",
        description="Child gives a meaningful on-target observation about texture",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! What happens when you rub the fur backwards?"},
            {"role": "user", "content": "It gets messy!"},
            {"role": "assistant", "content": "Messy! What does it feel like?"},
        ],
        child_input="It feels rough and a little bumpy when I go backwards",
        expected_strategy="Confirm + observation bridge, extend same texture angle, NO question",
    ),
    TestScenario(
        intent="informative",
        description="Child shares relevant information about texture",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! What kind of fur does your cat have?"},
            {"role": "user", "content": "I don't have a cat."},
            {"role": "assistant", "content": "No cat! What animal do you like to touch?"},
        ],
        child_input="My dog has short hair but this cat has super long and fluffy fur",
        expected_strategy="Celebrate + extend same observation_angle, NO question",
    ),
    TestScenario(
        intent="play",
        description="Child wants to play",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! If you could give this cat a new texture, what would it be?"},
            {"role": "user", "content": "Like a cloud!"},
            {"role": "assistant", "content": "A cloud cat! What would that feel like?"},
        ],
        child_input="Pretend the cat is a pillow and we jump on it!",
        expected_strategy="Embrace play, bridge to texture, fun question about texture",
    ),
    TestScenario(
        intent="emotional",
        description="Child expresses emotion",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! How does touching it make you feel?"},
            {"role": "user", "content": "Happy!"},
            {"role": "assistant", "content": "Happy! What does it remind you of?"},
        ],
        child_input="I'm scared the cat will scratch me",
        expected_strategy="Acknowledge, gentle path back to texture, question",
    ),
    TestScenario(
        intent="avoidance",
        description="Child wants to avoid the topic",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! What else do you notice about the texture?"},
            {"role": "user", "content": "It's fluffy!"},
            {"role": "assistant", "content": "Fluffy! Can you describe it more?"},
        ],
        child_input="Let's talk about dogs instead",
        expected_strategy="Accept, one gentle option back to texture, question",
    ),
    TestScenario(
        intent="boundary",
        description="Child tests limits",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! Can you pat it gently?"},
            {"role": "user", "content": "Okay!"},
            {"role": "assistant", "content": "What does it feel like when you pat it?"},
        ],
        child_input="I don't want to talk about this anymore, this is boring",
        expected_strategy="Validate, brief boundary, redirect to texture, question",
    ),
    TestScenario(
        intent="action",
        description="Child asks the assistant to do something",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! Can you show me how soft with your hands?"},
            {"role": "user", "content": "Like this!"},
            {"role": "assistant", "content": "Great! What else do you feel?"},
        ],
        child_input="Draw a picture of the cat for me",
        expected_strategy="Brief response, redirect action toward texture, question",
    ),
    TestScenario(
        intent="social",
        description="Child asks a social question",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! Do you have a favorite animal?"},
            {"role": "user", "content": "Dogs!"},
            {"role": "assistant", "content": "Dogs! What do you like about them?"},
        ],
        child_input="What's your favorite animal?",
        expected_strategy="Playful answer, redirect to texture, NO question",
    ),
    TestScenario(
        intent="social_acknowledgment",
        description="Child says thank you",
        history=[
            _OPENING,
            {"role": "user", "content": "It's soft!"},
            {"role": "assistant", "content": "Soft! You did great noticing that!"},
            {"role": "user", "content": "Thank you!"},
            {"role": "assistant", "content": "You're welcome! What else do you feel?"},
        ],
        child_input="Thanks for talking with me!",
        expected_strategy="Brief warm response, NO question",
    ),
]


# ============================================================================
# Minimal assistant for classify_intent
# ============================================================================

class MinimalAssistant:
    """Just enough to satisfy classify_intent's needs."""

    def __init__(self, client: genai.Client, config: dict, conversation_history: list[dict]):
        self.client = client
        self.config = config
        self.conversation_history = conversation_history


# ============================================================================
# Guide builders
# ============================================================================

def build_continue_guide(observation_angle: str, object_name: str) -> str:
    """Build a simplified CONTINUE-mode guide for the attribute pipeline."""
    return f"""{paixueji_prompts.SENSORY_SAFETY_RULES}

CONVERSATION DIRECTION: Explore the {observation_angle} of the {object_name}.
Be playful and curious. Ask open-ended questions that help the child notice
and describe the {observation_angle} in their own words.

ANTI-PATTERNS -- NEVER produce these:
- "What {observation_angle} is it?" -- quiz
- "Do you know what {observation_angle} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
- Mention activities, games, quests, or collecting
"""


def build_followup_guide(observation_angle: str, object_name: str) -> str:
    """Build a soft guide for the follow-up question generator."""
    return f"""{paixueji_prompts.SENSORY_SAFETY_RULES}

CONVERSATION DIRECTION: Ask a playful, open-ended question about the
{observation_angle} of the {object_name}. Help the child notice something new.

ANTI-PATTERNS -- NEVER produce these:
- "What {observation_angle} is it?" -- quiz
- "Do you know what {observation_angle} it has?" -- quiz with wrapper
- "What else can you tell me about it?" -- too vague
"""


# ============================================================================
# Execution engine
# ============================================================================

async def run_scenario(
    scenario: TestScenario,
    client: genai.Client,
    config: dict,
) -> dict:
    """Run one scenario through the full attribute pipeline."""
    print(f"\n{'=' * 60}")
    print(f"Testing intent: {scenario.intent.upper()}")
    print(f"  Description: {scenario.description}")
    print(f"  Child input: '{scenario.child_input}'")
    print(f"  Expected: {scenario.expected_strategy}")

    # Build conversation history with a system message prefix
    system_msg = {"role": "system", "content": "You are a friendly assistant talking to a child about objects."}
    conversation_history = [system_msg] + scenario.history

    # Step 1: classify_intent
    assistant = MinimalAssistant(client, config, conversation_history)
    classification = await classify_intent(
        assistant=assistant,
        child_answer=scenario.child_input,
        object_name=OBJECT_NAME,
        age=AGE,
    )
    predicted_intent = classification.get("intent_type", "UNKNOWN")
    classification_match = predicted_intent.upper() == scenario.intent.upper()
    print(f"  Classification: {predicted_intent} (match={classification_match})")
    if not classification_match:
        print(f"    [MISMATCH] Expected {scenario.intent}, got {predicted_intent}")
        print(f"    Reasoning: {classification.get('reasoning', 'N/A')}")

    # Use target intent for generation (bypass if mismatch — ensures every prompt is tested)
    intent_for_generation = scenario.intent.lower()

    # Prepare messages for response generator
    messages = prepare_messages_for_streaming(conversation_history.copy(), AGE_PROMPT)
    last_model_response = ""
    for msg in reversed(scenario.history):
        if msg.get("role") == "assistant":
            last_model_response = msg.get("content", "")
            break

    continue_guide = build_continue_guide(OBSERVATION_ANGLE, OBJECT_NAME)

    # Step 2: generate_attribute_activation_response_stream
    print(f"  Generating response with intent='{intent_for_generation}'...")
    full_response = ""
    response_generator = generate_attribute_activation_response_stream(
        messages=messages,
        intent_type=intent_for_generation,
        object_name=OBJECT_NAME,
        attribute_label=OBSERVATION_ANGLE,
        observation_angle=OBSERVATION_ANGLE,
        activity_target=ACTIVITY_TARGET,
        child_answer=scenario.child_input,
        reply_type="discovery",
        state_action="continue_conversation",
        age=AGE,
        age_prompt=AGE_PROMPT,
        knowledge_context="",
        last_model_response=last_model_response,
        config=config,
        client=client,
        multi_topic_guide=continue_guide,
    )
    async for _chunk, _token_usage, full_so_far in response_generator:
        full_response = full_so_far
    print(f"  Response length: {len(full_response)} chars")

    # Step 3: follow-up question (if applicable)
    full_followup = ""
    needs_followup = intent_for_generation not in INTENTS_WITHOUT_FOLLOWUP
    if needs_followup:
        print(f"  Generating follow-up question...")
        messages_with_response = messages + [
            {"role": "user", "content": scenario.child_input},
            {"role": "assistant", "content": full_response},
        ]
        followup_guide = build_followup_guide(OBSERVATION_ANGLE, OBJECT_NAME)
        followup_generator = ask_followup_question_stream(
            messages=messages_with_response,
            object_name=OBJECT_NAME,
            age_prompt=AGE_PROMPT,
            age=AGE,
            config=config,
            client=client,
            knowledge_context="",
            attribute_soft_guide=followup_guide,
            response_text=full_response,
            focus_topic=f"the {OBSERVATION_ANGLE} of the {OBJECT_NAME}",
        )
        async for _chunk, _token_usage, full_so_far in followup_generator:
            full_followup = full_so_far
        print(f"  Followup length: {len(full_followup)} chars")
    else:
        print(f"  Skipping follow-up (intent in INTENTS_WITHOUT_FOLLOWUP)")

    combined = (full_response + " " + full_followup).strip()

    return {
        "intent": scenario.intent,
        "description": scenario.description,
        "expected_strategy": scenario.expected_strategy,
        "history": scenario.history,
        "child_input": scenario.child_input,
        "classification": {
            "target": scenario.intent,
            "predicted": predicted_intent,
            "match": classification_match,
            "reasoning": classification.get("reasoning", ""),
            "action_subtype": classification.get("action_subtype"),
        },
        "response": full_response,
        "followup": full_followup,
        "combined": combined,
        "needs_followup": needs_followup,
    }


# ============================================================================
# Report generation
# ============================================================================

def generate_json_report(results: list[dict], output_dir: Path) -> Path:
    """Save raw results as JSON."""
    timestamp = int(time.time())
    output_path = output_dir / f"attribute_quality_raw_{timestamp}.json"
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def generate_markdown_report(results: list[dict], output_dir: Path) -> Path:
    """Generate a human-readable Markdown report."""
    timestamp = int(time.time())
    output_path = output_dir / f"attribute_quality_raw_{timestamp}.md"

    lines = []
    lines.append("# Attribute Prompt Quality Evaluation Report")
    lines.append(f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Object: `{OBJECT_NAME}` | Attribute: `{OBSERVATION_ANGLE}` | Age: `{AGE}`")
    lines.append("\n---\n")

    # Classification summary
    lines.append("## Classification Audit\n")
    mismatches = [r for r in results if not r["classification"]["match"]]
    lines.append(f"- Total intents tested: {len(results)}")
    lines.append(f"- Correct classifications: {len(results) - len(mismatches)}")
    lines.append(f"- Mismatches: {len(mismatches)}")
    if mismatches:
        lines.append("\n### Mismatches (classify_intent bugs)\n")
        for r in mismatches:
            c = r["classification"]
            lines.append(f"- **{r['intent']}**: expected `{c['target']}`, got `{c['predicted']}` — {c['reasoning']}")
    lines.append("\n---\n")

    # Per-intent deep dives
    lines.append("## Per-Intent Outputs\n")
    for r in results:
        lines.append(f"\n### {r['intent'].upper()}")
        lines.append(f"\n**Description**: {r['description']}")
        lines.append(f"\n**Expected strategy**: {r['expected_strategy']}")

        c = r["classification"]
        if c["match"]:
            lines.append(f"\n**Classification**: [OK] {c['predicted']} (correct)")
        else:
            lines.append(f"\n**Classification**: [MISMATCH] expected `{c['target']}`, got `{c['predicted']}`")
            lines.append(f"\n**Classifier reasoning**: {c['reasoning']}")

        lines.append(f"\n**Child input**: \"{r['child_input']}\"")

        lines.append(f"\n**Conversation history**:")
        for msg in r["history"]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"  - **{role}**: {content}")

        lines.append(f"\n**Assistant response**:")
        lines.append(f"\n```")
        lines.append(r["response"])
        lines.append("```")

        if r["needs_followup"]:
            lines.append(f"\n**Follow-up question**:")
            lines.append(f"\n```")
            lines.append(r["followup"])
            lines.append("```")
        else:
            lines.append(f"\n**Follow-up**: (inline — skipped)")

        lines.append(f"\n**Combined output**:")
        lines.append(f"\n```")
        lines.append(r["combined"])
        lines.append("```")

        lines.append("\n---")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ============================================================================
# Main
# ============================================================================

async def main():
    # Allow filtering intents via command line: python script.py curiosity play
    import sys
    filter_intents = None
    if len(sys.argv) > 1:
        filter_intents = {arg.lower() for arg in sys.argv[1:]}

    scenarios = ALL_SCENARIOS
    if filter_intents:
        scenarios = [s for s in ALL_SCENARIOS if s.intent.lower() in filter_intents]
        if not scenarios:
            print(f"No matching intents found for: {filter_intents}")
            print(f"Available: {[s.intent for s in ALL_SCENARIOS]}")
            return 1

    config_path = REPO_ROOT / "config.json"
    if not config_path.exists():
        # Fallback to tests/config.json
        config_path = REPO_ROOT / "tests" / "config.json"

    config = json.loads(config_path.read_text(encoding="utf-8"))
    print(f"Loaded config from {config_path}")

    client = genai.Client(
        vertexai=True,
        project=config["project"],
        location=config["location"],
        http_options=HttpOptions(api_version="v1"),
    )
    print(f"Gemini client initialized (project={config['project']}, location={config['location']})")

    # Use model from config
    if "model_name" not in config:
        config["model_name"] = "gemini-2.0-flash-lite"

    print(f"\nRunning {len(scenarios)} attribute intent scenarios...")
    print(f"Object: {OBJECT_NAME} | Attribute: {OBSERVATION_ANGLE} | Age: {AGE}")

    results: list[dict] = []
    for idx, scenario in enumerate(scenarios):
        print(f"\n  --- Scenario {idx + 1}/{len(scenarios)} ---")
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                result = await run_scenario(scenario, client, config)
                results.append(result)
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait = attempt * 15
                    print(f"  [RATE LIMIT] Attempt {attempt}/{max_retries}, waiting {wait}s...")
                    await asyncio.sleep(wait)
                    if attempt == max_retries:
                        print(f"  [FAILED] Max retries exceeded for {scenario.intent}")
                        results.append({
                            "intent": scenario.intent,
                            "description": scenario.description,
                            "error": err_str,
                        })
                else:
                    print(f"  [ERROR] {err_str}")
                    import traceback
                    traceback.print_exc()
                    results.append({
                        "intent": scenario.intent,
                        "description": scenario.description,
                        "error": err_str,
                    })
                    break
        # Delay between scenarios to respect rate limits
        if idx < len(scenarios) - 1:
            await asyncio.sleep(5)

    # Save reports
    output_dir = REPO_ROOT / "tests" / "integration_scenarios" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = generate_json_report(results, output_dir)
    md_path = generate_markdown_report(results, output_dir)

    print(f"\n{'=' * 60}")
    print("Evaluation complete!")
    print(f"  JSON report: {json_path}")
    print(f"  Markdown report: {md_path}")
    print(f"\nNext step: Read the Markdown report and manually audit each output.")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
