# tests/test_switch_marker.py
import pytest
from stream.response_generators import detect_switch_marker


def test_detect_switch_marker_found():
    text = "Let us switch! [SWITCH_TO:appearance.shape]\nREASON: child said round"
    target, cleaned = detect_switch_marker(text)
    assert target == "appearance.shape"
    assert "[SWITCH_TO" not in cleaned


def test_detect_switch_marker_not_found():
    text = "What color do you see?"
    target, cleaned = detect_switch_marker(text)
    assert target is None
    assert cleaned == text


def test_detect_switch_marker_multiline():
    text = "Wow, you noticed the size!\n[SWITCH_TO:appearance.size]"
    target, cleaned = detect_switch_marker(text)
    assert target == "appearance.size"
