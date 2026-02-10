"""
CLI interface for the Pedagogical Quality Critique System.

Usage:
    python -m tests.quality.cli critique --scenario SCAFFOLD-WHY-001
    python -m tests.quality.cli critique-all --output report.html
    python -m tests.quality.cli list-scenarios
    python -m tests.quality.cli generate-responses --scenario SCAFFOLD-WHY-001 --output responses/
    python -m tests.quality.cli run-and-critique --scenario SCAFFOLD-WHY-001 --output report.md
    python -m meta_agent evolve <report> --max-iterations 5
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

from google import genai

from .pipeline import PedagogicalCritiquePipeline, ScenarioLoader, run_critique_pipeline
from .critique_report import CritiqueReportGenerator
from .schema import Scenario
from .scenario_runner import ScenarioRunner, run_scenario_to_json


def get_client() -> genai.Client:
    """Create a GenAI client using Vertex AI with config from config.json."""
    # Load config from the project root
    config_path = Path(__file__).parent.parent.parent / "config.json"
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


def get_scenarios_dir() -> Path:
    """Get the scenarios directory path."""
    return Path(__file__).parent / "scenarios"


def list_scenarios(args):
    """List all available scenarios."""
    loader = ScenarioLoader(get_scenarios_dir())
    scenarios = loader.load_all()

    if not scenarios:
        print("No scenarios found in:", get_scenarios_dir())
        return

    print(f"\nFound {len(scenarios)} scenario(s):\n")
    print("-" * 60)

    for scenario in scenarios:
        print(f"ID: {scenario.id}")
        print(f"Name: {scenario.name}")
        print(f"Description: {scenario.description}")
        print(f"Object: {scenario.setup.object_name}")
        print(f"Concept: {scenario.setup.key_concept}")
        print("-" * 60)


def critique_scenario(args):
    """Critique a specific scenario."""
    loader = ScenarioLoader(get_scenarios_dir())

    try:
        scenario = loader.load_scenario(args.scenario)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"\nCritiquing scenario: {scenario.name}")
    print(f"Description: {scenario.description}")
    print()

    # Get model responses interactively or from file
    if args.responses:
        with open(args.responses, 'r', encoding='utf-8') as f:
            import json
            model_responses = json.load(f)
    else:
        print("Enter model responses (one per line, empty line to finish):")
        model_responses = []
        while True:
            response = input("> ").strip()
            if not response:
                break
            model_responses.append(response)

    if not model_responses:
        print("Error: No model responses provided")
        sys.exit(1)

    # Run critique
    client = get_client()

    async def run():
        return await run_critique_pipeline(
            client=client,
            scenario=scenario,
            model_responses=model_responses,
            output_path=args.output,
            output_format=args.format,
        )

    critique = asyncio.run(run())

    # Print summary
    print("\n" + "=" * 60)
    print("CRITIQUE SUMMARY")
    print("=" * 60)
    print(f"Overall Effectiveness: {critique.overall_effectiveness:.1f}/100")
    print(f"Exchanges Analyzed: {critique.total_exchanges}")
    print(f"Exchanges with Failures: {critique.failed_exchanges}")

    if critique.critical_failures:
        print("\nCritical Failures:")
        for failure in critique.critical_failures:
            print(f"  ❌ {failure}")

    if critique.improvement_priorities:
        print("\nImprovement Priorities:")
        for i, priority in enumerate(critique.improvement_priorities[:3], 1):
            print(f"  {i}. {priority}")

    if args.output:
        print(f"\nFull report saved to: {args.output}")
    else:
        print("\nUse --output to save the full report")


def critique_all(args):
    """Critique all scenarios and generate a combined report."""
    loader = ScenarioLoader(get_scenarios_dir())
    scenarios = loader.load_all()

    if not scenarios:
        print("No scenarios found")
        sys.exit(1)

    print(f"\nFound {len(scenarios)} scenario(s)")

    # For automated testing, we'd need pre-recorded responses
    # For now, just show what would be critiqued
    print("\nTo critique all scenarios, you need pre-recorded model responses.")
    print("Use --responses-dir to provide a directory with response files.")
    print("Each file should be named {scenario_id}.json containing a list of responses.")

    if args.responses_dir:
        responses_dir = Path(args.responses_dir)
        client = get_client()
        pipeline = PedagogicalCritiquePipeline(client)

        all_critiques = []

        for scenario in scenarios:
            response_file = responses_dir / f"{scenario.id}.json"
            if not response_file.exists():
                print(f"Skipping {scenario.id}: no response file found")
                continue

            with open(response_file, 'r', encoding='utf-8') as f:
                import json
                model_responses = json.load(f)

            print(f"Critiquing: {scenario.id}...")

            async def run():
                return await pipeline.critique_scenario(scenario, model_responses)

            critique = asyncio.run(run())
            all_critiques.append(critique)

        # Generate combined report
        if all_critiques and args.output:
            combined_md = ["# Combined Critique Report\n"]
            for critique in all_critiques:
                combined_md.append(CritiqueReportGenerator.to_markdown(critique))
                combined_md.append("\n---\n")

            output_path = Path(args.output)
            output_path.write_text("\n".join(combined_md), encoding='utf-8')
            print(f"\nCombined report saved to: {output_path}")


def generate_responses(args):
    """Generate responses by running scenarios through the real Paixueji system."""
    loader = ScenarioLoader(get_scenarios_dir())
    client = get_client()

    # Determine which scenarios to run
    if args.scenario:
        try:
            scenarios = [loader.load_scenario(args.scenario)]
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        scenarios = loader.load_all()

    if not scenarios:
        print("No scenarios found")
        sys.exit(1)

    print(f"\nGenerating responses for {len(scenarios)} scenario(s)...")
    print("-" * 60)

    # Create output directory
    output_dir = Path(args.output) if args.output else Path("responses")
    output_dir.mkdir(parents=True, exist_ok=True)

    runner = ScenarioRunner(client)

    for scenario in scenarios:
        print(f"\nRunning: {scenario.id}")
        print(f"  Object: {scenario.setup.object_name}")
        print(f"  Age: {scenario.setup.age}")

        async def run():
            return await runner.run_scenario(scenario)

        try:
            responses = asyncio.run(run())
        except Exception as e:
            print(f"  Error: {e}")
            continue

        # Save responses
        output_file = output_dir / f"{scenario.id}.json"
        result = {
            "scenario_id": scenario.id,
            "scenario_name": scenario.name,
            "object_name": scenario.setup.object_name,
            "age": scenario.setup.age,
            "responses": responses,
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"  Captured {len(responses)} response(s)")
        print(f"  Saved to: {output_file}")

        # Show preview of responses
        for i, resp in enumerate(responses[:2], 1):  # Show first 2
            preview = resp[:100] + "..." if len(resp) > 100 else resp
            print(f"  Response {i}: {preview}")

    print("\n" + "-" * 60)
    print(f"Done! Responses saved to: {output_dir}/")


def run_and_critique(args):
    """Run scenario through real system, then critique the responses."""
    loader = ScenarioLoader(get_scenarios_dir())
    client = get_client()

    # Load scenario
    if args.scenario:
        try:
            scenario = loader.load_scenario(args.scenario)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        print("Error: --scenario is required")
        sys.exit(1)

    print(f"\nRunning and critiquing: {scenario.name}")
    print(f"Description: {scenario.description}")
    print("-" * 60)

    # Step 1: Generate responses
    print("\nStep 1: Running scenario through Paixueji...")
    runner = ScenarioRunner(client)

    async def run_scenario():
        return await runner.run_scenario(scenario)

    try:
        responses = asyncio.run(run_scenario())
    except Exception as e:
        print(f"Error running scenario: {e}")
        sys.exit(1)

    print(f"  Captured {len(responses)} response(s)")
    for i, resp in enumerate(responses, 1):
        preview = resp[:80] + "..." if len(resp) > 80 else resp
        print(f"  [{i}] {preview}")

    # Step 2: Critique responses
    print("\nStep 2: Running pedagogical critique...")
    pipeline = PedagogicalCritiquePipeline(client)

    async def run_critique():
        return await pipeline.critique_scenario(scenario, responses)

    critique = asyncio.run(run_critique())

    # Print summary
    print("\n" + "=" * 60)
    print("CRITIQUE SUMMARY")
    print("=" * 60)
    print(f"Overall Effectiveness: {critique.overall_effectiveness:.1f}/100")
    print(f"Exchanges Analyzed: {critique.total_exchanges}")
    print(f"Exchanges with Failures: {critique.failed_exchanges}")

    if critique.failure_breakdown:
        print("\nFailure Breakdown:")
        for failure_type, count in critique.failure_breakdown.items():
            print(f"  {failure_type}: {count}")

    if critique.critical_failures:
        print("\nCritical Failures:")
        for failure in critique.critical_failures:
            print(f"  - {failure}")

    if critique.improvement_priorities:
        print("\nImprovement Priorities:")
        for i, priority in enumerate(critique.improvement_priorities[:3], 1):
            print(f"  {i}. {priority}")

    # Save report if output specified
    if args.output:
        output_path = Path(args.output)
        CritiqueReportGenerator.save_report(
            critique,
            output_path,
            args.format or "markdown"
        )
        print(f"\nFull report saved to: {output_path}")

    # Also save the responses for reference
    if args.save_responses:
        responses_path = Path(args.save_responses)
        responses_path.parent.mkdir(parents=True, exist_ok=True)
        with open(responses_path, 'w', encoding='utf-8') as f:
            json.dump({
                "scenario_id": scenario.id,
                "responses": responses,
            }, f, ensure_ascii=False, indent=2)
        print(f"Responses saved to: {responses_path}")


def demo(args):
    """Run a demo critique with a built-in example."""
    print("\n" + "=" * 60)
    print("PEDAGOGICAL CRITIQUE DEMO")
    print("=" * 60)

    # Create a demo scenario
    from .schema import ScenarioSetup, ScenarioEvaluation, ScenarioExchange

    demo_scenario = Scenario(
        id="DEMO-001",
        name="Demo: Scaffolding a 'I don't know' response",
        description="Tests whether the model scaffolds effectively when child says 'I don't know'",
        setup=ScenarioSetup(
            object_name="banana",
            key_concept="color change / ripening",
            age=5,
            guide_phase="active",
        ),
        conversation=[
            ScenarioExchange(
                role="model",
                content="Why do you think the banana peel changes color as it gets older?",
            ),
            ScenarioExchange(
                role="child",
                content="I don't know",
            ),
        ],
        evaluation=ScenarioEvaluation(
            must_do=[
                "Provide a hint about the mechanism (air, oxidation, ripening)",
                "Add NEW information not in the original question",
                "Keep focus on WHY, not just WHAT",
            ],
            must_not_do=[
                "Rephrase as WHAT/HOW question without adding info",
                "Ask child to re-observe the same phenomenon",
                "Change topic or abandon explanation",
            ],
        ),
    )

    # Example of a BAD response (the one from our problem statement)
    bad_response = "Does the peel stay bright yellow, or does it start to get some brown spots?"

    # Example of a GOOD response
    good_response = "That's okay! Here's a clue - when the banana sits out, the AIR touches it and makes it change. Just like when an apple slice turns brown! What do you think the air does to the banana?"

    print("\nScenario:")
    print(f"  Object: {demo_scenario.setup.object_name}")
    print(f"  Concept: {demo_scenario.setup.key_concept}")
    print(f"  Age: {demo_scenario.setup.age}")

    print("\nConversation:")
    print(f"  Model asked: \"{demo_scenario.conversation[0].content}\"")
    print(f"  Child said: \"{demo_scenario.conversation[1].content}\"")

    print("\n" + "-" * 60)
    print("Testing with a BAD response:")
    print(f"  \"{bad_response}\"")
    print("-" * 60)

    client = get_client()

    async def run_demo():
        return await run_critique_pipeline(
            client=client,
            scenario=demo_scenario,
            model_responses=[bad_response],
        )

    print("\nRunning critique...")
    critique = asyncio.run(run_demo())

    # Print results
    print("\n" + "=" * 60)
    print("CRITIQUE RESULTS")
    print("=" * 60)

    if critique.exchange_critiques:
        ec = critique.exchange_critiques[0]
        print(f"\nEffectiveness Score: {ec.effectiveness_score}/10")
        print(f"Advances Learning: {'Yes' if ec.advances_learning else 'No'}")
        print(f"Addresses Knowledge Gap: {'Yes' if ec.addresses_knowledge_gap else 'No'}")

        if ec.failures:
            print("\nFailures Detected:")
            for f in ec.failures:
                print(f"  - [{f.severity.value}] {f.type.value}")
                print(f"    {f.description}")

        if ec.expected_vs_actual:
            print("\nExpected vs Actual:")
            print(f"  Expected: {ec.expected_vs_actual.i_expected}")
            print(f"  Got: {ec.expected_vs_actual.but_got}")
            print(f"  Problem: {ec.expected_vs_actual.this_is_problematic_because}")

        if ec.ideal_response:
            print(f"\nIdeal Response:")
            print(f"  \"{ec.ideal_response}\"")

        if ec.picky_observations:
            print("\nPicky Observations:")
            for obs in ec.picky_observations:
                print(f"  - {obs}")

    print("\n" + "=" * 60)
    print("For comparison, a GOOD response would be:")
    print(f"  \"{good_response}\"")
    print("=" * 60)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Pedagogical Quality Critique System for Paixueji",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s demo                                    Run a demo critique
  %(prog)s list                                    List available scenarios
  %(prog)s critique -s SCAFFOLD-WHY-001            Critique a specific scenario
  %(prog)s critique-all -o report.html             Critique all scenarios
  %(prog)s generate-responses -o responses/        Generate responses for all scenarios
  %(prog)s generate-responses -s SCAFFOLD-WHY-001  Generate responses for one scenario
  %(prog)s run-and-critique -s SCAFFOLD-WHY-001    Run scenario then critique
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Demo command
    demo_parser = subparsers.add_parser("demo", help="Run a demo critique")
    demo_parser.set_defaults(func=demo)

    # List command
    list_parser = subparsers.add_parser("list", help="List available scenarios")
    list_parser.set_defaults(func=list_scenarios)

    # Critique command
    critique_parser = subparsers.add_parser("critique", help="Critique a specific scenario")
    critique_parser.add_argument("-s", "--scenario", required=True, help="Scenario ID")
    critique_parser.add_argument("-r", "--responses", help="JSON file with model responses")
    critique_parser.add_argument("-o", "--output", help="Output file path")
    critique_parser.add_argument(
        "-f", "--format",
        choices=["json", "markdown", "html"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    critique_parser.set_defaults(func=critique_scenario)

    # Critique-all command
    critique_all_parser = subparsers.add_parser("critique-all", help="Critique all scenarios")
    critique_all_parser.add_argument("-d", "--responses-dir", help="Directory with response files")
    critique_all_parser.add_argument("-o", "--output", help="Output file path")
    critique_all_parser.set_defaults(func=critique_all)

    # Generate-responses command (NEW)
    gen_parser = subparsers.add_parser(
        "generate-responses",
        help="Run scenarios through Paixueji and capture responses"
    )
    gen_parser.add_argument(
        "-s", "--scenario",
        help="Specific scenario ID (omit to run all scenarios)"
    )
    gen_parser.add_argument(
        "-o", "--output",
        default="responses",
        help="Output directory for response JSON files (default: responses/)"
    )
    gen_parser.set_defaults(func=generate_responses)

    # Run-and-critique command (NEW)
    rac_parser = subparsers.add_parser(
        "run-and-critique",
        help="Run scenario through Paixueji, then critique the responses"
    )
    rac_parser.add_argument(
        "-s", "--scenario",
        required=True,
        help="Scenario ID to run and critique"
    )
    rac_parser.add_argument(
        "-o", "--output",
        help="Output file path for critique report"
    )
    rac_parser.add_argument(
        "-f", "--format",
        choices=["json", "markdown", "html"],
        default="markdown",
        help="Report format (default: markdown)"
    )
    rac_parser.add_argument(
        "--save-responses",
        help="Optional path to save the captured responses JSON"
    )
    rac_parser.set_defaults(func=run_and_critique)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
