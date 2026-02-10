"""
Report Parser for AIF and HF critic reports.

Parses markdown-formatted critique reports into structured ParsedReport objects.
Auto-detects report type (AIF vs HF) by header patterns.
"""

import re
from pathlib import Path

from .schema import ParsedReport, ParsedExchange


def parse_report(report_path: str | Path) -> ParsedReport:
    """
    Parse a critic report file into a structured ParsedReport.

    Auto-detects AIF vs HF format.

    Args:
        report_path: Path to the .md report file

    Returns:
        ParsedReport with all extracted data
    """
    report_path = Path(report_path)
    text = report_path.read_text(encoding="utf-8")

    if _is_aif_report(text):
        return _parse_aif_report(text)
    elif _is_hf_report(text):
        return _parse_hf_report(text)
    else:
        raise ValueError(
            f"Cannot detect report type for {report_path.name}. "
            "Expected AIF (contains '## Detailed Exchange Analysis') "
            "or HF (contains '#### Human Critique')."
        )


def _is_aif_report(text: str) -> bool:
    return "## Detailed Exchange Analysis" in text and "### Overall Effectiveness" in text


def _is_hf_report(text: str) -> bool:
    return "#### Human Critique" in text


# ============================================================================
# AIF Report Parser
# ============================================================================

def _parse_aif_report(text: str) -> ParsedReport:
    """Parse an AIF (AI Feedback) critique report."""
    report = ParsedReport(source="AIF")

    # Header
    _parse_aif_header(text, report)

    # Summary section
    _parse_aif_summary(text, report)

    # Exchange sections
    report.exchanges = _parse_aif_exchanges(text)

    return report


def _parse_aif_header(text: str, report: ParsedReport):
    """Extract header fields from AIF report."""
    # "# Critique Report: banana"
    m = re.search(r"^# Critique Report:\s*(.+)$", text, re.MULTILINE)
    if m:
        report.object_name = m.group(1).strip()

    m = re.search(r"\*\*Session:\*\*\s*(.+)$", text, re.MULTILINE)
    if m:
        report.session_id = m.group(1).strip()

    m = re.search(r"\*\*Age:\*\*\s*(\d+)", text)
    if m:
        report.age = int(m.group(1))

    m = re.search(r"\*\*Date:\*\*\s*(.+)$", text, re.MULTILINE)
    if m:
        report.date = m.group(1).strip()

    # Key concept may appear in pedagogical context
    m = re.search(r"\*\*Target Knowledge:\*\*\s*(.+)$", text, re.MULTILINE)
    if m:
        report.key_concept = m.group(1).strip()


def _parse_aif_summary(text: str, report: ParsedReport):
    """Extract summary metrics from AIF report."""
    # Overall Effectiveness: ⚠️ 55.0/100
    m = re.search(r"Overall Effectiveness:.*?(\d+(?:\.\d+)?)/100", text)
    if m:
        report.overall_effectiveness = float(m.group(1))

    m = re.search(r"Total Exchanges Analyzed:\*\*\s*(\d+)", text)
    if m:
        report.total_exchanges = int(m.group(1))

    m = re.search(r"Exchanges with Failures:\*\*\s*(\d+)", text)
    if m:
        report.failed_exchanges = int(m.group(1))

    # Failure breakdown table
    for match in re.finditer(r"\|\s*(\w+(?:_\w+)*)\s*\|\s*(\d+)\s*\|", text):
        failure_type = match.group(1)
        if failure_type not in ("Failure", "Type", "Count"):  # Skip header
            report.failure_breakdown[failure_type] = int(match.group(2))

    # Critical failures
    critical_section = re.search(
        r"### ⚠️ Critical Failures\s*\n(.*?)(?=\n###|\n---|\Z)",
        text, re.DOTALL
    )
    if critical_section:
        for line in critical_section.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("- "):
                report.critical_failures.append(line[2:].strip())

    # Improvement priorities
    priorities_section = re.search(
        r"### 📋 Improvement Priorities\s*\n(.*?)(?=\n---|\n##|\Z)",
        text, re.DOTALL
    )
    if priorities_section:
        for line in priorities_section.group(1).strip().split("\n"):
            m = re.match(r"\d+\.\s*(.+)", line.strip())
            if m:
                report.improvement_priorities.append(m.group(1).strip())


def _parse_aif_exchanges(text: str) -> list[ParsedExchange]:
    """Parse individual exchange sections from AIF report."""
    exchanges = []

    # Split on "### Exchange N" headers
    exchange_pattern = r"### Exchange (\d+)\s*-\s*[🔴🟠🟡⚪]\s*(\w+)"
    exchange_starts = list(re.finditer(exchange_pattern, text))

    for i, match in enumerate(exchange_starts):
        turn = int(match.group(1))
        start = match.start()
        end = exchange_starts[i + 1].start() if i + 1 < len(exchange_starts) else len(text)
        section = text[start:end]

        exchange = _parse_single_aif_exchange(section, turn)
        exchanges.append(exchange)

    return exchanges


def _parse_single_aif_exchange(section: str, turn_number: int) -> ParsedExchange:
    """Parse a single exchange section from AIF report."""
    exchange = ParsedExchange(
        turn_number=turn_number,
        model_question="",
        child_response="",
        model_response="",
    )

    # Model asked / Child said / Model responded
    m = re.search(
        r'\*\*Model asked:\*\*\s*"(.+?)"(?:\s*\n)',
        section, re.DOTALL
    )
    if m:
        exchange.model_question = m.group(1).strip()

    m = re.search(r'\*\*Child said:\*\*\s*"(.+?)"', section, re.DOTALL)
    if m:
        exchange.child_response = m.group(1).strip()

    m = re.search(
        r'\*\*Model responded:\*\*\s*"(.+?)"(?:\s*\n)',
        section, re.DOTALL
    )
    if m:
        exchange.model_response = m.group(1).strip()

    # Effectiveness score: [███████░░░] 7/10
    m = re.search(r"\[█[█░]*\]\s*(\d+)/10", section)
    if m:
        exchange.effectiveness_score = int(m.group(1))

    # Advances Learning / Addresses Knowledge Gap
    exchange.advances_learning = "Advances Learning: ✅" in section
    exchange.addresses_knowledge_gap = "Addresses Knowledge Gap: ✅" in section

    # Node Execution Trace table
    exchange.node_trace = _parse_node_trace(section)

    # Failures
    exchange.failures = _parse_failures(section)

    # Expected vs Actual
    exchange.expected_vs_actual = _parse_expected_vs_actual(section)

    # Ideal Response
    m = re.search(r"#### Ideal Response\s*\n>\s*(.+?)(?=\n####|\n---|\Z)", section, re.DOTALL)
    if m:
        exchange.ideal_response = m.group(1).strip()

    # Picky Observations
    picky_section = re.search(
        r"#### Picky Observations\s*\n(.*?)(?=\n####|\n---|\Z)",
        section, re.DOTALL
    )
    if picky_section:
        for line in picky_section.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("- "):
                exchange.picky_observations.append(line[2:].strip())

    # Improvement Suggestions
    improvements_section = re.search(
        r"#### Improvement Suggestions\s*\n(.*?)(?=\n####|\n---|\Z)",
        section, re.DOTALL
    )
    if improvements_section:
        for line in improvements_section.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("- "):
                exchange.improvements.append(line[2:].strip())

    return exchange


def _parse_node_trace(section: str) -> list[dict]:
    """Parse the Node Execution Trace table."""
    traces = []
    # | analyze_input | 1372ms | is_engaged=False, is_factually_correct=False |
    for m in re.finditer(
        r"\|\s*(\w+)\s*\|\s*(\d+)ms\s*\|\s*(.*?)\s*\|",
        section,
    ):
        node_name = m.group(1)
        time_ms = int(m.group(2))
        changes_str = m.group(3).strip()

        changes = {}
        if changes_str and changes_str != "-":
            for pair in changes_str.split(","):
                pair = pair.strip()
                if "=" in pair:
                    key, val = pair.split("=", 1)
                    changes[key.strip()] = val.strip()

        traces.append({
            "node": node_name,
            "time_ms": time_ms,
            "changes": changes,
        })

    return traces


def _parse_failures(section: str) -> list[dict]:
    """Parse failure entries from an exchange section."""
    failures = []

    # Pattern: 1. **FAILURE_TYPE** 🔴 (SEVERITY)
    failure_pattern = re.compile(
        r"\d+\.\s+\*\*(\w+(?:_\w+)*)\*\*\s+[🔴🟠🟡]\s+\((\w+)\)\s*\n"
        r"\s+-\s+(.+?)\n"
        r"\s+-\s+Evidence:\s*\"(.+?)\"",
        re.DOTALL,
    )

    for m in failure_pattern.finditer(section):
        failures.append({
            "type": m.group(1),
            "severity": m.group(2),
            "description": m.group(3).strip(),
            "evidence": m.group(4).strip(),
        })

    return failures


def _parse_expected_vs_actual(section: str) -> dict | None:
    """Parse the Expected vs Actual block."""
    m = re.search(
        r"\*\*I expected:\*\*\s*(.+?)\n>\s*\n"
        r">\s*\*\*But got:\*\*\s*(.+?)\n>\s*\n"
        r">\s*\*\*This is problematic because:\*\*\s*(.+?)(?=\n\n|\n####|\Z)",
        section, re.DOTALL,
    )
    if m:
        return {
            "expected": m.group(1).strip(),
            "got": m.group(2).strip(),
            "problematic_because": m.group(3).strip(),
        }
    return None


# ============================================================================
# HF Report Parser
# ============================================================================

def _parse_hf_report(text: str) -> ParsedReport:
    """Parse an HF (Human Feedback) critique report."""
    report = ParsedReport(source="HF")

    # Header
    _parse_hf_header(text, report)

    # Exchange sections
    report.exchanges = _parse_hf_exchanges(text)
    report.total_exchanges = len(report.exchanges)
    report.failed_exchanges = len(report.exchanges)  # All HF exchanges have critiques

    return report


def _parse_hf_header(text: str, report: ParsedReport):
    """Extract header fields from HF report."""
    m = re.search(r"# Human Feedback Critique Report:\s*(.+)$", text, re.MULTILINE)
    if m:
        report.object_name = m.group(1).strip()

    m = re.search(r"\*\*Session:\*\*\s*(.+)$", text, re.MULTILINE)
    if m:
        report.session_id = m.group(1).strip()

    m = re.search(r"\*\*Age:\*\*\s*(\d+)", text)
    if m:
        report.age = int(m.group(1))

    m = re.search(r"\*\*Date:\*\*\s*(.+)$", text, re.MULTILINE)
    if m:
        report.date = m.group(1).strip()

    m = re.search(r"\*\*Feedback Type:\*\*\s*(.+)$", text, re.MULTILINE)
    if m:
        report.feedback_type = m.group(1).strip()

    m = re.search(r"\*\*Exchanges Critiqued:\*\*\s*(\d+)\s*/\s*(\d+)", text)
    if m:
        report.exchanges_critiqued_count = int(m.group(1))
        report.exchanges_total_count = int(m.group(2))


def _parse_hf_exchanges(text: str) -> list[ParsedExchange]:
    """Parse exchange sections from HF report."""
    exchanges = []

    # Split on "### Exchange N" headers
    exchange_starts = list(re.finditer(r"### Exchange (\d+)", text))

    for i, match in enumerate(exchange_starts):
        turn = int(match.group(1))
        start = match.start()
        end = exchange_starts[i + 1].start() if i + 1 < len(exchange_starts) else len(text)
        section = text[start:end]

        exchange = _parse_single_hf_exchange(section, turn)
        exchanges.append(exchange)

    return exchanges


def _parse_single_hf_exchange(section: str, turn_number: int) -> ParsedExchange:
    """Parse a single exchange section from HF report."""
    exchange = ParsedExchange(
        turn_number=turn_number,
        model_question="",
        child_response="",
        model_response="",
    )

    # Model asked / Child said / Model responded
    m = re.search(r'\*\*Model asked:\*\*\s*"(.+?)"', section, re.DOTALL)
    if m:
        exchange.model_question = m.group(1).strip()

    m = re.search(r'\*\*Child said:\*\*\s*"(.+?)"', section, re.DOTALL)
    if m:
        exchange.child_response = m.group(1).strip()

    m = re.search(r'\*\*Model responded:\*\*\s*"(.+?)"', section, re.DOTALL)
    if m:
        exchange.model_response = m.group(1).strip()

    # Node trace
    exchange.node_trace = _parse_node_trace(section)

    # Human critique
    critique_section = re.search(
        r"#### Human Critique\s*\n(.*?)(?=\n####|\n---|\Z)",
        section, re.DOTALL,
    )
    if critique_section:
        critique_text = critique_section.group(1).strip()
        # Extract "Why is it problematic:" field
        m = re.search(r"\*Why is it problematic:\*\s*(.+?)(?=\n\n|\Z)", critique_text, re.DOTALL)
        if m:
            exchange.human_critique = m.group(1).strip()
        else:
            exchange.human_critique = critique_text

    return exchange
