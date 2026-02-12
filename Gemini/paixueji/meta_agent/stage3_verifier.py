"""
Stage 3: Verification Loop with Anti-Hardcoding.

Tests proposed MODIFY_PROMPT changes through a 3-layer verification process:
  Layer 1: Constraint — anti-hardcoding rules baked into Stage 2 prompts
  Layer 2: Detection — automated hardcoding scan before running any scenario
  Layer 3: Cross-validation — primary scenario + CV scenarios must both pass

Acceptance criteria are FAILURE-BASED, not score-based:
  - Primary: all original failure types eliminated, no new ones introduced
  - Cross-validation: no new failure types vs baseline, total count doesn't increase

Structural changes (CREATE_NODE, MODIFY_ROUTER, etc.) are not auto-testable
and remain as human-reviewed proposals.
"""

import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from google import genai

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import paixueji_prompts
from tests.quality.schema import (
    Scenario,
    ScenarioSetup,
    ScenarioExchange,
    ScenarioEvaluation,
    ConversationCritique,
)
from tests.quality.scenario_runner import ScenarioRunner
from tests.quality.pipeline import PedagogicalCritiquePipeline, ScenarioLoader

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


# Map from prompt keys to module-level constant names in paixueji_prompts
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

# Heuristic: which prompt keys are exercised by which child response types
PROMPT_TO_RESPONSE_TYPES = {
    "explanation_response_prompt": {"DONT_KNOW", "CONFUSED"},
    "correction_response_prompt": {"ANSWER"},  # wrong answers
    "feedback_response_prompt": {"ANSWER"},    # correct answers
    "followup_question_prompt": None,          # always exercised
    "introduction_prompt": {"FIRST_TURN"},
}

SCENARIOS_DIR = Path(__file__).parent.parent / "tests" / "quality" / "scenarios"
GENERATED_DIR = SCENARIOS_DIR / "generated"


# ============================================================================
# Layer 2: Hardcoding Detection
# ============================================================================

def extract_phrases(text: str, min_len: int = 3) -> list[str]:
    """Extract meaningful word groups from text for fingerprinting."""
    if not text:
        return []
    # Split into sentences, then extract n-grams
    phrases = []
    words = text.split()
    # Extract contiguous word groups of min_len to min_len+3 words
    for n in range(min_len, min(min_len + 4, len(words) + 1)):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i + n])
            if len(phrase) > 10:  # Skip very short phrases
                phrases.append(phrase)
    return phrases


def detect_hardcoding(proposed_prompt: str, report: ParsedReport) -> list[str]:
    """
    Scan proposed prompt for verbatim content from the report.
    Returns list of violations (empty = clean).
    """
    violations = []

    if not proposed_prompt or not report:
        return violations

    # Build fingerprints from report content
    fingerprints = set()
    if report.object_name:
        fingerprints.add(report.object_name.lower())

    for exchange in report.exchanges:
        # Child's actual words (shorter phrases)
        for phrase in extract_phrases(exchange.child_response, min_len=3):
            fingerprints.add(phrase.lower())
        # Model's actual responses (longer phrases to avoid false positives)
        for phrase in extract_phrases(exchange.model_response, min_len=5):
            fingerprints.add(phrase.lower())
        # Ideal responses from critique
        if exchange.ideal_response:
            for phrase in extract_phrases(exchange.ideal_response, min_len=5):
                fingerprints.add(phrase.lower())

    proposed_lower = proposed_prompt.lower()

    # Check for object name (except in {object_name} placeholder)
    if report.object_name:
        cleaned = proposed_lower.replace("{object_name}", "")
        obj_lower = report.object_name.lower()
        if obj_lower in cleaned:
            violations.append(f"Contains specific object name '{report.object_name}'")

    # Check for verbatim phrases from report (only long enough to be meaningful)
    for phrase in fingerprints:
        if len(phrase) > 15 and phrase in proposed_lower:
            violations.append(f"Contains verbatim report content: '{phrase[:50]}...'")

    # Check for conditional rules referencing specific content
    if_then_pattern = r"if.*(?:child|student|they).*(?:say|answer|respond).*['\"](.+?)['\"]"
    matches = re.findall(if_then_pattern, proposed_lower)
    if matches:
        violations.append(f"Contains specific if-then rules: {matches}")

    return violations


# ============================================================================
# Cross-Validation Scenario Selection
# ============================================================================

def select_cv_scenarios(
    prompt_key: str,
    min_count: int = 2,
    max_count: int = 4,
) -> list[Scenario]:
    """
    Select cross-validation scenarios that exercise the same prompt being modified.

    Uses a heuristic based on child response types in the scenario conversations.
    """
    loader = ScenarioLoader(SCENARIOS_DIR)
    all_scenarios = loader.load_all()

    # Also load from generated/ subdirectory if it exists
    if GENERATED_DIR.exists():
        gen_loader = ScenarioLoader(GENERATED_DIR)
        try:
            all_scenarios.extend(gen_loader.load_all())
        except Exception:
            pass  # No generated scenarios yet

    # Determine which response types exercise this prompt
    target_types = PROMPT_TO_RESPONSE_TYPES.get(prompt_key)

    if target_types is None:
        # followup_question_prompt — any scenario works, pick diverse ones
        selected = all_scenarios[:max_count]
        return selected[:max(min_count, len(selected))]

    # Filter scenarios by whether they contain exchanges with matching response types
    matching = []
    for scenario in all_scenarios:
        for exchange in scenario.conversation:
            if exchange.role == "child" and exchange.response_type:
                if exchange.response_type.value in target_types:
                    matching.append(scenario)
                    break

    # If not enough matches, fall back to all scenarios
    if len(matching) < min_count:
        matching = all_scenarios

    return matching[:max_count]


# ============================================================================
# Baseline Cache
# ============================================================================

class BaselineCache:
    """Cache critique results for unpatched scenarios. Computed once per evolve run."""

    def __init__(self, client: genai.Client):
        self.client = client
        self._cache: dict[str, ConversationCritique] = {}
        self._runner = ScenarioRunner(client)
        self._pipeline = PedagogicalCritiquePipeline(client)

    async def get_baseline(self, scenario: Scenario) -> ConversationCritique:
        """Get (or compute) the baseline critique for a scenario with unpatched prompts."""
        if scenario.id not in self._cache:
            responses = await self._runner.run_scenario(scenario)
            critique = await self._pipeline.critique_scenario(scenario, responses)
            self._cache[scenario.id] = critique
        return self._cache[scenario.id]


# ============================================================================
# Auto-Save Verified Scenarios
# ============================================================================

def save_verified_scenario(
    report: ParsedReport,
    analysis: ReportAnalysis,
    change: ProposedChange,
    eliminated_failures: list[str],
) -> str:
    """
    Save a verified scenario as YAML for future cross-validation.
    Returns the path to the saved file.
    """
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    obj_name = report.object_name or "unknown"
    date_str = datetime.now().strftime("%Y%m%d")
    # Find next available number
    existing = list(GENERATED_DIR.glob(f"EVOLVE-{obj_name}-{date_str}-*.yaml"))
    idx = len(existing) + 1
    filename = f"EVOLVE-{obj_name}-{date_str}-{idx:03d}.yaml"
    filepath = GENERATED_DIR / filename

    # Build conversation from report exchanges
    conversation = []
    for exchange in report.exchanges:
        if exchange.model_question:
            conv_entry = {
                "role": "model",
                "content": exchange.model_question,
            }
            conversation.append(conv_entry)
        if exchange.child_response:
            conv_entry = {
                "role": "child",
                "content": exchange.child_response,
            }
            # Add response_type from node trace if available
            for trace in exchange.node_trace:
                changes = trace.get("changes", {})
                if "response_type" in changes:
                    rt = changes["response_type"]
                    if rt == "explanation":
                        conv_entry["response_type"] = "DONT_KNOW"
                    elif rt == "gentle_correction":
                        conv_entry["response_type"] = "ANSWER"
                    elif rt == "feedback":
                        conv_entry["response_type"] = "ANSWER"
            conversation.append(conv_entry)

    # Build must_do from eliminated failures
    must_do = []
    for ft in eliminated_failures:
        if ft == "MISSED_TEACHABLE_MOMENT":
            must_do.append("Engage with the teaching moment instead of moving on")
        elif ft == "ABANDONED_INTENT":
            must_do.append("Maintain focus on the current learning concept")
        elif ft == "TOO_COMPLEX":
            must_do.append("Keep language and questions age-appropriate")
        elif ft == "SAME_QUESTION_REPHRASED":
            must_do.append("Add new information rather than rephrasing")
        elif ft == "MISSED_SCAFFOLD":
            must_do.append("Provide scaffolding when child is stuck")
        else:
            must_do.append(f"Avoid {ft.replace('_', ' ').lower()}")

    # Build must_not_do from failure descriptions
    must_not_do = []
    for issue in analysis.critical_issues[:3]:
        must_not_do.append(f"Avoid: {issue[:100]}")

    scenario_data = {
        "scenarios": [{
            "id": f"EVOLVE-{obj_name.upper()}-{date_str}-{idx:03d}",
            "name": f"Evolution regression test: {obj_name}",
            "description": f"Auto-generated from meta_agent evolution. Tests fix for: {', '.join(eliminated_failures)}",
            "setup": {
                "object_name": obj_name,
                "key_concept": report.key_concept or f"general knowledge about {obj_name}",
                "age": report.age,
            },
            "conversation": conversation,
            "evaluation": {
                "must_do": must_do or ["Engage the child's curiosity"],
                "must_not_do": must_not_do or ["Repeat the same question without new information"],
            },
            "metadata": {
                "source": "meta_agent_evolution",
                "report_path": str(report.session_id),
                "date": datetime.now().isoformat(),
                "prompt_modified": change.prompt_key or change.target,
            },
        }],
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(scenario_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return str(filepath)


# ============================================================================
# Main Verification Loop
# ============================================================================

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
    Run the 3-layer verification loop on proposed MODIFY_PROMPT changes.

    Layer 1: Constraint (anti-hardcoding rules in Stage 2 prompt — already applied)
    Layer 2: Detection (automated hardcoding scan before running scenarios)
    Layer 3: Cross-validation (primary + CV scenarios, failure-based acceptance)
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
            summary="No testable prompt changes proposed. Only structural changes (human review needed).",
        )

    # Build primary scenario from the original report
    primary_scenario = _build_scenario_from_report(parsed_report, analysis)

    # Extract original failure types from the report
    original_failure_types = set()
    for exchange in parsed_report.exchanges:
        for failure in exchange.failures:
            ft = failure.get("type")
            if ft:
                original_failure_types.add(ft)

    if verbose:
        print(f"  Primary scenario: {primary_scenario.name}")
        print(f"  Original failure types: {original_failure_types}")

    # Initialize baseline cache for CV scenarios
    baseline_cache = BaselineCache(client)

    # Run verification loop for each prompt change
    verified = []
    rejected = []
    current_analysis = analysis
    current_diagnosis = diagnosis

    for change in prompt_changes:
        if verbose:
            print(f"\n  Testing: {change.target} (P{change.priority})")

        history = EvolutionHistory(target_prompt=change.prompt_key or change.target)

        for iteration in range(1, config.max_iterations + 1):
            current_change = change if iteration == 1 else _get_latest_change(
                current_diagnosis, change.prompt_key or change.target
            )
            if current_change is None:
                if verbose:
                    print(f"    No new change proposed for {change.target}, skipping")
                break

            if verbose:
                print(f"    Iteration {iteration}/{config.max_iterations}")

            # --- Layer 2: Hardcoding Detection ---
            violations = detect_hardcoding(current_change.prompt_proposed, parsed_report)
            if violations:
                result = AttemptResult(
                    iteration=iteration,
                    change_applied=current_change,
                    rejection_type="HARDCODED",
                    violations=violations,
                )
                history.attempts.append(result)
                rejected.append(result)

                if verbose:
                    print(f"    REJECTED [HARDCODED]: {'; '.join(violations[:3])}")

                # Re-run Stage 2 with feedback
                if iteration < config.max_iterations:
                    if verbose:
                        print(f"    Re-running Stage 2 with hardcoding feedback...")
                    current_diagnosis = await diagnose(
                        client=client,
                        analysis=current_analysis,
                        model_name=model_name,
                        evolution_history=history,
                        verbose=verbose,
                    )
                continue

            # --- Layer 3: Cross-Validation ---
            result = await _verify_with_cross_validation(
                client=client,
                primary_scenario=primary_scenario,
                change=current_change,
                original_failure_types=original_failure_types,
                baseline_cache=baseline_cache,
                config=config,
                verbose=verbose,
            )
            result.iteration = iteration

            if result.rejection_type == "":
                # ACCEPTED!
                # Auto-save the verified scenario
                saved_path = save_verified_scenario(
                    report=parsed_report,
                    analysis=analysis,
                    change=current_change,
                    eliminated_failures=list(original_failure_types),
                )

                verified.append(VerifiedChange(
                    change=current_change,
                    primary_failures_eliminated=list(original_failure_types),
                    cv_scenarios_tested=[
                        r.get("scenario_id", "?")
                        for r in result.cv_regressions
                    ] if result.cv_regressions else [],
                    cv_regressions=0,
                    iterations_needed=iteration,
                    saved_scenario_path=saved_path,
                ))
                if verbose:
                    print(f"    ACCEPTED! Scenario saved to: {saved_path}")
                break
            else:
                # REJECTED
                history.attempts.append(result)
                rejected.append(result)

                if verbose:
                    print(f"    REJECTED [{result.rejection_type}]")

                if iteration < config.max_iterations:
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

    return EvolutionResult(
        verified_changes=verified,
        unverified_proposals=structural_changes,
        rejected_attempts=rejected,
        summary=_build_summary(verified, rejected, structural_changes),
    )


async def _verify_with_cross_validation(
    client: genai.Client,
    primary_scenario: Scenario,
    change: ProposedChange,
    original_failure_types: set[str],
    baseline_cache: BaselineCache,
    config: VerificationConfig,
    verbose: bool = False,
) -> AttemptResult:
    """
    Apply prompt patch, run primary + CV scenarios, compare failures.

    Returns AttemptResult with rejection_type="" for acceptance.
    """
    prompt_key = change.prompt_key
    constant_name = PROMPT_KEY_TO_CONSTANT.get(prompt_key)

    if not constant_name:
        return AttemptResult(
            iteration=0,
            change_applied=change,
            rejection_type="INEFFECTIVE",
            remaining_failures=list(original_failure_types),
            new_failures=[f"Unknown prompt key: {prompt_key}"],
        )

    # Save original prompt
    original_value = getattr(paixueji_prompts, constant_name)

    try:
        # 1. Apply prompt patch
        if verbose:
            print(f"      Patching {constant_name}...")
        setattr(paixueji_prompts, constant_name, change.prompt_proposed)

        # 2. Run primary scenario
        if verbose:
            print(f"      Running primary scenario...")
        runner = ScenarioRunner(client)
        pipeline = PedagogicalCritiquePipeline(client)

        primary_responses = await runner.run_scenario(primary_scenario)
        primary_critique = await pipeline.critique_scenario(primary_scenario, primary_responses)

        # 3. Check primary acceptance: original failure types eliminated?
        new_failure_types = set(primary_critique.failure_breakdown.keys())
        remaining = original_failure_types & new_failure_types
        introduced = new_failure_types - original_failure_types

        if verbose:
            print(f"      Primary failures: {new_failure_types}")
            print(f"      Remaining original: {remaining}")
            print(f"      Newly introduced: {introduced}")

        primary_passed = (len(remaining) == 0 and len(introduced) == 0)

        if not primary_passed:
            return AttemptResult(
                iteration=0,
                change_applied=change,
                rejection_type="INEFFECTIVE",
                remaining_failures=list(remaining),
                new_failures=list(introduced),
                primary_passed=False,
            )

        # 4. Select and run cross-validation scenarios
        cv_scenarios = select_cv_scenarios(
            prompt_key=prompt_key,
            min_count=config.min_cv_scenarios,
            max_count=config.max_cv_scenarios,
        )

        if verbose:
            print(f"      Running {len(cv_scenarios)} CV scenario(s)...")

        cv_regressions = []
        for cv_scenario in cv_scenarios:
            # Get baseline (with UNPATCHED prompts — needs restore first!)
            # The baseline was cached before patching, OR we compute it now
            # Note: baseline_cache should have been populated before patching
            # but if not, we restore, compute, then re-patch
            baseline_critique = baseline_cache._cache.get(cv_scenario.id)

            if baseline_critique is None:
                # Need to compute baseline with original prompt
                setattr(paixueji_prompts, constant_name, original_value)
                baseline_critique = await baseline_cache.get_baseline(cv_scenario)
                setattr(paixueji_prompts, constant_name, change.prompt_proposed)

            baseline_failures = set(baseline_critique.failure_breakdown.keys())
            baseline_count = sum(baseline_critique.failure_breakdown.values())

            # Run CV scenario with patched prompt
            cv_responses = await runner.run_scenario(cv_scenario)
            cv_critique = await pipeline.critique_scenario(cv_scenario, cv_responses)

            cv_failures = set(cv_critique.failure_breakdown.keys())
            cv_count = sum(cv_critique.failure_breakdown.values())

            # Check: no new failure types, total count doesn't increase
            new_cv_failures = cv_failures - baseline_failures
            if new_cv_failures or cv_count > baseline_count:
                cv_regressions.append({
                    "scenario_id": cv_scenario.id,
                    "new_failures_introduced": list(new_cv_failures),
                    "baseline_count": baseline_count,
                    "new_count": cv_count,
                })

                if verbose:
                    print(f"      CV regression in {cv_scenario.id}: new={new_cv_failures}, count {baseline_count}→{cv_count}")

        if cv_regressions:
            return AttemptResult(
                iteration=0,
                change_applied=change,
                rejection_type="OVERFITTING",
                primary_passed=True,
                cv_regressions=cv_regressions,
            )

        # 5. All checks passed!
        return AttemptResult(
            iteration=0,
            change_applied=change,
            rejection_type="",  # Empty = accepted
            primary_passed=True,
            cv_regressions=[],
        )

    except Exception as e:
        if verbose:
            print(f"      ERROR during verification: {e}")
        return AttemptResult(
            iteration=0,
            change_applied=change,
            rejection_type="INEFFECTIVE",
            remaining_failures=list(original_failure_types),
            new_failures=[f"Scenario run failed: {e}"],
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
    """
    conversation = []
    for exchange in parsed_report.exchanges:
        if exchange.model_question:
            conversation.append(ScenarioExchange(
                role="model",
                content=exchange.model_question,
            ))
        if exchange.child_response:
            conversation.append(ScenarioExchange(
                role="child",
                content=exchange.child_response,
            ))

    must_do = analysis.consolidated_improvements[:5] if analysis.consolidated_improvements else [
        "Engage the child's curiosity",
        "Scaffold appropriately for the child's age",
    ]
    must_not_do = [f"Avoid: {issue}" for issue in analysis.critical_issues[:3]]

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
) -> str:
    """Build a human-readable summary of the evolution result."""
    parts = []

    if verified:
        targets = [v.change.target for v in verified]
        parts.append(
            f"{len(verified)} prompt change(s) verified and auto-saved "
            f"({', '.join(targets)})"
        )
    else:
        parts.append("No prompt changes passed verification")

    if rejected:
        by_type = {}
        for r in rejected:
            by_type[r.rejection_type] = by_type.get(r.rejection_type, 0) + 1
        type_str = ", ".join(f"{k}: {v}" for k, v in by_type.items())
        parts.append(f"{len(rejected)} attempt(s) rejected ({type_str})")

    if structural:
        parts.append(f"{len(structural)} structural change(s) proposed (requires human review)")

    return ". ".join(parts) + "."
