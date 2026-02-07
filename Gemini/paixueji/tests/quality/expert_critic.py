"""
Expert Critic - The "Picky Teacher" LLM reviewer.

This is the core innovation of the pedagogical critique system.
Instead of checklist compliance, we use a strong reasoning LLM
as an educational expert who reviews transcripts like a frustrated,
picky teacher would.

The critic asks:
1. What was the pedagogical INTENT?
2. What KNOWLEDGE GAP exists?
3. Does the response ADVANCE learning?
4. What SHOULD have happened?
5. What ACTUALLY happened?
6. What's the specific FAILURE?
"""

import json
from google import genai
from google.genai.types import GenerateContentConfig

from .schema import (
    PedagogicalContext,
    ScenarioSetup,
    ScenarioEvaluation,
    Failure,
    FailureType,
    Severity,
    ExpectedVsActual,
    ExchangeCritique,
)


EXPERT_CRITIC_PROMPT = """You are a VERY PICKY educational expert reviewing a children's learning conversation.
You are easily frustrated when teaching is ineffective. Be critical, specific, and demanding.

CONTEXT:
- Object: {object_name}
- Key Concept: {key_concept}
- Child's Age: {age}

PEDAGOGICAL ANALYSIS (from pre-analysis):
- Question Type: {question_type}
- Question Intent: {question_intent}
- Target Knowledge: {target_knowledge}
- Child Response Type: {child_response_type}
- Knowledge Gap: {knowledge_gap}
- Ideal Next Action: {ideal_next_action}
- Acceptable Actions: {acceptable_actions}
- Unacceptable Actions: {unacceptable_actions}

SCENARIO REQUIREMENTS:
- Must do: {must_do}
- Must not do: {must_not_do}

ACTUAL EXCHANGE:
Model asked: "{model_question}"
Child responded: "{child_response}"
Model then said: "{model_actual_response}"

YOUR TASK:
As a picky, demanding educational expert, critique this response.

1. **Does the response ADVANCE learning?**
   - Does it help close the knowledge gap?
   - Does it move the child closer to understanding {target_knowledge}?
   - Or does it sidestep, repeat, or fail to add new information?

2. **Is this what the child NEEDED?**
   - The child's response indicated: {child_response_type}
   - The knowledge gap was: {knowledge_gap}
   - Did the model address THIS gap, or something else?

3. **Specific Failures** (be picky!):
   - Did the model commit any of the unacceptable actions?
   - Did it miss an opportunity to teach effectively?
   - Is there a subtle pedagogical failure that a checklist wouldn't catch?

4. **What SHOULD have happened?**
   - Write what an IDEAL response would look like
   - Explain why this would be better

FAILURE TYPES to consider:
- SAME_QUESTION_REPHRASED: Asked the same thing in different words without adding info
- MISSED_SCAFFOLD: Failed to provide a hint or bridge when child was stuck
- WRONG_QUESTION_TYPE: Changed question type inappropriately (e.g., WHY → WHAT without scaffolding)
- NO_NEW_INFO: Response adds nothing new to help understanding
- ABANDONED_INTENT: Gave up on the teaching goal and moved to something else
- IGNORED_CONFUSION: Didn't address apparent confusion
- TOO_COMPLEX: Made it harder than necessary for the age
- TOO_SIMPLE: Underestimated the child or was patronizing
- MISSED_TEACHABLE_MOMENT: Had an opportunity to teach but didn't take it
- OTHER: Some other pedagogical failure

OUTPUT FORMAT (JSON):
{{
    "advances_learning": true | false,
    "addresses_knowledge_gap": true | false,
    "effectiveness_score": 1-10,

    "failures": [
        {{
            "type": "SAME_QUESTION_REPHRASED" | "MISSED_SCAFFOLD" | "WRONG_QUESTION_TYPE" | "NO_NEW_INFO" | "ABANDONED_INTENT" | "IGNORED_CONFUSION" | "TOO_COMPLEX" | "TOO_SIMPLE" | "MISSED_TEACHABLE_MOMENT" | "OTHER",
            "description": "Specific description of the failure",
            "evidence": "Exact text that shows the problem",
            "severity": "CRITICAL" | "MAJOR" | "MINOR"
        }}
    ],

    "expected_vs_actual": {{
        "i_expected": "What I expected the model to do given the pedagogical context",
        "but_got": "What the model actually did",
        "this_is_problematic_because": "Why this fails the child pedagogically"
    }},

    "ideal_response": "Write an example of what the model SHOULD have said",

    "improvement_suggestions": [
        "Specific suggestion 1",
        "Specific suggestion 2"
    ],

    "picky_observations": [
        "Detailed observation about subtle issues",
        "Another picky observation a demanding teacher would notice"
    ]
}}

Be harsh but fair. If the response is actually good, say so. But if there are problems, don't sugarcoat them.
"""


class ExpertCritic:
    """The "picky teacher" critic that reviews pedagogical effectiveness."""

    def __init__(
        self,
        client: genai.Client,
        model: str = "gemini-2.5-pro",  # Strong reasoning model (configurable)
    ):
        """
        Initialize the expert critic.

        Args:
            client: Google GenAI client
            model: Model to use for critique (should be a STRONG model)
        """
        self.client = client
        self.model = model

    async def critique(
        self,
        turn_number: int,
        model_question: str,
        child_response: str,
        model_actual_response: str,
        context: PedagogicalContext,
        setup: ScenarioSetup,
        evaluation: ScenarioEvaluation,
    ) -> ExchangeCritique:
        """
        Critique a single exchange in a conversation.

        Args:
            turn_number: Which turn in the conversation
            model_question: What the model asked
            child_response: How the child responded
            model_actual_response: How the model responded to the child
            context: Extracted pedagogical context
            setup: Scenario setup
            evaluation: Evaluation criteria

        Returns:
            ExchangeCritique with detailed analysis
        """
        prompt = EXPERT_CRITIC_PROMPT.format(
            object_name=setup.object_name,
            key_concept=setup.key_concept,
            age=setup.age,
            question_type=context.question_type.value,
            question_intent=context.question_intent,
            target_knowledge=context.target_knowledge,
            child_response_type=context.child_response_type.value,
            knowledge_gap=context.knowledge_gap,
            ideal_next_action=context.ideal_next_action,
            acceptable_actions=", ".join(context.acceptable_actions) or "None specified",
            unacceptable_actions=", ".join(context.unacceptable_actions) or "None specified",
            must_do=", ".join(evaluation.must_do) or "None specified",
            must_not_do=", ".join(evaluation.must_not_do) or "None specified",
            model_question=model_question,
            child_response=child_response,
            model_actual_response=model_actual_response,
        )

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.3,  # Some creativity for insights, but mostly consistent
            },
        )

        return self._parse_critique(
            response.text,
            turn_number,
            model_question,
            child_response,
            model_actual_response,
            context,
        )

    def critique_sync(
        self,
        turn_number: int,
        model_question: str,
        child_response: str,
        model_actual_response: str,
        context: PedagogicalContext,
        setup: ScenarioSetup,
        evaluation: ScenarioEvaluation,
    ) -> ExchangeCritique:
        """Synchronous version of critique."""
        prompt = EXPERT_CRITIC_PROMPT.format(
            object_name=setup.object_name,
            key_concept=setup.key_concept,
            age=setup.age,
            question_type=context.question_type.value,
            question_intent=context.question_intent,
            target_knowledge=context.target_knowledge,
            child_response_type=context.child_response_type.value,
            knowledge_gap=context.knowledge_gap,
            ideal_next_action=context.ideal_next_action,
            acceptable_actions=", ".join(context.acceptable_actions) or "None specified",
            unacceptable_actions=", ".join(context.unacceptable_actions) or "None specified",
            must_do=", ".join(evaluation.must_do) or "None specified",
            must_not_do=", ".join(evaluation.must_not_do) or "None specified",
            model_question=model_question,
            child_response=child_response,
            model_actual_response=model_actual_response,
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )

        return self._parse_critique(
            response.text,
            turn_number,
            model_question,
            child_response,
            model_actual_response,
            context,
        )

    def _parse_critique(
        self,
        response_text: str,
        turn_number: int,
        model_question: str,
        child_response: str,
        model_actual_response: str,
        context: PedagogicalContext,
    ) -> ExchangeCritique:
        """Parse the LLM's critique response into structured data."""
        try:
            data = json.loads(response_text)

            # Parse failures
            failures = []
            for f in data.get("failures", []):
                try:
                    failures.append(Failure(
                        type=FailureType(f["type"]),
                        description=f["description"],
                        evidence=f["evidence"],
                        severity=Severity(f["severity"]),
                    ))
                except (KeyError, ValueError):
                    # Skip malformed failures
                    pass

            # Parse expected vs actual
            eva_data = data.get("expected_vs_actual", {})
            expected_vs_actual = None
            if eva_data:
                try:
                    expected_vs_actual = ExpectedVsActual(
                        i_expected=eva_data.get("i_expected", ""),
                        but_got=eva_data.get("but_got", ""),
                        this_is_problematic_because=eva_data.get("this_is_problematic_because", ""),
                    )
                except Exception:
                    pass

            return ExchangeCritique(
                turn_number=turn_number,
                model_question=model_question,
                child_response=child_response,
                model_actual=model_actual_response,
                context=context,
                advances_learning=data.get("advances_learning", False),
                addresses_knowledge_gap=data.get("addresses_knowledge_gap", False),
                effectiveness_score=max(1, min(10, data.get("effectiveness_score", 5))),
                failures=failures,
                expected_vs_actual=expected_vs_actual,
                ideal_response=data.get("ideal_response", ""),
                improvements=data.get("improvement_suggestions", []),
                picky_observations=data.get("picky_observations", []),
            )

        except json.JSONDecodeError:
            # Return a default critique if parsing fails
            return ExchangeCritique(
                turn_number=turn_number,
                model_question=model_question,
                child_response=child_response,
                model_actual=model_actual_response,
                context=context,
                advances_learning=False,
                addresses_knowledge_gap=False,
                effectiveness_score=1,
                failures=[
                    Failure(
                        type=FailureType.OTHER,
                        description="Failed to parse critique response",
                        evidence=response_text[:200],
                        severity=Severity.MINOR,
                    )
                ],
                expected_vs_actual=None,
                ideal_response="Unable to generate ideal response",
                improvements=[],
                picky_observations=[],
            )
