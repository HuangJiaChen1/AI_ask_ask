import pytest
from unittest.mock import AsyncMock, MagicMock
from stream.exploration_loader import (
    SubAttributeCandidate,
    get_candidate_sub_attributes,
    infer_domain,
    sub_attribute_to_label,
    dimension_to_activity_target,
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
