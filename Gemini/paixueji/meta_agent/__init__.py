"""
Meta-Agent Evolution System for Paixueji.

A three-stage meta-agent that:
1. Analyzes critic reports to identify failing nodes (Stage 1)
2. Diagnoses root causes and proposes architectural changes (Stage 2)
3. Verifies prompt changes via a test-compare loop (Stage 3)

Usage:
    python -m meta_agent evolve reports/AIF/banana_20260209_102935.md
    python -m meta_agent analyze reports/AIF/banana_20260209_102935.md
    python -m meta_agent diagnose reports/AIF/banana_20260209_102935.md
"""

from .schema import (
    ReportAnalysis,
    ArchitectureDiagnosis,
    EvolutionResult,
    VerificationConfig,
    VerifiedChange,
    ProposedChange,
    ChangeType,
)
from .report_parser import parse_report
from .stage1_analyzer import analyze_report
from .stage2_diagnostician import diagnose
from .stage3_verifier import verify_changes


async def evolve(
    client,
    report_path: str,
    max_iterations: int = 3,
    improvement_threshold: float = 5.0,
    no_verify: bool = False,
    model_name: str = "gemini-2.5-pro",
    verbose: bool = False,
) -> EvolutionResult:
    """
    Run the full meta-agent evolution loop.

    Stage 1: Analyze the report → ReportAnalysis
    Stage 2: Diagnose root causes → ArchitectureDiagnosis
    Stage 3: Verify prompt changes → EvolutionResult

    Args:
        client: Google GenAI client (Vertex AI)
        report_path: Path to the .md critic report
        max_iterations: Max verification attempts per change
        improvement_threshold: Min effectiveness gain to accept a change
        no_verify: If True, skip Stage 3 (return Stage 1+2 results only)
        model_name: Gemini model for LLM calls
        verbose: Print intermediate results

    Returns:
        EvolutionResult with verified and proposed changes
    """
    # Stage 1: Analyze
    if verbose:
        print("=" * 60)
        print("STAGE 1: Report Analysis")
        print("=" * 60)

    analysis = await analyze_report(
        client=client,
        report_path=report_path,
        model_name=model_name,
        verbose=verbose,
    )

    if analysis.severity_assessment == "minor" and not analysis.suspected_nodes:
        return EvolutionResult(
            summary="No significant issues detected. System is performing well.",
        )

    # Stage 2: Diagnose
    if verbose:
        print("\n" + "=" * 60)
        print("STAGE 2: Architecture Diagnosis")
        print("=" * 60)

    diagnosis = await diagnose(
        client=client,
        analysis=analysis,
        model_name=model_name,
        verbose=verbose,
    )

    if no_verify:
        # Return Stage 1+2 results without verification
        return EvolutionResult(
            unverified_proposals=diagnosis.proposed_changes,
            final_effectiveness=analysis.overall_effectiveness,
            summary=(
                f"Analysis + Diagnosis complete (verification skipped). "
                f"{len(diagnosis.proposed_changes)} change(s) proposed. "
                f"Root causes: {len(diagnosis.root_causes)}."
            ),
        )

    # Stage 3: Verify
    if verbose:
        print("\n" + "=" * 60)
        print("STAGE 3: Verification Loop")
        print("=" * 60)

    parsed_report = parse_report(report_path)

    verification_config = VerificationConfig(
        max_iterations=max_iterations,
        improvement_threshold=improvement_threshold,
    )

    result = await verify_changes(
        client=client,
        report_path=report_path,
        parsed_report=parsed_report,
        analysis=analysis,
        diagnosis=diagnosis,
        config=verification_config,
        model_name=model_name,
        verbose=verbose,
    )

    return result


__all__ = [
    "evolve",
    "parse_report",
    "analyze_report",
    "diagnose",
    "verify_changes",
    "ReportAnalysis",
    "ArchitectureDiagnosis",
    "EvolutionResult",
    "VerificationConfig",
    "VerifiedChange",
    "ProposedChange",
    "ChangeType",
]
