# tests/test_activity_catalog.py
import pytest
from activities import get_activity_for_attribute, list_activities_for_attribute


def test_get_activity_for_color():
    activity = get_activity_for_attribute("appearance.color", 5)
    assert activity is not None
    assert activity.activity_id == "color_exploration_v1"


def test_get_activity_for_shape():
    activity = get_activity_for_attribute("appearance.shape", 5)
    assert activity is not None
    assert activity.activity_id == "shape_exploration_v1"


def test_get_activity_no_match():
    activity = get_activity_for_attribute("nonexistent.attribute", 5)
    assert activity is None


def test_tier_filtering():
    assert get_activity_for_attribute("appearance.color", 3) is not None
    assert get_activity_for_attribute("appearance.color", 8) is not None
