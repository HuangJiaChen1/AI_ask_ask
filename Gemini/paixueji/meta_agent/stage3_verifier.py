"""
Stage 3: Verification Loop.

Tests proposed MODIFY_PROMPT changes by:
1. Building a test scenario from the original report
2. Applying prompt patches (monkey-patching)
3. Running the scenario through the real graph
4. Re-critiquing the new output
5. Comparing effectiveness scores
6. Accepting or rejecting the change

Only MODIFY_PROMPT changes are auto-testable. Structural changes remain
as unverified proposals for human review.
"""

import sys
from pathlib import Path

from google import genai

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import paixueji_prompts
from tests.quality.schema import (
    Scenario,
    ScenarioSetup,
    ScenarioExchange,
    ScenarioEvaluation,
)
from tests.quality.scenario_runner import ScenarioRunner
from tests.quality.pipeline import PedagogicalCritiquePipeline

from .schema import (
    ParsedReport,
    ReportAnalysis,
    ArchitectureDiagnosis,
    ChangeType,
    ProposedChange,
    VerificationConfig,
    AttemptResult,
    EvolutionHistory,
    VerifiedChange,
    EvolutionResult,
)
from .stage1_analyzer import analyze_report
from .stage2_diagnostician import diagnose


# Map from prompt keys to module-level constant names
PROMPT_KEY_TO_CONSTANT = {
    "system_prompt": "SYSTEM_PROMPT",
    "introduction_prompt": "INTRODUCTION_PROMPT",
    "feedback_response_prompt": "FEEDBACK_RESPONSE_PROMPT",
    "explanation_response_prompt": "EXPLANATION_RESPONSE_PROMPT",
    "correction_response_prompt": "CORRECTION_RESPONSE_PROMPT",
    "topic_switch_response_prompt": "TOPIC_SWITCH_RESPONSE_PROMPT",
    "followup_question_prompt": "FOLLOWUP_QUESTION_PROMPT",
    "completion_prompt": "COMPLETION_PROMPT",
    "fun_fact_grounding_prompt": "FUN_FACT_GROUNDING_PROMPT",
    "fun_fact_structuring_prompt": "FUN_FACT_STRUCTURING_PROMPT",
}


async def verify_changes(
    client: genai.Client,
    report_path: str,
    parsed_report: ParsedReport,
    analysis: ReportAnalysis,
    diagnosis: ArchitectureDiagnosis,
    config: VerificationConfig | None = None,
    model_name: str = "gemini-2.5-pro",
    verbose: bool = False,
) -> EvolutionResult:
    """
    Run the verification loop on proposed MODIFY_PROMPT changes.

    Args:
        client: Google GenAI client
        report_path: Path to the original report (for re-analysis on rejection)
        parsed_report: The parsed report data
        analysis: Stage 1 analysis
        diagnosis: Stage 2 diagnosis
        config: Verification configuration
        model_name: Model for re-analysis on rejection
        verbose: Print intermediate results

    Returns:
        EvolutionResult with verified and unverified changes
    """
    config = config or VerificationConfig()

    # Separate testable (MODIFY_PROMPT) from untestable changes
    prompt_changes = [
        c for c in diagnosis.proposed_changes
        if c.change_type == ChangeType.MODIFY_PROMPT
        and c.prompt_key
        and c.prompt_proposed
    ]
    structural_changes = [
        c for c in diagnosis.proposed_changes
        if c.change_type != ChangeType.MODIFY_PROMPT
    ]

    if verbose:
        print(f"\nVerification Loop:")
        print(f"  Testable prompt changes: {len(prompt_changes)}")
        print(f"  Structural proposals (untestable): {len(structural_changes)}")

    if not prompt_changes:
        return EvolutionResult(
            verified_changes=[],
            unverified_proposals=structural_changes,
            rejected_attempts=[],
            final_effectiveness=analysis.overall_effectiveness,
            summary="No testable prompt changes proposed. Only structural changes (human review needed).",
        )

    # Build test scenario from the original report
    scenario = _build_scenario_from_report(parsed_report, analysis)

    if verbose:
        print(f"  Built scenario: {scenario.name}")
        print(f"  Child turns: {sum(1 for e in scenario.conversation if e.role == 'child')}")

    # Get baseline effectiveness
    baseline_effectiveness = analysis.overall_effectiveness or 50.0

    # Run verification loop
    verified = []
    rejected = []
    current_analysis = analysis
    current_diagnosis = diagnosis

    for change in prompt_changes:
        if verbose:
            print(f"\n  Testing: {change.target} (P{change.priority})")

        history = EvolutionHistory(target_prompt=change.prompt_key or change.target)

        for iteration in range(1, config.max_iterations + 1):
            if verbose:
                print(f"    Iteration {iteration}/{config.max_iterations}")

            # Use the current iteration's change (may be updated on retry)
            current_change = change if iteration == 1 else _get_latest_change(
                current_diagnosis, change.prompt_key or change.target
            )
            if current_change is None:
                if verbose:
                    print(f"    No new change proposed for {change.target}, skipping")
                break

            result = await _test_single_change(
                client=client,
                scenario=scenario,
                change=current_change,
                baseline_effectiveness=baseline_effectiveness,
                threshold=config.improvement_threshold,
                verbose=verbose,
            )
            result.iteration = iteration

            if result.new_effectiveness > baseline_effectiveness + config.improvement_threshold:
                # Accept!
                verified.append(VerifiedChange(
                    change=current_change,
                    old_effectiveness=result.old_effectiveness,
                    new_effectiveness=result.new_effectiveness,
                    delta=result.new_effectiveness - result.old_effectiveness,
                    iterations_needed=iteration,
                ))
                if verbose:
                    print(f"    ACCEPTED! Delta: +{result.new_effectiveness - result.old_effectiveness:.1f}")
                break
            else:
                # Reject and feed back
                result.rejection_reason = (
                    f"Effectiveness did not improve by threshold "
                    f"({result.old_effectiveness:.1f} → {result.new_effectiveness:.1f}, "
                    f"needed +{config.improvement_threshold:.1f})"
                )
                history.attempts.append(result)
                rejected.append(result)

                if verbose:
                    print(f"    REJECTED: {result.rejection_reason}")

                if iteration < config.max_iterations:
                    # Re-run Stage 1+2 with failure context
                    if verbose:
                        print(f"    Re-running Stage 1+2 with failure context...")

                    current_analysis = await analyze_report(
                        client=client,
                        report_path=report_path,
                        model_name=model_name,
                        evolution_history=history,
                        verbose=verbose,
                    )
                    current_diagnosis = await diagnose(
                        client=client,
                        analysis=current_analysis,
                        model_name=model_name,
                        evolution_history=history,
                        verbose=verbose,
                    )

    # Calculate final effectiveness
    final_effectiveness = baseline_effectiveness
    if verified:
        final_effectiveness = max(v.new_effectiveness for v in verified)

    return EvolutionResult(
        verified_changes=verified,
        unverified_proposals=structural_changes,
        rejected_attempts=rejected,
        final_effectiveness=final_effectiveness,
        summary=_build_summary(verified, rejected, structural_changes, baseline_effectiveness, final_effectiveness),
    )


async def _test_single_change(
    client: genai.Client,
    scenario: Scenario,
    change: ProposedChange,
    baseline_effectiveness: float,
    threshold: float,
    verbose: bool = False,
) -> AttemptResult:
    """
    Test a single MODIFY_PROMPT change.

    Applies the patch, runs the scenario, critiques, compares, restores.
    """
    prompt_key = change.prompt_key
    constant_name = PROMPT_KEY_TO_CONSTANT.get(prompt_key)

    if not constant_name:
        return AttemptResult(
            iteration=0,
            change_applied=change,
            old_effectiveness=baseline_effectiveness,
            new_effectiveness=baseline_effectiveness,
            new_failures=[],
            rejection_reason=f"Unknown prompt key: {prompt_key}",
        )

    # Save original prompt
    original_value = getattr(paixueji_prompts, constant_name)

    try:
        # 1. Apply prompt patch
        if verbose:
            print(f"      Patching {constant_name}...")
        setattr(paixueji_prompts, constant_name, change.prompt_proposed)

        # 2. Run scenario
        if verbose:
            print(f"      Running scenario...")
        runner = ScenarioRunner(client)
        model_responses = await runner.run_scenario(scenario)

        # 3. Critique new output
        if verbose:
            print(f"      Critiquing new output...")
        pipeline = PedagogicalCritiquePipeline(client)
        critique = await pipeline.critique_scenario(scenario, model_responses)

        new_effectiveness = critique.overall_effectiveness

        # 4. Extract new failure types
        new_failures = list(critique.failure_breakdown.keys())

        if verbose:
            print(f"      New effectiveness: {new_effectiveness:.1f} (baseline: {baseline_effectiveness:.1f})")

        return AttemptResult(
            iteration=0,  # Set by caller
            change_applied=change,
            old_effectiveness=baseline_effectiveness,
            new_effectiveness=new_effectiveness,
            new_failures=new_failures,
        )

    except Exception as e:
        if verbose:
            print(f"      ERROR during verification: {e}")
        return AttemptResult(
            iteration=0,
            change_applied=change,
            old_effectiveness=baseline_effectiveness,
            new_effectiveness=baseline_effectiveness,
            new_failures=[],
            rejection_reason=f"Scenario run failed: {e}",
        )

    finally:
        # ALWAYS restore original prompt
        setattr(paixueji_prompts, constant_name, original_value)
        if verbose:
            print(f"      Restored {constant_name}")


def _get_latest_change(
    diagnosis: ArchitectureDiagnosis,
    target_prompt_key: str,
) -> ProposedChange | None:
    """Get the latest proposed change for a specific prompt key from a re-diagnosis."""
    for change in diagnosis.proposed_changes:
        if (
            change.change_type == ChangeType.MODIFY_PROMPT
            and change.prompt_key == target_prompt_key
            and change.prompt_proposed
        ):
            return change
    return None


def _build_scenario_from_report(
    parsed_report: ParsedReport,
    analysis: ReportAnalysis,
) -> Scenario:
    """
    Convert the original report's exchanges into a Scenario object for testing.

    Uses the report's child responses as the conversation input, and
    the analysis improvements as evaluation criteria.
    """
    conversation = []
    for exchange in parsed_report.exchanges:
        # Add the model's question
        if exchange.model_question:
            conversation.append(ScenarioExchange(
                role="model",
                content=exchange.model_question,
            ))
        # Add the child's response
        if exchange.child_response:
            conversation.append(ScenarioExchange(
                role="child",
                content=exchange.child_response,
            ))

    # Build evaluation criteria from the analysis
    must_do = analysis.consolidated_improvements[:5] if analysis.consolidated_improvements else [
        "Engage the child's curiosity",
        "Scaffold appropriately for the child's age",
    ]
    must_not_do = []
    for issue in analysis.critical_issues[:3]:
        must_not_do.append(f"Avoid: {issue}")

    setup = ScenarioSetup(
        object_name=parsed_report.object_name or "unknown",
        key_concept=parsed_report.key_concept or f"general knowledge about {parsed_report.object_name}",
        age=parsed_report.age or 6,
    )

    return Scenario(
        id=f"evolution-{parsed_report.session_id or 'test'}",
        name=f"Evolution test for {parsed_report.object_name}",
        description=f"Auto-generated scenario from {parsed_report.source} report",
        setup=setup,
        conversation=conversation,
        evaluation=ScenarioEvaluation(
            must_do=must_do,
            must_not_do=must_not_do,
        ),
    )


def _build_summary(
    verified: list[VerifiedChange],
    rejected: list[AttemptResult],
    structural: list[ProposedChange],
    baseline: float,
    final: float,
) -> str:
    """Build a human-readable summary of the evolution result."""
    parts = []

    if verified:
        parts.append(
            f"{len(verified)} prompt change(s) verified "
            f"(effectiveness: {baseline:.1f} → {final:.1f}, "
            f"delta: +{final - baseline:.1f})"
        )
    else:
        parts.append("No prompt changes improved effectiveness above threshold")

    if rejected:
        parts.append(f"{len(rejected)} attempt(s) rejected")

    if structural:
        parts.append(f"{len(structural)} structural change(s) proposed (requires human review)")

    return ". ".join(parts) + "."
