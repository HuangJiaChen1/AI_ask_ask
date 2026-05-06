#!/usr/bin/env python3
"""
Generic IRL (In-Real-Life) Verification Harness.

Runs live LLM calls through Vertex AI Gemini and captures outputs into a
structured Markdown report.  Accepts test cases as a JSON config file so
different feature sets can be verified without editing this script.

Usage:
    python scripts/irl_verify.py --config scripts/irl_verify_scenarios.json

Config format (JSON):
    {
      "report_prefix": "my-feature",
      "model_overrides": {"temperature": 0.3},
      "delay_seconds": 3,
      "tests": [
        {
          "id": "hook_type_imitation",
          "task_num": 1,
          "title": "Hook Type — 模仿引导",
          "implemented": "Added imitation hook type with voice-only safety.",
          "scenario": "Object: toy dog | Age: 5",
          "generator": "ask_introduction_question_stream",
          "params": {
            "object_name": "toy dog",
            "intro_mode": "default",
            "age": 5,
            "hook_type_section": "..."
          },
          "checks": [
            {"criterion": "Invites voice or movement", "assert": "?"},
            {"criterion": "No touch invitation", "assert_not": "touch"}
          ]
        },
        ...
      ]
    }

Generators supported:
    - ask_introduction_question_stream
    - ask_attribute_intro_stream
    - ask_followup_question_stream
    - generate_intent_response_stream
    - direct_prompt  (makes a raw non-streaming call)

Output:
    docs/verification/<prefix>-verification-<timestamp>.md
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google import genai
from google.genai.types import HttpOptions

from paixueji_assistant import PaixuejiAssistant
from stream.question_generators import (
    ask_attribute_intro_stream,
    ask_followup_question_stream,
    ask_introduction_question_stream,
)
from stream.response_generators import generate_intent_response_stream
from stream.utils import clean_messages_for_api, convert_messages_to_gemini_format


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _age_prompt_for(age: int) -> str:
    assistant = PaixuejiAssistant(config_path=str(PROJECT_ROOT / "config.json"))
    return assistant.get_age_prompt(age)


async def _call_llm_direct(assistant, prompt: str, messages: list[dict], max_retries=3) -> str:
    messages_to_send = messages + [{"role": "user", "content": prompt}]
    clean = clean_messages_for_api(messages_to_send)
    system_instruction, contents = convert_messages_to_gemini_format(clean)

    for attempt in range(max_retries):
        try:
            response = await assistant.client.aio.models.generate_content(
                model=assistant.config["model_name"],
                contents=contents,
                config={
                    "temperature": assistant.config.get("temperature", 0.3),
                    "max_output_tokens": assistant.config.get("max_tokens", 500),
                    "system_instruction": system_instruction if system_instruction else None,
                },
            )
            return (response.text or "").strip()
        except Exception as exc:
            from stream.errors import is_rate_limit_error
            if is_rate_limit_error(exc) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 2)
                print(f"    [RATE LIMIT] Retry {attempt + 1}/{max_retries} after {wait}s...")
                await asyncio.sleep(wait)
                continue
            return f"[ERROR: {exc}]"
    return ""


async def _collect_stream(gen_factory, max_retries=3):
    for attempt in range(max_retries):
        full = ""
        try:
            async for chunk in gen_factory():
                if chunk and chunk[0]:
                    full += chunk[0]
            return full.strip()
        except Exception as exc:
            from stream.errors import is_rate_limit_error
            if is_rate_limit_error(exc) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 2)
                print(f"    [RATE LIMIT] Retry {attempt + 1}/{max_retries} after {wait}s...")
                await asyncio.sleep(wait)
                continue
            return f"[ERROR: {exc}]"
    return full.strip()


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

class ReportBuilder:
    def __init__(self):
        self.lines = [
            "# IRL Verification Report\n",
            f"**Generated:** {datetime.now().isoformat()}\n",
            "**Model:** Gemini via Vertex AI (live calls)\n",
            "**Method:** Each section shows the actual model output when the "
            "corresponding feature is triggered with a realistic input.\n",
            "---\n",
        ]

    def add_section(self, task_num, title, implemented, scenario, prompt_excerpt, output, checks):
        self.lines.append(f"## Task {task_num}: {title}\n")
        self.lines.append(f"**What was implemented:** {implemented}\n")
        self.lines.append(f"**Test scenario:** {scenario}\n")
        self.lines.append(f"**Prompt excerpt:**\n```\n{prompt_excerpt}\n```\n")
        self.lines.append("### Model Output:\n")
        self.lines.append(f"```\n{output}\n```\n")
        self.lines.append("### Verification:\n")
        for check in checks:
            mark = "[x]" if check.get("passed", False) else "[ ]"
            note = check.get("note", "")
            line = f"- {mark} {check['criterion']}"
            if note:
                line += f" ({note})"
            self.lines.append(line + "\n")
        self.lines.append("\n---\n")

    def add_summary(self, findings):
        self.lines.append("# Summary of Findings\n")
        self.lines.append("## ✅ What Works Well\n")
        for item in findings.get("good", []):
            self.lines.append(f"- {item}\n")
        self.lines.append("\n## ⚠️ Issues Discovered\n")
        for item in findings.get("issues", []):
            self.lines.append(f"- **{item['title']}**\n")
            self.lines.append(f"  - {item['detail']}\n")
            if "impact" in item:
                self.lines.append(f"  - Impact: {item['impact']}\n")
            if "recommendation" in item:
                self.lines.append(f"  - Recommendation: {item['recommendation']}\n")
        self.lines.append("\n---\n")

    def write(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(self.lines)
        print(f"Report written to: {path}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

async def _run_test(test_config: dict, assistant) -> dict:
    """Run a single test case and return results."""
    generator_name = test_config["generator"]
    params = test_config.get("params", {})

    # Resolve age_prompt if age is provided
    if "age" in params and "age_prompt" not in params:
        params["age_prompt"] = _age_prompt_for(params["age"])

    # Build messages if not provided
    if "messages" not in params:
        last_response = params.get("last_model_response", "")
        params["messages"] = [{"role": "assistant", "content": last_response}] if last_response else []

    # Inject config and client
    params["config"] = assistant.config
    params["client"] = assistant.client

    output = ""
    if generator_name == "ask_introduction_question_stream":
        output = await _collect_stream(lambda: ask_introduction_question_stream(**params))
    elif generator_name == "ask_attribute_intro_stream":
        output = await _collect_stream(lambda: ask_attribute_intro_stream(**params))
    elif generator_name == "ask_followup_question_stream":
        output = await _collect_stream(lambda: ask_followup_question_stream(**params))
    elif generator_name == "generate_intent_response_stream":
        output = await _collect_stream(lambda: generate_intent_response_stream(**params))
    elif generator_name == "direct_prompt":
        prompt = params.get("prompt", "")
        messages = params.get("messages", [])
        output = await _call_llm_direct(assistant, prompt, messages)
    else:
        output = f"[Unknown generator: {generator_name}]"

    # Evaluate checks
    checks = []
    lower = output.lower()
    for check in test_config.get("checks", []):
        passed = True
        note = ""
        if "assert" in check:
            passed = check["assert"] in output
        if "assert_not" in check:
            if check["assert_not"] in lower:
                passed = False
                note = f"contains '{check['assert_not']}'"
        if "assert_in" in check:
            passed = any(k in lower for k in check["assert_in"])
        checks.append({
            "criterion": check["criterion"],
            "passed": passed,
            "note": note,
        })

    return {
        "output": output,
        "checks": checks,
    }


async def run_verification(config_path: str, report_name: str = None, overwrite: bool = False):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Load project config
    project_config_path = PROJECT_ROOT / "config.json"
    with open(project_config_path, "r", encoding="utf-8") as f:
        project_config = json.load(f)

    print(f"[INFO] project={project_config['project']} model={project_config['model_name']}")

    client = genai.Client(
        vertexai=True,
        project=project_config["project"],
        location=project_config["location"],
        http_options=HttpOptions(api_version="v1"),
    )
    assistant = PaixuejiAssistant(config_path=str(project_config_path), client=client)

    report = ReportBuilder()
    findings = {"good": [], "issues": []}

    tests = cfg.get("tests", [])
    delay = cfg.get("delay_seconds", 3)
    print(f"[INFO] Running {len(tests)} IRL verification tests...")

    for i, test in enumerate(tests, 1):
        print(f"\n[{i}/{len(tests)}] {test['title']}...")
        try:
            result = await _run_test(test, assistant)
        except Exception as e:
            result = {
                "output": f"[EXCEPTION: {e}]",
                "checks": [{"criterion": "Test executed without error", "passed": False, "note": str(e)}],
            }

        report.add_section(
            task_num=test.get("task_num", i),
            title=test["title"],
            implemented=test["implemented"],
            scenario=test["scenario"],
            prompt_excerpt=test.get("prompt_excerpt", test.get("params", {}).get("hook_type_section", "")[:300] + "..."),
            output=result["output"],
            checks=result["checks"],
        )

        # Categorize for summary
        all_passed = all(c["passed"] for c in result["checks"])
        if all_passed:
            findings["good"].append(f"{test['title']}: all checks passed")
        else:
            failed = [c["criterion"] for c in result["checks"] if not c["passed"]]
            findings["issues"].append({
                "title": test["title"],
                "detail": f"Failed checks: {', '.join(failed)}",
                "impact": "See report for model output and specific failures",
            })

        if i < len(tests):
            await asyncio.sleep(delay)

    # Write report
    prefix = cfg.get("report_prefix", "irl")
    if report_name:
        filename = f"{report_name}.md"
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"{prefix}-verification-{timestamp}.md"
    report_path = PROJECT_ROOT / "docs" / "verification" / filename

    if report_path.exists() and not overwrite:
        print(f"\n[ERROR] Report already exists: {report_path}")
        print("[INFO] Use --overwrite to replace it, or use a different --report-name.")
        return str(report_path)

    report.add_summary(findings)
    report.write(report_path)
    print(f"\n[INFO] Verification complete! Report: {report_path}")
    return str(report_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="IRL Verification Harness")
    parser.add_argument("--config", required=True, help="Path to JSON test config file")
    parser.add_argument("--report-name", default=None, help="Custom report filename (no extension). If omitted, uses timestamp.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing report if --report-name is used.")
    args = parser.parse_args()
    asyncio.run(run_verification(args.config, report_name=args.report_name, overwrite=args.overwrite))


if __name__ == "__main__":
    main()
