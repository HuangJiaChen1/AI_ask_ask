"""
CLI interface for the Meta-Agent Evolution System.

Usage:
    python -m meta_agent evolve reports/AIF/banana_20260209_102935.md
    python -m meta_agent analyze reports/AIF/banana_20260209_102935.md
    python -m meta_agent diagnose reports/AIF/banana_20260209_102935.md
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

from google import genai

from . import evolve, analyze_report, diagnose, parse_report
from .schema import EvolutionResult, ChangeType


def get_client() -> genai.Client:
    """Create a GenAI client using Vertex AI with config from config.json."""
    config_path = Path(__file__).parent.parent / "config.json"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        project = config.get("project", "elaborate-baton-480304-r8")
        location = config.get("location", "us-central1")
    else:
        project = "elaborate-baton-480304-r8"
        location = "us-central1"

    return genai.Client(
        vertexai=True,
        project=project,
        location=location,
    )


def _format_json(result, indent=2) -> str:
    """Format a Pydantic model as JSON."""
    return result.model_dump_json(indent=indent)


def _format_markdown(result: EvolutionResult) -> str:
    """Format an EvolutionResult as markdown."""
    lines = ["# Meta-Agent Evolution Report\n"]

    lines.append(f"## Summary\n{result.summary}\n")

    if result.verified_changes:
        lines.append("## Verified Changes (Tested & Proven)\n")
        for i, vc in enumerate(result.verified_changes, 1):
            lines.append(f"### {i}. {vc.change.target}")
            lines.append(f"- **Type:** {vc.change.change_type.value}")
            lines.append(f"- **Failures eliminated:** {', '.join(vc.primary_failures_eliminated)}")
            lines.append(f"- **CV scenarios tested:** {', '.join(vc.cv_scenarios_tested) or 'none'}")
            lines.append(f"- **CV regressions:** {vc.cv_regressions}")
            lines.append(f"- **Iterations:** {vc.iterations_needed}")
            lines.append(f"- **Rationale:** {vc.change.rationale}")
            if vc.saved_scenario_path:
                lines.append(f"- **Saved scenario:** {vc.saved_scenario_path}")
            if vc.change.prompt_proposed:
                lines.append(f"\n**New Prompt:**\n```\n{vc.change.prompt_proposed}\n```\n")

    if result.unverified_proposals:
        lines.append("## Proposed Changes (Human Review Needed)\n")
        for i, pc in enumerate(result.unverified_proposals, 1):
            lines.append(f"### {i}. [{pc.change_type.value}] {pc.target}")
            lines.append(f"- **Priority:** P{pc.priority}")
            lines.append(f"- **Risk:** {pc.risk_level}")
            lines.append(f"- **Description:** {pc.description}")
            lines.append(f"- **Rationale:** {pc.rationale}")
            if pc.graph_position:
                lines.append(f"- **Position:** {pc.graph_position}")
            if pc.router_conditions:
                lines.append(f"- **Conditions:** {pc.router_conditions}")
            lines.append("")

    if result.rejected_attempts:
        lines.append("## Rejected Attempts (Learning Record)\n")
        for att in result.rejected_attempts:
            details = f"[{att.rejection_type}]"
            if att.rejection_type == "HARDCODED":
                details += f" Violations: {'; '.join(att.violations[:2])}"
            elif att.rejection_type == "INEFFECTIVE":
                details += f" Remaining: {', '.join(att.remaining_failures)}"
            elif att.rejection_type == "OVERFITTING":
                details += f" CV regressions: {len(att.cv_regressions)}"
            lines.append(
                f"- **Iter {att.iteration}** {att.change_applied.target}: {details}"
            )
        lines.append("")

    return "\n".join(lines)


def _print_structural_proposals(result: EvolutionResult):
    """Print structural proposals in a prominent format for human review."""
    structural = [
        p for p in result.unverified_proposals
        if p.change_type != ChangeType.MODIFY_PROMPT
    ]
    if not structural:
        return

    print()
    print("=" * 59)
    print("  STRUCTURAL CHANGES PROPOSED (requires human review)")
    print("=" * 59)

    for i, pc in enumerate(structural, 1):
        print(f"\n{i}. [{pc.change_type.value}] \"{pc.target}\" (priority: {pc.priority}, risk: {pc.risk_level})")
        print(f"   Purpose: {pc.description}")
        if pc.graph_position:
            print(f"   Position: {pc.graph_position}")
        if pc.router_conditions:
            print(f"   Conditions: {pc.router_conditions}")
        print(f"   Rationale: {pc.rationale}")

    print(f"\nTo continue evolution after implementing these changes:")
    print(f"  python -m meta_agent evolve <new_report>")
    print("=" * 59)


# ============================================================================
# Commands
# ============================================================================

def cmd_analyze(args):
    """Stage 1 only: Analyze a report."""
    client = get_client()

    async def run():
        return await analyze_report(
            client=client,
            report_path=args.report,
            verbose=args.verbose,
        )

    analysis = asyncio.run(run())

    # Output
    output = _format_json(analysis)
    if args.output:
        Path(args.output).write_text(output, encoding='utf-8')
        print(f"Analysis saved to: {args.output}")
    else:
        print(output)

    # Print summary
    print(f"\n{'=' * 50}")
    print(f"Source: {analysis.report_source}")
    print(f"Severity: {analysis.severity_assessment}")
    print(f"Suspected nodes: {len(analysis.suspected_nodes)}")
    for node in analysis.suspected_nodes:
        print(f"  - {node.node_name} ({node.confidence}): "
              f"{node.failure_count} failures, types={node.response_types}")
    print(f"Failure groups: {len(analysis.failure_groups)}")
    print(f"Summary: {analysis.summary}")


def cmd_diagnose(args):
    """Stage 1 + 2: Analyze and diagnose."""
    client = get_client()

    async def run():
        analysis = await analyze_report(
            client=client,
            report_path=args.report,
            verbose=args.verbose,
        )
        diagnosis = await diagnose(
            client=client,
            analysis=analysis,
            verbose=args.verbose,
        )
        return analysis, diagnosis

    analysis, diagnosis = asyncio.run(run())

    # Output
    output = json.dumps({
        "analysis": json.loads(analysis.model_dump_json()),
        "diagnosis": json.loads(diagnosis.model_dump_json()),
    }, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding='utf-8')
        print(f"Diagnosis saved to: {args.output}")
    else:
        print(output)

    # Print summary
    print(f"\n{'=' * 50}")
    print(f"Root causes: {len(diagnosis.root_causes)}")
    for rc in diagnosis.root_causes:
        print(f"  - {rc.description}")
        print(f"    Mechanism: {rc.mechanism}")
    print(f"\nProposed changes: {len(diagnosis.proposed_changes)}")
    for change in diagnosis.proposed_changes:
        print(f"  - [{change.change_type.value}] {change.target} "
              f"(P{change.priority}, {change.risk_level})")
        print(f"    {change.description}")
    print(f"\nEstimated impact: {diagnosis.estimated_impact}")


def cmd_evolve(args):
    """Full evolution loop: Stage 1 + 2 + 3."""
    client = get_client()

    async def run():
        return await evolve(
            client=client,
            report_path=args.report,
            max_iterations=args.max_iterations,
            no_verify=args.no_verify,
            verbose=args.verbose,
        )

    result = asyncio.run(run())

    # Output
    fmt = args.format or "json"
    if fmt == "markdown":
        output = _format_markdown(result)
    else:
        output = _format_json(result)

    if args.output:
        Path(args.output).write_text(output, encoding='utf-8')
        print(f"Results saved to: {args.output}")
    else:
        print(output)

    # Print summary
    print(f"\n{'=' * 50}")
    print(f"EVOLUTION RESULT")
    print(f"{'=' * 50}")
    print(f"Verified changes: {len(result.verified_changes)}")
    for vc in result.verified_changes:
        print(f"  - {vc.change.target}: eliminated {', '.join(vc.primary_failures_eliminated)}")
        if vc.saved_scenario_path:
            print(f"    Scenario saved: {vc.saved_scenario_path}")
    print(f"Unverified proposals: {len(result.unverified_proposals)}")
    print(f"Rejected attempts: {len(result.rejected_attempts)}")
    for att in result.rejected_attempts:
        print(f"  - [{att.rejection_type}] {att.change_applied.target} (iter {att.iteration})")

    print(f"\n{result.summary}")

    # Print structural proposals prominently
    _print_structural_proposals(result)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Meta-Agent Evolution System for Paixueji",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s analyze reports/AIF/banana_20260209_102935.md
  %(prog)s diagnose reports/AIF/banana_20260209_102935.md
  %(prog)s evolve reports/AIF/banana_20260209_102935.md
  %(prog)s evolve reports/AIF/banana_20260209_102935.md --max-iterations 5
  %(prog)s evolve reports/AIF/banana_20260209_102935.md --no-verify
  %(prog)s evolve reports/AIF/banana_20260209_102935.md -f markdown -o results.md
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- analyze ---
    analyze_parser = subparsers.add_parser(
        "analyze", help="Stage 1: Analyze a critic report"
    )
    analyze_parser.add_argument("report", help="Path to the .md report file")
    analyze_parser.add_argument("-o", "--output", help="Output file path")
    analyze_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    analyze_parser.set_defaults(func=cmd_analyze)

    # --- diagnose ---
    diagnose_parser = subparsers.add_parser(
        "diagnose", help="Stage 1+2: Analyze and diagnose"
    )
    diagnose_parser.add_argument("report", help="Path to the .md report file")
    diagnose_parser.add_argument("-o", "--output", help="Output file path")
    diagnose_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    diagnose_parser.set_defaults(func=cmd_diagnose)

    # --- evolve ---
    evolve_parser = subparsers.add_parser(
        "evolve", help="Full evolution loop (Stage 1+2+3)"
    )
    evolve_parser.add_argument("report", help="Path to the .md report file")
    evolve_parser.add_argument(
        "--max-iterations", type=int, default=3,
        help="Max verification attempts per change (default: 3)",
    )
    evolve_parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip Stage 3 (output Stage 1+2 results only)",
    )
    evolve_parser.add_argument("-o", "--output", help="Output file path")
    evolve_parser.add_argument(
        "-f", "--format", choices=["json", "markdown"],
        default="json", help="Output format (default: json)",
    )
    evolve_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    evolve_parser.set_defaults(func=cmd_evolve)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
