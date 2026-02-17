"""
CLI interface for the Pedagogical Quality Critique System.

Usage:
    python -m tests.quality.cli critique --transcript transcript.json --object banana --concept ripening
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

from google import genai

from .pipeline import PedagogicalCritiquePipeline
from .critique_report import CritiqueReportGenerator


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


def critique_transcript(args):
    """Critique a conversation transcript."""
    transcript_path = Path(args.transcript)
    if not transcript_path.exists():
        print(f"Error: Transcript file not found: {args.transcript}")
        sys.exit(1)

    with open(transcript_path, 'r', encoding='utf-8') as f:
        transcript = json.load(f)

    # If it's a wrapper object (like from scenario generation), extract the transcript
    if isinstance(transcript, dict) and "responses" in transcript:
        # Reconstruct transcript format from responses if needed
        # (This is just a fallback for compatibility)
        print("Warning: Input looks like a response file, attempting to parse...")
        # Implement reconstruction if necessary, but ideally we want a raw transcript
    
    if not isinstance(transcript, list):
        print("Error: Transcript must be a JSON list of {'role': '...', 'content': '...'} objects")
        sys.exit(1)

    print(f"\nCritiquing transcript from: {args.transcript}")
    print(f"Object: {args.object}")
    print(f"Concept: {args.concept}")
    print(f"Age: {args.age}")
    print()

    # Run critique
    client = get_client()
    pipeline = PedagogicalCritiquePipeline(client)

    async def run():
        return await pipeline.critique_transcript(
            transcript=transcript,
            object_name=args.object,
            key_concept=args.concept,
            age=args.age,
            mode=args.mode,
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
        CritiqueReportGenerator.save_report(
            critique,
            args.output,
            args.format
        )
        print(f"\nFull report saved to: {args.output}")
    else:
        print("\nUse --output to save the full report")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Pedagogical Quality Critique System for Paixueji",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Critique command
    critique_parser = subparsers.add_parser("critique", help="Critique a conversation transcript")
    critique_parser.add_argument("-t", "--transcript", required=True, help="Path to JSON transcript file")
    critique_parser.add_argument("-obj", "--object", required=True, help="Object discussed (e.g. banana)")
    critique_parser.add_argument("-c", "--concept", required=True, help="Key concept (e.g. ripening)")
    critique_parser.add_argument("-a", "--age", type=int, default=5, help="Child's age (default: 5)")
    critique_parser.add_argument("-m", "--mode", choices=["chat", "guide"], default="chat", help="Evaluation mode")
    critique_parser.add_argument("-o", "--output", help="Output file path")
    critique_parser.add_argument(
        "-f", "--format",
        choices=["json", "markdown", "html"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    critique_parser.set_defaults(func=critique_transcript)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()