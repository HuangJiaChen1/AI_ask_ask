"""
LLM judge for HF replay verdicts.
"""

from __future__ import annotations

import json
from typing import Any

from google import genai


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        last_fence = text.rfind("```")
        if first_newline != -1 and last_fence != -1 and last_fence > first_newline:
            text = text[first_newline + 1:last_fence].strip()
    return json.loads(text)


class HFReplayJudge:
    def __init__(self, client: genai.Client, model: str = "gemini-2.5-pro"):
        self.client = client
        self.model = model

    async def judge_critiqued_case(
        self,
        bundle: dict[str, Any],
        case: dict[str, Any],
        candidate_response: str,
    ) -> dict[str, Any]:
        prompt = f"""You are an expert evaluator for LLM behavior regressions.
Decide if candidate output FIXES the issue described by human feedback for this exchange.

Context:
- Object: {bundle.get("object_name")}
- Age: {bundle.get("age")}
- Key Concept: {bundle.get("key_concept")}
- Mode: {case.get("mode")}

Exchange:
- Model question: {case.get("model_question")}
- Child response: {case.get("child_response")}
- Original historical response: {case.get("baseline_model_response")}
- Candidate response: {candidate_response}

Human feedback rubric:
- Expected model question: {case.get("human_feedback", {}).get("model_question_expected")}
- Question problem: {case.get("human_feedback", {}).get("model_question_problem")}
- Expected model response: {case.get("human_feedback", {}).get("model_response_expected")}
- Response problem: {case.get("human_feedback", {}).get("model_response_problem")}
- Conclusion: {case.get("human_feedback", {}).get("conclusion")}

Return JSON only:
{{
  "verdict": "pass" | "fail",
  "confidence": 0.0,
  "improvement_detected": true,
  "regression_detected": false,
  "reason_summary": "short reason",
  "evidence_quotes": ["short quote 1", "short quote 2"],
  "checks": {{
    "fixes_reported_problem": true,
    "satisfies_expected_behavior": true,
    "introduces_new_problem": false,
    "preserves_working_behavior": true
  }}
}}

Rules:
- pass only if candidate clearly fixes reported issue and does not introduce severe new issues.
- if uncertain, fail with lower confidence.
"""

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        )
        return _extract_json(response.text)
