from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_JS = PROJECT_ROOT / "static" / "app.js"
INDEX_HTML = PROJECT_ROOT / "static" / "index.html"


def test_frontend_progress_uses_threshold_two():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "const CORRECT_ANSWER_THRESHOLD = 2;" in app_js
    assert "Correct answers: ${correctAnswerCount}/${CORRECT_ANSWER_THRESHOLD}" in app_js
    assert "correctAnswerCount / CORRECT_ANSWER_THRESHOLD" in app_js
    assert "`${correctAnswerCount}/4`" not in app_js


def test_frontend_default_progress_labels_show_two():
    index_html = INDEX_HTML.read_text(encoding="utf-8")

    assert "Correct answers: 0/2" in index_html
    assert 'id="debugCorrectCount">0/2<' in index_html
    assert "Correct answers: 0/4" not in index_html
