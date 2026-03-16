from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
INDEX_HTML = PROJECT_ROOT / "static" / "index.html"
APP_JS = PROJECT_ROOT / "static" / "app.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_debug_panel_has_intent_description_element():
    html = _read(INDEX_HTML)
    assert 'id="debugIntentDescription"' in html, (
        "debug intent description element missing from index.html"
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
