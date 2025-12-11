import json
import os
import re
from enum import Enum
import requests


def remove_emojis(text):
    """
    Remove emojis from text for clean TTS output.

    Args:
        text: Input text that may contain emojis

    Returns:
        Text with all emojis removed
    """
    # Emoji pattern - covers most common emojis
    emoji_pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001F900-\U0001F9FF"  # supplemental symbols
        u"\U0001FA00-\U0001FA6F"  # extended symbols
        u"\U00002600-\U000026FF"  # misc symbols
        u"\U00002700-\U000027BF"
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text).strip()


def extract_json_from_response(text):
    """
    Extract JSON from a response that might contain markdown code blocks or extra text.

    Handles cases like:
    - ```json\n{...}\n```
    - Sure, here's the JSON: {...}
    - {...} (plain JSON)
    - Text before {JSON} text after
    """
    if not text or not text.strip():
        print("[DEBUG extract_json] Empty or whitespace-only text received")
        return "{}"  # Return empty JSON object instead of None

    text = text.strip()

    # Try to find JSON in markdown code blocks first (greedy to capture full JSON)
    code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        extracted = match.group(1).strip()
        print(f"[DEBUG extract_json] Found JSON in code block: {extracted[:100]}...")
        # Validate it's parseable
        try:
            json.loads(extracted)
            return extracted
        except:
            print(f"[DEBUG extract_json] Code block JSON invalid, trying other methods...")

    # Try to find a balanced JSON object (matching braces)
    # Start from first { and find its matching }
    first_brace = text.find('{')
    if first_brace != -1:
        brace_count = 0
        for i in range(first_brace, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    # Found matching closing brace
                    extracted = text[first_brace:i+1]
                    print(f"[DEBUG extract_json] Found balanced JSON: {extracted[:100]}...")
                    # Validate it's parseable
                    try:
                        json.loads(extracted)
                        return extracted
                    except Exception as e:
                        print(f"[DEBUG extract_json] Balanced JSON invalid: {e}")
                        break

    # Try greedy match from first { to last } as fallback
    json_pattern = r'\{.*\}'
    match = re.search(json_pattern, text, re.DOTALL)
    if match:
        extracted = match.group(0).strip()
        print(f"[DEBUG extract_json] Found JSON (greedy): {extracted[:100]}...")
        return extracted

    # If nothing found, check if it's already valid JSON
    try:
        json.loads(text)
        print(f"[DEBUG extract_json] Text is already valid JSON")
        return text
    except:
        pass

    # Last resort: return original text for error handling
    print(f"[DEBUG extract_json] No JSON found, returning original: {text[:100]}...")
    return text


class ConversationState(Enum):
    """Tracks the current state of the conversation to enforce behavioral rules."""
    INITIAL_QUESTION = "initial"
    AWAITING_ANSWER = "awaiting"
    GIVING_HINT_1 = "hint1"
    GIVING_HINT_2 = "hint2"
    REVEALING_ANSWER = "reveal"
    RECONNECTING = "reconnecting"  # New state: reconnect hint answer back to original question
    CELEBRATING = "celebrating"
    MASTERY_ACHIEVED = "mastery"


class ChildLearningAssistant:
    """
    An educational assistant for young children that asks suggestive questions
    about objects to encourage learning and curiosity.
    """

    def __init__(self, config_path="config.json", age_prompts_path="age_prompts.json", category_prompts_path="category_prompts.json"):
        """Initialize the assistant with configuration."""
        self.config = self._load_config(config_path)
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
        self.last_audio_output = None  # Clean text for TTS (without emojis)

        # Track original question before hints (for reconnecting after hint is answered)
        self.question_before_hint = None  # The original question that needed hints
        self.answer_before_hint = None  # The expected answer to the original question

        # Load age and category prompts
        self.age_prompts = self._load_age_prompts(age_prompts_path)
        self.category_prompts = self._load_category_prompts(category_prompts_path)

        # Load hardcoded prompts
        import prompts as prompts_module
        self.prompts = prompts_module.get_prompts()

    def _load_config(self, config_path):
        """Load configuration from JSON file."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            config = json.load(f)

        if config["gemini_api_key"] == "YOUR_GEMINI_API_KEY_HERE":
            raise ValueError("Please set your API key in config.json")

        return config

    def _load_age_prompts(self, age_prompts_path):
        """Load age-based prompts from JSON file."""
        if not os.path.exists(age_prompts_path):
            print(f"[WARNING] Age prompts file not found: {age_prompts_path}")
            return None

        with open(age_prompts_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_category_prompts(self, category_prompts_path):
        """Load category-based prompts from JSON file."""
        if not os.path.exists(category_prompts_path):
            print(f"[WARNING] Category prompts file not found: {category_prompts_path}")
            return None

        with open(category_prompts_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _get_age_prompt(self, age):
        """
        Get the appropriate age-based prompt based on child's age.

        Args:
            age: Integer age of the child

        Returns:
            Age-appropriate prompt string
        """
        if not self.age_prompts:
            return ""

        age_groups = self.age_prompts.get('age_groups', {})

        # Determine age group
        if 3 <= age <= 4:
            return age_groups.get('3-4', {}).get('prompt', '')
        elif 5 <= age <= 6:
            return age_groups.get('5-6', {}).get('prompt', '')
        elif 7 <= age <= 8:
            return age_groups.get('7-8', {}).get('prompt', '')
        else:
            # Default to middle group if age is outside range
            return age_groups.get('5-6', {}).get('prompt', '')

    def _get_category_prompt(self, level1_category=None, level2_category=None):
        """
        Get and combine category-based prompts.
        If level1 is not provided, automatically looks up parent from level2.
        If a category is not found in the database, it will be skipped gracefully.

        Args:
            level1_category: Most abstract category (e.g., 'animals', 'plants') - optional if level2 provided
            level2_category: Medium abstract category (e.g., 'vertebrates', 'fresh_ingredients')

        Returns:
            Combined category prompt string (empty if categories not found)
        """
        if not self.category_prompts:
            print("[INFO] Category prompts database not loaded. Using base prompts only.")
            return ""

        prompts = []
        categories_found = []
        categories_missing = []

        # If level2 is provided but not level1, auto-find parent
        if level2_category and not level1_category:
            level2_data = self.category_prompts.get('level2_categories', {}).get(level2_category, {})
            if level2_data:
                level1_category = level2_data.get('parent')
                if level1_category:
                    print(f"[INFO] Auto-detected Level 1 category '{level1_category}' from Level 2 '{level2_category}'")

        # Get level 1 prompt
        if level1_category:
            level1_data = self.category_prompts.get('level1_categories', {}).get(level1_category, {})
            level1_prompt = level1_data.get('prompt', '').strip()
            if level1_prompt:
                prompts.append(level1_prompt)
                categories_found.append(f"Level 1: {level1_category}")
            else:
                categories_missing.append(f"Level 1: {level1_category}")

        # Get level 2 prompt
        if level2_category:
            level2_data = self.category_prompts.get('level2_categories', {}).get(level2_category, {})
            level2_prompt = level2_data.get('prompt', '').strip()
            if level2_prompt:
                prompts.append(level2_prompt)
                categories_found.append(f"Level 2: {level2_category}")
            else:
                categories_missing.append(f"Level 2: {level2_category}")

        # Log what was found/missing
        if categories_found:
            print(f"[INFO] Using category prompts: {', '.join(categories_found)}")
        if categories_missing:
            print(f"[WARNING] Categories not found in database: {', '.join(categories_missing)}")
            print(f"[INFO] Continuing with available prompts. Add these categories to category_prompts.json if needed.")

        # Combine with newlines
        return '\n'.join(prompts) if prompts else ""

    def _call_gemini_api(self, messages, response_format=None, temperature=None, max_tokens=None):
        """
        Call Gemini API using requests.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            response_format: Optional dict with {"type": "json_object"} for JSON mode
            temperature: Optional temperature override
            max_tokens: Optional max_tokens override

        Returns:
            The response content as string
        """
        headers = {
            "Authorization": f"Bearer {self.config['gemini_api_key']}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.config["model_name"],
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config["temperature"],
            "max_tokens": max_tokens if max_tokens is not None else self.config["max_tokens"]
        }

        # Add JSON mode if requested
        if response_format and response_format.get("type") == "json_object":
            # For Gemini, we need to explicitly request JSON
            # Add a VERY strong JSON instruction to the last message
            modified_messages = messages.copy()
            if modified_messages:
                last_msg = modified_messages[-1].copy()
                last_msg["content"] = last_msg["content"] + """

CRITICAL INSTRUCTIONS:
1. Respond with ONLY valid JSON
2. NO text before the JSON
3. NO text after the JSON
4. NO markdown code blocks (no ```)
5. NO explanations or reasoning
6. Start directly with { and end directly with }
7. Your ENTIRE response must be parseable JSON

Example of CORRECT response:
{"key": "value"}

Example of WRONG response:
Here's the JSON: {"key": "value"}
```json
{"key": "value"}
```

Your response:"""
                modified_messages[-1] = last_msg
            payload["messages"] = modified_messages

        try:
            response = requests.post(
                self.config["api_base_url"],
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            response_data = response.json()

            # Debug: Print response structure
            print(f"[DEBUG] API Response keys: {response_data.keys()}")

            # Check for truncation
            finish_reason = response_data["choices"][0].get("finish_reason")
            if finish_reason == "MAX_TOKENS":
                print(f"[WARNING] Response was truncated due to MAX_TOKENS limit!")
                print(f"[WARNING] Token usage: {response_data.get('usage', {})}")

            # Validate response structure
            if "choices" not in response_data or not response_data["choices"]:
                print(f"[ERROR] Full API response: {json.dumps(response_data, indent=2)}")
                raise Exception(f"Invalid API response structure: missing 'choices'")

            content = response_data["choices"][0]["message"]["content"]

            # Validate content is not empty
            if not content or not content.strip():
                print(f"[ERROR] Empty content. Full response: {json.dumps(response_data, indent=2)}")
                raise Exception("API returned empty content")

            # Check if content seems truncated
            if len(content) > 0 and not content.rstrip().endswith(('.', '!', '?', '"', "'")):
                print(f"[WARNING] Response may be truncated (doesn't end with punctuation): '{content[-50:]}'")

            return content

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Request failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[ERROR] Response status: {e.response.status_code}")
                print(f"[ERROR] Response body: {e.response.text[:500]}")
            raise Exception(f"Gemini API error: {str(e)}")
        except KeyError as e:
            print(f"[ERROR] Missing key in response: {str(e)}")
            print(f"[ERROR] Full response: {json.dumps(response_data, indent=2)}")
            raise Exception(f"Unexpected API response format: missing key {str(e)}")

    def start_new_object(self, object_name, category, system_prompt, user_prompt_template,
                         age=None, level1_category=None, level2_category=None, level3_category=None):
        """
        Start a new learning session with an object, using provided prompts.

        :param object_name: The name of the object to learn about.
        :param category: The category of the object (for backward compatibility).
        :param system_prompt: The system prompt to guide the assistant's personality.
        :param user_prompt_template: The template for the initial user prompt, with placeholders.
        :param age: Optional child's age (3-8) for age-appropriate questioning.
        :param level1_category: Optional most abstract category (e.g., 'animals', 'plants').
        :param level2_category: Optional medium abstract category (e.g., 'spinal_animals').
        :param level3_category: Optional most exact category (e.g., 'insects', 'mammals').
        """
        self.current_object = object_name
        self.current_category = category
        self.conversation_history = []
        self.state = ConversationState.INITIAL_QUESTION
        self.stuck_count = 0
        self.question_count = 0
        self.correct_count = 0

        # Build enhanced system prompt by combining base + age + category prompts
        enhanced_system_prompt = system_prompt

        # Add age-based prompt
        if age is not None:
            age_prompt = self._get_age_prompt(age)
            if age_prompt:
                enhanced_system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"
                print(f"[INFO] Using age-appropriate prompting for age: {age}")
            else:
                print(f"[WARNING] No age prompt found for age {age}. Using base prompts.")
        else:
            print("[INFO] No age specified. Using base prompts without age-specific guidance.")

        # Add category-based prompts
        if level1_category or level2_category:
            category_prompt = self._get_category_prompt(level1_category, level2_category)
            if category_prompt:
                enhanced_system_prompt += f"\n\nCATEGORY-SPECIFIC GUIDANCE:\n{category_prompt}"
            else:
                print("[INFO] No category prompts found or loaded. Using base prompts only.")
        else:
            print("[INFO] No categories specified. Using base prompts without category-specific guidance.")

        # Format the user prompt with the specific object and category
        final_user_prompt = user_prompt_template.format(
            object_name=object_name,
            category=category
        )

        # Add enhanced system prompt and the formatted user prompt to history
        self.conversation_history.append({
            "role": "system",
            "content": enhanced_system_prompt
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
            print(f"[DEBUG] Requesting initial question for: {self.current_object}")
            response_text = self._call_gemini_api(
                messages=self.conversation_history + [{"role": "user", "content": initial_prompt}],
                response_format={"type": "json_object"},
                max_tokens=2000  # Increased to account for Gemini's reasoning tokens
            )

            print(f"[DEBUG] Got response, length: {len(response_text) if response_text else 0}")
            print(f"[DEBUG] First 200 chars: {response_text[:200] if response_text else 'EMPTY'}")

            # Extract JSON from response (handles markdown code blocks)
            json_text = extract_json_from_response(response_text)
            print(f"[DEBUG] Extracted JSON, length: {len(json_text) if json_text else 0}")

            structured = json.loads(json_text)
            print(f"[DEBUG] Parsed JSON successfully, keys: {structured.keys()}")

            # Extract main_question, expected_answer, and full_response
            self.current_main_question = structured.get("main_question", "")
            self.expected_answer = structured.get("expected_answer", "")
            full_response = structured.get("full_response", "Let's explore together!")

            # Extract audio_output or create clean version
            self.last_audio_output = structured.get("audio_output")
            if not self.last_audio_output:
                self.last_audio_output = remove_emojis(full_response)

            print(f"[DEBUG] Full response: {full_response[:100]}...")

            # Add only the full response to conversation history (what user sees)
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response
            })

            return full_response

        except Exception as e:
            print(f"[Error getting initial question]: {e}")
            import traceback
            traceback.print_exc()
            # Set fallback values to prevent None errors
            self.current_main_question = f"Can you tell me about {self.current_object}?"
            self.expected_answer = f"Information about {self.current_object}"
            return self._get_model_response()  # Fallback

    def continue_conversation(self, child_response):
        """
        Continue the conversation based on the child's response using state machine.

        Returns:
            tuple: (response_text, mastery_achieved, is_correct, is_neutral_state, audio_output)
        """
        print(f"[DEBUG] State BEFORE update: {self.state.value}, stuck_count: {self.stuck_count}")

        # Add the child's response to history
        self.conversation_history.append({
            "role": "user",
            "content": child_response
        })

        # Update state based on child's response
        self._update_state(child_response)

        print(f"[DEBUG] State AFTER update: {self.state.value}, stuck_count: {self.stuck_count}")

        # This will be set by the response generation logic
        is_correct_answer = False

        # Get the model's response based on current state
        if self.state in [ConversationState.GIVING_HINT_1, ConversationState.GIVING_HINT_2]:
            print(f"[DEBUG] Calling _generate_hint_only() for state: {self.state.value}")
            response = self._generate_hint_only()
            # For hints without structured JSON, create clean audio version
            self.last_audio_output = remove_emojis(response)
        elif self.state == ConversationState.REVEALING_ANSWER:
            print(f"[DEBUG] Calling _generate_reveal_answer()")
            response = self._generate_reveal_answer()
            # For reveal without structured JSON, create clean audio version
            self.last_audio_output = remove_emojis(response)
        elif self.state == ConversationState.RECONNECTING:
            print(f"[DEBUG] Calling _generate_reconnect_response()")
            response = self._generate_reconnect_response()
            # For reconnect without structured JSON, create clean audio version
            self.last_audio_output = remove_emojis(response)
        else:
            print(f"[DEBUG] Calling _get_model_response_with_validation() for state: {self.state.value}")
            # Normal response for answers/celebrating
            response, is_correct_answer = self._get_model_response_with_validation()
            # audio_output is set inside _get_model_response_with_validation()

        # Track correct answers
        if is_correct_answer:
            self.correct_count += 1

        is_neutral_state = self.state in [
            ConversationState.GIVING_HINT_1,
            ConversationState.GIVING_HINT_2,
            ConversationState.REVEALING_ANSWER,
            ConversationState.RECONNECTING
        ]

        # Check for mastery
        mastery_achieved = False
        if self.correct_count >= self.mastery_threshold and self.state != ConversationState.MASTERY_ACHIEVED:
            self.state = ConversationState.MASTERY_ACHIEVED
            mastery_achieved = True
            response = f"🎉 WOW! You have now mastered the {self.current_object}! Congratulations! You answered {self.correct_count} questions correctly! You're amazing! 🎉"
            # Create clean audio version for mastery message
            self.last_audio_output = f"WOW! You have now mastered the {self.current_object}! Congratulations! You answered {self.correct_count} questions correctly! You're amazing!"
            # Return early for mastery. The other flags aren't relevant for the final message.
            return response, mastery_achieved, False, True, self.last_audio_output

        return response, mastery_achieved, is_correct_answer, is_neutral_state, self.last_audio_output

    def _update_state(self, child_response):
        """Update conversation state based on child's response."""
        # Use LLM to determine if child is stuck (more robust than keyword matching)
        is_stuck = self._is_child_stuck(child_response)
        print(f"[DEBUG] is_stuck detection: {is_stuck} for response: '{child_response}'")

        if is_stuck:
            self.stuck_count += 1
            print(f"[DEBUG] Child is stuck, stuck_count now: {self.stuck_count}")
        else:
            # Child gave an answer attempt, reset stuck count
            print(f"[DEBUG] Child attempting answer, resetting stuck_count to 0")
            self.stuck_count = 0

        # State transitions - use cascading if statements to allow multiple transitions
        # First, handle special cases that transition to AWAITING_ANSWER
        # These need to be checked BEFORE the main if-elif chain so we can cascade
        if self.state == ConversationState.INITIAL_QUESTION:
            print(f"[DEBUG] Transitioning from INITIAL_QUESTION to AWAITING_ANSWER")
            self.state = ConversationState.AWAITING_ANSWER
            # Don't return - continue to check if we should immediately transition to hint state

        if self.state == ConversationState.CELEBRATING:
            # After celebration, ask next question
            print(f"[DEBUG] Transitioning from CELEBRATING to AWAITING_ANSWER")
            self.state = ConversationState.AWAITING_ANSWER
            self.question_count += 1
            # Don't return - continue to check if we should immediately transition to hint state

        if self.state == ConversationState.RECONNECTING:
            # After reconnecting hint back to original question, await answer to original question
            print(f"[DEBUG] After reconnect, transitioning to AWAITING_ANSWER")
            self.state = ConversationState.AWAITING_ANSWER
            # Clear the saved original question since we've reconnected
            self.question_before_hint = None
            self.answer_before_hint = None
            # Don't return - continue to check if we should immediately transition to hint state

        # Now handle the current state (after any initial transition)
        if self.state == ConversationState.AWAITING_ANSWER:
            if self.stuck_count >= 2:
                print(f"[DEBUG] stuck_count={self.stuck_count}, transitioning to GIVING_HINT_2")
                # Save original question before giving second hint
                if not self.question_before_hint:
                    self.question_before_hint = self.current_main_question
                    self.answer_before_hint = self.expected_answer
                    question_preview = self.question_before_hint[:50] if self.question_before_hint else "None"
                    print(f"[DEBUG] Saved original question: {question_preview}...")
                self.state = ConversationState.GIVING_HINT_2
            elif self.stuck_count == 1:
                print(f"[DEBUG] stuck_count={self.stuck_count}, transitioning to GIVING_HINT_1")
                # Save original question before giving first hint
                self.question_before_hint = self.current_main_question
                self.answer_before_hint = self.expected_answer
                question_preview = self.question_before_hint[:50] if self.question_before_hint else "None"
                print(f"[DEBUG] Saved original question: {question_preview}...")
                self.state = ConversationState.GIVING_HINT_1
            elif self.stuck_count == 0 and not is_stuck:
                # Child answered, celebrate and move to next question
                print(f"[DEBUG] stuck_count=0 and not stuck, transitioning to CELEBRATING")
                self.state = ConversationState.CELEBRATING

        elif self.state == ConversationState.GIVING_HINT_1:
            if self.stuck_count >= 2:
                self.state = ConversationState.GIVING_HINT_2
            elif self.stuck_count == 0:
                # They answered the hint question! Now reconnect back to original question
                print(f"[DEBUG] Answered hint 1 question, transitioning to RECONNECTING")
                self.state = ConversationState.RECONNECTING

        elif self.state == ConversationState.GIVING_HINT_2:
            if self.stuck_count >= 3:
                # After 2 hints and still stuck, reveal the answer
                self.state = ConversationState.REVEALING_ANSWER
            elif self.stuck_count == 0:
                # They answered the hint question! Now reconnect back to original question
                print(f"[DEBUG] Answered hint 2 question, transitioning to RECONNECTING")
                self.state = ConversationState.RECONNECTING

        elif self.state == ConversationState.REVEALING_ANSWER:
            # After revealing, move to next question
            self.state = ConversationState.CELEBRATING
            self.stuck_count = 0

        # Note: CELEBRATING and RECONNECTING are now handled at the top as special cases that cascade to AWAITING_ANSWER

    def _generate_hint_only(self):
        """
        Generate a hint by asking a DIFFERENT, easier question that has the same answer.
        This creative approach helps children connect concepts across different topics.
        """
        # Debug: Check what values we have
        print(f"[DEBUG _generate_hint_only] current_main_question: {repr(self.current_main_question)}")
        print(f"[DEBUG _generate_hint_only] expected_answer: {repr(self.expected_answer)}")

        # Check if we have both the question and expected answer
        if not self.current_main_question or not self.expected_answer:
            print(f"[ERROR] Hint generation failed - missing data!")
            print(f"  current_main_question is None or empty: {not self.current_main_question}")
            print(f"  expected_answer is None or empty: {not self.expected_answer}")
            # This should rarely happen - it means initial question didn't extract properly
            # Return a generic encouraging message but this is NOT ideal
            return "That's okay! Let's think about this together... Can you make a guess?"

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
            hint_response = self._call_gemini_api(
                messages=[
                    {"role": "system", "content": "You create alternative questions that help children discover answers. You NEVER reveal answers directly. You ONLY ask questions. You're creative and connect concepts across different topics."},
                    {"role": "user", "content": hint_prompt}
                ],
                temperature=0.7,
                max_tokens=2000  # Increased to account for Gemini's reasoning tokens
            )

            hint_response = hint_response.strip()

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
            reveal_response = self._call_gemini_api(
                messages=[
                    {"role": "system", "content": f"You're teaching a child about {self.current_object}. Be warm and encouraging!"},
                    {"role": "user", "content": reveal_prompt}
                ],
                temperature=0.7,
                max_tokens=2000  # Increased to account for Gemini's reasoning tokens
            )

            reveal_response = reveal_response.strip()

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": reveal_response
            })

            return reveal_response

        except Exception as e:
            print(f"[Error revealing answer]: {e}")
            return f"That's okay! Let me tell you about {self.current_object}..."

    def _generate_reconnect_response(self):
        """
        Reconnect the child's answer to the hint question back to the original question.
        This bridges the hint answer to help them answer the original question.
        """
        if not self.question_before_hint or not self.answer_before_hint:
            print("[WARNING] No original question saved, cannot reconnect")
            return "That's great! Let's keep learning!"

        original_question = self.question_before_hint
        original_answer = self.answer_before_hint

        # Get the child's last response (their answer to the hint question)
        child_hint_answer = ""
        for msg in reversed(self.conversation_history):
            if msg["role"] == "user":
                child_hint_answer = msg["content"]
                break

        # Get the hint question that was just asked
        hint_question = ""
        for msg in reversed(self.conversation_history):
            if msg["role"] == "assistant":
                hint_question = msg["content"]
                break

        orig_q_preview = original_question[:50] if original_question else "None"
        hint_q_preview = hint_question[:50] if hint_question else "None"
        print(f"[DEBUG] Reconnecting: Original Q: {orig_q_preview}...")
        print(f"[DEBUG] Hint Q: {hint_q_preview}...")
        print(f"[DEBUG] Child's hint answer: {child_hint_answer}")

        reconnect_prompt = f"""The child was struggling with this question: "{original_question}"

You gave them a hint by asking a different, easier question: "{hint_question}"

The child answered: "{child_hint_answer}"

Now you need to:
1. Celebrate their answer to the hint question
2. Use their answer to BRIDGE back to the original question
3. Re-ask the original question with more context that connects to their hint answer

The expected answer to the original question is: "{original_answer}"

Your response should be warm, encouraging, and help them see how their hint answer relates to the original question.

IMPORTANT: End your response by re-asking the original question (or a simpler version of it).

Your response:"""

        try:
            reconnect_response = self._call_gemini_api(
                messages=[
                    {"role": "system", "content": f"You're teaching a child about {self.current_object}. You help them connect ideas across different topics."},
                    {"role": "user", "content": reconnect_prompt}
                ],
                temperature=0.7,
                max_tokens=2000  # Increased to account for Gemini's reasoning tokens
            )

            reconnect_response = reconnect_response.strip()

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": reconnect_response
            })

            # Update current_main_question back to the original question
            self.current_main_question = original_question
            self.expected_answer = original_answer

            return reconnect_response

        except Exception as e:
            print(f"[Error generating reconnect response]: {e}")
            return f"Great thinking! Now, back to our original question: {original_question}"

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
            result = self._call_gemini_api(
                messages=[{"role": "user", "content": classification_prompt}],
                temperature=0.1,
                max_tokens=200  # Further increased - 100 was still not enough for reasoning
            )

            result = result.strip().upper()
            print(f"[DEBUG] LLM classification result: '{result}' for input: '{child_response}'")

            # Return True if stuck (A), False if attempting (B)
            is_stuck = result.startswith("A")
            print(f"[DEBUG] Returning is_stuck={is_stuck}")
            return is_stuck

        except Exception as e:
            # Fallback to simple keyword detection if LLM fails
            print(f"[Warning] LLM classification failed, using fallback: {e}")
            response_lower = child_response.lower().strip()
            stuck_keywords = [
                "don't know", "dont know", "idk", "dunno", "not sure",
                "what", "huh", "nope", "no idea", "help", "?"
            ]
            is_stuck_fallback = any(keyword in response_lower for keyword in stuck_keywords)
            print(f"[DEBUG] Fallback classification: is_stuck={is_stuck_fallback} for '{response_lower}'")
            return is_stuck_fallback

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

            # Extract audio_output or create clean version
            self.last_audio_output = structured_response.get("audio_output")
            if not self.last_audio_output:
                self.last_audio_output = remove_emojis(response)

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
            response_text = self._call_gemini_api(
                messages=messages_with_instruction,
                response_format={"type": "json_object"},
                max_tokens=2000  # Increased to account for Gemini's reasoning tokens
            )

            # Extract JSON from response (handles markdown code blocks)
            json_text = extract_json_from_response(response_text)
            structured = json.loads(json_text)
            return structured

        except json.JSONDecodeError as e:
            # Fallback: when JSON parsing fails completely
            print(f"[Warning] Failed to parse JSON: {e}")
            if 'response_text' in locals():
                print(f"[Debug] Raw response (first 200 chars): {response_text[:200]}...")
            # Return a safe fallback response
            return {
                "reaction": "That's interesting!",
                "next_question": "Let me ask you something else...",
                "is_correct": False,
                "main_question": "",
                "expected_answer": ""
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
        """Get response from the Gemini model (fallback for initial question)."""
        try:
            assistant_message = self._call_gemini_api(
                messages=self.conversation_history
            )

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
        self.question_before_hint = None
        self.answer_before_hint = None
