"""
Ask Ask Assistant - A conversational assistant where children ask questions
and the LLM provides age-appropriate answers with follow-up questions.

Now using official Google Gemini SDK with real streaming support.
"""
import json
import os
import re
import sys
from enum import Enum
from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig

# Add parent directory to path to access shared utilities
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def remove_emojis(text):
    """
    Remove emojis from text for clean TTS output.
    """
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


def safe_print(message):
    """Print message with fallback for encoding errors."""
    try:
        print(message)
    except UnicodeEncodeError:
        # Fallback: encode to ascii with replacement
        print(message.encode('ascii', 'replace').decode('ascii'))


def extract_json_from_response(text):
    """
    Extract JSON from a response that might contain markdown code blocks or extra text.
    """
    if not text or not text.strip():
        safe_print("[DEBUG extract_json] Empty or whitespace-only text received")
        return "{}"

    text = text.strip()

    # Try to find JSON in markdown code blocks first
    code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        extracted = match.group(1).strip()
        safe_print(f"[DEBUG extract_json] Found JSON in code block (length: {len(extracted)})")
        try:
            json.loads(extracted)
            return extracted
        except:
            safe_print(f"[DEBUG extract_json] Code block JSON invalid, trying other methods...")

    # Try to find a balanced JSON object
    first_brace = text.find('{')
    if first_brace != -1:
        brace_count = 0
        for i in range(first_brace, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    extracted = text[first_brace:i+1]
                    safe_print(f"[DEBUG extract_json] Found balanced JSON (length: {len(extracted)})")
                    try:
                        json.loads(extracted)
                        return extracted
                    except Exception as e:
                        safe_print(f"[DEBUG extract_json] Balanced JSON invalid: {e}")
                        break

    # Try greedy match as fallback
    json_pattern = r'\{.*\}'
    match = re.search(json_pattern, text, re.DOTALL)
    if match:
        extracted = match.group(0).strip()
        safe_print(f"[DEBUG extract_json] Found JSON (greedy, length: {len(extracted)})")
        return extracted

    # Check if it's already valid JSON
    try:
        json.loads(text)
        safe_print(f"[DEBUG extract_json] Text is already valid JSON")
        return text
    except:
        pass

    safe_print(f"[DEBUG extract_json] No JSON found, returning original (length: {len(text)})")
    return text


class ConversationState(Enum):
    """Tracks the current state of the Ask Ask conversation."""
    INTRODUCTION = "introduction"
    AWAITING_QUESTION = "awaiting_question"
    ANSWERING = "answering"
    SUGGESTING_TOPICS = "suggesting_topics"


class AskAskAssistant:
    """
    An educational assistant where children ask questions and receive
    age-appropriate answers with follow-up questions.
    """

    def __init__(self, config_path="config.json", age_prompts_path="age_prompts.json"):
        """Initialize the assistant with configuration and Gemini client."""
        self.config = self._load_config(config_path)
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.last_audio_output = None
        self.age = None

        # Initialize Google Gemini client
        self.client = genai.Client(
            vertexai=True,
            project=self.config["project"],
            location=self.config["location"],
            http_options=HttpOptions(api_version="v1")
        )

        # Load age prompts
        self.age_prompts = self._load_age_prompts(age_prompts_path)

        # Load prompts
        import ask_ask_prompts
        self.prompts = ask_ask_prompts.get_prompts()

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

    def _get_age_prompt(self, age):
        """Get the appropriate age-based prompt."""
        if not self.age_prompts:
            return ""

        age_groups = self.age_prompts.get('age_groups', {})

        if 3 <= age <= 4:
            return age_groups.get('3-4', {}).get('prompt', '')
        elif 5 <= age <= 6:
            return age_groups.get('5-6', {}).get('prompt', '')
        elif 7 <= age <= 8:
            return age_groups.get('7-8', {}).get('prompt', '')
        else:
            return age_groups.get('5-6', {}).get('prompt', '')

    def _convert_messages_to_gemini_format(self, messages):
        """
        Convert OpenAI-style messages to Gemini format.

        OpenAI format: [{"role": "system"/"user"/"assistant", "content": "..."}]
        Gemini format: (system_instruction, contents_array)

        Returns:
            tuple: (system_instruction_str, contents_array)
        """
        system_instruction = ""
        contents = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system":
                # System messages become system_instruction
                system_instruction += content + "\n"
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                # Convert "assistant" to "model" for Gemini
                contents.append({"role": "model", "parts": [{"text": content}]})

        return system_instruction.strip(), contents

    def _call_gemini_api(self, messages, temperature=None, max_tokens=None):
        """
        Call Gemini API using official Google SDK (non-streaming).

        Args:
            messages: OpenAI-style message array
            temperature: Optional temperature override
            max_tokens: Optional max_tokens override

        Returns:
            str: Complete response text
        """
        try:
            # Convert to Gemini format
            system_instruction, contents = self._convert_messages_to_gemini_format(messages)

            # Configure generation
            config = GenerateContentConfig(
                temperature=temperature if temperature is not None else self.config["temperature"],
                max_output_tokens=max_tokens if max_tokens is not None else self.config["max_tokens"],
                system_instruction=system_instruction if system_instruction else None
            )

            # Call API
            response = self.client.models.generate_content(
                model=self.config["model_name"],
                contents=contents,
                config=config
            )

            # Extract text from response
            if not response.text:
                safe_print(f"[ERROR] Empty response from Gemini API")
                raise Exception("API returned empty content")

            return response.text

        except Exception as e:
            safe_print(f"[ERROR] Gemini API call failed: {str(e)}")
            raise Exception(f"Gemini API error: {str(e)}")

    def _call_gemini_api_stream(self, messages, temperature=None, max_tokens=None):
        """
        Call Gemini API with REAL streaming using official Google SDK.

        This provides true token-by-token streaming from the Gemini model!

        Args:
            messages: OpenAI-style message array
            temperature: Optional temperature override
            max_tokens: Optional max_tokens override

        Yields:
            str: Text chunks as they arrive (true streaming!)
        """
        try:
            # Convert to Gemini format
            system_instruction, contents = self._convert_messages_to_gemini_format(messages)

            # Configure generation
            config = GenerateContentConfig(
                temperature=temperature if temperature is not None else self.config["temperature"],
                max_output_tokens=max_tokens if max_tokens is not None else self.config["max_tokens"],
                system_instruction=system_instruction if system_instruction else None
            )

            # Call streaming API - THIS IS TRUE STREAMING!
            stream = self.client.models.generate_content_stream(
                model=self.config["model_name"],
                contents=contents,
                config=config
            )

            # Yield chunks as they arrive in real-time
            for chunk in stream:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            safe_print(f"[ERROR] Gemini streaming failed: {str(e)}")
            raise Exception(f"Gemini API streaming error: {str(e)}")

    def start_conversation(self, age=None):
        """
        Start a new conversation with an introduction.

        Args:
            age: Optional child's age (3-8) for age-appropriate responses

        Returns:
            Introduction message
        """
        self.age = age
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION

        # Build system prompt with age guidance
        system_prompt = self.prompts['system_prompt']
        if age is not None:
            age_prompt = self._get_age_prompt(age)
            if age_prompt:
                system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"
                safe_print(f"[INFO] Using age-appropriate prompting for age: {age}")
            else:
                safe_print(f"[WARNING] No age prompt found for age {age}. Using base prompts.")
        else:
            safe_print("[INFO] No age specified. Using base prompts.")

        # Add system prompt to history
        self.conversation_history.append({
            "role": "system",
            "content": system_prompt
        })

        # Get introduction
        response = self._generate_introduction()

        # Transition to awaiting question
        self.state = ConversationState.AWAITING_QUESTION

        return response

    def _generate_introduction(self):
        """Generate the introduction message (plain text, no JSON)."""
        try:
            safe_print(f"[DEBUG] Generating introduction")
            response_text = self._call_gemini_api(
                messages=self.conversation_history + [
                    {"role": "user", "content": self.prompts['introduction_prompt']}
                ]
            )

            # Plain text response - use directly
            introduction = response_text.strip()
            self.last_audio_output = remove_emojis(introduction)

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": introduction
            })

            return introduction

        except Exception as e:
            safe_print(f"[Error generating introduction]: {e}")
            import traceback
            traceback.print_exc()
            fallback = "👋 Hi! I'm here to answer your questions! What do you want to know?"
            self.last_audio_output = remove_emojis(fallback)
            self.conversation_history.append({
                "role": "assistant",
                "content": fallback
            })
            return fallback

    def continue_conversation(self, child_input):
        """
        Continue the conversation based on child's input.

        Args:
            child_input: The child's question or response

        Returns:
            tuple: (response_text, audio_output)
        """
        # Add child's input to history
        self.conversation_history.append({
            "role": "user",
            "content": child_input
        })

        # Check if child is stuck (doesn't know what to ask)
        if self._is_child_stuck(child_input):
            safe_print("[DEBUG] Child is stuck, suggesting topics")
            response = self._suggest_topics()
        else:
            safe_print("[DEBUG] Child asked a question, answering")
            response = self._answer_question(child_input)

        return response, self.last_audio_output

    def _is_child_stuck(self, child_input):
        """
        Check if child is stuck and doesn't know what to ask.
        Uses simple keyword detection.
        """
        input_lower = child_input.lower().strip()

        # Check if it's a question (ends with ? or starts with why/what/how/when/where)
        question_starters = ["why", "what", "how", "when", "where", "who", "can", "could", "do", "does"]
        is_likely_question = (
            child_input.strip().endswith("?") or
            any(input_lower.startswith(word + " ") for word in question_starters)
        )

        # If it looks like a question, they're not stuck
        if is_likely_question and len(input_lower) > 5:
            return False

        stuck_phrases = [
            "don't know", "dont know", "idk", "dunno", "not sure",
            "no idea", "help me", "i need help"
        ]

        # Check for stuck phrases
        if any(phrase in input_lower for phrase in stuck_phrases):
            return True

        # Also check if input is very short and not a question (likely stuck)
        if len(input_lower) <= 3 and not is_likely_question:
            return True

        # Single word responses like "huh", "what", "nope" without context
        single_word_stuck = ["huh", "what", "nope", "idk", "dunno", "help"]
        if input_lower in single_word_stuck:
            return True

        return False

    def _answer_question(self, child_question):
        """Answer the child's question with a follow-up (plain text, no JSON)."""
        self.state = ConversationState.ANSWERING

        answer_prompt = self.prompts['answer_question_prompt'].format(
            child_question=child_question
        )

        try:
            safe_print(f"[DEBUG] Answering question")
            response_text = self._call_gemini_api(
                messages=self.conversation_history + [
                    {"role": "user", "content": answer_prompt}
                ]
            )

            # Plain text response - use directly
            full_response = response_text.strip()
            self.last_audio_output = remove_emojis(full_response)

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response
            })

            # Return to awaiting next question
            self.state = ConversationState.AWAITING_QUESTION

            return full_response

        except Exception as e:
            safe_print(f"[Error answering question]: {e}")
            import traceback
            traceback.print_exc()
            fallback = "That's a great question! Let me think about that..."
            self.last_audio_output = remove_emojis(fallback)
            self.conversation_history.append({
                "role": "assistant",
                "content": fallback
            })
            return fallback

    def _suggest_topics(self):
        """Suggest topics when child is stuck (plain text, no JSON)."""
        self.state = ConversationState.SUGGESTING_TOPICS

        try:
            safe_print(f"[DEBUG] Suggesting topics")
            response_text = self._call_gemini_api(
                messages=self.conversation_history + [
                    {"role": "user", "content": self.prompts['suggest_topics_prompt']}
                ]
            )

            # Plain text response - use directly
            full_response = response_text.strip()
            self.last_audio_output = remove_emojis(full_response)

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response
            })

            # Return to awaiting question
            self.state = ConversationState.AWAITING_QUESTION

            return full_response

        except Exception as e:
            safe_print(f"[Error suggesting topics]: {e}")
            import traceback
            traceback.print_exc()
            fallback = "🤗 That's okay! Want to learn about animals? Or space? Or how things work?"
            self.last_audio_output = remove_emojis(fallback)
            self.conversation_history.append({
                "role": "assistant",
                "content": fallback
            })
            return fallback

    def get_conversation_history(self):
        """Get the full conversation history."""
        return self.conversation_history

    def reset(self):
        """Reset the conversation."""
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION
        self.last_audio_output = None

    def start_conversation_stream(self, age=None):
        """
        Start conversation with streaming introduction.

        Yields:
            tuple: (event_type, data)
                - ("metadata", dict) - Initial metadata
                - ("text", str) - Text chunks (plain text, character by character)
                - ("complete", dict) - Final completion data
                - ("error", dict) - Error information
        """
        self.age = age
        self.conversation_history = []
        self.state = ConversationState.INTRODUCTION

        # Build system prompt with age guidance
        system_prompt = self.prompts['system_prompt']
        if age is not None:
            age_prompt = self._get_age_prompt(age)
            if age_prompt:
                system_prompt += f"\n\nAGE-SPECIFIC GUIDANCE:\n{age_prompt}"

        self.conversation_history.append({
            "role": "system",
            "content": system_prompt
        })

        # Yield metadata first
        yield ("metadata", {"state": "introduction", "age": age})

        # Stream introduction (plain text, no JSON)
        accumulated_text = ""
        try:
            for chunk in self._call_gemini_api_stream(
                messages=self.conversation_history + [
                    {"role": "user", "content": self.prompts['introduction_prompt']}
                ],
                max_tokens=None  # Use config default
            ):
                accumulated_text += chunk
                yield ("text", chunk)

            # Store in history
            self.conversation_history.append({
                "role": "assistant",
                "content": accumulated_text
            })

            self.last_audio_output = remove_emojis(accumulated_text)
            self.state = ConversationState.AWAITING_QUESTION

            yield ("complete", {
                "success": True,
                "audio_output": self.last_audio_output
            })

        except Exception as e:
            safe_print(f"[Error streaming introduction]: {e}")
            yield ("error", {"message": str(e)})

    def continue_conversation_stream(self, child_input):
        """
        Continue conversation with streaming response.

        Args:
            child_input: The child's question or input

        Yields:
            tuple: (event_type, data)
                - ("metadata", dict) - Immediate metadata (is_stuck, state)
                - ("text", str) - Text chunks (plain text, character by character)
                - ("complete", dict) - Final completion data
                - ("error", dict) - Error information
        """
        # Add to history
        self.conversation_history.append({
            "role": "user",
            "content": child_input
        })

        # Check if stuck
        is_stuck = self._is_child_stuck(child_input)

        # Yield metadata immediately
        yield ("metadata", {
            "is_stuck": is_stuck,
            "state": self.state.value
        })

        # Stream response (plain text, no JSON)
        accumulated_text = ""

        try:
            if is_stuck:
                # Stream topic suggestions
                for chunk in self._call_gemini_api_stream(
                    messages=self.conversation_history + [
                        {"role": "user", "content": self.prompts['suggest_topics_prompt']}
                    ],
                    max_tokens=2000
                ):
                    accumulated_text += chunk
                    yield ("text", chunk)

                self.state = ConversationState.SUGGESTING_TOPICS

            else:
                # Stream answer
                answer_prompt = self.prompts['answer_question_prompt'].format(
                    child_question=child_input
                )

                for chunk in self._call_gemini_api_stream(
                    messages=self.conversation_history + [
                        {"role": "user", "content": answer_prompt}
                    ],
                    max_tokens=2000
                ):
                    accumulated_text += chunk
                    yield ("text", chunk)

                self.state = ConversationState.ANSWERING

            # Store in history
            self.conversation_history.append({
                "role": "assistant",
                "content": accumulated_text
            })

            self.last_audio_output = remove_emojis(accumulated_text)
            self.state = ConversationState.AWAITING_QUESTION

            yield ("complete", {
                "success": True,
                "audio_output": self.last_audio_output
            })

        except Exception as e:
            safe_print(f"[Error streaming response]: {e}")
            yield ("error", {"message": str(e)})
