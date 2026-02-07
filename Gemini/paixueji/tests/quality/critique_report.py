"""
Critique Report Generator.

Generates detailed, actionable reports from pedagogical critiques
in various formats: JSON, Markdown, and HTML.
"""

import json
from datetime import datetime
from pathlib import Path

from .schema import (
    ConversationCritique,
    ExchangeCritique,
    Severity,
)


class CritiqueReportGenerator:
    """Generates formatted reports from critique results."""

    @staticmethod
    def to_json(critique: ConversationCritique) -> str:
        """Export critique as JSON."""
        return critique.model_dump_json(indent=2)

    @staticmethod
    def to_markdown(critique: ConversationCritique) -> str:
        """Generate a detailed Markdown report."""
        lines = []

        # Header
        lines.append(f"# Pedagogical Critique Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # Scenario info
        lines.append(f"## Scenario: {critique.scenario_name}")
        lines.append(f"**ID:** `{critique.scenario_id}`")
        lines.append("")

        # Overall metrics
        effectiveness_emoji = "✅" if critique.overall_effectiveness >= 70 else "⚠️" if critique.overall_effectiveness >= 40 else "❌"
        lines.append(f"### Overall Effectiveness: {effectiveness_emoji} {critique.overall_effectiveness:.1f}/100")
        lines.append("")
        lines.append(f"- **Total Exchanges Analyzed:** {critique.total_exchanges}")
        lines.append(f"- **Exchanges with Failures:** {critique.failed_exchanges}")
        lines.append("")

        # Failure breakdown
        if critique.failure_breakdown:
            lines.append("### Failure Breakdown")
            lines.append("")
            lines.append("| Failure Type | Count |")
            lines.append("|-------------|-------|")
            for failure_type, count in sorted(critique.failure_breakdown.items(), key=lambda x: -x[1]):
                lines.append(f"| {failure_type} | {count} |")
            lines.append("")

        # Critical failures summary
        if critique.critical_failures:
            lines.append("### ⚠️ Critical Failures")
            lines.append("")
            for failure in critique.critical_failures:
                lines.append(f"- {failure}")
            lines.append("")

        # Improvement priorities
        if critique.improvement_priorities:
            lines.append("### 📋 Improvement Priorities")
            lines.append("")
            for i, priority in enumerate(critique.improvement_priorities, 1):
                lines.append(f"{i}. {priority}")
            lines.append("")

        # Detailed exchange critiques
        lines.append("---")
        lines.append("")
        lines.append("## Detailed Exchange Analysis")
        lines.append("")

        for exchange in critique.exchange_critiques:
            lines.extend(CritiqueReportGenerator._format_exchange_markdown(exchange))
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_exchange_markdown(exchange: ExchangeCritique) -> list[str]:
        """Format a single exchange critique as Markdown."""
        lines = []

        # Determine severity color
        has_critical = any(f.severity == Severity.CRITICAL for f in exchange.failures)
        has_major = any(f.severity == Severity.MAJOR for f in exchange.failures)

        if has_critical:
            severity_marker = "🔴 CRITICAL"
        elif has_major:
            severity_marker = "🟠 MAJOR"
        elif exchange.failures:
            severity_marker = "🟡 MINOR"
        else:
            severity_marker = "🟢 OK"

        lines.append(f"### Exchange {exchange.turn_number} - {severity_marker}")
        lines.append("")

        # The exchange
        lines.append(f"**Model asked:** \"{exchange.model_question}\"")
        lines.append("")
        lines.append(f"**Child said:** \"{exchange.child_response}\"")
        lines.append("")
        lines.append(f"**Model responded:** \"{exchange.model_actual}\"")
        lines.append("")

        # Score
        score_bar = "█" * exchange.effectiveness_score + "░" * (10 - exchange.effectiveness_score)
        lines.append(f"**Effectiveness:** [{score_bar}] {exchange.effectiveness_score}/10")
        lines.append(f"- Advances Learning: {'✅' if exchange.advances_learning else '❌'}")
        lines.append(f"- Addresses Knowledge Gap: {'✅' if exchange.addresses_knowledge_gap else '❌'}")
        lines.append("")

        # Pedagogical context
        lines.append("#### Pedagogical Context")
        lines.append(f"- **Question Type:** {exchange.context.question_type.value}")
        lines.append(f"- **Intent:** {exchange.context.question_intent}")
        lines.append(f"- **Target Knowledge:** {exchange.context.target_knowledge}")
        lines.append(f"- **Child Response Type:** {exchange.context.child_response_type.value}")
        lines.append(f"- **Knowledge Gap:** {exchange.context.knowledge_gap}")
        lines.append("")

        # Expected vs Actual
        if exchange.expected_vs_actual:
            lines.append("#### Expected vs Actual")
            lines.append(f"> **I expected:** {exchange.expected_vs_actual.i_expected}")
            lines.append(">")
            lines.append(f"> **But got:** {exchange.expected_vs_actual.but_got}")
            lines.append(">")
            lines.append(f"> **This is problematic because:** {exchange.expected_vs_actual.this_is_problematic_because}")
            lines.append("")

        # Failures
        if exchange.failures:
            lines.append("#### Failures")
            lines.append("")
            for i, failure in enumerate(exchange.failures, 1):
                severity_icon = {"CRITICAL": "🔴", "MAJOR": "🟠", "MINOR": "🟡"}[failure.severity.value]
                lines.append(f"{i}. **{failure.type.value}** {severity_icon} ({failure.severity.value})")
                lines.append(f"   - {failure.description}")
                lines.append(f"   - Evidence: \"{failure.evidence}\"")
            lines.append("")

        # Ideal response
        if exchange.ideal_response:
            lines.append("#### Ideal Response")
            lines.append(f"> {exchange.ideal_response}")
            lines.append("")

        # Picky observations
        if exchange.picky_observations:
            lines.append("#### Picky Observations")
            for obs in exchange.picky_observations:
                lines.append(f"- {obs}")
            lines.append("")

        # Improvement suggestions
        if exchange.improvements:
            lines.append("#### Improvement Suggestions")
            for suggestion in exchange.improvements:
                lines.append(f"- {suggestion}")
            lines.append("")

        lines.append("---")

        return lines

    @staticmethod
    def to_html(critique: ConversationCritique) -> str:
        """Generate an HTML report with styling."""
        # Convert Markdown to basic HTML
        md = CritiqueReportGenerator.to_markdown(critique)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pedagogical Critique Report - {critique.scenario_name}</title>
    <style>
        :root {{
            --bg-primary: #1a1a2e;
            --bg-secondary: #16213e;
            --text-primary: #eee;
            --text-secondary: #aaa;
            --accent: #e94560;
            --success: #4ade80;
            --warning: #fbbf24;
            --error: #ef4444;
            --info: #60a5fa;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem;
            max-width: 900px;
            margin: 0 auto;
        }}

        h1 {{
            color: var(--accent);
            border-bottom: 2px solid var(--accent);
            padding-bottom: 0.5rem;
        }}

        h2 {{
            color: var(--info);
            margin-top: 2rem;
        }}

        h3 {{
            color: var(--text-primary);
            background: var(--bg-secondary);
            padding: 0.5rem 1rem;
            border-radius: 4px;
        }}

        h4 {{
            color: var(--text-secondary);
            margin-top: 1rem;
        }}

        blockquote {{
            background: var(--bg-secondary);
            border-left: 4px solid var(--accent);
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 0 4px 4px 0;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }}

        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--bg-secondary);
        }}

        th {{
            background: var(--bg-secondary);
            color: var(--accent);
        }}

        code {{
            background: var(--bg-secondary);
            padding: 0.2rem 0.4rem;
            border-radius: 3px;
            font-family: 'Monaco', 'Menlo', monospace;
        }}

        hr {{
            border: none;
            border-top: 1px solid var(--bg-secondary);
            margin: 2rem 0;
        }}

        ul, ol {{
            padding-left: 1.5rem;
        }}

        li {{
            margin: 0.5rem 0;
        }}

        .effectiveness-bar {{
            font-family: monospace;
            letter-spacing: 2px;
        }}

        .critical {{ color: var(--error); }}
        .major {{ color: var(--warning); }}
        .minor {{ color: #a78bfa; }}
        .ok {{ color: var(--success); }}
    </style>
</head>
<body>
    <article id="content">
        {CritiqueReportGenerator._md_to_html(md)}
    </article>
</body>
</html>"""

        return html_content

    @staticmethod
    def _md_to_html(md: str) -> str:
        """Simple Markdown to HTML conversion."""
        import re

        html = md

        # Headers
        html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

        # Bold
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

        # Inline code
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)

        # Blockquotes (multi-line)
        lines = html.split('\n')
        in_blockquote = False
        new_lines = []
        for line in lines:
            if line.startswith('>'):
                if not in_blockquote:
                    new_lines.append('<blockquote>')
                    in_blockquote = True
                new_lines.append(line[1:].strip())
            else:
                if in_blockquote:
                    new_lines.append('</blockquote>')
                    in_blockquote = False
                new_lines.append(line)
        if in_blockquote:
            new_lines.append('</blockquote>')
        html = '\n'.join(new_lines)

        # Tables
        html = re.sub(r'\|[-|]+\|', '', html)  # Remove separator rows
        html = re.sub(r'^\|(.+)\|$', lambda m: '<tr>' + ''.join(f'<td>{c.strip()}</td>' for c in m.group(1).split('|')) + '</tr>', html, flags=re.MULTILINE)

        # Lists
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        html = re.sub(r'^(\d+)\. (.+)$', r'<li>\2</li>', html, flags=re.MULTILINE)

        # Horizontal rules
        html = re.sub(r'^---$', '<hr>', html, flags=re.MULTILINE)

        # Paragraphs (simple)
        html = re.sub(r'\n\n+', '\n<br><br>\n', html)

        return html

    @staticmethod
    def save_report(
        critique: ConversationCritique,
        output_path: str | Path,
        format: str = "markdown",
    ) -> Path:
        """
        Save a critique report to a file.

        Args:
            critique: The critique to save
            output_path: Where to save (without extension)
            format: "json", "markdown", or "html"

        Returns:
            Path to the saved file
        """
        output_path = Path(output_path)

        if format == "json":
            content = CritiqueReportGenerator.to_json(critique)
            output_path = output_path.with_suffix(".json")
        elif format == "html":
            content = CritiqueReportGenerator.to_html(critique)
            output_path = output_path.with_suffix(".html")
        else:  # markdown
            content = CritiqueReportGenerator.to_markdown(critique)
            output_path = output_path.with_suffix(".md")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

        return output_path


def compile_conversation_critique(
    scenario_id: str,
    scenario_name: str,
    exchange_critiques: list[ExchangeCritique],
) -> ConversationCritique:
    """
    Compile individual exchange critiques into a full conversation critique.

    Args:
        scenario_id: Scenario identifier
        scenario_name: Human-readable name
        exchange_critiques: List of individual exchange critiques

    Returns:
        ConversationCritique with aggregated metrics
    """
    if not exchange_critiques:
        return ConversationCritique(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            overall_effectiveness=0,
            total_exchanges=0,
            failed_exchanges=0,
            failure_breakdown={},
            exchange_critiques=[],
            critical_failures=[],
            improvement_priorities=[],
        )

    # Calculate metrics
    total_score = sum(e.effectiveness_score for e in exchange_critiques)
    overall_effectiveness = (total_score / len(exchange_critiques)) * 10  # Scale to 100

    failed_exchanges = sum(1 for e in exchange_critiques if e.failures)

    # Failure breakdown
    failure_breakdown: dict[str, int] = {}
    for exchange in exchange_critiques:
        for failure in exchange.failures:
            key = failure.type.value
            failure_breakdown[key] = failure_breakdown.get(key, 0) + 1

    # Critical failures (from CRITICAL severity)
    critical_failures = []
    for exchange in exchange_critiques:
        for failure in exchange.failures:
            if failure.severity == Severity.CRITICAL:
                critical_failures.append(
                    f"Exchange {exchange.turn_number}: {failure.description}"
                )

    # Improvement priorities (from most common failure types)
    improvement_priorities = []
    seen_types = set()
    for exchange in exchange_critiques:
        for improvement in exchange.improvements:
            if improvement not in seen_types:
                improvement_priorities.append(improvement)
                seen_types.add(improvement)
            if len(improvement_priorities) >= 5:
                break
        if len(improvement_priorities) >= 5:
            break

    return ConversationCritique(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        overall_effectiveness=overall_effectiveness,
        total_exchanges=len(exchange_critiques),
        failed_exchanges=failed_exchanges,
        failure_breakdown=failure_breakdown,
        exchange_critiques=exchange_critiques,
        critical_failures=critical_failures,
        improvement_priorities=improvement_priorities,
    )
