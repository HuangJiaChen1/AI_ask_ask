from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_JS = PROJECT_ROOT / "static" / "app.js"
REPORTS_JS = PROJECT_ROOT / "static" / "reports.js"


def test_primary_view_controller_exists():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "window.paixuejiUi = {" in app_js
    assert "showMainPage()" in app_js
    assert "showChatPage()" in app_js
    assert "showReportsPage()" in app_js
    assert "leaveReportsPage()" in app_js


def test_chat_visibility_routes_through_controller():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "window.paixuejiUi.showMainPage();" in app_js
    assert "window.paixuejiUi.showChatPage();" in app_js
    assert "window.paixuejiUi.setLearningAnchorVisible(learningAnchorActive);" in app_js
    assert "window.paixuejiUi.setManualSwitchVisible(true);" in app_js
    assert "window.paixuejiUi.setManualSwitchVisible(false);" in app_js


def test_reports_page_uses_controller_and_restores_previous_view():
    reports_js = REPORTS_JS.read_text(encoding="utf-8")

    assert "window.paixuejiUi.showReportsPage();" in reports_js
    assert "window.paixuejiUi.leaveReportsPage();" in reports_js
    assert "document.getElementById('startForm').style.display" not in reports_js


def test_reports_close_clears_report_overlays():
    reports_js = REPORTS_JS.read_text(encoding="utf-8")

    assert "closeRvCritiquePopup();" in reports_js
    assert "closeRvRawModal();" in reports_js
