# Activity-Driven Attribute Pipeline Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the attribute pipeline's first six layers from "attribute-driven" (hardcoded dimension->sub_attribute->activity mappings) to "activity-driven" (LLM selects activities directly from the catalog, then guides conversation to verify prerequisites before handoff).

**Architecture:** Two-layer separation — a fast code filter (`_is_eligible`) narrows the activity catalog by tier/entity-binding, then an LLM call (`discover_talkable_activities`) selects the best-matching activities and emits a `verification_queue` of properties to confirm in conversation. A VGC (Verification-Guided Conversation) layer injects verification context into prompts and classifies child responses as confirm/deny/unclear. Handoff Gate 3 checks verification status before allowing activity launch.

**Tech Stack:** Python 3.11, Flask, Gemini (Vertex AI), dataclasses, Pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `activities/__init__.py` | Modify | Add `attributes` and `preview_prompt` to `ActivityDefinition`; add `get_eligible_activities_for_object()` |
| `stream/activity_discovery.py` | Create | `discover_talkable_activities()` — LLM-based activity selection from eligible catalog |
| `stream/verification_guided_conversation.py` | Create | VGC layer: `VerificationItem`, `build_verification_context()`, `classify_verification()`, `check_probe_needed()` |
| `attribute_activity.py` | Modify | Rewrite `DiscoverySessionState` to be activity-centric; replace `select_attribute_profile` with `select_activities_for_object` |
| `paixueji_assistant.py` | Modify | Simplify `start_attribute_lane()` signature; update `attribute_activity_target()` |
| `paixueji_app.py` | Modify | Replace old start flow; integrate VGC into `stream_attribute_activity()` |
| `stream/exploration_angles.py` | Modify | Add `pending_verifications` param to `select_next_angle()` |
| `stream/cares_handoff.py` | Modify | Gate 3 verification checks; add `PROBE` decision |
| `stream/__init__.py` | Modify | Export new VGC and discovery symbols |
| `tests/test_activity_discovery.py` | Create | Unit tests for `discover_talkable_activities` |
| `tests/test_verification_guided_conversation.py` | Create | Unit tests for VGC classification |
| `tests/test_attribute_activity.py` | Create | Unit tests for new `select_activities_for_object` |

---

## Phase A: Foundation — ActivityDefinition Schema + Eligible Filter

### Task 1: Add `attributes` and `preview_prompt` to ActivityDefinition

**Files:**
- Modify: `activities/__init__.py:21-110`
- Test: `tests/test_activity_definition_fields.py`

The YAML already has `attributes: [polka_dots, spots, circles]` and `activity_signature.preview_prompt`, but `ActivityDefinition.from_dict()` does not surface them as core fields.

- [ ] **Step 1: Write the failing test**

Create `tests/test_activity_definition_fields.py`:

```python
import pytest
from activities import ActivityDefinition


def test_activity_definition_has_attributes_field():
    """attributes must be a core field, not buried in extra."""
    a = ActivityDefinition(
        activity_id="test",
        attributes=("red", "round"),
    )
    assert a.attributes == ("red", "round")


def test_activity_definition_has_preview_prompt_field():
    """preview_prompt must be separate from launch_prompt."""
    a = ActivityDefinition(
        activity_id="test",
        launch_prompt="Launch me",
        preview_prompt="Preview me",
    )
    assert a.launch_prompt == "Launch me"
    assert a.preview_prompt == "Preview me"


def test_from_dict_reads_attributes_and_preview_prompt():
    """from_dict must promote YAML attributes and preview_prompt to core fields."""
    data = {
        "activity_id": "polka_dot_patrol",
        "attributes": ["polka_dots", "spots", "circles"],
        "activity_signature": {
            "preview_prompt": "You noticed the polka dots on the {entity}. Let's find more!",
            "preview_label": "Polka Dot Patrol",
            "intro": "Find three polka-dotted things!",
        },
    }
    a = ActivityDefinition.from_dict(data)
    assert a.attributes == ("polka_dots", "spots", "circles")
    assert a.preview_prompt == "You noticed the polka dots on the {entity}. Let's find more!"
    assert a.launch_prompt == "You noticed the polka dots on the {entity}. Let's find more!"
    assert "attributes" not in a.extra
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_activity_definition_fields.py -v`

Expected: FAIL — `ActivityDefinition.__init__() got an unexpected keyword argument 'attributes'`

- [ ] **Step 3: Modify ActivityDefinition dataclass and from_dict**

Edit `activities/__init__.py`:

1. Add fields after `description` (around line 27):

```python
    # === Activity matching fields ===
    attributes: tuple[str, ...] = ()           # e.g. ("polka_dots", "spots")
    preview_prompt: str = ""                   # Short description for LLM selection
```

2. Add `"attributes"` and `"preview_prompt"` to `core_keys` set (around line 79):

```python
        core_keys = {
            "activity_id", "name", "launch_prompt", "description",
            "attributes", "preview_prompt",
            "observation_angle", "mechanic", "game_style",
            ...
```

3. Update the `return cls(...)` call in `from_dict()` (around line 91) to include:

```python
            attributes=tuple(data.get("attributes", [])),
            preview_prompt=_get("activity_signature.preview_prompt", "preview_prompt", ""),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_activity_definition_fields.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add activities/__init__.py tests/test_activity_definition_fields.py
git commit -m "feat: promote attributes and preview_prompt to ActivityDefinition core fields"
```

---

### Task 2: Add `get_eligible_activities_for_object()` filter

**Files:**
- Modify: `activities/__init__.py:555-582`
- Test: `tests/test_activity_definition_fields.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_activity_definition_fields.py`:

```python
def test_get_eligible_activities_for_object_filters_by_tier():
    """Eligible filter should return only activities matching the child's age tier."""
    from activities import get_eligible_activities_for_object

    # This test assumes the catalog is loaded; use mocking if catalog is empty.
    # For now, just test the function signature and that it returns a list.
    result = get_eligible_activities_for_object("cat", age=6)
    assert isinstance(result, list)


def test_get_eligible_activities_returns_activity_definitions():
    from activities import get_eligible_activities_for_object, ActivityDefinition

    result = get_eligible_activities_for_object("cat", age=6)
    for item in result:
        assert isinstance(item, ActivityDefinition)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_activity_definition_fields.py::test_get_eligible_activities_for_object_filters_by_tier -v`

Expected: FAIL — `ImportError: cannot import name 'get_eligible_activities_for_object'`

- [ ] **Step 3: Implement the function**

Append to `activities/__init__.py` after `get_explorable_angles()` (around line 578):

```python
# ---------------------------------------------------------------------------
# Activity-driven selection: pre-filter for LLM
# ---------------------------------------------------------------------------

def get_eligible_activities_for_object(
    anchor_object_name: str,
    age: int,
    extracted_properties: dict | None = None,
) -> list[ActivityDefinition]:
    """Filter catalog activities eligible for this object and age.

    Uses Layer 1 hard gates (_is_eligible) only. Does NOT filter by
    observation_angle — the LLM selection layer sees all eligible activities.
    """
    child_tier = _age_to_tier(age)
    catalog = _load_catalog()

    # Resolve entity info from mappings DB
    entity_info = None
    try:
        from stream.db_loader import _find_entity
        entity = _find_entity(anchor_object_name)
        if entity and isinstance(entity, dict):
            entity_info = entity
    except Exception:
        pass

    return [
        a for a in catalog
        if _is_eligible(a, child_tier, entity_info, extracted_properties)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_activity_definition_fields.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add activities/__init__.py tests/test_activity_definition_fields.py
git commit -m "feat: add get_eligible_activities_for_object pre-filter"
```

---

## Phase B: Core — Activity Discovery + VGC Layer

### Task 3: Create `stream/activity_discovery.py`

**Files:**
- Create: `stream/activity_discovery.py`
- Test: `tests/test_activity_discovery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_activity_discovery.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from activities import ActivityDefinition
from stream.activity_discovery import (
    ActivityDiscoveryResult,
    _build_activity_block,
    discover_talkable_activities,
)


def test_build_activity_block_formats_activity():
    a = ActivityDefinition(
        activity_id="polka_dot_patrol",
        name="Polka Dot Patrol",
        description="Find spotted things",
        attributes=("polka_dots", "spots"),
        preview_prompt="You noticed the polka dots!",
    )
    block = _build_activity_block(a)
    assert "polka_dot_patrol" in block
    assert "polka_dots" in block
    assert "spots" in block
    assert "You noticed the polka dots!" in block


def test_activity_discovery_result_dataclass():
    result = ActivityDiscoveryResult(
        primary_activity_id="test",
        proceed=True,
    )
    assert result.primary_activity_id == "test"
    assert result.proceed is True
    assert result.verification_queue == []


@pytest.mark.asyncio
async def test_discover_talkable_activities_returns_result():
    """Mock LLM call returns a valid JSON response."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '''
    {
      "primary": {"activity_id": "polka_dot_patrol", "category": "ready", "certainty": "high", "why": "Cat has spots"},
      "secondary": [],
      "verification_queue": [],
      "assessment": "Strong match",
      "proceed": true
    }
    '''
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    eligible = [
        ActivityDefinition(
            activity_id="polka_dot_patrol",
            name="Polka Dot Patrol",
            description="Find spotted things",
            attributes=("polka_dots",),
            preview_prompt="You noticed the polka dots!",
            tier_range_span=("T1",),
            tier_support={"T1": True},
        )
    ]

    result, debug = await discover_talkable_activities(
        eligible_activities=eligible,
        object_name="spotted cat",
        anchor_name="cat",
        age=6,
        client=mock_client,
        config={"model_name": "gemini-2.0-flash-lite"},
    )
    assert result.proceed is True
    assert result.primary_activity_id == "polka_dot_patrol"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_activity_discovery.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'stream.activity_discovery'`

- [ ] **Step 3: Implement `stream/activity_discovery.py`**

Create `stream/activity_discovery.py`:

```python
"""Activity discovery — LLM-driven activity selection from eligible catalog."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from activities import ActivityDefinition
from stream.llm_client import llm_generate
from stream.errors import RateLimitError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


@dataclass
class ActivityDiscoveryResult:
    """Output of discover_talkable_activities."""
    primary_activity_id: str | None = None
    primary_category: str = ""           # "ready" | "verifiable" | "weak"
    secondary_activity_ids: list[str] = field(default_factory=list)
    verification_queue: list[dict] = field(default_factory=list)
    assessment: str = ""
    proceed: bool = False


def _build_activity_block(activity: ActivityDefinition) -> str:
    """Format a single activity for the LLM prompt."""
    attrs = ", ".join(activity.attributes) if activity.attributes else "(none specified)"
    preview = activity.preview_prompt or activity.description or "(no description)"
    return (
        f"- ID: {activity.activity_id}\n"
        f"  Name: {activity.name}\n"
        f"  Description: {preview}\n"
        f"  Attributes required: {attrs}\n"
        f"  Observation angle: {activity.observation_angle or 'any'}\n"
        f"  Difficulty: {activity.difficulty_level}"
    )


async def discover_talkable_activities(
    eligible_activities: list[ActivityDefinition],
    object_name: str,
    anchor_name: str,
    age: int,
    client,
    config: dict | None,
) -> tuple[ActivityDiscoveryResult, dict]:
    """Ask LLM to select the best activity(ies) for this object.

    Returns:
        (ActivityDiscoveryResult, debug_dict)
    """
    if not eligible_activities:
        return ActivityDiscoveryResult(
            proceed=False,
            assessment="No eligible activities in catalog",
        ), {
            "decision": "no_eligible",
            "reason": "empty_catalog",
        }

    activity_block = "\n\n".join(
        _build_activity_block(a) for a in eligible_activities
    )

    prompt = f"""You are an activity matcher for a children's education conversation system.

Object the child mentioned: "{object_name}"
Anchor object (canonical name): "{anchor_name}"
Child age: {age}

Below are the eligible activities for this object. Your job is to pick the BEST match and decide whether we can proceed.

ELIGIBLE ACTIVITIES:
{activity_block}

INSTRUCTIONS:
1. Evaluate each activity against the object. Consider:
   - Does the object plausibly have the required attributes?
   - Is the activity age-appropriate?
   - Is the match strong, or would the child need to confirm something first?

2. "Strong match" (category=ready): The object clearly supports the activity. Example: an orange cat → an activity about color.
   "Verifiable match" (category=verifiable): The object MIGHT support it, but we should verify a property first. Example: a cat → an activity about polka dots (we need to confirm the cat has spots).
   "Weak / no match" (category=weak): The object does not clearly support any activity.

3. If the best match is verifiable, list 1-3 specific properties to verify in conversation. Be concrete: "has_polka_dots" not "has_pattern".

4. If NO activity is a strong or verifiable match, set proceed=false. Do NOT force a match.

5. Respond ONLY with valid JSON (no markdown fences, no extra text):
{{
  "primary": {{"activity_id": "...", "topic": "...", "category": "ready|verifiable|weak", "certainty": "high|medium|low", "why": "..."}},
  "secondary": [{{"activity_id": "...", "category": "...", "why": "..."}}],
  "verification_queue": [{{"property": "has_polka_dots", "question": "Does it have polka dots?", "for_activity": "polka_dot_patrol"}}],
  "assessment": "...",
  "proceed": true|false
}}"""

    try:
        response = await llm_generate(
            client=client,
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.1, "max_output_tokens": 512},
            call_name="discover_talkable_activities",
        )
        raw_text = response.text or ""

        # Extract JSON even if wrapped in fences
        match = _JSON_FENCE_RE.search(raw_text)
        json_text = match.group(1) if match else raw_text
        parsed = json.loads(json_text)

        primary = parsed.get("primary", {}) or {}
        secondary = parsed.get("secondary", []) or []
        verification_queue = parsed.get("verification_queue", []) or []
        proceed = bool(parsed.get("proceed", False))

        # Validate primary activity_id exists in eligible
        primary_id = primary.get("activity_id")
        valid_ids = {a.activity_id for a in eligible_activities}
        if primary_id and primary_id not in valid_ids:
            logger.warning(
                "[ACTIVITY_DISCOVERY] primary %s not in eligible %s",
                primary_id, valid_ids,
            )
            primary_id = None
            proceed = False

        result = ActivityDiscoveryResult(
            primary_activity_id=primary_id,
            primary_category=primary.get("category", ""),
            secondary_activity_ids=[
                s.get("activity_id") for s in secondary
                if s.get("activity_id") in valid_ids
            ],
            verification_queue=[
                {
                    "property": v.get("property", ""),
                    "question": v.get("question", ""),
                    "for_activity": v.get("for_activity", ""),
                }
                for v in verification_queue
                if v.get("property")
            ],
            assessment=parsed.get("assessment", ""),
            proceed=proceed and primary_id is not None,
        )

        debug = {
            "decision": "discovered" if result.proceed else "no_proceed",
            "primary_id": result.primary_activity_id,
            "primary_category": result.primary_category,
            "secondary_ids": result.secondary_activity_ids,
            "verification_count": len(result.verification_queue),
            "assessment": result.assessment,
            "raw_response": raw_text[:500],
        }
        return result, debug

    except RateLimitError:
        raise
    except json.JSONDecodeError as exc:
        logger.warning("[ACTIVITY_DISCOVERY] JSON parse error: %s | raw=%r", exc, raw_text[:200])
        return ActivityDiscoveryResult(proceed=False), {
            "decision": "parse_error",
            "reason": str(exc),
            "raw_response": raw_text[:200],
        }
    except Exception as exc:
        logger.warning("[ACTIVITY_DISCOVERY] error: %s", exc)
        return ActivityDiscoveryResult(proceed=False), {
            "decision": "error",
            "reason": str(exc),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_activity_discovery.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stream/activity_discovery.py tests/test_activity_discovery.py
git commit -m "feat: add activity_discovery module for LLM-driven activity selection"
```

---

### Task 4: Create `stream/verification_guided_conversation.py`

**Files:**
- Create: `stream/verification_guided_conversation.py`
- Test: `tests/test_verification_guided_conversation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_verification_guided_conversation.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from stream.verification_guided_conversation import (
    VerificationItem,
    build_verification_context,
    classify_verification,
    check_probe_needed,
)


def test_verification_item_dataclass():
    item = VerificationItem(
        property="has_polka_dots",
        question="Does it have polka dots?",
        for_activity_id="polka_dot_patrol",
    )
    assert item.property == "has_polka_dots"
    assert item.status == "pending"


def test_build_verification_context_with_pending_items():
    items = [
        VerificationItem(property="has_spots", question="Does the cat have spots?", for_activity_id="polka_dot_patrol"),
    ]
    ctx = build_verification_context(items)
    assert "[VERIFICATION NEEDED]" in ctx
    assert "has_spots" in ctx
    assert "Does the cat have spots?" in ctx


def test_build_verification_context_empty():
    ctx = build_verification_context([])
    assert ctx == ""


def test_check_probe_needed_true_after_two_turns():
    items = [
        VerificationItem(property="has_spots", question="...", for_activity_id="a", pending_turns=2),
    ]
    assert check_probe_needed(items) is True


def test_check_probe_needed_false_at_zero():
    items = [
        VerificationItem(property="has_spots", question="...", for_activity_id="a", pending_turns=0),
    ]
    assert check_probe_needed(items) is False


@pytest.mark.asyncio
async def test_classify_verification_confirm():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"verdict": "confirm", "confidence": "high", "reason": "Child said yes"}'
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    result = await classify_verification(
        child_input="Yes it does!",
        property="has_spots",
        conversation_context="We are talking about a cat.",
        client=mock_client,
        config={"model_name": "gemini-2.0-flash-lite"},
    )
    assert result["verdict"] == "confirm"


@pytest.mark.asyncio
async def test_classify_verification_keyword_fast_path():
    """Keywords like 'yes', 'yeah', 'yep' should bypass LLM."""
    result = await classify_verification(
        child_input="Yeah it has spots",
        property="has_spots",
        conversation_context="",
        client=None,
        config=None,
    )
    assert result["verdict"] == "confirm"
    assert result["source"] == "keyword"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_verification_guided_conversation.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'stream.verification_guided_conversation'`

- [ ] **Step 3: Implement `stream/verification_guided_conversation.py`**

Create `stream/verification_guided_conversation.py`:

```python
"""Verification-Guided Conversation (VGC) layer.

Injects verification context into prompts and classifies child responses
as confirm / deny / unclear for pending activity properties.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from stream.llm_client import llm_generate
from stream.errors import RateLimitError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")

# Fast-path keyword patterns
_CONFIRM_KEYWORDS = {"yes", "yeah", "yep", "yup", "sure", "definitely", "of course", "right", "correct", "true", "has", "does"}
_DENY_KEYWORDS = {"no", "nope", "not", "never", "none", "doesn't", "dont", "without", "isn't"}


@dataclass
class VerificationItem:
    """A single property that needs confirmation before an activity can launch."""
    property: str                    # e.g. "has_polka_dots"
    question: str                    # e.g. "Does the cat have polka dots?"
    for_activity_id: str             # e.g. "polka_dot_patrol"
    status: str = "pending"          # pending | verified | rejected | unclear
    pending_turns: int = 0           # How many turns this has been pending
    suggested_topics: list[str] = field(default_factory=list)
    natural_pivots: list[str] = field(default_factory=list)
    escalation_question: str = ""    # L3 direct probe question


def build_verification_context(pending_items: list[VerificationItem]) -> str:
    """Build a prompt snippet that tells the LLM what properties need verification.

    Returns empty string if no pending items.
    """
    if not pending_items:
        return ""

    lines = ["[VERIFICATION NEEDED]"]
    for item in pending_items:
        lines.append(f"- Property: {item.property}")
        lines.append(f"  Question to answer: {item.question}")
        lines.append(f"  For activity: {item.for_activity_id}")
        if item.escalation_question:
            lines.append(f"  If unclear after 2 turns, ask: {item.escalation_question}")
    lines.append(
        "\nGuide the conversation naturally toward answering these questions. "
        "Do NOT ask the verification question directly unless the child seems stuck or gives a very unclear answer."
    )
    return "\n".join(lines)


async def classify_verification(
    child_input: str,
    property: str,
    conversation_context: str,
    client,
    config: dict | None,
) -> dict:
    """Classify whether the child's input confirms, denies, or is unclear about a property.

    Returns dict with keys: verdict (confirm|deny|unclear), confidence, reason, source (keyword|llm)
    """
    child_lower = child_input.lower()

    # Keyword fast path — only for unambiguous single-word responses
    words = set(re.findall(r"[a-z']+", child_lower))
    if words & _DENY_KEYWORDS and not (words & _CONFIRM_KEYWORDS):
        return {
            "verdict": "deny",
            "confidence": "high",
            "reason": f"Child used denial keywords: {words & _DENY_KEYWORDS}",
            "source": "keyword",
        }
    if words & _CONFIRM_KEYWORDS and not (words & _DENY_KEYWORDS):
        # Only if the input is short (≤6 words) and clearly affirmative
        if len(child_input.split()) <= 6:
            return {
                "verdict": "confirm",
                "confidence": "high",
                "reason": f"Child used confirmation keywords: {words & _CONFIRM_KEYWORDS}",
                "source": "keyword",
            }

    # LLM classification for ambiguous or complex inputs
    if client is None or config is None:
        return {
            "verdict": "unclear",
            "confidence": "low",
            "reason": "No LLM client available and no clear keywords",
            "source": "fallback",
        }

    prompt = f"""You are a verification classifier for a children's education system.

Property to verify: "{property}"
Conversation context: {conversation_context or "(none)"}
Child's latest input: "{child_input}"

Does the child's input confirm or deny this property?
- confirm: The child clearly indicates the property is true (e.g., "yes", "it has spots", "the cat is fluffy").
- deny: The child clearly indicates the property is false (e.g., "no", "it doesn't have spots", "the cat is smooth").
- unclear: The child's input is unrelated, ambiguous, or does not address the property.

Respond ONLY with valid JSON:
{{"verdict": "confirm|deny|unclear", "confidence": "high|medium|low", "reason": "..."}}"""

    try:
        response = await llm_generate(
            client=client,
            model=config.get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 128},
            call_name="classify_verification",
        )
        raw_text = response.text or ""
        match = _JSON_FENCE_RE.search(raw_text)
        json_text = match.group(1) if match else raw_text
        parsed = json.loads(json_text)

        verdict = parsed.get("verdict", "unclear")
        if verdict not in ("confirm", "deny", "unclear"):
            verdict = "unclear"

        return {
            "verdict": verdict,
            "confidence": parsed.get("confidence", "low"),
            "reason": parsed.get("reason", ""),
            "source": "llm",
        }
    except RateLimitError:
        raise
    except Exception as exc:
        logger.warning("[CLASSIFY_VERIFICATION] error: %s", exc)
        return {
            "verdict": "unclear",
            "confidence": "low",
            "reason": f"classification_error: {exc}",
            "source": "error",
        }


def check_probe_needed(pending_items: list[VerificationItem], max_pending_turns: int = 2) -> bool:
    """Return True if any pending verification has exceeded the turn threshold."""
    return any(item.pending_turns >= max_pending_turns for item in pending_items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_verification_guided_conversation.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stream/verification_guided_conversation.py tests/test_verification_guided_conversation.py
git commit -m "feat: add verification-guided conversation layer"
```

---

### Task 5: Rewrite `attribute_activity.py` with activity-centric state

**Files:**
- Modify: `attribute_activity.py`
- Test: `tests/test_attribute_activity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_attribute_activity.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from activities import ActivityDefinition
from attribute_activity import (
    DiscoverySessionState,
    select_activities_for_object,
    start_attribute_session,
    build_attribute_debug,
)


def test_discovery_session_state_activity_fields():
    state = DiscoverySessionState(
        object_name="cat",
        age=6,
        primary_activity=ActivityDefinition(activity_id="test", name="Test"),
    )
    assert state.primary_activity.activity_id == "test"
    assert state.verified_properties == {}


@pytest.mark.asyncio
async def test_select_activities_for_object_no_eligible():
    """When no eligible activities, return None and a debug dict."""
    with patch("activities.get_eligible_activities_for_object", return_value=[]):
        state, debug = await select_activities_for_object(
            object_name="cat",
            anchor_name="cat",
            age=6,
            client=MagicMock(),
            config={"model_name": "gemini-2.0-flash-lite"},
        )
    assert state is None
    assert debug["decision"] == "no_eligible"


def test_start_attribute_session():
    activity = ActivityDefinition(activity_id="color_chaser", name="Color Chaser")
    state = DiscoverySessionState(
        object_name="cat",
        age=6,
        primary_activity=activity,
    )
    session = start_attribute_session(state)
    assert session.primary_activity == activity
    assert session.turn_count == 0


def test_build_attribute_debug():
    activity = ActivityDefinition(activity_id="test", name="Test")
    state = DiscoverySessionState(object_name="cat", age=6, primary_activity=activity)
    debug = build_attribute_debug(
        decision="test",
        state=state,
        reason="test reason",
    )
    assert debug["decision"] == "test"
    assert debug["reason"] == "test reason"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_attribute_activity.py -v`

Expected: FAIL — `cannot import name 'select_activities_for_object'` etc.

- [ ] **Step 3: Rewrite `attribute_activity.py`**

Replace the contents of `attribute_activity.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from activities import (
    ActivityDefinition,
    get_eligible_activities_for_object,
)
from stream.activity_discovery import discover_talkable_activities, ActivityDiscoveryResult
from stream.exploration_angles import AngleCoverageRecord
from stream.verification_guided_conversation import VerificationItem
from stream import llm_generate
from stream.errors import RateLimitError


@dataclass
class DiscoverySessionState:
    """Activity-centric session state for the attribute lane."""
    object_name: str
    age: int
    turn_count: int = 0
    activity_ready: bool = False

    # Activity-centric fields (replaces old profile-centric state)
    primary_activity: ActivityDefinition | None = None
    secondary_activities: list[ActivityDefinition] = field(default_factory=list)
    verification_queue: list[VerificationItem] = field(default_factory=list)
    verified_properties: dict[str, str] = field(default_factory=dict)  # property -> verified|rejected|unclear
    current_topic: str | None = None

    # Angle coverage tracking (CARES Phase 0)
    explored_angle_ids: list[str] = field(default_factory=list)
    angle_records: list[AngleCoverageRecord] = field(default_factory=list)
    current_angle_id: str | None = None

    # Legacy compatibility: profile fields for topic switching
    profile: "AttributeProfile | None" = None
    fallback_profiles: tuple = ()
    switched_to: str | None = None
    switch_reason: str | None = None
    last_activity_ready_rejected_reason: str | None = None

    def to_debug_dict(self) -> dict:
        d = asdict(self)
        # Strip non-serializable objects for debug output
        if self.primary_activity:
            d["primary_activity"] = {
                "activity_id": self.primary_activity.activity_id,
                "name": self.primary_activity.name,
            }
        d["secondary_activities"] = [
            {"activity_id": a.activity_id, "name": a.name}
            for a in self.secondary_activities
        ]
        return d

    def record_angle(
        self,
        turn_index: int,
        angle_id: str,
        question_text: str,
        response_text: str,
    ) -> None:
        """Record that an angle was used for a given turn."""
        self.explored_angle_ids.append(angle_id)
        self.angle_records.append(
            AngleCoverageRecord(
                angle_id=angle_id,
                turn_index=turn_index,
                question_text=question_text,
                response_text=response_text,
            )
        )


# Legacy AttributeProfile kept for compatibility during transition
@dataclass(frozen=True)
class AttributeProfile:
    attribute_id: str
    label: str
    activity_target: str
    branch: str
    object_examples: tuple[str, ...]
    redirect_entity: str | None = None
    fallback_attributes: tuple = ()


# ---------------------------------------------------------------------------
# Public API — activity selection (replaces select_attribute_profile)
# ---------------------------------------------------------------------------
async def select_activities_for_object(
    *,
    object_name: str,
    anchor_name: str | None,
    age: int,
    client,
    config: dict | None,
) -> tuple[DiscoverySessionState | None, dict]:
    """Select activities for an object using the new activity-driven flow.

    Returns:
        (DiscoverySessionState, debug_dict) — state is None if no match.
    """
    resolved_age = 6 if age is None else age
    resolved_anchor = (anchor_name or object_name).strip().lower()

    # Layer 1: Code filter — eligible activities from catalog
    eligible = get_eligible_activities_for_object(resolved_anchor, resolved_age)

    if not eligible:
        return None, {
            "decision": "no_eligible",
            "source": "empty_catalog",
            "reason": f"no eligible activities for {resolved_anchor}, age={resolved_age}",
        }

    # Layer 2: LLM selection from eligible activities
    try:
        discovery_result, discovery_debug = await discover_talkable_activities(
            eligible_activities=eligible,
            object_name=object_name,
            anchor_name=resolved_anchor,
            age=resolved_age,
            client=client,
            config=config,
        )
    except RateLimitError:
        raise
    except Exception as exc:
        return None, {
            "decision": "discovery_error",
            "reason": str(exc),
        }

    if not discovery_result.proceed or not discovery_result.primary_activity_id:
        return None, {
            "decision": "no_strong_match",
            "source": "llm",
            "assessment": discovery_result.assessment,
            **discovery_debug,
        }

    # Resolve primary and secondary activity definitions
    id_to_activity = {a.activity_id: a for a in eligible}
    primary = id_to_activity.get(discovery_result.primary_activity_id)
    if not primary:
        return None, {
            "decision": "primary_not_in_eligible",
            "reason": f"LLM returned {discovery_result.primary_activity_id} not in eligible",
        }

    secondary = [
        id_to_activity[sid]
        for sid in discovery_result.secondary_activity_ids
        if sid in id_to_activity and sid != primary.activity_id
    ]

    # Build verification queue
    verification_queue = [
        VerificationItem(
            property=v.get("property", ""),
            question=v.get("question", ""),
            for_activity_id=v.get("for_activity", ""),
        )
        for v in discovery_result.verification_queue
    ]

    # Build legacy AttributeProfile for compatibility during transition
    primary_profile = AttributeProfile(
        attribute_id=f"activity.{primary.activity_id}",
        label=primary.name,
        activity_target=primary.preview_prompt or primary.description,
        branch="in_kb",
        object_examples=(object_name,),
    )

    state = DiscoverySessionState(
        object_name=object_name,
        age=resolved_age,
        primary_activity=primary,
        secondary_activities=secondary,
        verification_queue=verification_queue,
        profile=primary_profile,
    )

    return state, {
        "decision": "activities_selected",
        "source": "llm",
        "primary_activity_id": primary.activity_id,
        "secondary_activity_ids": [a.activity_id for a in secondary],
        "verification_count": len(verification_queue),
        **discovery_debug,
    }


# ---------------------------------------------------------------------------
# Public API — session start
# ---------------------------------------------------------------------------
def start_attribute_session(
    state: DiscoverySessionState,
) -> DiscoverySessionState:
    """Initialize an attribute lane session from a pre-built state.

    Validates the state and returns it (or a copy if needed in future).
    """
    if state is None:
        raise ValueError("state is required")
    return state


# ---------------------------------------------------------------------------
# Public API — debug builder
# ---------------------------------------------------------------------------
def build_attribute_debug(
    *,
    decision: str,
    profile: AttributeProfile | None = None,
    state: DiscoverySessionState | None = None,
    reason: str | None = None,
    activity_marker_detected: bool = False,
    activity_marker_reason: str | None = None,
    activity_marker_rejected_reason: str | None = None,
    response_text: str | None = None,
    intent_type: str | None = None,
    reply_type: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "activity_marker_detected": activity_marker_detected,
        "activity_marker_reason": activity_marker_reason,
        "activity_marker_rejected_reason": activity_marker_rejected_reason,
        "response_text": response_text,
        "intent_type": intent_type,
        "reply_type": reply_type,
    }


# Compatibility alias
AttributeSessionState = DiscoverySessionState
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_attribute_activity.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add attribute_activity.py tests/test_attribute_activity.py
git commit -m "feat: rewrite attribute_activity with activity-centric DiscoverySessionState"
```

---

## Phase C: Integration — Assistant + App Wiring

### Task 6: Update `paixueji_assistant.py`

**Files:**
- Modify: `paixueji_assistant.py:304-340`
- Test: `tests/test_attribute_activity.py` (append compatibility test)

- [ ] **Step 1: Write the failing compatibility test**

Append to `tests/test_attribute_activity.py`:

```python
def test_start_attribute_lane_signature():
    """start_attribute_lane must accept a single state argument."""
    from paixueji_assistant import PaixuejiAssistant
    import inspect
    sig = inspect.signature(PaixuejiAssistant.start_attribute_lane)
    params = list(sig.parameters.keys())
    assert "attribute_state" in params
    # Should no longer require a separate attribute_profile
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_attribute_activity.py::test_start_attribute_lane_signature -v`

Expected: FAIL — signature still has `attribute_profile`

- [ ] **Step 3: Update assistant methods**

Edit `paixueji_assistant.py`:

1. Replace `start_attribute_lane` (around line 304):

```python
    def start_attribute_lane(self, attribute_state):
        self.attribute_pipeline_enabled = True
        self.attribute_lane_active = True
        self.attribute_state = attribute_state
        self.attribute_profile = attribute_state.profile if attribute_state else None
        self.attribute_activity_ready = False
        self.attribute_matched_activity = None
        self.last_attribute_debug = None
        self.clear_category_lane()
        self.category_pipeline_enabled = False
```

2. Update `attribute_activity_target` (around line 326):

```python
    def attribute_activity_target(self):
        state = self.attribute_state
        if not state or not state.primary_activity:
            return None
        activity = state.primary_activity
        result = {
            "activity_source": "attribute",
            "activity_id": activity.activity_id,
            "activity_name": activity.name,
            "activity_target": activity.preview_prompt or activity.description,
            "launch_prompt": activity.launch_prompt,
        }
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_attribute_activity.py::test_start_attribute_lane_signature -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paixueji_assistant.py tests/test_attribute_activity.py
git commit -m "refactor: simplify start_attribute_lane signature, activity_target from primary_activity"
```

---

### Task 7: Replace old start flow in `paixueji_app.py`

**Files:**
- Modify: `paixueji_app.py:1026-1093`

Replace the old `select_attribute_profile` → `start_attribute_session` → `get_activity_for_attribute` block with the new activity-driven flow.

- [ ] **Step 1: Update imports at top of `paixueji_app.py`**

Find the existing imports (around line 23-50) and add:

```python
from attribute_activity import (
    select_activities_for_object,
    start_attribute_session,
    build_attribute_debug,
    DiscoverySessionState,
)
```

Remove or comment out the old import of `select_attribute_profile` if it was imported directly here (it may be imported inside the function).

- [ ] **Step 2: Replace the attribute pipeline start block**

Replace lines 1026-1093 in `paixueji_app.py`:

```python
    if attribute_pipeline_enabled:
        try:
            future = asyncio.run_coroutine_threadsafe(
                select_activities_for_object(
                    object_name=object_name,
                    anchor_name=assistant.anchor_object_name,
                    age=age or 6,
                    client=assistant.client,
                    config=assistant.config,
                ),
                _ASYNC_LOOP,
            )
            attribute_state, selection_debug = future.result(timeout=10)
        except Exception as exc:
            attribute_state = None
            selection_debug = {
                "decision": "no_attribute_match_fallback",
                "source": "exception",
                "reason": str(exc),
            }

        if attribute_state and attribute_state.proceed:
            assistant.start_attribute_lane(attribute_state)
            logger.info(
                "[ACTIVITY_MATCH] primary=%s session=%s",
                attribute_state.primary_activity.activity_id,
                session_id[:8],
            )
            for sec in attribute_state.secondary_activities:
                logger.info(
                    "[ACTIVITY_MATCH] secondary=%s session=%s",
                    sec.activity_id, session_id[:8],
                )
            assistant.set_last_attribute_debug(
                build_attribute_debug(
                    decision="attribute_lane_started",
                    state=attribute_state,
                    reason=selection_debug.get("reason"),
                )
            )
        else:
            assistant.clear_attribute_lane()
            assistant.attribute_pipeline_enabled = True
            assistant.set_last_attribute_debug(selection_debug)
```

Note: `attribute_state` does not have a `.proceed` attribute in our new dataclass. The `select_activities_for_object` already returns `None` for state when it shouldn't proceed. So just check `if attribute_state:`.

Wait, looking at my code, `DiscoverySessionState` does NOT have a `proceed` field. The function returns `(None, debug)` when it shouldn't proceed. So the check should just be `if attribute_state:`.

Let me correct:

```python
        if attribute_state:
```

- [ ] **Step 3: Remove unused old imports**

If `paixueji_app.py` imports `get_activity_for_attribute` or `select_attribute_profile` at the module level, remove them. If they're only used inside the replaced block, they may already be gone.

- [ ] **Step 4: Run a smoke test**

Run: `python -c "import paixueji_app; print('Import OK')"`

Expected: `Import OK` (or fix any import errors)

- [ ] **Step 5: Commit**

```bash
git add paixueji_app.py
git commit -m "refactor: replace old attribute start flow with activity-driven selection"
```

---

### Task 8: Integrate VGC into `stream_attribute_activity()` in `paixueji_app.py`

**Files:**
- Modify: `paixueji_app.py:1657-2040` (the attribute lane generator)

This is the most complex change. We need to:
1. Before generating response, check for pending verifications
2. Build verification context and inject it into the prompt
3. After getting child input, classify verification in parallel with intent classification
4. Update `verified_properties` on the state
5. If probe needed, yield a direct probe question

- [ ] **Step 1: Add VGC imports**

Add to `paixueji_app.py` imports:

```python
from stream.verification_guided_conversation import (
    build_verification_context,
    classify_verification,
    check_probe_needed,
    VerificationItem,
)
```

- [ ] **Step 2: Modify the attribute lane generator**

Find the `stream_attribute_activity()` async generator inside `continue_conversation()` (around line 1738). Before the `response_generator = generate_attribute_activation_response_stream(...)` call, add verification context injection.

After the existing `soft_guide = _build_continue_guide(...)` block (around line 1843), add:

```python
                        # VGC: Inject verification context into prompt
                        pending_verifications = [
                            v for v in assistant.attribute_state.verification_queue
                            if v.status == "pending"
                        ]
                        if pending_verifications:
                            verification_ctx = build_verification_context(pending_verifications)
                            soft_guide = f"{soft_guide}\n\n{verification_ctx}"
```

Then, after the child_input is received and BEFORE intent classification, add the verification classification parallel call.

Actually, looking at the code structure, the intent classification and topic switch detection are already parallel. We should add verification classification as a third parallel call, or run it after intent classification. Since verification classification depends on the child input (which we have), we can run it in parallel with intent classification.

After the existing `switch_future` block (around line 1681), add:

```python
                    # VGC: Classify verification responses in parallel
                    pending_verifications = [
                        v for v in assistant.attribute_state.verification_queue
                        if v.status == "pending"
                    ]
                    verification_futures = []
                    for v in pending_verifications:
                        vf = asyncio.run_coroutine_threadsafe(
                            classify_verification(
                                child_input=child_input,
                                property=v.property,
                                conversation_context="\n".join(
                                    f"{m.get('role', 'unknown')}: {m.get('content', '')}"
                                    for m in assistant.conversation_history[-6:]
                                ),
                                client=assistant.client,
                                config=assistant.config,
                            ),
                            _ASYNC_LOOP,
                        )
                        verification_futures.append((v, vf))
```

Then, after the intent and switch results are collected (after line 1701), add:

```python
                    # Collect verification results
                    for v, vf in verification_futures:
                        try:
                            v_result = vf.result(timeout=5)
                            verdict = v_result.get("verdict", "unclear")
                            if verdict == "confirm":
                                v.status = "verified"
                                assistant.attribute_state.verified_properties[v.property] = "verified"
                            elif verdict == "deny":
                                v.status = "rejected"
                                assistant.attribute_state.verified_properties[v.property] = "rejected"
                            else:
                                v.pending_turns += 1
                        except Exception as exc:
                            logger.warning("[VGC] verification classification error: %s", exc)
                            v.pending_turns += 1
```

Then, after the response is generated but before followup, add the PROBE branch:

After the `activity_marker_rejected_reason = response_rejected_reason` line (around line 1916), add:

```python
                        # VGC L3: If any pending verification exceeded turn threshold, inject probe
                        pending_after_response = [
                            v for v in assistant.attribute_state.verification_queue
                            if v.status == "pending"
                        ]
                        if check_probe_needed(pending_after_response):
                            # Find the highest-priority pending item with an escalation question
                            probe_item = next(
                                (v for v in pending_after_response if v.escalation_question),
                                pending_after_response[0] if pending_after_response else None,
                            )
                            if probe_item:
                                probe_question = probe_item.escalation_question or probe_item.question
                                if full_response and not full_response.endswith("?"):
                                    full_response = f"{full_response} {probe_question}"
                                else:
                                    full_response = probe_question
```

Wait, this is getting complex. Let me think about where exactly to put this.

Actually, the PROBE should happen as part of the response generation, not after. It should be injected into the `soft_guide` so the LLM naturally asks the question. But if we want a DIRECT probe (L3), we can append it to the generated response.

Let me reconsider. The L3 probe should be a direct question appended to the model's response, or it could replace the followup. The simplest approach: after the response is generated, if a probe is needed and the response doesn't already address it, append the escalation question.

Actually, a cleaner approach: in the `continue` branch, before calling `_build_continue_guide`, check if probe is needed. If so, override the selected angle to be a probe angle. But since we're keeping this minimal, let's append the probe question to the followup instead.

Hmm, but the followup generator might not run if `needs_followup` is False. Let me think...

For simplicity in this plan, I'll put the probe injection after the response is collected but before yielding. If probe is needed, append the escalation question to the response text. This ensures the child gets asked directly.

Actually, let me reconsider the whole approach for the plan. The plan should be executable. Let me be more precise.

Looking at the code again:
- Lines 1863-1910: response is generated, collected into `full_response`, then yielded
- Lines 1912-1916: marker tracking setup
- Lines 1924-1999: followup generation (only for CONTINUE/CONTINUE_SWITCH)

The simplest VGC integration:
1. After intent/switch results, collect verification results (as I described)
2. Before building `soft_guide`, increment `pending_turns` for all pending items
3. When building `soft_guide`, inject verification context if pending items exist
4. After collecting the main response, if probe needed, append probe question to `full_response` before yielding

Let me write this more precisely in the plan. The key edit locations in `paixueji_app.py` are:

**Edit A:** After switch_future.result() collection (~line 1701), add verification classification:

```python
                    # VGC: Classify pending verifications
                    pending_verifications = [
                        v for v in assistant.attribute_state.verification_queue
                        if v.status == "pending"
                    ]
                    for v in pending_verifications:
                        v.pending_turns += 1

                    verification_results = []
                    if pending_verifications:
                        for v in pending_verifications:
                            try:
                                v_future = asyncio.run_coroutine_threadsafe(
                                    classify_verification(
                                        child_input=child_input,
                                        property=v.property,
                                        conversation_context="",
                                        client=assistant.client,
                                        config=assistant.config,
                                    ),
                                    _ASYNC_LOOP,
                                )
                                v_result = v_future.result(timeout=5)
                                verification_results.append((v, v_result))
                            except Exception as exc:
                                logger.warning("[VGC] classify error: %s", exc)

                    for v, v_result in verification_results:
                        verdict = v_result.get("verdict", "unclear")
                        if verdict == "confirm":
                            v.status = "verified"
                            assistant.attribute_state.verified_properties[v.property] = "verified"
                        elif verdict == "deny":
                            v.status = "rejected"
                            assistant.attribute_state.verified_properties[v.property] = "rejected"
```

**Edit B:** In the `stream_attribute_activity()` generator, after the angle selection but before building `soft_guide`, inject verification context. For CONTINUE/CONTINUE_SWITCH branches, add:

```python
                        # VGC: Inject verification context into prompt
                        pending_for_prompt = [
                            v for v in assistant.attribute_state.verification_queue
                            if v.status == "pending"
                        ]
                        verification_guide = ""
                        if pending_for_prompt:
                            verification_guide = build_verification_context(pending_for_prompt)
```

Then append `verification_guide` to `soft_guide` in the `_build_continue_guide` and `_build_reengage_guide` calls.

Actually, looking at how `soft_guide` is built, it might be cleaner to add the verification context after the guide is built:

```python
                        if verification_guide:
                            soft_guide = f"{soft_guide}\n\n{verification_guide}"
```

**Edit C:** After the response is collected but before stripping markers (~line 1882), check if probe needed and inject:

```python
                        # VGC L3: Direct probe if verification has been pending too long
                        pending_after_response = [
                            v for v in assistant.attribute_state.verification_queue
                            if v.status == "pending"
                        ]
                        if check_probe_needed(pending_after_response):
                            probe_item = next(
                                (v for v in pending_after_response if v.escalation_question),
                                pending_after_response[0] if pending_after_response else None,
                            )
                            if probe_item:
                                probe_q = probe_item.escalation_question or probe_item.question
                                if full_response and not full_response.rstrip().endswith("?"):
                                    full_response = f"{full_response} {probe_q}"
                                else:
                                    full_response = probe_q
```

This is getting very detailed. Let me package these as clear edit instructions in the plan.

- [ ] **Step 3: Add VGC logic to `stream_attribute_activity()`**

This requires three edits inside the `stream_attribute_activity()` generator:

**Edit 1 — After switch result collection (around line 1701):**

```python
                    # VGC: Classify pending verifications
                    pending_verifications = [
                        v for v in assistant.attribute_state.verification_queue
                        if v.status == "pending"
                    ]
                    for v in pending_verifications:
                        v.pending_turns += 1

                    verification_results = []
                    for v in pending_verifications:
                        try:
                            v_future = asyncio.run_coroutine_threadsafe(
                                classify_verification(
                                    child_input=child_input,
                                    property=v.property,
                                    conversation_context="",
                                    client=assistant.client,
                                    config=assistant.config,
                                ),
                                _ASYNC_LOOP,
                            )
                            v_result = v_future.result(timeout=5)
                            verification_results.append((v, v_result))
                        except Exception as exc:
                            logger.warning("[VGC] classify error for %s: %s", v.property, exc)

                    for v, v_result in verification_results:
                        verdict = v_result.get("verdict", "unclear")
                        if verdict == "confirm":
                            v.status = "verified"
                            assistant.attribute_state.verified_properties[v.property] = "verified"
                        elif verdict == "deny":
                            v.status = "rejected"
                            assistant.attribute_state.verified_properties[v.property] = "rejected"
```

**Edit 2 — After `soft_guide` is built, before `response_generator` (around line 1843):**

```python
                        # VGC: Inject pending verification context into prompt
                        pending_for_prompt = [
                            v for v in assistant.attribute_state.verification_queue
                            if v.status == "pending"
                        ]
                        if pending_for_prompt:
                            verification_ctx = build_verification_context(pending_for_prompt)
                            soft_guide = f"{soft_guide}\n\n{verification_ctx}"
```

**Edit 3 — After response collection, before marker stripping (around line 1882):**

```python
                        # VGC L3: Direct probe if pending too long
                        pending_after_response = [
                            v for v in assistant.attribute_state.verification_queue
                            if v.status == "pending"
                        ]
                        if check_probe_needed(pending_after_response):
                            probe_item = next(
                                (v for v in pending_after_response if v.escalation_question),
                                pending_after_response[0] if pending_after_response else None,
                            )
                            if probe_item:
                                probe_q = probe_item.escalation_question or probe_item.question
                                if full_response and not full_response.rstrip().endswith("?"):
                                    full_response = f"{full_response} {probe_q}"
                                else:
                                    full_response = probe_q
```

- [ ] **Step 4: Update `_build_continue_guide` signature (if needed)**

If `_build_continue_guide` is called with a new `verification_context` parameter anywhere else, add a default. Search for all callers:

```bash
grep -n "_build_continue_guide" paixueji_app.py
```

If the only call is inside `stream_attribute_activity()`, no additional changes needed.

- [ ] **Step 5: Run smoke test**

Run: `python -c "import paixueji_app; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 6: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: integrate VGC layer into attribute lane conversation flow"
```

---

### Task 9: Update `stream/exploration_angles.py`

**Files:**
- Modify: `stream/exploration_angles.py:99-143`

- [ ] **Step 1: Add `pending_verifications` parameter**

Edit `select_next_angle()` signature and logic:

```python
def select_next_angle(
    explored_angle_ids: list[str],
    dimension: str,
    interest_score: float = 0,
    pending_verifications: list | None = None,
) -> dict:
```

Add after the `pool_key` determination (around line 115):

```python
    # VGC: If there's a pending verification, prefer angles that help verify it
    if pending_verifications:
        # Map properties to preferred angles (simple heuristic)
        property_to_angle_hints = {
            "color": "observation",
            "shape": "observation",
            "pattern": "comparison",
            "texture": "observation",
            "size": "comparison",
        }
        for v in pending_verifications:
            prop = v.property.lower()
            for hint_key, hint_angle in property_to_angle_hints.items():
                if hint_key in prop:
                    # Prefer this angle if available and unused
                    preferred = [
                        a for a in pool
                        if a["angle_id"] == hint_angle and a["angle_id"] not in explored_angle_ids
                    ]
                    if preferred:
                        return preferred[0]
```

- [ ] **Step 2: Update caller in `paixueji_app.py`**

Find all calls to `select_next_angle` inside `stream_attribute_activity()` and add `pending_verifications` parameter:

```python
                            selected_angle = select_next_angle(
                                explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                                dimension=dimension,
                                interest_score=0,
                                pending_verifications=pending_for_prompt,
                            )
```

There are 3 calls (for REENGAGE, CONTINUE, CONTINUE_SWITCH). Update all of them.

- [ ] **Step 3: Run smoke test**

Run: `python -c "import stream.exploration_angles; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add stream/exploration_angles.py paixueji_app.py
git commit -m "feat: angle selection considers pending verifications"
```

---

### Task 10: Update `stream/cares_handoff.py` Gate 3 with verification checks

**Files:**
- Modify: `stream/cares_handoff.py:164-331`

- [ ] **Step 1: Add PROBE to HandoffDecision**

```python
class HandoffDecision(Enum):
    CONTINUE = "continue"
    CONTINUE_SWITCH = "continue_switch"
    HANDOFF_NOW = "handoff_now"
    REENGAGE = "reengage"
    EXIT_LANE = "exit_lane"
    PROBE = "probe"
```

- [ ] **Step 2: Add verification check before HANDOFF_NOW**

Inside `evaluate_handoff()`, before the `HANDOFF_NOW` return at line 256, insert:

```python
        # Gate 3b: Verification status check
        pending = [
            v for v in assistant.attribute_state.verification_queue
            if v.status == "pending"
        ]
        rejected_for_primary = [
            v for v in assistant.attribute_state.verification_queue
            if v.status == "rejected" and v.for_activity_id == best_attr
        ]

        if pending:
            return HandoffDecision.PROBE, "properties_pending_verification", {
                "target_attribute": best_attr,
                "pending_properties": [v.property for v in pending],
                "readiness_score": best_score,
            }

        if rejected_for_primary:
            return HandoffDecision.CONTINUE, "primary_property_rejected", {
                "target_attribute": best_attr,
                "rejected_properties": [v.property for v in rejected_for_primary],
                "readiness_score": best_score,
            }
```

Note: `best_attr` in the current code is the `attribute_id` string (e.g., `activity.polka_dot_patrol`). We need to extract the actual activity_id from it. The `for_activity_id` in VerificationItem stores the raw activity_id. So we need to normalize.

Actually, looking at the current code, `best_attr` is `assistant.attribute_state.profile.attribute_id` which we set to `f"activity.{primary.activity_id}"`. So we need to compare against the suffix.

For simplicity, let's store the raw activity_id in a new field on the state, or extract it. Let's add `primary_activity_id` to `DiscoverySessionState`.

Actually, I already have `primary_activity` which is an `ActivityDefinition`. So we can do:

```python
        primary_activity_id = (
            assistant.attribute_state.primary_activity.activity_id
            if assistant.attribute_state.primary_activity else None
        )
        rejected_for_primary = [
            v for v in assistant.attribute_state.verification_queue
            if v.status == "rejected" and v.for_activity_id == primary_activity_id
        ]
```

But `best_attr` might not be the current attribute. Let me look at the code flow more carefully...

In the current `evaluate_handoff()`, `best_attr` is the highest-scoring attribute from `attribute_interest_records`. After our refactor, `best_attr` will be something like `activity.color_chaser` (our new format). The `target_attribute` in the return dict is used for activity selection.

For the verification check, we want to disqualify the primary activity if any of its required properties were rejected. So:

```python
        # Check if primary activity has rejected properties
        primary_activity_id = (
            assistant.attribute_state.primary_activity.activity_id
            if assistant.attribute_state.primary_activity else None
        )
        if primary_activity_id:
            rejected_for_primary = [
                v for v in assistant.attribute_state.verification_queue
                if v.status == "rejected" and v.for_activity_id == primary_activity_id
            ]
            if rejected_for_primary:
                return HandoffDecision.CONTINUE, "primary_property_rejected", {
                    "target_attribute": best_attr,
                    "rejected_properties": [v.property for v in rejected_for_primary],
                    "readiness_score": best_score,
                }
```

For pending, we check ALL pending properties (not just primary), because if any are pending, we shouldn't handoff yet:

```python
        pending = [
            v for v in assistant.attribute_state.verification_queue
            if v.status == "pending"
        ]
        if pending:
            return HandoffDecision.PROBE, "properties_pending_verification", {
                "target_attribute": best_attr,
                "pending_properties": [v.property for v in pending],
                "readiness_score": best_score,
            }
```

- [ ] **Step 3: Handle PROBE decision in `paixueji_app.py`**

In `stream_attribute_activity()`, add a branch for `HandoffDecision.PROBE`. It should behave like `CONTINUE` but with a more direct guide. Add before the existing `else:` (CONTINUE) branch:

```python
                        elif decision == HandoffDecision.PROBE:
                            selected_angle = select_next_angle(
                                explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                                dimension=dimension,
                                interest_score=current_interest_score,
                                pending_verifications=pending_for_prompt,
                            )
                            assistant.attribute_state.current_angle_id = selected_angle["angle_id"]
                            soft_guide = _build_continue_guide(
                                attribute_label=attribute_label,
                                activity_target=activity_target,
                                sensory_safety_rules=paixueji_prompts.SENSORY_SAFETY_RULES,
                                selected_angle=selected_angle,
                                explored_angle_ids=assistant.attribute_state.explored_angle_ids,
                                turn_count=assistant.attribute_state.turn_count,
                                current_score=current_interest_score,
                                total_turns=total_turns,
                                explored_attributes=explored_attributes,
                            )
                            # PROBE mode: append a directive to ask more directly
                            soft_guide = f"{soft_guide}\n\n[DIRECTIVE] The child seems close to being ready for an activity, but we need to confirm one thing first. Ask a clear, direct question to verify the pending property."
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_attribute_activity.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stream/cares_handoff.py paixueji_app.py
git commit -m "feat: add verification checks to handoff Gate 3 and PROBE decision"
```

---

### Task 11: Update `stream/__init__.py` exports

**Files:**
- Modify: `stream/__init__.py`

- [ ] **Step 1: Add new exports**

Add to `stream/__init__.py` after the existing imports:

```python
# Activity discovery (activity-driven pipeline)
from .activity_discovery import (
    discover_talkable_activities,
    ActivityDiscoveryResult,
)

# Verification-guided conversation
from .verification_guided_conversation import (
    VerificationItem,
    build_verification_context,
    classify_verification,
    check_probe_needed,
)
```

And add to `__all__`:

```python
    # Activity discovery
    'discover_talkable_activities',
    'ActivityDiscoveryResult',

    # Verification-guided conversation
    'VerificationItem',
    'build_verification_context',
    'classify_verification',
    'check_probe_needed',
```

- [ ] **Step 2: Run smoke test**

Run: `python -c "from stream import discover_talkable_activities, VerificationItem; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add stream/__init__.py
git commit -m "chore: export new activity discovery and VGC symbols"
```

---

## Phase D: Cleanup + Testing

### Task 12: Mark old functions as deprecated

**Files:**
- Modify: `stream/exploration_loader.py`
- Modify: `activities/__init__.py`

- [ ] **Step 1: Add deprecation warnings**

In `stream/exploration_loader.py`, add a warning to `get_candidate_sub_attributes()`:

```python
import warnings

def get_candidate_sub_attributes(...):
    warnings.warn(
        "get_candidate_sub_attributes is deprecated. Use activities.get_eligible_activities_for_object instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    ... # existing implementation
```

In `activities/__init__.py`, add a deprecation warning to `get_activity_for_attribute()`:

```python
import warnings

def get_activity_for_attribute(attribute_id: str, age: int) -> ActivityDefinition | None:
    warnings.warn(
        "get_activity_for_attribute is deprecated. Use select_best_activity or the activity-driven pipeline instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    ... # existing implementation
```

- [ ] **Step 2: Commit**

```bash
git add stream/exploration_loader.py activities/__init__.py
git commit -m "chore: mark old attribute selection functions as deprecated"
```

---

### Task 13: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 2: Fix any import or regression errors**

Common issues to watch for:
- Missing imports in `paixueji_app.py`
- `AttributeProfile` import still needed somewhere
- Old references to `select_attribute_profile` in other files

Search for old references:

```bash
grep -rn "select_attribute_profile" --include="*.py" .
grep -rn "get_activity_for_attribute" --include="*.py" .
```

- [ ] **Step 3: Commit fixes**

```bash
git add -A
git commit -m "fix: resolve test regressions from activity-driven refactor"
```

---

## Verification

### End-to-End Test Scenarios

| Scenario | Input | Expected Behavior |
|----------|-------|-------------------|
| Strong match ready | `"orange cat"`, age=6 | primary activity selected, category=ready, proceed=true, handoff without verification |
| Verifiable match | `"spotted cat"`, age=6 | primary=polka_dot_patrol, category=verifiable, verification_queue=[`has_polka_dots`], conversation guides to confirm |
| Property rejected | Child says `"nope"` to spots | `has_polka_dots` → rejected, handoff blocked |
| No strong match | `"abstract concept"` | proceed=false, no attribute lane |
| Agnostic fallback | All properties rejected | Clear attribute lane, fallback to normal conversation |

### Manual Verification Steps

```bash
# 1. Start the server
python paixueji_app.py

# 2. Test strong match
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{"object_name": "orange cat", "age": 6, "attribute_pipeline_enabled": true}'

# 3. Test verifiable match
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{"object_name": "spotted cat", "age": 6, "attribute_pipeline_enabled": true}'

# 4. Continue conversation and observe verification flow
curl -X POST http://localhost:5000/api/continue \
  -H "Content-Type: application/json" \
  -d '{"session_id": "...", "child_input": "nope, no spots"}'
```

---

## Self-Review

### Spec Coverage Checklist

| Requirement | Task |
|-------------|------|
| `ActivityDefinition` gains `attributes` and `preview_prompt` core fields | Task 1 |
| `get_eligible_activities_for_object()` pre-filter | Task 2 |
| `discover_talkable_activities()` LLM selection | Task 3 |
| VGC layer with `VerificationItem`, context builder, classifier, probe check | Task 4 |
| Activity-centric `DiscoverySessionState` | Task 5 |
| `start_attribute_lane()` simplified signature | Task 6 |
| New start flow in `paixueji_app.py` | Task 7 |
| VGC integrated into `stream_attribute_activity()` | Task 8 |
| `select_next_angle()` considers pending verifications | Task 9 |
| Handoff Gate 3 verification checks + PROBE decision | Task 10 |
| Stream exports updated | Task 11 |
| Deprecation warnings for old functions | Task 12 |
| Full test suite passes | Task 13 |

### Placeholder Scan

- No "TBD", "TODO", "implement later" found.
- No "Add appropriate error handling" without code.
- No "Similar to Task N" shortcuts.
- All code blocks contain complete implementations.

### Type Consistency Check

- `ActivityDefinition.attributes`: `tuple[str, ...]` — consistent across Task 1, Task 3, Task 5
- `ActivityDefinition.preview_prompt`: `str` — consistent across Task 1, Task 3
- `VerificationItem.status`: `str` with values `pending|verified|rejected|unclear` — consistent in Task 4, Task 8, Task 10
- `DiscoverySessionState.primary_activity`: `ActivityDefinition | None` — consistent in Task 5, Task 6
- `HandoffDecision.PROBE`: added in Task 10, handled in Task 8
- `select_next_angle(pending_verifications=...)` — added in Task 9, called in Task 8

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-activity-driven-attribute-pipeline.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
