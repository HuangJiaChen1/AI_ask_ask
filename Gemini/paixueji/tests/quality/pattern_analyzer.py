"""
Multi-Turn Pattern Analyzer for Pedagogical Critique.

Analyzes sequences of exchange critiques to detect patterns
that emerge over multiple turns, such as:
- Repeated scaffold failures
- Stuck conversation loops
- Engagement decline
- Lost learning threads
"""

import json
from typing import Any

from google import genai
from google.genai.types import GenerateContentConfig

from .schema import (
    ExchangeCritique,
    FailureType,
    Severity,
    MultiTurnPattern,
    ScenarioSetup,
)


# Multi-turn failure type descriptions for the prompt
MULTI_TURN_FAILURE_DESCRIPTIONS = {
    FailureType.REPEATED_SCAFFOLD_FAILURE: (
        "Model uses the same scaffolding approach 2+ times without adjusting. "
        "Same hints, same question rephrasing, no new teaching strategy."
    ),
    FailureType.STUCK_LOOP: (
        "Conversation circles back to the same point without making progress. "
        "Child and model are going in circles."
    ),
    FailureType.PREMATURE_ADVANCEMENT: (
        "Model moves to a new concept/question when the child is still confused "
        "about the previous one."
    ),
    FailureType.ENGAGEMENT_DECLINE: (
        "Child's responses are getting progressively shorter, less enthusiastic, "
        "or more disengaged over time."
    ),
    FailureType.LOST_THREAD: (
        "The original learning goal has been abandoned. The conversation has "
        "drifted to a different topic without achieving the teaching objective."
    ),
}


class MultiTurnPatternAnalyzer:
    """
    Analyzes sequences of exchange critiques to detect multi-turn patterns.

    Uses an LLM to identify pedagogical patterns that only emerge when
    looking at multiple exchanges together.
    """

    def __init__(
        self,
        client: genai.Client,
        model_name: str = "gemini-2.5-pro",
    ):
        """
        Initialize the pattern analyzer.

        Args:
            client: Google GenAI client
            model_name: Model for pattern analysis
        """
        self.client = client
        self.model_name = model_name

    async def analyze_patterns(
        self,
        exchange_critiques: list[ExchangeCritique],
        setup: ScenarioSetup,
    ) -> tuple[list[MultiTurnPattern], str, str]:
        """
        Analyze a sequence of exchange critiques for multi-turn patterns.

        Args:
            exchange_critiques: Per-turn critiques from the expert critic
            setup: Scenario setup (object, concept, age)

        Returns:
            Tuple of:
            - List of detected MultiTurnPattern objects
            - Overall trajectory description (improving/declining/stable)
            - Learning progress summary
        """
        if len(exchange_critiques) < 2:
            return [], "insufficient_data", "Not enough turns to analyze patterns"

        prompt = self._build_analysis_prompt(exchange_critiques, setup)

        config = GenerateContentConfig(
            temperature=0.3,  # More deterministic for analysis
            response_mime_type="application/json",
        )

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        # Parse the response
        if response.candidates and response.candidates[0].content.parts:
            result_text = response.candidates[0].content.parts[0].text
            return self._parse_analysis_result(result_text)

        return [], "unknown", "Analysis failed"

    def _build_analysis_prompt(
        self,
        exchange_critiques: list[ExchangeCritique],
        setup: ScenarioSetup,
    ) -> str:
        """Build the prompt for multi-turn pattern analysis."""
        # Format the exchanges for the prompt
        exchanges_text = ""
        for ec in exchange_critiques:
            failures_str = ", ".join([f.type.value for f in ec.failures]) if ec.failures else "none"
            exchanges_text += f"""
Turn {ec.turn_number}:
  Model asked: "{ec.model_question[:100]}..."
  Child said: "{ec.child_response[:100]}..."
  Model responded: "{ec.model_actual[:100]}..."
  Effectiveness: {ec.effectiveness_score}/10
  Failures: {failures_str}
"""

        # Build pattern descriptions
        pattern_descriptions = "\n".join([
            f"- {ptype.value}: {desc}"
            for ptype, desc in MULTI_TURN_FAILURE_DESCRIPTIONS.items()
        ])

        prompt = f"""You are an expert in children's education analyzing a multi-turn conversation for patterns.

CONTEXT:
- Topic: {setup.object_name}
- Key concept: {setup.key_concept}
- Child age: {setup.age}

CONVERSATION EXCHANGES:
{exchanges_text}

MULTI-TURN PATTERNS TO DETECT:
{pattern_descriptions}

ANALYSIS TASK:
Look at the SEQUENCE of exchanges and identify any multi-turn patterns.
These are problems that only become visible when looking at multiple turns together.

Respond with JSON in this exact format:
{{
    "patterns": [
        {{
            "pattern_type": "PATTERN_NAME (one of the multi-turn failure types)",
            "severity": "CRITICAL or MAJOR or MINOR",
            "turns_affected": [1, 2, 3],
            "description": "What specifically is happening",
            "evidence": "Specific quotes or observations from the turns"
        }}
    ],
    "trajectory": "improving OR declining OR stable OR mixed",
    "learning_progress": "Brief summary of what learning occurred (or didn't)"
}}

IMPORTANT:
- Only report patterns you're confident about
- Include specific turn numbers and evidence
- An empty patterns list is fine if no multi-turn issues exist
- Focus on the SEQUENCE, not individual turn problems (those are already captured)

Return ONLY valid JSON, no additional text:"""

        return prompt

    def _parse_analysis_result(
        self,
        result_text: str,
    ) -> tuple[list[MultiTurnPattern], str, str]:
        """Parse the JSON analysis result into structured objects."""
        try:
            # Clean up the response (remove markdown code blocks if present)
            cleaned = result_text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])  # Remove first and last lines

            result = json.loads(cleaned)

            patterns = []
            for p in result.get("patterns", []):
                try:
                    pattern = MultiTurnPattern(
                        pattern_type=FailureType(p["pattern_type"]),
                        severity=Severity(p["severity"]),
                        turns_affected=p["turns_affected"],
                        description=p["description"],
                        evidence=p["evidence"],
                    )
                    patterns.append(pattern)
                except (KeyError, ValueError) as e:
                    # Skip malformed patterns
                    print(f"Warning: Skipping malformed pattern: {e}")
                    continue

            trajectory = result.get("trajectory", "unknown")
            learning_progress = result.get("learning_progress", "Unable to assess")

            return patterns, trajectory, learning_progress

        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse pattern analysis JSON: {e}")
            return [], "unknown", "Analysis parsing failed"


class SimulationCritiqueSummary:
    """
    Summarizes a full simulation critique including multi-turn patterns.

    Combines per-turn critiques with pattern analysis for a complete picture.
    """

    def __init__(
        self,
        exchange_critiques: list[ExchangeCritique],
        patterns: list[MultiTurnPattern],
        trajectory: str,
        learning_progress: str,
    ):
        self.exchange_critiques = exchange_critiques
        self.patterns = patterns
        self.trajectory = trajectory
        self.learning_progress = learning_progress

    @property
    def has_multi_turn_failures(self) -> bool:
        """Check if any multi-turn patterns were detected."""
        return len(self.patterns) > 0

    @property
    def critical_patterns(self) -> list[MultiTurnPattern]:
        """Get patterns with CRITICAL severity."""
        return [p for p in self.patterns if p.severity == Severity.CRITICAL]

    @property
    def average_effectiveness(self) -> float:
        """Calculate average effectiveness across all turns."""
        if not self.exchange_critiques:
            return 0.0
        scores = [ec.effectiveness_score for ec in self.exchange_critiques]
        return sum(scores) / len(scores)

    def to_markdown_summary(self) -> str:
        """Generate a markdown summary of the simulation critique."""
        lines = [
            "## Multi-Turn Analysis Summary",
            "",
            f"**Trajectory:** {self.trajectory}",
            f"**Average Effectiveness:** {self.average_effectiveness:.1f}/10",
            f"**Learning Progress:** {self.learning_progress}",
            "",
        ]

        if self.patterns:
            lines.append("### Multi-Turn Patterns Detected")
            lines.append("")
            for p in self.patterns:
                lines.append(f"#### {p.pattern_type.value} ({p.severity.value})")
                lines.append(f"Turns affected: {p.turns_affected}")
                lines.append(f"{p.description}")
                lines.append(f"> {p.evidence}")
                lines.append("")
        else:
            lines.append("### No Multi-Turn Patterns Detected")
            lines.append("The conversation maintained good pedagogical flow across turns.")
            lines.append("")

        return "\n".join(lines)
