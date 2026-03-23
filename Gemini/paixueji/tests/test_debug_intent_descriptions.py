from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
INDEX_HTML = PROJECT_ROOT / "static" / "index.html"
APP_JS = PROJECT_ROOT / "static" / "app.js"
APP_PY = PROJECT_ROOT / "paixueji_app.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_debug_panel_has_intent_description_element():
    html = _read(INDEX_HTML)
    assert 'id="debugIntentDescription"' in html, (
        "debug intent description element missing from index.html"
    )


def test_debug_panel_has_response_description_element():
    html = _read(INDEX_HTML)
    assert 'id="debugResponseDescription"' in html, (
        "debug response description element missing from index.html"
    )


def test_debug_panel_has_classifier_failure_elements():
    html = _read(INDEX_HTML)
    assert 'id="debugClassificationStatus"' in html, (
        "debug classifier status element missing from index.html"
    )
    assert 'id="debugClassificationReason"' in html, (
        "debug classifier reason element missing from index.html"
    )


def test_app_js_defines_plain_english_intent_descriptions():
    js = _read(APP_JS)
    assert 'SOCIAL_ACKNOWLEDGMENT' in js, "expected SOCIAL_ACKNOWLEDGMENT mapping in app.js"
    assert 'The child is reacting briefly to what the assistant said.' in js, (
        "plain-English SOCIAL_ACKNOWLEDGMENT description missing from app.js"
    )
    assert 'CURIOSITY' in js, "expected CURIOSITY mapping in app.js"
    assert 'The child is asking to learn more about the topic.' in js, (
        "plain-English CURIOSITY description missing from app.js"
    )
    assert '孩子只是在简短回应助手刚才说的话。' in js, (
        "Chinese SOCIAL_ACKNOWLEDGMENT description missing from app.js"
    )
    assert '孩子正在提问，想更了解这个话题。' in js, (
        "Chinese CURIOSITY description missing from app.js"
    )


def test_app_js_defines_plain_english_response_descriptions():
    js = _read(APP_JS)
    assert 'SOCIAL_ACKNOWLEDGMENT' in js, "expected social acknowledgment response mapping in app.js"
    assert 'The assistant gives a brief warm reaction without repeating the same fact.' in js, (
        "plain-English social acknowledgment response description missing from app.js"
    )
    assert 'QUESTION' in js, "expected guide question response mapping in app.js"
    assert 'The assistant is starting a discovery question to guide the child toward a bigger idea.' in js, (
        "plain-English guide question response description missing from app.js"
    )
    assert '助手会先给一个简短温暖的回应，不重复刚才的事实。' in js, (
        "Chinese social acknowledgment response description missing from app.js"
    )
    assert '助手正在用一个发现式问题，引导孩子走向更大的核心想法。' in js, (
        "Chinese guide question response description missing from app.js"
    )


def test_app_js_handles_classification_failure_debug_state():
    js = _read(APP_JS)
    assert 'classification_status' in js, "app.js must read chunk.classification_status"
    assert 'debugClassificationStatus' in js, "app.js must update the debug classifier status element"
    assert 'debugClassificationReason' in js, "app.js must update the debug classifier reason element"
    assert "'intent_type' in chunk" in js or '"intent_type" in chunk' in js, (
        "app.js must clear stale intent state by checking property presence, not truthiness"
    )


def test_paixueji_app_propagates_classification_failure_metadata():
    source = _read(APP_PY)
    assert '"classification_status": chunk.classification_status' in source, (
        "paixueji_app.py must persist classification_status on assistant transcript messages"
    )
    assert '"classification_failure_reason": chunk.classification_failure_reason' in source, (
        "paixueji_app.py must persist classification_failure_reason on assistant transcript messages"
    )
    assert 'entry["classification_status"] = msg.get("classification_status")' in source, (
        "transcript builders must include classification_status for model messages"
    )
    assert 'entry["classification_failure_reason"] = msg.get("classification_failure_reason")' in source, (
        "transcript builders must include classification_failure_reason for model messages"
    )
