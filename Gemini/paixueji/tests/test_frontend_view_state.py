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
    assert "if (chunk.finish && (chunk.chat_phase_complete || chunk.activity_ready)) {" in app_js
    assert app_js.count("if (!conversationComplete) {") >= 2
    assert app_js.count("disableCompletedChatInput();") >= 4


def test_activities_launcher_has_visible_bottom_left_design():
    style_css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".activities-mini-launcher" in style_css
    assert "bottom: 20px" in style_css
    assert "left: 20px" in style_css
    assert "@keyframes activities-mini-pulse" in style_css
    assert "z-index: 1900" in style_css


def test_frontend_sends_attribute_pipeline_toggle():
    app_js = APP_JS.read_text(encoding="utf-8")
    index_html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="attributePipelineEnabled"' in index_html
    assert "attributePipelineEnabled" in app_js
    assert "attribute_pipeline_enabled" in app_js


def test_frontend_sends_category_pipeline_toggle_and_enforces_mutual_exclusion():
    app_js = APP_JS.read_text(encoding="utf-8")
    index_html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="categoryPipelineEnabled"' in index_html
    assert "categoryPipelineEnabled" in app_js
    assert "category_pipeline_enabled" in app_js
    assert "addEventListener('change'" in app_js
    assert "attributePipelineEnabled" in app_js


def test_attribute_activity_ready_uses_existing_activity_launcher():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "currentAttributeActivityTarget" in app_js
    assert "chunk.activity_target" in app_js
    assert "chunk.activity_ready" in app_js
    assert "function hasAttributeActivityReady()" in app_js
    assert "isCurrentObjectGameEligible() || hasAttributeActivityReady()" in app_js
    assert "if (isCurrentObjectGameEligible() || hasAttributeActivityReady())" in app_js


def test_category_activity_ready_uses_existing_activity_launcher():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "activity_source === 'category'" in app_js


def test_debug_panel_exposes_attribute_debug_fields():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "Attribute Debug:" in html
    for field_id in (
        "debugAttributePipeline",
        "debugAttributeLane",
        "debugAttributeId",
        "debugAttributeLabel",
        "debugAttributeActivityTarget",
        "debugAttributeBranch",
        "debugAttributeReplyType",
    ):
        assert f'id="{field_id}"' in html


def test_debug_panel_exposes_category_debug_fields():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "Category Debug:" in html
    for field_id in (
        "debugCategoryPipeline",
        "debugCategoryLane",
        "debugCategoryId",
        "debugCategoryLabel",
        "debugCategoryActivityTarget",
        "debugCategoryReplyType",
        "debugCategoryDecision",
    ):
        assert f'id="{field_id}"' in html


def test_frontend_renders_attribute_debug_payload():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "let currentAttributeDebug = null;" in app_js
    assert "let currentAttributePipelineEnabled = false;" in app_js
    assert "let currentAttributeLaneActive = false;" in app_js
    assert "currentAttributeDebug = null;" in app_js
    assert "currentAttributePipelineEnabled = false;" in app_js
    assert "currentAttributeLaneActive = false;" in app_js
    assert "currentAttributeDebug = chunk.attribute_debug;" in app_js
    assert "currentAttributePipelineEnabled = !!chunk.attribute_pipeline_enabled;" in app_js
    assert "currentAttributeLaneActive = !!chunk.attribute_lane_active;" in app_js
    assert "const attributeProfile = attributeDebug.profile || {};" in app_js
    assert "setText('debugAttributeId', attributeProfile.attribute_id);" in app_js
    assert "setText('debugAttributeReplyType', attributeReply.reply_type);" in app_js


def test_frontend_renders_category_debug_payload():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "let currentCategoryDebug = null;" in app_js
    assert "let currentCategoryPipelineEnabled = false;" in app_js
    assert "let currentCategoryLaneActive = false;" in app_js
    assert "currentCategoryDebug = null;" in app_js
    assert "currentCategoryPipelineEnabled = false;" in app_js
    assert "currentCategoryLaneActive = false;" in app_js
    assert "currentCategoryDebug = chunk.category_debug;" in app_js
    assert "currentCategoryPipelineEnabled = !!chunk.category_pipeline_enabled;" in app_js
    assert "currentCategoryLaneActive = !!chunk.category_lane_active;" in app_js
    assert "const categoryProfile = categoryDebug.profile || {};" in app_js
    assert "setText('debugCategoryId', categoryProfile.category_id);" in app_js
    assert "setText('debugCategoryReplyType', categoryReply.reply_type);" in app_js
