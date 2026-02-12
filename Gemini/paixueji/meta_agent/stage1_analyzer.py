"""
Stage 1: Report Analyzer.

Parses a critic report and uses Gemini 2.5 Pro (with thinking) to produce
a structured ReportAnalysis with node blame attribution and failure grouping.
"""

import json
import re

from google import genai
from google.genai.types import GenerateContentConfig

from .schema import ReportAnalysis, ParsedReport, EvolutionHistory
from .report_parser import parse_report
from .prompts import STAGE1_SYSTEM, STAGE1_PROMPT, STAGE1_PREVIOUS_ATTEMPTS


async def analyze_report(
    client: genai.Client,
    report_path: str,
    model_name: str = "gemini-2.5-pro",
    evolution_history: EvolutionHistory | None = None,
    verbose: bool = False,
) -> ReportAnalysis:
    """
    Analyze a critic report and produce a structured ReportAnalysis.

    Args:
        client: Google GenAI client (Vertex AI)
        report_path: Path to the .md report file
        model_name: Model to use for analysis
        evolution_history: Previous failed attempts (for retry loop)
        verbose: Print intermediate results

    Returns:
        ReportAnalysis with suspected nodes and failure groups
    """
    # Step 1: Parse the report
    parsed = parse_report(report_path)

    if verbose:
        print(f"Parsed {parsed.source} report: {parsed.object_name}")
        print(f"  Exchanges: {parsed.total_exchanges}, Failures: {parsed.failed_exchanges}")

    # Check for empty report
    if not parsed.exchanges:
        return ReportAnalysis(
            report_source=parsed.source,
            overall_effectiveness=parsed.overall_effectiveness,
            total_exchanges=0,
            failed_exchanges=0,
            severity_assessment="minor",
            summary="No exchanges found in report. Nothing to analyze.",
        )

    # Check if all exchanges have no failures
    has_failures = any(
        ex.failures or ex.human_critique
        for ex in parsed.exchanges
    )
    if not has_failures:
        return ReportAnalysis(
            report_source=parsed.source,
            overall_effectiveness=parsed.overall_effectiveness,
            total_exchanges=parsed.total_exchanges,
            failed_exchanges=0,
            severity_assessment="minor",
            summary="No failures detected in report. System is performing well.",
        )

    # Step 2: Build the LLM prompt
    report_json = parsed.model_dump_json(indent=2)

    previous_attempts_section = ""
    if evolution_history and evolution_history.attempts:
        attempts_lines = []
        for attempt in evolution_history.attempts:
            detail = f"[{attempt.rejection_type}]" if attempt.rejection_type else "[UNKNOWN]"
            if attempt.rejection_type == "INEFFECTIVE":
                detail += f" Remaining: {', '.join(attempt.remaining_failures) or 'unknown'}"
            elif attempt.rejection_type == "OVERFITTING":
                detail += f" CV regressions: {len(attempt.cv_regressions)}"
            elif attempt.rejection_type == "HARDCODED":
                detail += f" Violations: {len(attempt.violations)}"
            attempts_lines.append(
                f"- Iteration {attempt.iteration}: Changed {attempt.change_applied.target}. "
                f"Result: {detail}. "
                f"New failures: {', '.join(attempt.new_failures) or 'none'}."
            )
        previous_attempts_section = STAGE1_PREVIOUS_ATTEMPTS.format(
            attempts_text="\n".join(attempts_lines)
        )

    prompt = STAGE1_PROMPT.format(
        report_json=report_json,
        previous_attempts_section=previous_attempts_section,
    )

    if verbose:
        print(f"Calling {model_name} for Stage 1 analysis...")

    # Step 3: Call Gemini with thinking enabled
    config = GenerateContentConfig(
        system_instruction=STAGE1_SYSTEM,
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
    analysis = _parse_analysis_response(raw_text)

    if verbose:
        print(f"Analysis complete: {len(analysis.suspected_nodes)} suspected nodes")
        for node in analysis.suspected_nodes:
            print(f"  - {node.node_name} ({node.confidence}): {node.failure_count} failures")

    return analysis


def _parse_analysis_response(raw_text: str) -> ReportAnalysis:
    """Parse the LLM response into a ReportAnalysis, handling edge cases."""
    # Strip markdown code fences if present
    text = raw_text.strip()
    text = re.sub(r"^```json\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    try:
        data = json.loads(text)
        return ReportAnalysis(**data)
    except (json.JSONDecodeError, Exception) as e:
        # Return a minimal analysis on parse failure
        return ReportAnalysis(
            report_source="unknown",
            total_exchanges=0,
            failed_exchanges=0,
            severity_assessment="minor",
            summary=f"Failed to parse LLM response: {e}. Raw: {text[:500]}",
        )
