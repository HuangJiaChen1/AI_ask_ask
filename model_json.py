from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(raw_text: str | None) -> tuple[dict[str, Any] | None, str | None, bool]:
    normalized = (raw_text or "").strip()
    if not normalized:
        return None, "empty", False

    try:
        payload = json.loads(normalized)
        return (payload if isinstance(payload, dict) else None), "plain_json", False
    except Exception:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", normalized, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        try:
            payload = json.loads(fenced_match.group(1))
            return (payload if isinstance(payload, dict) else None), "fenced_json", True
        except Exception:
            pass

    wrapped_match = re.search(r"(\{.*\})", normalized, re.DOTALL)
    if wrapped_match:
        try:
            payload = json.loads(wrapped_match.group(1))
            return (payload if isinstance(payload, dict) else None), "wrapped_json", True
        except Exception:
            pass

    return None, "invalid_json", False
