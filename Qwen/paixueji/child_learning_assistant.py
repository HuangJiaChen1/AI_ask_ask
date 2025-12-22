import json
import os
from enum import Enum
from openai import OpenAI


class ConversationState(Enum):
    """Tracks the current state of the conversation to enforce behavioral rules."""
    INITIAL_QUESTION = "initial"
    AWAITING_ANSWER = "awaiting"
    GIVING_HINT_1 = "hint1"
    GIVING_HINT_2 = "hint2"
    REVEALING_ANSWER = "reveal"
    CELEBRATING = "celebrating"
    MASTERY_ACHIEVED = "mastery"


class ChildLearningAssistant:
    """
    An educational assistant for young children that asks suggestive questions
    about objects to encourage learning and curiosity.
    """

    def __init__(self, config_path="config.json"):
        """Initialize the assistant with configuration."""
        self.config = self._load_config(config_path)
        self.client = OpenAI(
            api_key=self.config["qwen_api_key"],
            base_url=self.config["api_base_url"]
        )
        self.conversation_history = []
        self.current_object = None
        self.current_category = None
        self.state = ConversationState.INITIAL_QUESTION
        self.stuck_count = 0
        self.question_count = 0
        self.correct_count = 0
        self.mastery_threshold = 4  # Number of correct answers needed for mastery
        self.current_main_question = None  # Track the current main question being asked
        self.expected_answer = None  # The answer we're looking for (used for hint generation)
        self.prompts = None  # Will be loaded from database

    def _load_config(self, config_path):
        """Load configuration from JSON file."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            config = json.load(f)

        if config["qwen_api_key"] == "YOUR_API_KEY_HERE":
            raise ValueError("Please set your API key in config.json")

        return config

    def _load_prompts_from_db(self):
        """Load prompts from database."""
        import database
        self.prompts = database.get_prompts()
        if self.prompts is None:
            raise Exception("No prompts found in database. Please run init_db() first.")

    def start_new_object(self, object_name, category, system_prompt, user_prompt_template):
        """
        Start a new learning session with an object, using provided prompts.

        :param object_name: The name of the object to learn about.
        :param category: The category of the object.
        :param system_prompt: The system prompt to guide the assistant's personality.
        :param user_prompt_template: The template for the initial user prompt, with placeholders.
        """
        # Load prompts from database if not already loaded
        if self.prompts is None:
            self._load_prompts_from_db()

        self.current_object = object_name
        self.current_category = category
        self.conversation_history = []
        self.state = ConversationState.INITIAL_QUESTION
        self.stuck_count = 0
        self.question_count = 0
        self.correct_count = 0

        # Format the user prompt with the specific object and category
        final_user_prompt = user_prompt_template.format(
            object_name=object_name,
            category=category
        )

        # Add system prompt and the formatted user prompt to history
        self.conversation_history.append({
            "role": "system",
            "content": system_prompt
        })

        self.conversation_history.append({
            "role": "user",
            "content": final_user_prompt
        })

        # Get the first question from the model (with structured JSON to extract main_question)
        response = self._get_initial_question()
        return response

    def _get_initial_question(self):
        """Get the initial question with structured output to capture main_question and expected_answer."""
        # Use prompt from database
        initial_prompt = self.prompts['initial_question_prompt'].format(
            object_name=self.current_object
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.config["model_name"],
                messages=self.conversation_history + [{"role": "user", "content": initial_prompt}],
                response_format={"type": "json_object"},
                temperature=self.config["temperature"],
                max_tokens=self.config["max_tokens"]
            )

            response_text = completion.choices[0].message.content
            structured = json.loads(response_text)

            # Extract main_question, expected_answer, and full_response
            self.current_main_question = structured.get("main_question", "")
            self.expected_answer = structured.get("expected_answer", "")
            full_response = structured.get("full_response", "Let's explore together!")

            # Add only the full response to conversation history (what user sees)
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response
            })

            return full_response

        except Exception as e:
            print(f"[Error getting initial question]: {e}")
            return self._get_model_response()  # Fallback

    def continue_conversation(self, child_response):
        """
        Continue the conversation based on the child's response using state machine.

        Returns:
            tuple: (response_text, mastery_achieved, is_correct, is_neutral_state)
        """
        # Load prompts from database if not already loaded
        if self.prompts is None:
            self._load_prompts_from_db()

        # Add the child's response to history
        self.conversation_history.append({
            "role": "user",
            "content": child_response
        })

        # Update state based on child's response
        self._update_state(child_response)

        # This will be set by the response generation logic
        is_correct_answer = False

        # Get the model's response based on current state
        if self.state in [ConversationState.GIVING_HINT_1, ConversationState.GIVING_HINT_2]:
            response = self._generate_hint_only()
        elif self.state == ConversationState.REVEALING_ANSWER:
            response = self._generate_reveal_answer()
        else:
            # Normal response for answers/celebrating
            response, is_correct_answer = self._get_model_response_with_validation()

        # Track correct answers
        if is_correct_answer:
            self.correct_count += 1

        is_neutral_state = self.state in [
            ConversationState.GIVING_HINT_1,
            ConversationState.GIVING_HINT_2,
            ConversationState.REVEALING_ANSWER
        ]

        # Check for mastery
        mastery_achieved = False
        if self.correct_count >= self.mastery_threshold and self.state != ConversationState.MASTERY_ACHIEVED:
            self.state = ConversationState.MASTERY_ACHIEVED
            mastery_achieved = True
            response = f"🎉 WOW! You have now mastered the {self.current_object}! Congratulations! You answered {self.correct_count} questions correctly! You're amazing! 🎉"
            # Return early for mastery. The other flags aren't relevant for the final message.
            return response, mastery_achieved, False, True

        return response, mastery_achieved, is_correct_answer, is_neutral_state

    def _update_state(self, child_response):
        """Update conversation state based on child's response."""
        # Use LLM to determine if child is stuck (more robust than keyword matching)
        is_stuck = self._is_child_stuck(child_response)

        if is_stuck:
            self.stuck_count += 1
        else:
            # Child gave an answer attempt, reset stuck count
            self.stuck_count = 0

        # State transitions - use cascading if statements to allow multiple transitions
        # First, handle special case: initial question
        if self.state == ConversationState.INITIAL_QUESTION:
            self.state = ConversationState.AWAITING_ANSWER
            # Don't return - continue to check if we should immediately transition to hint state

        # Now handle the current state (after any initial transition)
        if self.state == ConversationState.AWAITING_ANSWER:
            if self.stuck_count >= 2:
                self.state = ConversationState.GIVING_HINT_2
            elif self.stuck_count == 1:
                self.state = ConversationState.GIVING_HINT_1
            elif self.stuck_count == 0 and not is_stuck:
                # Child answered, celebrate and move to next question
                self.state = ConversationState.CELEBRATING

        elif self.state == ConversationState.GIVING_HINT_1:
            if self.stuck_count >= 2:
                self.state = ConversationState.GIVING_HINT_2
            elif self.stuck_count == 0:
                # They figured it out after hint 1
                self.state = ConversationState.CELEBRATING

        elif self.state == ConversationState.GIVING_HINT_2:
            if self.stuck_count >= 3:
                # After 2 hints and still stuck, reveal the answer
                self.state = ConversationState.REVEALING_ANSWER
            elif self.stuck_count == 0:
                # They figured it out after hint 2
                self.state = ConversationState.CELEBRATING

        elif self.state == ConversationState.REVEALING_ANSWER:
            # After revealing, move to next question
            self.state = ConversationState.CELEBRATING
            self.stuck_count = 0

        elif self.state == ConversationState.CELEBRATING:
            # After celebration, ask next question
            self.state = ConversationState.AWAITING_ANSWER
            self.question_count += 1

    def _generate_hint_only(self):
        """
        Generate a hint by asking a DIFFERENT, easier question that has the same answer.
        This creative approach helps children connect concepts across different topics.
        """
        # Check if we have both the question and expected answer
        if not self.current_main_question or not self.expected_answer:
            return "That's okay! Let's think about this together..."

        original_question = self.current_main_question
        answer = self.expected_answer

        # Determine hint strength based on state
        if self.state == ConversationState.GIVING_HINT_1:
            hint_level = "first"
            difficulty_instruction = "MODERATELY easier - something the child might know from everyday experience"
        else:  # GIVING_HINT_2
            hint_level = "second"
            difficulty_instruction = "MUCH easier - something very obvious and simple"

        # Use prompt from database
        hint_prompt = self.prompts['hint_prompt'].format(
            original_question=original_question,
            answer=answer,
            difficulty_instruction=difficulty_instruction
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.config["model_name"],
                messages=[
                    {"role": "system", "content": "You create alternative questions that help children discover answers. You NEVER reveal answers directly. You ONLY ask questions. You're creative and connect concepts across different topics."},
                    {"role": "user", "content": hint_prompt}
                ],
                temperature=0.7,  # Slightly lower for better instruction following
                max_tokens=150
            )

            hint_response = completion.choices[0].message.content.strip()

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": hint_response
            })

            return hint_response

        except Exception as e:
            print(f"[Error generating hint]: {e}")
            return "That's okay! Think about what you already know, and take a guess!"

    def _generate_reveal_answer(self):
        """
        Reveal the answer after multiple hints, then ask a new question.
        """
        # Use the stored main question
        if not self.current_main_question:
            return "Let me tell you something cool..."

        last_question = self.current_main_question

        # Use prompt from database
        reveal_prompt = self.prompts['reveal_prompt'].format(
            last_question=last_question
        )

        try:
            completion = self.client.chat.completions.create(
                model=self.config["model_name"],
                messages=[
                    {"role": "system", "content": f"You're teaching a child about {self.current_object}. Be warm and encouraging!"},
                    {"role": "user", "content": reveal_prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )

            reveal_response = completion.choices[0].message.content.strip()

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": reveal_response
            })

            return reveal_response

        except Exception as e:
            print(f"[Error revealing answer]: {e}")
            return f"That's okay! Let me tell you about {self.current_object}..."

    def _get_last_question_asked(self):
        """
        Extract the main question the assistant asked.

        Strategy: Get the FIRST substantial question (usually the main one),
        not the last (which is often a rhetorical example).
        """
        # Look backwards through conversation history for last assistant message
        for msg in reversed(self.conversation_history):
            if msg["role"] == "assistant":
                content = msg["content"]

                # Split by question marks
                sentences = content.split('?')

                if len(sentences) <= 1:
                    # No question mark found, return whole content
                    return content

                # Find all questions (segments ending with ?)
                questions = []
                for i, segment in enumerate(sentences[:-1]):  # Exclude last element (after final ?)
                    # Clean up the segment (remove leading punctuation/whitespace)
                    question = segment.strip()

                    # Get the last sentence from this segment (in case there's a period)
                    if '.' in question or '!' in question:
                        # Split by . or ! and take the last part
                        parts = question.replace('!', '.').split('.')
                        question = parts[-1].strip()

                    if question and len(question) > 10:  # Ignore very short questions
                        questions.append(question + "?")

                if not questions:
                    return content

                # Return the LONGEST question (usually the main one, not rhetorical examples)
                main_question = max(questions, key=len)

                print(f"[Extracted main question]: {main_question[:80]}...")
                return main_question

        return None

    def _is_child_stuck(self, child_response):
        """
        Use LLM to determine if child is stuck/confused or attempting to answer.
        More robust than hardcoded keyword matching.
        """
        # Quick classification prompt
        classification_prompt = f"""A child was asked a question and responded: "{child_response}"

Is the child:
A) Stuck/confused/doesn't know (e.g., "I don't know", "what?", "huh?", "dunno", "nope", "idk", "help", "?")
B) Attempting to answer (even if wrong - e.g., "red", "on trees", "yes", "5", "it flies")

Respond with ONLY the letter A or B."""

        try:
            completion = self.client.chat.completions.create(
                model=self.config.get("classification_model", self.config["model_name"]),
                messages=[
                    {"role": "user", "content": classification_prompt}
                ],
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=10
            )

            result = completion.choices[0].message.content.strip().upper()

            # Return True if stuck (A), False if attempting (B)
            return result.startswith("A")

        except Exception as e:
            # Fallback to simple keyword detection if LLM fails
            print(f"[Warning] LLM classification failed, using fallback: {e}")
            response_lower = child_response.lower().strip()
            stuck_keywords = [
                "don't know", "dont know", "idk", "dunno", "not sure",
                "what", "huh", "nope", "no idea", "help", "?"
            ]
            return any(keyword in response_lower for keyword in stuck_keywords)

    def _get_model_response_with_validation(self):
        """
        Get response from model. (Validation removed - hints handled separately)

        Returns:
            tuple: (response_text, is_correct)
        """
        try:
            # Get structured response from model
            structured_response = self._get_structured_response()

            # Extract is_correct flag for mastery tracking
            is_correct = structured_response.get("is_correct", False)

            # Extract and store main_question and expected_answer for future hints
            main_question = structured_response.get("main_question", "")
            if main_question:
                self.current_main_question = main_question

            expected_answer = structured_response.get("expected_answer", "")
            if expected_answer:
                self.expected_answer = expected_answer

            # Build final response text
            response = self._build_response_from_structured(structured_response)

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": response
            })

            return response, is_correct

        except Exception as e:
            print(f"[Error getting response]: {str(e)}")
            # Fallback to simple response
            fallback_response = self._get_model_response()
            return fallback_response, False

    def _get_structured_response(self):
        """Get structured JSON response from the model based on current state."""
        # Add state-specific instruction
        state_instruction = self._get_state_instruction()

        messages_with_instruction = self.conversation_history + [
            {
                "role": "system",
                "content": state_instruction
            }
        ]

        try:
            completion = self.client.chat.completions.create(
                model=self.config["model_name"],
                messages=messages_with_instruction,
                response_format={"type": "json_object"},
                temperature=self.config["temperature"],
                max_tokens=self.config["max_tokens"]
            )

            response_text = completion.choices[0].message.content
            structured = json.loads(response_text)
            return structured

        except json.JSONDecodeError:
            # Fallback: try to extract JSON from response
            print("[Warning] Failed to parse JSON, using fallback")
            return {
                "type": "fallback",
                "message": response_text,
                "should_give_answer": False
            }

    def _get_state_instruction(self):
        """Get specific instructions based on current conversation state."""
        # Load state instructions from database
        import json
        state_instructions_data = json.loads(self.prompts['state_instructions_json'])
        base_format = state_instructions_data['base_format']

        state_instructions = {
            ConversationState.INITIAL_QUESTION: base_format + "\n" + state_instructions_data['initial_question'],
            ConversationState.AWAITING_ANSWER: base_format + "\n" + state_instructions_data['awaiting_answer'],
            ConversationState.CELEBRATING: base_format + "\n" + state_instructions_data['celebrating']
        }

        # Note: GIVING_HINT_1, GIVING_HINT_2, REVEALING_ANSWER states are handled by dedicated functions
        return state_instructions.get(self.state, base_format)

    def _build_response_from_structured(self, structured_response):
        """Build natural language response from structured JSON."""
        if structured_response.get("type") == "fallback":
            return structured_response.get("message", "Let's continue learning!")

        parts = []

        reaction = structured_response.get("reaction", "")
        if reaction:
            parts.append(reaction)

        next_question = structured_response.get("next_question", "")
        if next_question:
            parts.append(next_question)

        response = " ".join(parts)
        return response if response else "Let's keep exploring!"

    def _get_model_response(self):
        """Get response from the Qwen model (fallback for initial question)."""
        try:
            completion = self.client.chat.completions.create(
                model=self.config["model_name"],
                messages=self.conversation_history,
                temperature=self.config["temperature"],
                max_tokens=self.config["max_tokens"]
            )

            assistant_message = completion.choices[0].message.content

            # Add assistant's response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            return assistant_message

        except Exception as e:
            return f"Error communicating with the model: {str(e)}"

    def get_conversation_history(self):
        """Get the full conversation history."""
        return self.conversation_history

    def reset(self):
        """Reset the conversation."""
        self.conversation_history = []
        self.current_object = None
        self.current_category = None
        self.state = ConversationState.INITIAL_QUESTION
        self.stuck_count = 0
        self.question_count = 0
        self.correct_count = 0
