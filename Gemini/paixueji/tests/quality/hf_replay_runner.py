"""
Replay runner for HF case bundles.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from google import genai

# Add project root for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph import paixueji_graph
from paixueji_assistant import PaixuejiAssistant
from schema import StreamChunk


class ResponseCapture:
    """Capture streaming chunks and expose the final full response."""

    def __init__(self):
        self.chunks: list[StreamChunk] = []
        self.full_response: str = ""
        self.response_type: str | None = None

    async def callback(self, chunk: StreamChunk):
        self.chunks.append(chunk)
        if chunk.finish:
            self.full_response = chunk.response
            self.response_type = chunk.response_type

    def get_response_text(self) -> str:
        if self.full_response:
            return self.full_response
        return "".join(c.response for c in self.chunks if c.response)


class HFReplayRunner:
    """Run replay cases against the live graph and capture candidate responses."""

    def __init__(self, client: genai.Client, config: dict | None = None):
        self.client = client
        self.config = config or self._load_config()

    def _load_config(self) -> dict:
        config_path = Path(__file__).parent.parent.parent / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    async def replay_case(
        self,
        bundle: dict[str, Any],
        case: dict[str, Any],
    ) -> dict[str, Any]:
        assistant = PaixuejiAssistant(client=self.client, system_managed=False)

        # Restore session-level context
        assistant.age = bundle.get("age")
        assistant.object_name = bundle.get("object_name")
        snapshot = bundle.get("assistant_snapshot", {}) or {}
        assistant.level1_category = snapshot.get("level1_category")
        assistant.level2_category = snapshot.get("level2_category")
        assistant.level3_category = snapshot.get("level3_category")
        assistant.ibpyp_theme = snapshot.get("ibpyp_theme")
        assistant.ibpyp_theme_name = snapshot.get("ibpyp_theme_name")
        assistant.guide_phase = snapshot.get("guide_phase")
        assistant.character = snapshot.get("character")
        if snapshot.get("current_focus_mode"):
            assistant.current_focus_mode = snapshot["current_focus_mode"]

        messages: list[dict[str, str]] = []
        prefix = case.get("conversation_prefix", [])
        for item in prefix:
            role = item.get("role")
            content = item.get("content", "")
            if role == "model":
                messages.append({"role": "assistant", "content": content})
                assistant.conversation_history.append({"role": "assistant", "content": content})
            elif role == "child":
                messages.append({"role": "user", "content": content})
                assistant.conversation_history.append({"role": "user", "content": content})

        child_input = case.get("child_response", "")
        if not child_input and prefix and prefix[-1].get("role") == "child":
            child_input = prefix[-1].get("content", "")

        state = self._build_state(
            assistant=assistant,
            messages=messages,
            child_input=child_input,
            bundle=bundle,
            case=case,
        )

        capture = ResponseCapture()
        state["stream_callback"] = capture.callback

        try:
            await paixueji_graph.ainvoke(state)
            return {
                "ok": True,
                "candidate_response": capture.get_response_text(),
                "candidate_response_type": capture.response_type,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "candidate_response": "",
                "candidate_response_type": None,
            }

    def _build_state(
        self,
        assistant: PaixuejiAssistant,
        messages: list[dict[str, str]],
        child_input: str,
        bundle: dict[str, Any],
        case: dict[str, Any],
    ) -> dict[str, Any]:
        age = bundle.get("age", 6)
        object_name = bundle.get("object_name")
        focus_mode = (bundle.get("assistant_snapshot", {}) or {}).get("current_focus_mode") or "depth"
        mode = case.get("mode", "chat")
        guide_phase = "active" if mode == "guide" else None

        age_prompt = assistant.get_age_prompt(age)
        category_prompt = assistant.get_category_prompt(
            assistant.level1_category,
            assistant.level2_category,
            assistant.level3_category,
        )
        character_prompt = assistant.get_character_prompt("friendly")
        focus_prompt = assistant.get_focus_prompt(focus_mode)

        has_assistant_messages = any(m.get("role") == "assistant" for m in messages)
        response_type = None if has_assistant_messages else "introduction"

        return {
            "age": age,
            "messages": messages,
            "content": child_input,
            "status": "normal",
            "session_id": f"hf-replay-{bundle.get('session_id', 'unknown')}",
            "request_id": f"hf-replay-{case.get('exchange_index', 0)}-{int(time.time())}",
            "config": self.config,
            "client": self.client,
            "assistant": assistant,
            "object_name": object_name,
            "level1_category": assistant.level1_category,
            "level2_category": assistant.level2_category,
            "level3_category": assistant.level3_category,
            "correct_answer_count": assistant.correct_answer_count,
            "age_prompt": age_prompt,
            "character_prompt": character_prompt,
            "category_prompt": category_prompt,
            "focus_prompt": focus_prompt,
            "focus_mode": focus_mode,
            "validation_result": None,
            "is_engaged": None,
            "is_factually_correct": None,
            "correctness_reasoning": None,
            "switch_decision_reasoning": None,
            "new_object_name": None,
            "detected_object_name": None,
            "response_type": response_type,
            "suggested_objects": None,
            "natural_topic_completion": False,
            "guide_phase": guide_phase,
            "guide_status": None,
            "guide_strategy": None,
            "guide_turn_count": None,
            "scaffold_level": None,
            "last_navigation_state": None,
            "fun_fact": None,
            "fun_fact_hook": None,
            "fun_fact_question": None,
            "real_facts": None,
            "full_response_text": "",
            "full_question_text": "",
            "sequence_number": 0,
            "stream_callback": None,
            "start_time": time.time(),
        }
