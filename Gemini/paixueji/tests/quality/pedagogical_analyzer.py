"""
Pedagogical Analyzer for extracting teaching intent and learning gaps.

Before the expert critic reviews a conversation, this analyzer extracts
structured metadata about:
- What type of question was asked
- What the model was trying to teach
- What knowledge gap the child's response reveals
- What actions would advance learning vs. fail pedagogically
"""

import json
from google import genai
from google.genai.types import GenerateContentConfig

from .schema import (
    QuestionType,
    ResponseType,
    PedagogicalContext,
    ScenarioSetup,
)


ANALYZER_PROMPT = """You are an educational expert analyzing a single exchange in a children's learning conversation.

CONTEXT:
- Object being discussed: {object_name}
- Key concept being taught: {key_concept}
- Child's age: {age}

EXCHANGE:
- Model said: "{model_utterance}"
- Child responded: "{child_response}"

Analyze this exchange and extract:

1. **Question Type**: What type of question did the model ask?
   - WHY: Asking for causation, reasoning, explanation
   - WHAT: Asking for description, identification, naming
   - HOW: Asking about process, mechanism, method
   - WHERE: Asking about location, spatial relationship
   - WHEN: Asking about time, sequence
   - WHICH: Asking for selection, comparison
   - OPEN: Open-ended exploration without specific answer
   - STATEMENT: Not a question (giving information)

2. **Question Intent**: What is the model trying to get the child to understand?

3. **Target Knowledge**: What specific knowledge/concept is being taught?

4. **Child Response Type**: How did the child respond?
   - ANSWER: Attempted to answer (right or wrong)
   - PARTIAL: Gave an incomplete or partially correct answer
   - CONFUSED: Shows confusion or misunderstanding
   - DONT_KNOW: Explicitly said "I don't know" or similar
   - OFF_TOPIC: Response was unrelated
   - QUESTION: Child asked a question back
   - ENGAGEMENT: Shows interest but didn't answer

5. **Knowledge Gap**: What does the child's response reveal they don't understand?

6. **Ideal Next Action**: What should the model do next to ADVANCE learning?

7. **Acceptable Actions**: What other approaches would also be acceptable?

8. **Unacceptable Actions**: What would FAIL pedagogically? (e.g., rephrasing without adding info)

OUTPUT as JSON:
{{
    "question_type": "WHY" | "WHAT" | "HOW" | "WHERE" | "WHEN" | "WHICH" | "OPEN" | "STATEMENT",
    "question_intent": "string",
    "target_knowledge": "string",
    "child_response_type": "ANSWER" | "PARTIAL" | "CONFUSED" | "DONT_KNOW" | "OFF_TOPIC" | "QUESTION" | "ENGAGEMENT",
    "knowledge_gap": "string",
    "ideal_next_action": "string",
    "acceptable_actions": ["string", ...],
    "unacceptable_actions": ["string", ...]
}}
"""


class PedagogicalAnalyzer:
    """Extracts pedagogical context from conversation exchanges."""

    def __init__(self, client: genai.Client, model: str = "gemini-2.5-pro"):
        """
        Initialize the analyzer.

        Args:
            client: Google GenAI client
            model: Model to use for analysis (Flash is fine for extraction)
        """
        self.client = client
        self.model = model

    async def analyze(
        self,
        model_utterance: str,
        child_response: str,
        setup: ScenarioSetup,
    ) -> PedagogicalContext:
        """
        Analyze an exchange to extract pedagogical context.

        Args:
            model_utterance: What the model said (question/statement)
            child_response: How the child responded
            setup: Scenario setup with object, concept, age

        Returns:
            PedagogicalContext with extracted information
        """
        prompt = ANALYZER_PROMPT.format(
            object_name=setup.object_name,
            key_concept=setup.key_concept,
            age=setup.age,
            model_utterance=model_utterance,
            child_response=child_response,
        )

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,  # Low temperature for consistent extraction
            },
        )

        try:
            data = json.loads(response.text)
            return PedagogicalContext(
                question_type=QuestionType(data["question_type"]),
                question_intent=data["question_intent"],
                target_knowledge=data["target_knowledge"],
                child_response_type=ResponseType(data["child_response_type"]),
                knowledge_gap=data["knowledge_gap"],
                ideal_next_action=data["ideal_next_action"],
                acceptable_actions=data.get("acceptable_actions", []),
                unacceptable_actions=data.get("unacceptable_actions", []),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Return a default context if parsing fails
            return PedagogicalContext(
                question_type=QuestionType.OPEN,
                question_intent="Unable to determine intent",
                target_knowledge="Unable to determine target knowledge",
                child_response_type=ResponseType.ANSWER,
                knowledge_gap="Unable to determine knowledge gap",
                ideal_next_action="Continue with appropriate scaffolding",
                acceptable_actions=[],
                unacceptable_actions=[],
            )

    def analyze_sync(
        self,
        model_utterance: str,
        child_response: str,
        setup: ScenarioSetup,
    ) -> PedagogicalContext:
        """
        Synchronous version of analyze.

        Args:
            model_utterance: What the model said
            child_response: How the child responded
            setup: Scenario setup

        Returns:
            PedagogicalContext with extracted information
        """
        prompt = ANALYZER_PROMPT.format(
            object_name=setup.object_name,
            key_concept=setup.key_concept,
            age=setup.age,
            model_utterance=model_utterance,
            child_response=child_response,
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        try:
            data = json.loads(response.text)
            return PedagogicalContext(
                question_type=QuestionType(data["question_type"]),
                question_intent=data["question_intent"],
                target_knowledge=data["target_knowledge"],
                child_response_type=ResponseType(data["child_response_type"]),
                knowledge_gap=data["knowledge_gap"],
                ideal_next_action=data["ideal_next_action"],
                acceptable_actions=data.get("acceptable_actions", []),
                unacceptable_actions=data.get("unacceptable_actions", []),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return PedagogicalContext(
                question_type=QuestionType.OPEN,
                question_intent="Unable to determine intent",
                target_knowledge="Unable to determine target knowledge",
                child_response_type=ResponseType.ANSWER,
                knowledge_gap="Unable to determine knowledge gap",
                ideal_next_action="Continue with appropriate scaffolding",
                acceptable_actions=[],
                unacceptable_actions=[],
            )
