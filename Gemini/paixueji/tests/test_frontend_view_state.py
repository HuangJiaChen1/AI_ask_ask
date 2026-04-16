from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_JS = PROJECT_ROOT / "static" / "app.js"
REPORTS_JS = PROJECT_ROOT / "static" / "reports.js"
INDEX_HTML = PROJECT_ROOT / "static" / "index.html"
STYLE_CSS = PROJECT_ROOT / "static" / "style.css"


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


def test_chat_complete_modal_has_close_and_activities_launcher():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="chatCompleteCloseBtn"' in html
    assert 'id="chatCompletePrimaryBtn"' in html
    assert 'id="activitiesMiniLauncher"' in html
    assert 'onclick="minimizeChatPhaseCompleteModal()"' in html
    assert 'onclick="restoreChatPhaseCompleteModal()"' in html
    assert "Activities are ready" in html
    assert "Wonderlens" not in html


def test_chat_complete_modal_routes_game_handoff_through_reopenable_launcher():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "function isCurrentObjectGameEligible()" in app_js
    assert ".toLowerCase()" in app_js
    assert "function setActivitiesMiniLauncherVisible(visible)" in app_js
    assert "setActivitiesMiniLauncherVisible(true);" in app_js
    assert "setActivitiesMiniLauncherVisible(false);" in app_js
    assert "function minimizeChatPhaseCompleteModal()" in app_js
    assert "function restoreChatPhaseCompleteModal()" in app_js


def test_chat_complete_keeps_input_disabled_after_stream_finally():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "conversationComplete = true;" in app_js
    assert "if (chunk.finish && chunk.chat_phase_complete) {" in app_js
    assert app_js.count("if (!conversationComplete) {") >= 2
    assert app_js.count("disableCompletedChatInput();") >= 4


def test_activities_launcher_has_visible_bottom_left_design():
    style_css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".activities-mini-launcher" in style_css
    assert "bottom: 20px" in style_css
    assert "left: 20px" in style_css
    assert "@keyframes activities-mini-pulse" in style_css
    assert "z-index: 1900" in style_css
