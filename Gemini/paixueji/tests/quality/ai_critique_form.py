"""
AI Critique Form Filler.

Replaces the PedagogicalCritiquePipeline for the /api/critique endpoint.
Calls the LLM once per exchange to fill in the same 5 fields a human reviewer
would type on the manual critique form. Returns None for passing exchanges,
a HumanCritique object for flawed ones.
"""

import asyncio
import json

from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from trace_schema import HumanCritique


AI_CRITIQUE_FORM_PROMPT = """You are an expert educational AI reviewer conducting a thorough pedagogical quality assessment of a children's learning exchange.

CONTEXT
- Object being discussed: {object_name}
- Child's age: {age} years old
- Mode: {mode}  (chat = exploratory Q&A, guide = leading child toward a key concept){key_concept_line}{theme_line}

EXCHANGE TO ASSESS
Model question: "{model_question}"
Child's response: "{child_response}"
Model response: "{model_response}"

TASK
Fill in the five critique form fields below. Be thorough and honest — flag any genuine pedagogical issue, even a minor one. A {age}-year-old's learning experience depends on this feedback.

Evaluate the MODEL QUESTION on:
- Is it age-appropriate vocabulary and length for a {age}-year-old?
- Does it build on what the child just said, or ignore it?
- Is it interesting and curiosity-provoking, or generic?
- Does it avoid repeating information already established?

Evaluate the MODEL RESPONSE on:
- Does it genuinely acknowledge and engage with the child's specific answer?
- Does it add meaningful new information (not just restate the question)?
- Does it miss a teachable moment the child's answer opened up?
- Is the length and complexity appropriate for {age} years old?
- In guide mode: does it advance understanding toward the key concept?

FORM FIELDS

1. model_question_problem — What is suboptimal about the model's question?
   Quote the specific phrase that is problematic. Leave "" ONLY if the question is genuinely exemplary.

2. model_question_expected — What should the model have asked instead? (concrete alternative)
   Leave "" if model_question_problem is "".

3. model_response_problem — What is suboptimal about the model's response?
   Quote the specific phrase that is problematic. Leave "" ONLY if the response is genuinely exemplary.

4. model_response_expected — What should the model have responded instead? (concrete alternative)
   Leave "" if model_response_problem is "".

5. conclusion — 1-2 sentence overall assessment of this exchange's effectiveness.
   Write this for any exchange where at least one field above is non-empty.

IMPORTANT: Empty fields ("") mean the question or response was genuinely excellent with no room for improvement for a {age}-year-old. This should be the exception, not the rule. Most exchanges have at least minor issues.

Return ONLY a valid JSON object. Do NOT include any text outside the JSON.

Use this schema — fill every field with a complete sentence (or "" ONLY for genuinely
exemplary content). The values below are guidance for the expected style of critique:

{{
  "model_question_problem": "<quote the problematic phrase and explain why it fails for a {age}-year-old>",
  "model_question_expected": "<a concrete, better alternative question>",
  "model_response_problem": "<quote the problematic phrase and explain the pedagogical failure>",
  "model_response_expected": "<a concrete, better alternative response>",
  "conclusion": "<1-2 sentence summary of this exchange's overall quality>"
}}

If the question had no flaws at all, set model_question_problem and model_question_expected to "".
If the response had no flaws at all, set model_response_problem and model_response_expected to "".
If both were flawless, set conclusion to "" as well.
Finding no issues in a real teaching exchange should be rare — most have at least one.
"""


class AICritiqueFormFiller:
    """
    AI-powered form filler that mirrors the manual critique workflow.

    For each exchange triplet (model_question → child_response → model_response),
    calls the LLM to fill in the 5 HumanCritique form fields. Exchanges with no
    genuine problems return None (skipped from the final report and trace assembly).
    """

    def __init__(self, client: genai.Client, config: dict):
        self.client = client
        self.model = config["high_reasoning_model"]

    async def fill_exchange(
        self,
        exchange_index: int,
        model_question: str,
        child_response: str,
        model_response: str,
        object_name: str,
        age: int,
        mode: str = "chat",
        key_concept: str | None = None,
        ibpyp_theme_name: str | None = None,
    ) -> HumanCritique | None:
        """
        Ask the LLM to fill in the 5-field critique form for one exchange.

        Returns:
            HumanCritique if any problem field is non-empty, else None.
        """
        key_concept_line = f"\n- Key concept being taught: {key_concept}" if key_concept and mode == "guide" else ""
        theme_line = f"\n- IB PYP Theme: {ibpyp_theme_name}" if ibpyp_theme_name else ""

        prompt = AI_CRITIQUE_FORM_PROMPT.format(
            object_name=object_name,
            age=age,
            mode=mode,
            key_concept_line=key_concept_line,
            theme_line=theme_line,
            model_question=model_question,
            child_response=child_response,
            model_response=model_response,
        )

        MAX_RETRIES = 3
        BACKOFF_SECONDS = [2, 4, 8]

        response = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                break  # success — exit retry loop
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    if attempt < MAX_RETRIES - 1:
                        wait = BACKOFF_SECONDS[attempt]
                        logger.warning(
                            f"[AICritiqueFormFiller] 429 on exchange {exchange_index}, "
                            f"retry {attempt + 1}/{MAX_RETRIES - 1} in {wait}s"
                        )
                        await asyncio.sleep(wait)
                        continue
                # Non-429 error or final attempt: log and return None
                logger.error(
                    f"[AICritiqueFormFiller] LLM call failed for exchange {exchange_index}: {e}"
                )
                return None

        if response is None:
            return None

        text = response.text.strip()
        logger.debug(f"[AICritiqueFormFiller] Exchange {exchange_index} raw: {text[:300]}")

        # Strip markdown code fences if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except Exception as e:
            logger.error(
                f"[AICritiqueFormFiller] JSON parse failed for exchange {exchange_index}: {e}"
            )
            return None

        mq_problem = data.get("model_question_problem", "").strip()
        mq_expected = data.get("model_question_expected", "").strip()
        mr_problem = data.get("model_response_problem", "").strip()
        mr_expected = data.get("model_response_expected", "").strip()
        conclusion = data.get("conclusion", "").strip()

        # If all fields are empty the exchange passes — return None (skip it)
        if not any([mq_problem, mq_expected, mr_problem, mr_expected, conclusion]):
            logger.info(
                f"[AICritiqueFormFiller] Exchange {exchange_index}: no issues found "
                f"(raw: {text[:120]})"
            )
            return None

        logger.info(
            f"[AICritiqueFormFiller] Exchange {exchange_index}: "
            f"Q-problem={'yes' if mq_problem else 'no'}, "
            f"R-problem={'yes' if mr_problem else 'no'}"
        )

        return HumanCritique(
            exchange_index=exchange_index,
            model_question_problem=mq_problem,
            model_question_expected=mq_expected,
            model_response_problem=mr_problem,
            model_response_expected=mr_expected,
            conclusion=conclusion,
        )
