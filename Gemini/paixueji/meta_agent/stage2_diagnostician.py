"""
Stage 2: Architecture Diagnostician.

Takes a ReportAnalysis from Stage 1, enriches it with architecture context,
and uses Gemini 2.5 Pro (with thinking) to diagnose root causes and propose
specific architectural changes.
"""

import json
import re

from google import genai
from google.genai.types import GenerateContentConfig

from .schema import (
    ReportAnalysis,
    ArchitectureDiagnosis,
    EvolutionHistory,
)
from .architecture_manifest import build_architecture_context
from .prompts import STAGE2_SYSTEM, STAGE2_PROMPT, STAGE2_PREVIOUS_ATTEMPTS


async def diagnose(
    client: genai.Client,
    analysis: ReportAnalysis,
    model_name: str = "gemini-2.5-pro",
    evolution_history: EvolutionHistory | None = None,
    verbose: bool = False,
) -> ArchitectureDiagnosis:
    """
    Diagnose root causes and propose architectural changes.

    Args:
        client: Google GenAI client (Vertex AI)
        analysis: Stage 1 ReportAnalysis
        model_name: Model to use for diagnosis
        evolution_history: Previous failed attempts (for retry loop)
        verbose: Print intermediate results

    Returns:
        ArchitectureDiagnosis with root causes and proposed changes
    """
    # Step 1: Build architecture context from suspected nodes
    suspected_nodes_dicts = [
        node.model_dump() for node in analysis.suspected_nodes
    ]

    # Collect all response types across suspected nodes
    all_response_types = []
    for node in analysis.suspected_nodes:
        all_response_types.extend(node.response_types)

    architecture_context = build_architecture_context(
        suspected_nodes=suspected_nodes_dicts,
        response_types=list(set(all_response_types)),
    )

    if verbose:
        print(f"Built architecture context ({len(architecture_context)} chars)")
        print(f"  Suspected nodes: {[n.node_name for n in analysis.suspected_nodes]}")
        print(f"  Response types: {list(set(all_response_types))}")

    # Step 2: Build the LLM prompt
    analysis_json = analysis.model_dump_json(indent=2)

    previous_attempts_section = ""
    if evolution_history and evolution_history.attempts:
        attempts_lines = []
        for attempt in evolution_history.attempts:
            attempts_lines.append(
                f"- Iteration {attempt.iteration}: "
                f"Changed {attempt.change_applied.change_type.value} on '{attempt.change_applied.target}'. "
                f"Description: {attempt.change_applied.description}. "
                f"Result: effectiveness {attempt.old_effectiveness:.1f} → {attempt.new_effectiveness:.1f}. "
                f"New failures: {', '.join(attempt.new_failures) or 'none'}. "
                f"Reason: {attempt.rejection_reason}"
            )
        previous_attempts_section = STAGE2_PREVIOUS_ATTEMPTS.format(
            attempts_text="\n".join(attempts_lines)
        )

    prompt = STAGE2_PROMPT.format(
        analysis_json=analysis_json,
        architecture_context=architecture_context,
        previous_attempts_section=previous_attempts_section,
    )

    if verbose:
        print(f"Calling {model_name} for Stage 2 diagnosis...")

    # Step 3: Call Gemini with thinking enabled
    config = GenerateContentConfig(
        system_instruction=STAGE2_SYSTEM,
        temperature=0.2,
        response_mime_type="application/json",
        thinking_config={"thinking_budget": 8192},
    )

    response = await client.aio.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )

    # Step 4: Parse and validate response
    raw_text = response.text
    diagnosis = _parse_diagnosis_response(raw_text)

    if verbose:
        print(f"Diagnosis complete: {len(diagnosis.root_causes)} root causes")
        print(f"  Proposed changes: {len(diagnosis.proposed_changes)}")
        for change in diagnosis.proposed_changes:
            print(f"  - [{change.change_type.value}] {change.target} (P{change.priority}, {change.risk_level})")

    return diagnosis


def _parse_diagnosis_response(raw_text: str) -> ArchitectureDiagnosis:
    """Parse the LLM response into an ArchitectureDiagnosis."""
    text = raw_text.strip()
    text = re.sub(r"^```json\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    try:
        data = json.loads(text)
        return ArchitectureDiagnosis(**data)
    except (json.JSONDecodeError, Exception) as e:
        return ArchitectureDiagnosis(
            root_causes=[],
            proposed_changes=[],
            summary=f"Failed to parse LLM response: {e}. Raw: {text[:500]}",
            estimated_impact="unknown",
        )
