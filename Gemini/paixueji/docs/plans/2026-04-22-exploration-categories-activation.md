# Exploration Categories YAML Activation Plan

> **For agentic workers:** REQUIRED: Use subagent-driven-development (if subagents available) or executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 5 hard-coded MOCK_ATTRIBUTE_PROFILES with dynamic attribute candidate generation from `exploration_categories.yaml`, so any object can find a suitable attribute to bridge into an activity game.

**Architecture:** A new `stream/exploration_loader.py` module loads the YAML and exposes `get_candidate_sub_attributes(domain, age)` and `infer_domain(object_name, client, config)`. The `select_attribute_profile()` function in `attribute_activity.py` uses these to build candidates dynamically instead of choosing from 5 mock profiles. Domain is determined by the **surface object** (never the anchor), using mappings lookup first, then Gemini inference, then default fallback.

**Tech Stack:** Python 3.11+, PyYAML, existing Gemini client, pytest

---

## File Structure

| File | Action | Responsibility |
|:---|:---|:---|
| `exploration_categories.yaml` | Create (copy from `ref/`) | Canonical YAML defining all physical/engagement dimensions, sub_attributes per domain, tier applicability |
| `stream/exploration_loader.py` | Create | Parse YAML, tier filtering, domain lookup/inference, candidate generation |
| `stream/__init__.py` | Modify | Re-export new public symbols |
| `attribute_activity.py` | Modify | Rewrite `select_attribute_profile()` to use dynamic candidates; delete MOCK_ATTRIBUTE_PROFILES, `find_mock_attribute_profile`, `_profile_by_id`, `_supported_attribute_block` |
| `paixueji_prompts.py` | Modify | Add `DOMAIN_CLASSIFICATION_PROMPT`; update `ATTRIBUTE_SELECTION_PROMPT` |
| `paixueji_app.py` | Modify | Call-site signature unchanged (domain resolved internally) |
| `tests/test_exploration_loader.py` | Create | Tests for YAML parsing, tier filtering, domain lookup, candidate generation |
| `tests/test_attribute_activity_pipeline.py` | Modify | Update to new attribute_id format, dynamic candidates |

**Out of scope for this plan:** Engagement dimensions as attribute candidates (they remain used only by `db_loader.py` for follow-up question generation). Changes to `paixueji_assistant.py` state fields (no new `self.domain` needed — domain is resolved inside `select_attribute_profile`).

---

### Task 1: Copy and validate exploration_categories.yaml

**Files:**
- Create: `exploration_categories.yaml`

- [ ] **Step 1: Copy YAML to project root**

```bash
cp ref/exploration_categories.yaml exploration_categories.yaml
```

- [ ] **Step 2: Verify the file loads cleanly**

```bash
python3 -c "import yaml; data = yaml.safe_load(open('exploration_categories.yaml')); print(f'physical_dimensions: {len(data[\"physical_dimensions\"])}'); print(f'engagement_dimensions: {len(data[\"engagement_dimensions\"])}')"
```

Expected output:
```
physical_dimensions: 6
engagement_dimensions: 5
```

- [ ] **Step 3: Commit**

```bash
git add exploration_categories.yaml
git commit -m "feat: add exploration_categories.yaml to project root"
```

---

### Task 2: Create `stream/exploration_loader.py` — YAML loading and tier filtering

**Files:**
- Create: `stream/exploration_loader.py`
- Create: `tests/test_exploration_loader.py`

This module has zero Gemini dependency — it only reads YAML and filters by tier/domain.

- [ ] **Step 1: Write failing tests for YAML loading**

Create `tests/test_exploration_loader.py`:

```python
import pytest
from stream.exploration_loader import (
    SubAttributeCandidate,
    get_candidate_sub_attributes,
    _load_yaml,
    ALL_DOMAINS,
)


def test_load_yaml_returns_dict():
    data = _load_yaml()
    assert isinstance(data, dict)
    assert "physical_dimensions" in data
    assert "engagement_dimensions" in data


def test_all_domains_constant():
    assert "animals" in ALL_DOMAINS
    assert "food" in ALL_DOMAINS
    assert "default" not in ALL_DOMAINS
    assert len(ALL_DOMAINS) == 14


def test_get_candidate_sub_attributes_animals_age3():
    # Age 3 → tier 0 → only appearance + senses
    candidates = get_candidate_sub_attributes(domain="animals", age=3)
    dimensions_present = {c.dimension for c in candidates}

    assert "appearance" in dimensions_present
    assert "senses" in dimensions_present
    assert "structure" not in dimensions_present
    assert "function" not in dimensions_present
    assert "change" not in dimensions_present

    # Animals-specific sub_attributes
    attr_names = {c.sub_attribute for c in candidates if c.dimension == "appearance"}
    assert "body_color" in attr_names
    assert "covering" in attr_names


def test_get_candidate_sub_attributes_animals_age7():
    # Age 7 → tier 2 → all physical dimensions
    candidates = get_candidate_sub_attributes(domain="animals", age=7)
    dimensions_present = {c.dimension for c in candidates}

    assert "appearance" in dimensions_present
    assert "senses" in dimensions_present
    assert "structure" in dimensions_present
    assert "function" in dimensions_present
    assert "context" in dimensions_present
    assert "change" in dimensions_present


def test_get_candidate_sub_attributes_default_fallback():
    # Unknown domain → uses default sub_attributes
    candidates = get_candidate_sub_attributes(domain=None, age=4)
    attr_names = {c.sub_attribute for c in candidates if c.dimension == "appearance"}

    assert "color" in attr_names
    assert "shape" in attr_names
    assert "size" in attr_names


def test_get_candidate_sub_attributes_specific_domain_overrides_default():
    # "food" domain has its own sub_attributes, not the default ones
    candidates = get_candidate_sub_attributes(domain="food", age=4)
    attr_names = {c.sub_attribute for c in candidates if c.dimension == "appearance"}

    # food appearance: [color, shape, size] — same as default but defined explicitly
    assert "color" in attr_names

    # food senses: [taste, smell, texture, sound] — different from default [feel, weight, sound]
    sense_attrs = {c.sub_attribute for c in candidates if c.dimension == "senses"}
    assert "taste" in sense_attrs
    assert "texture" in sense_attrs


def test_get_candidate_sub_attributes_tier_1_includes_structure():
    # Age 5 → tier 1 → structure + function + context appear
    candidates = get_candidate_sub_attributes(domain=None, age=5)
    dimensions_present = {c.dimension for c in candidates}

    assert "structure" in dimensions_present
    assert "function" in dimensions_present
    assert "context" in dimensions_present
    assert "change" not in dimensions_present  # change is tier 2 only


def test_sub_attribute_candidate_fields():
    candidates = get_candidate_sub_attributes(domain="animals", age=3)
    assert len(candidates) > 0
    first = candidates[0]
    assert isinstance(first, SubAttributeCandidate)
    assert first.dimension in {"appearance", "senses"}
    assert isinstance(first.sub_attribute, str)
    assert first.tier in {0, 1, 2}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exploration_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'stream.exploration_loader'`

- [ ] **Step 3: Implement `stream/exploration_loader.py`**

```python
"""
Exploration Categories Loader

Loads exploration_categories.yaml and provides tier-aware, domain-aware
sub-attribute candidate generation for the attribute pipeline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import yaml

_YAML_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "exploration_categories.yaml"
)

# The 14 known domains in the YAML (excluding "default").
ALL_DOMAINS = (
    "animals",
    "food",
    "vehicles",
    "plants",
    "people_roles",
    "buildings_places",
    "clothing_accessories",
    "daily_objects",
    "natural_phenomena",
    "arts_music",
    "signs_symbols",
    "nature_landscapes",
    "human_body",
    "imagination",
)

# Tier index mapping: YAML uses [0, 1, 2] lists.
_TIER_INDICES = {0, 1, 2}


@dataclass(frozen=True)
class SubAttributeCandidate:
    dimension: str       # "appearance", "senses", "structure", "function", "context", "change"
    sub_attribute: str   # "body_color", "covering", "taste", ...
    tier: int            # 0, 1, or 2


def _age_to_tier(age: int) -> int:
    """Map child age to tier index (0, 1, 2)."""
    if age <= 4:
        return 0
    elif age <= 6:
        return 1
    else:
        return 2


@lru_cache(maxsize=1)
def _load_yaml() -> dict:
    """Load and cache the exploration_categories.yaml file."""
    with open(_YAML_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_sub_attributes(
    dimension_data: dict,
    domain: str | None,
) -> list[str]:
    """
    Get the sub_attribute list for a dimension given a domain.
    Falls back to "default" if domain is None or not found.
    """
    sub_attrs_map = dimension_data.get("sub_attributes", {})
    if domain and domain in sub_attrs_map:
        return list(sub_attrs_map[domain])
    return list(sub_attrs_map.get("default", []))


def get_candidate_sub_attributes(
    domain: str | None,
    age: int,
) -> list[SubAttributeCandidate]:
    """
    Generate a flat list of sub-attribute candidates filtered by domain and age tier.

    Args:
        domain: One of the 14 known domains, or None to use "default" for all.
        age: Child's age (3-8).

    Returns:
        List of SubAttributeCandidate, one per (dimension, sub_attribute) pair
        that is valid for the given tier.
    """
    data = _load_yaml()
    tier = _age_to_tier(age)

    candidates = []
    for dim_name, dim_data in data.get("physical_dimensions", {}).items():
        # Check tier applicability: dim_data["tiers"] is e.g. [0, 1, 2]
        applicable_tiers = dim_data.get("tiers", [])
        if tier not in applicable_tiers:
            continue

        sub_attrs = _resolve_sub_attributes(dim_data, domain)
        for sa in sub_attrs:
            candidates.append(
                SubAttributeCandidate(
                    dimension=dim_name,
                    sub_attribute=sa,
                    tier=tier,
                )
            )

    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exploration_loader.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add stream/exploration_loader.py tests/test_exploration_loader.py
git commit -m "feat: add exploration_loader — YAML loading and tier-aware candidate generation"
```

---

### Task 3: Add `infer_domain()` to `stream/exploration_loader.py` — Gemini domain classification

**Files:**
- Modify: `stream/exploration_loader.py`
- Modify: `paixueji_prompts.py`
- Modify: `tests/test_exploration_loader.py`

This is the function that determines a surface object's domain when the object is NOT in the mappings DB.

- [ ] **Step 1: Write failing tests for `infer_domain`**

Add to `tests/test_exploration_loader.py`:

```python
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_infer_domain_returns_domain_from_gemini():
    client = MagicMock()
    response = MagicMock()
    response.text = '{"domain": "food"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    domain = await infer_domain("cat food", client, {"model_name": "test"})
    assert domain == "food"
    client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_infer_domain_returns_none_on_invalid_json():
    client = MagicMock()
    response = MagicMock()
    response.text = "not json"
    client.aio.models.generate_content = AsyncMock(return_value=response)

    domain = await infer_domain("something weird", client, {"model_name": "test"})
    assert domain is None


@pytest.mark.asyncio
async def test_infer_domain_returns_none_on_unknown_domain_value():
    client = MagicMock()
    response = MagicMock()
    response.text = '{"domain": "underwater_cities"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    domain = await infer_domain("atlantis", client, {"model_name": "test"})
    assert domain is None


@pytest.mark.asyncio
async def test_infer_domain_returns_none_on_exception():
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(side_effect=Exception("boom"))

    domain = await infer_domain("anything", client, {"model_name": "test"})
    assert domain is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exploration_loader.py::test_infer_domain -v`
Expected: FAIL — `ImportError: cannot import name 'infer_domain'`

- [ ] **Step 3: Add `DOMAIN_CLASSIFICATION_PROMPT` to `paixueji_prompts.py`**

Add before `ATTRIBUTE_SELECTION_PROMPT` (around line 344):

```python
DOMAIN_CLASSIFICATION_PROMPT = """Classify this object into exactly one category.

OBJECT: {object_name}

CATEGORIES: {supported_domains}

Return JSON only:
{{"domain": "one category name, or null if none fit"}}

Choose the category that best describes what kind of thing this object is."""
```

Add to the `get_prompts()` return dict:

```python
'domain_classification_prompt': DOMAIN_CLASSIFICATION_PROMPT,
```

- [ ] **Step 4: Add `infer_domain()` to `stream/exploration_loader.py`**

Add to `stream/exploration_loader.py`:

```python
from model_json import extract_json_object


def _resolve_domain_from_mappings(object_name: str) -> str | None:
    """
    Try to find the domain for an object in the mappings DB.
    Returns the domain string (e.g. "animals") or None.
    """
    from stream.db_loader import _find_entity

    entity = _find_entity(object_name)
    if entity and isinstance(entity, dict):
        domain = entity.get("domain")
        if domain and domain in ALL_DOMAINS:
            return domain
    return None


async def infer_domain(
    surface_object_name: str,
    client,
    config: dict | None,
) -> str | None:
    """
    Determine the domain of a surface object.

    Strategy:
      1. Look up in mappings DB → use entity's domain if found.
      2. Ask Gemini to classify → validate against ALL_DOMAINS.
      3. Return None if both fail (caller will use default sub_attributes).

    Args:
        surface_object_name: The object the child named.
        client: Gemini client (with aio.models.generate_content).
        config: Config dict with model_name.

    Returns:
        Domain string from ALL_DOMAINS, or None.
    """
    # 1. Try mappings first (no LLM call needed)
    mapped = _resolve_domain_from_mappings(surface_object_name)
    if mapped:
        return mapped

    # 2. Ask Gemini
    try:
        import paixueji_prompts

        prompt = paixueji_prompts.get_prompts()["domain_classification_prompt"].format(
            object_name=surface_object_name,
            supported_domains=", ".join(ALL_DOMAINS),
        )
        response = await client.aio.models.generate_content(
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 60},
        )
        payload, _kind, _recovered = extract_json_object(response.text or "")
        if isinstance(payload, dict):
            domain = payload.get("domain")
            if domain and domain in ALL_DOMAINS:
                return domain
    except Exception:
        pass

    # 3. No match
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_exploration_loader.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add stream/exploration_loader.py tests/test_exploration_loader.py paixueji_prompts.py
git commit -m "feat: add infer_domain — mappings-first, Gemini-fallback domain classification"
```

---

### Task 4: Add dimension-level `activity_target` templates and `label` formatting

**Files:**
- Modify: `stream/exploration_loader.py`
- Modify: `tests/test_exploration_loader.py`

We need two pure functions: `sub_attribute_to_label()` and `dimension_to_activity_target()`. No LLM involved.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_exploration_loader.py`:

```python
from stream.exploration_loader import (
    sub_attribute_to_label,
    dimension_to_activity_target,
)


def test_sub_attribute_to_label_converts_snake_case():
    assert sub_attribute_to_label("body_color") == "body color"
    assert sub_attribute_to_label("fur_feel") == "fur feel"
    assert sub_attribute_to_label("paw_pads") == "paw pads"


def test_sub_attribute_to_label_handles_single_word():
    assert sub_attribute_to_label("size") == "size"
    assert sub_attribute_to_label("color") == "color"


def test_dimension_to_activity_target_returns_string():
    target = dimension_to_activity_target("appearance", "cat")
    assert "cat" in target
    assert isinstance(target, str)


def test_dimension_to_activity_target_covers_all_dimensions():
    for dim in ("appearance", "senses", "structure", "function", "context", "change"):
        target = dimension_to_activity_target(dim, "ball")
        assert isinstance(target, str)
        assert len(target) > 10


def test_dimension_to_activity_target_unknown_dimension():
    target = dimension_to_activity_target("unknown_dim", "ball")
    assert isinstance(target, str)  # returns generic fallback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exploration_loader.py::test_sub_attribute_to_label -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement in `stream/exploration_loader.py`**

Add to `stream/exploration_loader.py`:

```python
# Dimension-level activity target templates.
# {object} is replaced with the object name.
DIMENSION_ACTIVITY_TEMPLATES: dict[str, str] = {
    "appearance": "noticing and describing what {object} looks like",
    "senses": "exploring how {object} feels, sounds, or smells",
    "structure": "discovering the parts and materials of {object}",
    "function": "investigating what {object} does and how it is used",
    "context": "finding where and when you encounter {object}",
    "change": "observing how {object} changes over time",
}


def sub_attribute_to_label(sub_attribute: str) -> str:
    """Convert a snake_case sub_attribute name to a human-readable label."""
    return sub_attribute.replace("_", " ")


def dimension_to_activity_target(dimension: str, object_name: str) -> str:
    """
    Generate an activity_target string for a dimension + object.
    Falls back to a generic template if the dimension is unknown.
    """
    template = DIMENSION_ACTIVITY_TEMPLATES.get(
        dimension,
        "exploring {object}",
    )
    return template.format(object=object_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exploration_loader.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add stream/exploration_loader.py tests/test_exploration_loader.py
git commit -m "feat: add label formatting and dimension activity_target templates"
```

---

### Task 5: Rewrite `select_attribute_profile()` in `attribute_activity.py`

**Files:**
- Modify: `attribute_activity.py`
- Modify: `tests/test_attribute_activity_pipeline.py`

This is the core change: replace mock-based selection with dynamic YAML-driven selection.

- [ ] **Step 1: Write failing tests for the new `select_attribute_profile`**

The new function signature adds `anchor_status` (needed to set `branch`). The `domain` is resolved internally — not a parameter.

Add to `tests/test_attribute_activity_pipeline.py` (replacing existing tests that use mock profiles):

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from attribute_activity import (
    AttributeProfile,
    AttributeSessionState,
    build_attribute_debug,
    classify_attribute_reply,
    select_attribute_profile,
    start_attribute_session,
)


# --- select_attribute_profile tests ---


@pytest.mark.asyncio
async def test_select_attribute_profile_gemini_selects_from_dynamic_candidates():
    """Gemini returns a valid attribute_id from the dynamically generated candidates."""
    client = MagicMock()
    response = MagicMock()
    # New format: "dimension.sub_attribute"
    response.text = '{"attribute_id":"senses.taste","confidence":"high","reason":"smell is salient for food"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    profile, debug = await select_attribute_profile(
        object_name="cat food",
        age=6,
        anchor_status="anchored_high",
        client=client,
        config={"model_name": "gemini-test"},
    )

    assert profile is not None
    assert profile.attribute_id == "senses.taste"
    assert profile.label == "taste"
    assert "cat food" in profile.activity_target
    assert debug["decision"] == "attribute_selected"
    assert debug["source"] == "gemini"


@pytest.mark.asyncio
async def test_select_attribute_profile_falls_back_to_first_candidate_on_invalid_json():
    """When Gemini returns invalid JSON, the first candidate becomes the fallback."""
    client = MagicMock()
    response = MagicMock()
    response.text = "not json at all"
    client.aio.models.generate_content = AsyncMock(return_value=response)

    profile, debug = await select_attribute_profile(
        object_name="cat food",
        age=6,
        anchor_status="unresolved",
        client=client,
        config={"model_name": "gemini-test"},
    )

    assert profile is not None
    # Fallback is the first candidate; exact value depends on domain inference
    # but attribute_id should be in "dimension.sub_attribute" format
    assert "." in profile.attribute_id
    assert debug["source"] == "first_candidate_fallback"


@pytest.mark.asyncio
async def test_select_attribute_profile_returns_none_when_no_candidates():
    """Edge case: if somehow no candidates are generated, returns None."""
    # Age 3 with an extremely constrained scenario — in practice unlikely
    # but we test the path by monkeypatching get_candidate_sub_attributes
    from unittest.mock import patch

    client = MagicMock()
    with patch("attribute_activity.get_candidate_sub_attributes", return_value=[]):
        with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value=None):
            profile, debug = await select_attribute_profile(
                object_name="impossible thing",
                age=3,
                anchor_status="unresolved",
                client=client,
                config={"model_name": "gemini-test"},
            )

    assert profile is None
    assert debug["decision"] == "no_attribute_match_fallback"


@pytest.mark.asyncio
async def test_select_attribute_profile_uses_mappings_domain_for_known_object():
    """For objects in the mappings DB, domain is resolved from the entity, not Gemini."""
    client = MagicMock()

    # "cat" is in the mappings DB with domain="animals"
    # We need Gemini only for attribute selection, not domain inference
    response = MagicMock()
    response.text = '{"attribute_id":"appearance.body_color","confidence":"high","reason":"color is salient"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    profile, debug = await select_attribute_profile(
        object_name="cat",
        age=4,
        anchor_status="exact_supported",
        client=client,
        config={"model_name": "gemini-test"},
    )

    assert profile is not None
    assert profile.branch == "in_kb"


@pytest.mark.asyncio
async def test_select_attribute_profile_branch_unresolved_for_unresolved_anchor():
    """Unresolved anchor_status results in branch="unresolved_not_in_kb"."""
    client = MagicMock()
    response = MagicMock()
    response.text = '{"attribute_id":"appearance.color","confidence":"medium","reason":"generic attribute"}'
    client.aio.models.generate_content = AsyncMock(return_value=response)

    # "quantum computer" is not in mappings → domain=None → default sub_attributes
    with patch("attribute_activity.infer_domain", new_callable=AsyncMock, return_value=None):
        profile, debug = await select_attribute_profile(
            object_name="quantum computer",
            age=6,
            anchor_status="unresolved",
            client=client,
            config={"model_name": "gemini-test"},
        )

    assert profile is not None
    assert profile.branch == "unresolved_not_in_kb"


# --- classify_attribute_reply tests (unchanged behavior, new attribute_id format) ---


def test_classify_attribute_reply_preserves_selected_attribute():
    """classify_attribute_reply still works with new attribute_id format."""
    profile = AttributeProfile(
        attribute_id="appearance.body_color",
        label="body color",
        activity_target="noticing and describing what cat looks like",
        branch="in_kb",
        object_examples=("cat",),
    )
    state = start_attribute_session(object_name="cat", profile=profile, age=6)

    decision = classify_attribute_reply(state, "It has brown fur")
    assert decision.attribute_id == "appearance.body_color"
    assert decision.reply_type == "aligned"
    assert decision.counted_turn is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_attribute_activity_pipeline.py -v`
Expected: FAIL — `TypeError: select_attribute_profile() got an unexpected keyword argument 'anchor_status'`

- [ ] **Step 3: Rewrite `attribute_activity.py`**

Replace the entire `attribute_activity.py` with:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass

import paixueji_prompts
from model_json import extract_json_object
from stream.exploration_loader import (
    SubAttributeCandidate,
    get_candidate_sub_attributes,
    infer_domain,
    sub_attribute_to_label,
    dimension_to_activity_target,
)


@dataclass(frozen=True)
class AttributeProfile:
    attribute_id: str
    label: str
    activity_target: str
    branch: str
    object_examples: tuple[str, ...]
    redirect_entity: str | None = None


@dataclass
class AttributeSessionState:
    object_name: str
    profile: AttributeProfile
    age: int
    turn_count: int = 0
    activity_ready: bool = False
    last_question: str | None = None
    surface_object_name: str | None = None
    anchor_object_name: str | None = None

    def to_debug_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AttributeReplyDecision:
    reply_type: str
    attribute_id: str
    counted_turn: bool
    activity_ready: bool
    state_action: str
    reason: str

    def to_debug_dict(self) -> dict:
        return asdict(self)


def _normalize(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def _anchor_status_to_branch(anchor_status: str | None) -> str:
    """Map anchor_status to attribute branch."""
    if anchor_status == "exact_supported":
        return "in_kb"
    if anchor_status in ("anchored_high", "anchored_medium"):
        return "anchored_not_in_kb"
    return "unresolved_not_in_kb"


def _candidate_to_profile(
    candidate: SubAttributeCandidate,
    object_name: str,
    branch: str,
) -> AttributeProfile:
    """Convert a SubAttributeCandidate to an AttributeProfile."""
    return AttributeProfile(
        attribute_id=f"{candidate.dimension}.{candidate.sub_attribute}",
        label=sub_attribute_to_label(candidate.sub_attribute),
        activity_target=dimension_to_activity_target(candidate.dimension, object_name),
        branch=branch,
        object_examples=(object_name,),
    )


def _build_supported_attribute_block(profiles: tuple[AttributeProfile, ...]) -> str:
    """Build the text block listing all candidate attributes for the Gemini prompt."""
    lines = []
    for profile in profiles:
        lines.append(
            f"- {profile.attribute_id}: {profile.label}; activity={profile.activity_target}; "
            f"branch={profile.branch}"
        )
    return "\n".join(lines)


async def select_attribute_profile(
    *,
    object_name: str,
    age: int | None,
    anchor_status: str | None = None,
    client,
    config: dict | None,
) -> tuple[AttributeProfile | None, dict]:
    """
    Select an attribute profile for the given object.

    Dynamically generates candidates from exploration_categories.yaml
    based on the surface object's domain and the child's age tier.
    Then asks Gemini to pick the best one.

    Args:
        object_name: The surface object the child named.
        age: Child's age.
        anchor_status: From object resolution — determines the branch.
        client: Gemini client.
        config: Config dict with model_name.

    Returns:
        (AttributeProfile | None, debug_dict)
    """
    resolved_age = age or 6
    branch = _anchor_status_to_branch(anchor_status)

    # Determine domain for the surface object
    domain = await infer_domain(object_name, client, config)

    # Generate candidates from YAML
    candidates = get_candidate_sub_attributes(domain, resolved_age)

    if not candidates:
        return None, {
            "decision": "no_attribute_match_fallback",
            "source": "empty_candidates",
            "attribute_id": None,
            "confidence": None,
            "reason": f"no candidates for domain={domain}, age={resolved_age}",
            "domain": domain,
        }

    # Convert all candidates to profiles
    profiles = tuple(
        _candidate_to_profile(c, object_name, branch) for c in candidates
    )

    # Ask Gemini to select
    prompt = paixueji_prompts.get_prompts()["attribute_selection_prompt"].format(
        object_name=object_name,
        age=resolved_age,
        domain=domain or "unknown",
        supported_attributes=_build_supported_attribute_block(profiles),
    )

    try:
        response = await client.aio.models.generate_content(
            model=(config or {}).get("model_name"),
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 120},
        )
        payload, payload_kind, recovered = extract_json_object(response.text or "")
    except Exception as exc:
        payload = None
        payload_kind = "exception"
        recovered = False
        exc_reason = str(exc)
    else:
        exc_reason = None

    # Try to match Gemini's choice to a profile
    if isinstance(payload, dict):
        chosen_id = payload.get("attribute_id")
        for profile in profiles:
            if profile.attribute_id == chosen_id:
                return profile, {
                    "decision": "attribute_selected",
                    "source": "gemini",
                    "attribute_id": profile.attribute_id,
                    "confidence": payload.get("confidence"),
                    "reason": payload.get("reason") or "selected by Gemini",
                    "payload_kind": payload_kind,
                    "json_recovery_applied": recovered,
                    "domain": domain,
                }

    # Fallback: use the first candidate
    fallback = profiles[0]
    return fallback, {
        "decision": "attribute_selected",
        "source": "first_candidate_fallback",
        "attribute_id": fallback.attribute_id,
        "confidence": "fallback",
        "reason": exc_reason or f"invalid Gemini attribute selection payload: {payload_kind}",
        "payload_kind": payload_kind,
        "json_recovery_applied": recovered,
        "domain": domain,
    }


def start_attribute_session(
    *,
    object_name: str,
    profile: AttributeProfile,
    age: int | None,
    surface_object_name: str | None = None,
    anchor_object_name: str | None = None,
) -> AttributeSessionState:
    if profile is None:
        raise ValueError("profile is required to start an attribute session")
    return AttributeSessionState(
        object_name=object_name,
        profile=profile,
        age=age or 6,
        surface_object_name=surface_object_name,
        anchor_object_name=anchor_object_name,
    )


def classify_attribute_reply(
    state: AttributeSessionState,
    child_reply: str | None,
) -> AttributeReplyDecision:
    text = _normalize(child_reply)
    object_name = _normalize(state.object_name)
    attribute_words = set(_normalize(state.profile.label).replace("/", " ").split())

    if any(token in text for token in ("don't know", "dont know", "not sure", "idk", "maybe")):
        return AttributeReplyDecision(
            reply_type="uncertainty",
            attribute_id=state.profile.attribute_id,
            counted_turn=False,
            activity_ready=False,
            state_action="scaffold_attribute",
            reason="child expressed uncertainty",
        )

    if any(token in text for token in ("can't", "cannot", "dont want", "don't want", "stop", "no more")):
        return AttributeReplyDecision(
            reply_type="constraint_avoidance",
            attribute_id=state.profile.attribute_id,
            counted_turn=False,
            activity_ready=False,
            state_action="low_pressure_repair",
            reason="child expressed constraint or avoidance",
        )

    if any(token in text for token in ("let's", "lets", "game", "play", "activity", "ready")):
        return AttributeReplyDecision(
            reply_type="activity_ready",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=True,
            state_action="handoff_to_activity",
            reason="child is ready for activity",
        )

    if "?" in (child_reply or "") or text.startswith(("why ", "how ", "what ", "where ", "can ")):
        return AttributeReplyDecision(
            reply_type="curiosity",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=False,
            state_action="answer_and_reconnect",
            reason="child asked a curiosity question",
        )

    drift_words = {"crunchy", "sweet", "color", "red", "green", "tail", "eyes", "bowl"}
    text_words = set(text.split())
    if object_name and object_name in text and drift_words.intersection(text_words) and not attribute_words.intersection(text_words):
        return AttributeReplyDecision(
            reply_type="same_object_feature_drift",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=False,
            state_action="accept_then_return_to_attribute",
            reason="child stayed on object but shifted feature",
        )

    other_object_words = {"spoon", "ball", "toy", "car", "rock", "cup", "bowl", "blanket"}
    if attribute_words.intersection(text_words) and other_object_words.intersection(text_words) and object_name not in text:
        return AttributeReplyDecision(
            reply_type="new_object_same_attribute_drift",
            attribute_id=state.profile.attribute_id,
            counted_turn=True,
            activity_ready=False,
            state_action="accept_comparison_keep_attribute",
            reason="child named another object with same attribute",
        )

    return AttributeReplyDecision(
        reply_type="aligned",
        attribute_id=state.profile.attribute_id,
        counted_turn=True,
        activity_ready=False,
        state_action="continue_attribute_lane",
        reason="child stayed aligned with selected attribute",
    )


def build_attribute_debug(
    *,
    decision: str,
    profile: AttributeProfile | None,
    state: AttributeSessionState | None,
    reason: str | None = None,
    reply: dict | None = None,
    response_text: str | None = None,
) -> dict:
    return {
        "decision": decision,
        "profile": asdict(profile) if profile else None,
        "state": state.to_debug_dict() if state else None,
        "reason": reason,
        "reply": reply.to_debug_dict() if hasattr(reply, "to_debug_dict") else reply,
        "response_text": response_text,
    }
```

Key changes from the original:
- **Deleted:** `MOCK_ATTRIBUTE_PROFILES`, `find_mock_attribute_profile`, `_profile_by_id`, `_supported_attribute_block` (old version)
- **New:** `_anchor_status_to_branch`, `_candidate_to_profile`, `_build_supported_attribute_block` (new version with `AttributeProfile` input)
- **Changed:** `select_attribute_profile` now takes `anchor_status` param, resolves domain internally via `infer_domain()`, generates candidates dynamically, fallback is first candidate instead of mock lookup

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/test_attribute_activity_pipeline.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add attribute_activity.py tests/test_attribute_activity_pipeline.py
git commit -m "feat: rewrite select_attribute_profile with dynamic YAML-driven candidates"
```

---

### Task 6: Update `ATTRIBUTE_SELECTION_PROMPT` in `paixueji_prompts.py`

**Files:**
- Modify: `paixueji_prompts.py`

- [ ] **Step 1: Update the prompt**

Replace `ATTRIBUTE_SELECTION_PROMPT` (around line 344) with:

```python
ATTRIBUTE_SELECTION_PROMPT = """Choose one supported activity attribute for a child chat.

OBJECT: {object_name}
CHILD AGE: {age}
DOMAIN: {domain}

SUPPORTED ATTRIBUTES:
{supported_attributes}

Return JSON only:
{{
  "attribute_id": "one supported attribute id (format: dimension.sub_attribute), or null",
  "confidence": "high|medium|low|none",
  "reason": "short reason"
}}

Choose the attribute most naturally connected to this object.
If domain is "unknown", prefer attributes from appearance or senses dimensions.
The attribute_id must exactly match one from the SUPPORTED ATTRIBUTES list."""
```

- [ ] **Step 2: Verify prompt renders correctly**

```python
python3 -c "
import paixueji_prompts
p = paixueji_prompts.get_prompts()['attribute_selection_prompt']
rendered = p.format(object_name='cat', age=4, domain='animals', supported_attributes='- appearance.body_color: body color\n- senses.fur_feel: fur feel')
print(rendered)
"
```

Expected: rendered prompt contains "OBJECT: cat", "DOMAIN: animals", and the candidate list.

- [ ] **Step 3: Commit**

```bash
git add paixueji_prompts.py
git commit -m "feat: update ATTRIBUTE_SELECTION_PROMPT for dynamic candidate format"
```

---

### Task 7: Update `paixueji_app.py` call site

**Files:**
- Modify: `paixueji_app.py`

The `select_attribute_profile()` call in `/api/start` needs to pass `anchor_status`. The `object_name` should be the **surface object name** (not the anchor).

- [ ] **Step 1: Update the call at line ~616**

Find:

```python
select_attribute_profile(
    object_name=object_name,
    age=age or 6,
    client=assistant.client,
    config=assistant.config,
),
```

Replace with:

```python
select_attribute_profile(
    object_name=object_name,
    age=age or 6,
    anchor_status=assistant.anchor_status,
    client=assistant.client,
    config=assistant.config,
),
```

Note: `object_name` is already the surface object name from the request. `assistant.anchor_status` is already set via `apply_resolution()` at line 611. No other changes needed.

- [ ] **Step 2: Search for any other call sites of `select_attribute_profile`**

```bash
grep -n "select_attribute_profile" paixueji_app.py
```

There should be only the one call at ~line 616.

- [ ] **Step 3: Run existing tests to check for regressions**

Run: `pytest tests/test_all_endpoints.py -v -k "start"`
Expected: PASS (the mock Gemini client in conftest returns valid JSON; the new `anchor_status` param has a default of `None`)

- [ ] **Step 4: Commit**

```bash
git add paixueji_app.py
git commit -m "feat: pass anchor_status to select_attribute_profile in /api/start"
```

---

### Task 8: Update `stream/__init__.py` re-exports

**Files:**
- Modify: `stream/__init__.py`

- [ ] **Step 1: Add re-exports for new public symbols**

Add after the existing `from .fun_fact` import block:

```python
# Exploration categories
from .exploration_loader import (
    get_candidate_sub_attributes,
    infer_domain,
    SubAttributeCandidate,
    sub_attribute_to_label,
    dimension_to_activity_target,
    ALL_DOMAINS,
)
```

Add to `__all__`:

```python
    # Exploration categories
    'get_candidate_sub_attributes',
    'infer_domain',
    'SubAttributeCandidate',
    'sub_attribute_to_label',
    'dimension_to_activity_target',
    'ALL_DOMAINS',
```

- [ ] **Step 2: Verify import works**

```bash
python3 -c "from stream import get_candidate_sub_attributes, infer_domain, ALL_DOMAINS; print(f'ALL_DOMAINS: {len(ALL_DOMAINS)} domains')"
```

Expected: `ALL_DOMAINS: 14 domains`

- [ ] **Step 3: Commit**

```bash
git add stream/__init__.py
git commit -m "feat: re-export exploration_loader symbols from stream module"
```

---

### Task 9: Update existing test files for removed mock symbols

**Files:**
- Modify: `tests/test_attribute_activity_pipeline.py` (already updated in Task 5)
- Modify: any other test files importing `find_mock_attribute_profile` or `MOCK_ATTRIBUTE_PROFILES`

- [ ] **Step 1: Find all test files referencing removed symbols**

```bash
grep -rn "find_mock_attribute_profile\|MOCK_ATTRIBUTE_PROFILES" tests/
```

- [ ] **Step 2: Update each file**

For any file importing `find_mock_attribute_profile`:
- Replace usage with direct `AttributeProfile` construction, e.g.:

```python
# Before
profile = find_mock_attribute_profile("apple")

# After
profile = AttributeProfile(
    attribute_id="appearance.color",
    label="color",
    activity_target="noticing and describing what apple looks like",
    branch="in_kb",
    object_examples=("apple",),
)
```

For any test asserting `attribute_id == "surface_shiny_smooth"`:
- Update to the new format `"appearance.color"` or whichever candidate is appropriate for the test scenario.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --timeout=30`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "fix: update test files for removed mock attribute symbols"
```

---

### Task 10: Integration verification — three key scenarios

**Files:**
- No new files — verify with existing test infrastructure

- [ ] **Step 1: Test scenario 1 — In-KB object ("cat", age=4)**

```bash
pytest tests/test_all_endpoints.py -v -k "start" --timeout=30
```

Verify in the attribute_debug output:
- `domain` = `"animals"`
- `attribute_id` starts with `"appearance."` or `"senses."` (tier 0 dimensions only for age 4)
- `branch` = `"in_kb"`

- [ ] **Step 2: Test scenario 2 — Out-of-KB object with anchor ("cat food", age=6)**

This requires the mock Gemini client to return a domain inference response AND an attribute selection response. Verify that:
- `domain` resolves to `"food"` (from Gemini domain inference)
- `attribute_id` uses food-domain sub_attributes (e.g., `"senses.taste"`, `"senses.smell"`)
- `branch` = `"anchored_not_in_kb"`

- [ ] **Step 3: Test scenario 3 — Completely unresolved object ("quantum computer", age=7)**

Verify that:
- `domain` = `null` (Gemini can't classify or returns unknown domain)
- Candidates come from `default` sub_attributes
- `branch` = `"unresolved_not_in_kb"`
- At minimum, `appearance.color`, `appearance.shape`, `senses.feel` etc. appear as candidates

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v --timeout=60`
Expected: All PASS

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: exploration categories YAML activation — replace mock profiles with dynamic candidates"
```

---

## Summary of key design decisions

| Decision | Rationale |
|:---|:---|
| Domain is determined by **surface object**, never anchor | "cat food" → domain=food, not animals. Anchor domain is for bridge pipeline only. |
| `infer_domain()` tries mappings first, then Gemini, then None | Mappings lookup is free; Gemini is a cheap single-call fallback; None → default sub_attributes. |
| `attribute_id` format: `"dimension.sub_attribute"` | Namespace collision prevention; easy to parse; human-readable. |
| Fallback is first candidate, not None | Better UX: always have *something* to talk about, even if Gemini's choice is invalid. |
| Engagement dimensions NOT in attribute candidate pool | They serve a different purpose (follow-up question generation via `db_loader.py`). Can be extended later. |
| `anchor_status` as parameter, `domain` resolved internally | `select_attribute_profile` is self-contained — caller doesn't need to know about domain inference. |
