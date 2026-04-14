from pathlib import Path
import re

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HF_DIR = REPO_ROOT / "reports" / "HF"
INDEX_HTML = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
REPORTS_JS = (REPO_ROOT / "static" / "reports.js").read_text(encoding="utf-8")
STYLE_CSS = (REPO_ROOT / "static" / "style.css").read_text(encoding="utf-8")
APP_JS = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")


def _hf_reports():
    reports = sorted(HF_DIR.glob("*/*.md"))
    if not reports:
        pytest.skip("No HF reports are checked into this workspace")
    return reports


def _hf_report_url(report_path: Path) -> str:
    return f"/api/reports/hf/{report_path.parent.name}/{report_path.name}"


def test_report_viewer_shell_is_wired_into_index(client):
    response = client.get("/")

    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'id="reportsBtn"' in html
    assert 'onclick="openReportsViewer()"' in html
    assert 'id="reportViewer"' in html
    assert 'id="rvCritiquePopup"' in html
    assert 'id="rvRawModal"' in html
    assert '<script src="/static/reports.js"></script>' in html


def test_hf_reports_api_returns_full_corpus_with_metadata(client):
    response = client.get("/api/reports/hf")

    assert response.status_code == 200

    reports = response.get_json()
    expected_count = len(_hf_reports())

    assert expected_count >= 1
    assert len(reports) == expected_count
    assert reports[0]["date"] >= reports[-1]["date"]

    first = reports[0]
    assert set(first) == {"date", "filename", "meta"}
    assert first["filename"].endswith(".md")
    assert {"object", "date", "key_concept", "exchanges_critiqued", "exchanges_total"} <= set(first["meta"])


def test_hf_report_detail_exposes_transcript_and_critique_data(client):
    report_path = next((path for path in _hf_reports() if "banana" in path.name), _hf_reports()[0])
    response = client.get(_hf_report_url(report_path))

    assert response.status_code == 200

    report = response.get_json()
    assert report["date"] == report_path.parent.name
    assert report["filename"] == report_path.name
    assert report["meta"]["object"]
    assert report["meta"]["exchanges_critiqued"] >= 1
    assert report["meta"]["exchanges_total"] >= 1
    assert isinstance(report["global_conclusion"], str)

    child_turns = [turn for turn in report["transcript"] if turn["role"] == "child"]
    model_turns = [turn for turn in report["transcript"] if turn["role"] == "model"]

    assert child_turns
    assert model_turns
    assert any(turn["phase"] == "CHAT" for turn in model_turns)

    critiqued_turns = [turn for turn in model_turns if turn["critique"]]
    assert len(critiqued_turns) == 1
    critique = critiqued_turns[0]["critique"]
    assert critique["phase"] == "CHAT"
    assert critique["problematic"] == "Test"
    assert critique["conclusion"] == "Test"
    assert critique["node_trace"]


def test_hf_report_raw_endpoint_returns_exact_markdown(client):
    report_path = next((path for path in _hf_reports() if "apple" in path.name), _hf_reports()[0])
    parsed = client.get(_hf_report_url(report_path)).get_json()
    response = client.get(f"{_hf_report_url(report_path)}/raw")

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert response.get_data(as_text=True) == report_path.read_text(encoding="utf-8")

    critiqued_turn = next(
        turn for turn in parsed["transcript"]
        if turn["role"] == "model" and turn["critique"]
    )
    assert critiqued_turn["critique"]["problematic"] == "None"
    assert critiqued_turn["critique"]["conclusion"] == "Solid exchange"


def test_frontend_assets_cover_search_critique_badges_and_none_state():
    assert "placeholder=\"Search by object" in REPORTS_JS
    assert "fetch('/api/reports/hf')" in REPORTS_JS
    assert "data-exchange-idx" in REPORTS_JS
    assert "rv-crit-badge" in REPORTS_JS
    assert "rv-debug-badge" in REPORTS_JS
    assert "crit.problematic.toLowerCase() !== 'none'" in REPORTS_JS
    assert "turn.bridge_verdict" in REPORTS_JS
    assert "turn.bridge_debug" in REPORTS_JS
    assert "No human critique" in REPORTS_JS
    assert "No issues ✓" in REPORTS_JS
    assert "rv-panel-green" in REPORTS_JS
    assert "showRvRawModal" in REPORTS_JS
    assert "Bridge Verdict" in REPORTS_JS
    assert "rvPopupBridgeDebug" in REPORTS_JS
    assert "rvFormatBridgeDebug" in REPORTS_JS
    assert "Activation Transition" in REPORTS_JS
    assert "crit.bridge_verdict" in REPORTS_JS
    assert "crit.bridge_debug" in REPORTS_JS
    assert "currentBridgeDebug = null;" in APP_JS

    assert "@keyframes rv-critique-pulse" in STYLE_CSS
    assert ".rv-bubble-critiqued" in STYLE_CSS
    assert ".rv-bubble-debug" in STYLE_CSS
    assert "#rvRawModal" in STYLE_CSS


def test_frontend_assets_cover_critiqued_response_panel_and_pre_wrap():
    assert "rvPopupCritiquedResponse" in INDEX_HTML
    assert "rvPopupResponseLabel" in INDEX_HTML
    assert "Critiqued Model Response" in INDEX_HTML
    assert "rvPopupCritiquedResponse" in REPORTS_JS
    assert "white-space: pre-wrap" in STYLE_CSS


def test_frontend_assets_cover_scrollable_critique_popup():
    assert 'id="rvPopupBody"' in INDEX_HTML
    assert "#rvCritiquePopup" in STYLE_CSS
    assert ".rv-popup-inner" in STYLE_CSS
    assert ".rv-popup-body" in STYLE_CSS
    assert "max-height: min(88vh, 900px);" in STYLE_CSS
    assert "overflow-y: auto;" in STYLE_CSS
    assert "min-height: 0;" in STYLE_CSS
    assert "flex-direction: column;" in STYLE_CSS
    assert "overflow-wrap: anywhere;" in STYLE_CSS
    assert "@media (max-width: 640px)" in STYLE_CSS


def test_frontend_assets_reset_popup_scroll_and_trace_state():
    assert 'id="rvPopupTrace"' in INDEX_HTML
    assert "document.getElementById('rvPopupBody')" in REPORTS_JS
    assert "scrollTop = 0;" in REPORTS_JS
    assert "document.getElementById('rvPopupTrace')" in REPORTS_JS
    assert "popupTrace.open = false;" in REPORTS_JS


def test_hf_report_includes_anchor_resolution_and_bridge_debug_sections():
    from paixueji_app import build_human_feedback_report
    from bridge_debug import build_bridge_trace_entry

    exchange_trace = build_bridge_trace_entry(
        node="driver:bridge_decision",
        state_before={},
        changes={"decision": "bridge_retry"},
        time_ms=1.0,
    )

    report = build_human_feedback_report(
        object_name="cat food",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": "Cat food is what a cat eats. What helps a cat smell food?",
            "mode": "chat",
            "response_type": "introduction",
            "nodes_executed": [exchange_trace],
        }],
        all_exchanges=[{
            "child_response": "It looks like small cookies",
            "model_response": "Cat food is what a cat eats. What helps a cat smell food?",
            "nodes_executed": [exchange_trace],
            "bridge_debug": {
                "decision": "bridge_retry",
                "anchor_status": "anchored_high",
                "anchor_relation": "food_for",
                "bridge_visible_in_response": False,
                "pre_anchor_reply_type": "clarification_request",
                "support_action": "clarify",
                "pre_anchor_support_count_after": 1,
            },
        }],
        exchange_critiques=[{"exchange_index": 1}],
        global_conclusion="Test",
        introduction={
            "content": "Cat food is what a cat eats. What helps a cat smell food?",
            "nodes_executed": [exchange_trace],
            "mode": "chat",
            "response_type": "introduction",
            "bridge_debug": {
                "decision": "intro_bridge",
                "anchor_status": "anchored_high",
                "anchor_relation": "food_for",
                "bridge_visible_in_response": True,
                "decision_reason": "start high-confidence bridge",
                "activation_transition": {
                    "before_state": {
                        "activation_handoff_ready_before": False,
                    },
                    "question_validation": {
                        "source": "deterministic",
                        "confidence": "high",
                    },
                },
            },
        },
        introduction_critique={"exchange_index": 0, "model_response_problem": "Where is the connection?"},
        key_concept=None,
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
            "decision_source": "relation_repair",
            "decision_reason": "primary_low_confidence_single_candidate",
            "candidate_anchors": ["cat"],
            "raw_model_response": '{"anchor_object_name": null, "confidence_band":"low"}',
            "raw_model_payload_kind": "wrapped_json",
            "json_recovery_applied": True,
        },
    )
    assert "## Anchor Resolution" in report
    assert "Decision Source" in report
    assert "Decision Reason" in report
    assert "Candidate Anchors" in report
    assert "Raw Resolver Output" in report
    assert "Raw Payload Kind" in report
    assert "JSON Recovery Applied" in report
    assert "**Bridge Verdict:**" in report
    assert "#### Raw Bridge Debug" in report
    assert "[CHAT|introduction]" in report
    assert "decision: bridge_retry" in report
    assert "pre_anchor_reply_type: `clarification_request`" in report
    assert "support_action: `clarify`" in report
    assert "pre_anchor_support_count_after: `1`" in report
    assert "Activation Transition" in report
    assert "Before State" in report


def test_hf_report_parser_round_trips_nested_activation_debug(tmp_path):
    from paixueji_app import _parse_hf_report, build_human_feedback_report
    from bridge_debug import build_bridge_trace_entry

    trace = build_bridge_trace_entry(
        node="driver:bridge_decision",
        state_before={},
        changes={"decision": "bridge_activation"},
        time_ms=1.0,
    )

    report = build_human_feedback_report(
        object_name="cat food",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": "Your cat really likes wet food. What does your cat do when dinner is ready?",
            "mode": "chat",
            "response_type": "bridge_activation",
            "nodes_executed": [trace],
        }],
        all_exchanges=[],
        exchange_critiques=[],
        global_conclusion="Test",
        introduction={
            "content": "Your cat really likes wet food. What does your cat do when dinner is ready?",
            "nodes_executed": [trace],
            "mode": "chat",
            "response_type": "bridge_activation",
            "bridge_debug": {
                "decision": "bridge_activation",
                "activation_transition": {
                    "before_state": {
                        "activation_handoff_ready_before": True,
                    },
                    "question_validation": {
                        "source": "deterministic",
                        "confidence": "high",
                        "reason": "clear match",
                        "handoff_ready_question": True,
                    },
                    "answer_validation": {
                        "handoff_check_attempted": True,
                        "source": "deterministic",
                        "reason": "heuristic",
                        "answered_previous_question": True,
                        "answered_previous_kb_question": True,
                        "answer_polarity": "yes",
                    },
                    "outcome": {
                        "handoff_result": "committed_to_anchor_general",
                        "bridge_success": True,
                    },
                    "turn_interpretation": {
                        "activation_child_reply_type": "handoff_answer",
                        "counted_turn": False,
                    },
                    "continuity": {
                        "continuity_anchor_before": "physical.appearance.paw_pads",
                        "continuity_anchor_after": "physical.appearance.paw_pads",
                        "continuity_preserved": True,
                    },
                },
            },
        },
        introduction_critique={"exchange_index": 0},
        key_concept=None,
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
        },
    )
    path = tmp_path / "nested_activation.md"
    path.write_text(report, encoding="utf-8")

    parsed = _parse_hf_report(path)
    model_turn = next(turn for turn in parsed["transcript"] if turn["role"] == "model")

    assert model_turn["critique"]["bridge_debug"]["activation_transition"]["before_state"]["activation_handoff_ready_before"] == "True"
    assert model_turn["critique"]["bridge_debug"]["activation_transition"]["question_validation"]["confidence"] == "high"
    assert model_turn["critique"]["bridge_debug"]["activation_transition"]["question_validation"]["handoff_ready_question"] == "True"
    assert model_turn["critique"]["bridge_debug"]["activation_transition"]["answer_validation"]["answered_previous_question"] == "True"
    assert model_turn["critique"]["bridge_debug"]["activation_transition"]["outcome"]["bridge_success"] == "True"


def test_hf_report_exchange_critique_labels_are_unambiguous():
    from paixueji_app import build_human_feedback_report

    model_response = (
        "That's okay! Sometimes it's hard to know if you haven't seen it happen before.\n\n"
        "When you open a bag of food, it has a really strong smell. Do you think the cat "
        "uses its nose to find the food, or does it use its eyes to look for it?"
    )

    report = build_human_feedback_report(
        object_name="cat food",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": "Intro",
            "mode": "chat",
            "response_type": "introduction",
            "nodes_executed": [],
        }],
        all_exchanges=[{
            "child_response": "I don't know",
            "model_response": model_response,
            "nodes_executed": [],
        }],
        exchange_critiques=[{
            "exchange_index": 1,
            "model_response_problem": "This asks a new question instead of scaffolding the original one.",
        }],
        global_conclusion="",
        introduction=None,
        introduction_critique=None,
        key_concept="function",
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
        },
    )

    assert "**Critiqued Model Response:**" in report
    assert "**Feedback on the model response:**" in report
    assert "**Model Response:**" not in report
    assert '> That\'s okay! Sometimes it\'s hard to know if you haven\'t seen it happen before.' in report
    assert "> When you open a bag of food, it has a really strong smell." in report


def test_hf_report_detail_parser_preserves_response_type_and_bridge_debug(client):
    response = client.get(_hf_report_url(_hf_reports()[0]))
    assert response.status_code == 200
    report = response.get_json()
    intro_turn = next(turn for turn in report["transcript"] if turn["role"] == "model" and turn["exchange_index"] == 0)
    assert "response_type" in intro_turn


def test_hf_report_renders_bridge_activation_label():
    from paixueji_app import build_human_feedback_report
    from bridge_debug import build_bridge_trace_entry

    trace = build_bridge_trace_entry(
        node="driver:bridge_decision",
        state_before={},
        changes={"decision": "bridge_activation"},
        time_ms=1.0,
    )

    report = build_human_feedback_report(
        object_name="cat",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": "Your cat really likes wet food. What does your cat do when dinner is ready?",
            "mode": "chat",
            "response_type": "bridge_activation",
            "bridge_debug": {
                "decision": "bridge_activation",
                "bridge_visible_in_response": True,
            },
            "nodes_executed": [trace],
        }],
        all_exchanges=[],
        exchange_critiques=[],
        global_conclusion="Test",
        introduction=None,
        introduction_critique=None,
        key_concept=None,
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
        },
    )
    assert "[CHAT|bridge_activation]" in report


def test_hf_report_writes_turn_diagnostics_for_uncritiqued_model_turn():
    from paixueji_app import build_human_feedback_report
    from bridge_debug import build_bridge_trace_entry

    trace = build_bridge_trace_entry(
        node="driver:bridge_decision",
        state_before={},
        changes={"decision": "bridge_activation"},
        time_ms=1.0,
    )

    report = build_human_feedback_report(
        object_name="cat",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": "Your cat really likes wet food.",
            "mode": "chat",
            "response_type": "bridge_activation",
            "bridge_debug": {
                "decision": "bridge_activation",
                "bridge_visible_in_response": True,
                "activation_transition": {
                    "question_validation": {
                        "confidence": "high",
                    },
                },
            },
            "nodes_executed": [trace],
        }],
        all_exchanges=[],
        exchange_critiques=[],
        global_conclusion="",
        introduction=None,
        introduction_critique=None,
        key_concept=None,
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
        },
    )

    assert "#### Turn Diagnostics" in report
    assert "**Bridge Verdict:**" in report
    assert "#### Raw Bridge Debug" in report
    assert "##### Activation Transition" in report


def test_hf_report_parser_keeps_bridge_only_intro_diagnostics(tmp_path):
    from paixueji_app import _parse_hf_report, build_human_feedback_report
    from bridge_debug import build_bridge_trace_entry

    intro_trace = build_bridge_trace_entry(
        node="driver:bridge_decision",
        state_before={},
        changes={"decision": "intro_bridge"},
        time_ms=1.0,
    )

    report = build_human_feedback_report(
        object_name="cat food",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": "Cat food is what a cat eats. What helps a cat smell food?",
            "mode": "chat",
            "response_type": "introduction",
            "bridge_debug": {
                "decision": "intro_bridge",
                "anchor_status": "anchored_high",
                "anchor_relation": "food_for",
                "bridge_visible_in_response": True,
            },
            "nodes_executed": [intro_trace],
        }],
        all_exchanges=[],
        exchange_critiques=[],
        global_conclusion="Test",
        introduction={
            "content": "Cat food is what a cat eats. What helps a cat smell food?",
            "nodes_executed": [intro_trace],
            "mode": "chat",
            "response_type": "introduction",
            "bridge_debug": {
                "decision": "intro_bridge",
                "anchor_status": "anchored_high",
                "anchor_relation": "food_for",
                "bridge_visible_in_response": True,
            },
        },
        introduction_critique={"exchange_index": 0},
        key_concept=None,
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
        },
    )
    report_path = tmp_path / "bridge_only.md"
    report_path.write_text(report, encoding="utf-8")

    parsed = _parse_hf_report(report_path)
    intro_turn = next(turn for turn in parsed["transcript"] if turn["role"] == "model")

    assert intro_turn["critique"] is not None
    assert intro_turn["critique"]["bridge_verdict"] is not None
    assert intro_turn["critique"]["bridge_debug"]["decision"] == "intro_bridge"


def test_hf_report_parser_puts_turn_diagnostics_on_model_turn(tmp_path):
    from paixueji_app import _parse_hf_report, build_human_feedback_report
    from bridge_debug import build_bridge_trace_entry

    trace = build_bridge_trace_entry(
        node="driver:bridge_decision",
        state_before={},
        changes={"decision": "bridge_activation"},
        time_ms=1.0,
    )

    report = build_human_feedback_report(
        object_name="cat food",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": "Your cat really likes wet food. What does your cat do when dinner is ready?",
            "mode": "chat",
            "response_type": "bridge_activation",
            "bridge_debug": {
                "decision": "bridge_activation",
                "bridge_visible_in_response": True,
                "activation_transition": {
                    "before_state": {
                        "activation_handoff_ready_before": True,
                    },
                    "question_validation": {
                        "confidence": "high",
                    },
                },
            },
            "nodes_executed": [trace],
        }],
        all_exchanges=[],
        exchange_critiques=[],
        global_conclusion="",
        introduction=None,
        introduction_critique=None,
        key_concept=None,
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
        },
    )
    path = tmp_path / "turn_diagnostics.md"
    path.write_text(report, encoding="utf-8")

    parsed = _parse_hf_report(path)
    model_turn = next(turn for turn in parsed["transcript"] if turn["role"] == "model")

    assert model_turn["bridge_verdict"] is not None
    assert model_turn["bridge_debug"]["decision"] == "bridge_activation"
    assert model_turn["bridge_debug"]["activation_transition"]["question_validation"]["confidence"] == "high"
    assert model_turn["critique"] is None


def test_parse_hf_report_keeps_inline_model_turn_with_diagnostics(tmp_path):
    from paixueji_app import _parse_hf_report

    report_text = """# Human Feedback Critique Report: cat food

**Session:** sess
**Age:** 6
**Date:** 2026-04-14T00:00:00
**Feedback Type:** Manual (Human)
**Exchanges Critiqued:** 0 / 1

---

## Conversation Transcript

**Model** `[CHAT|bridge_activation]`**:** That's okay! It's hard to see inside a cat's mouth when they are eating.

#### Turn Diagnostics

**Bridge Verdict:** Bridge was visible in the response.

#### Raw Bridge Debug

- decision: `bridge_activation`
- bridge_visible_in_response: `True`

**Child:** no

---

## Conversation Critique

*No exchanges were critiqued.*
"""
    path = tmp_path / "inline_turn.md"
    path.write_text(report_text, encoding="utf-8")

    parsed = _parse_hf_report(path)

    assert len(parsed["transcript"]) == 2
    model_turn = parsed["transcript"][0]
    assert model_turn["role"] == "model"
    assert model_turn["text"] == "That's okay! It's hard to see inside a cat's mouth when they are eating."
    assert model_turn["nodes"] == []
    assert model_turn["time_ms"] == 0
    assert model_turn["bridge_verdict"] == "Bridge was visible in the response."
    assert model_turn["bridge_debug"]["decision"] == "bridge_activation"


def test_hf_report_detail_preserves_all_model_turns_for_cat_report(client):
    report_path = max(_hf_reports(), key=lambda path: path.read_text(encoding="utf-8").count("**Model**"))
    response = client.get(_hf_report_url(report_path))

    assert response.status_code == 200

    report = response.get_json()
    model_turns = [turn for turn in report["transcript"] if turn["role"] == "model"]
    raw_text = report_path.read_text(encoding="utf-8")
    raw_model_turns = len(re.findall(r"^\*\*Model\*\*", raw_text, flags=re.MULTILINE))

    assert len(model_turns) == raw_model_turns
    assert raw_model_turns >= 1
    assert all(turn["text"].strip() for turn in model_turns)


def test_parse_hf_report_preserves_multiline_model_reply(tmp_path):
    from paixueji_app import _parse_hf_report

    report_text = """# Human Feedback Critique Report: cat food

**Session:** sess
**Age:** 6
**Date:** 2026-04-10T00:00:00
**Feedback Type:** Manual (Human)
**Exchanges Critiqued:** 0 / 1

---

## Conversation Transcript

**Model** `[CHAT|bridge_support]`**:** [driver:bridge_decision] (1ms)
That's okay! Sometimes it's hard to know if you haven't seen it happen before.

When you open a bag of food, it has a really strong smell.

**Child:** maybe both

---

## Conversation Critique

*No exchanges were critiqued.*
"""
    path = tmp_path / "report.md"
    path.write_text(report_text, encoding="utf-8")

    parsed = _parse_hf_report(path)

    assert parsed["transcript"][0]["text"] == (
        "That's okay! Sometimes it's hard to know if you haven't seen it happen before.\n\n"
        "When you open a bag of food, it has a really strong smell."
    )


def test_hf_report_parser_keeps_second_paragraph_in_model_turn(tmp_path):
    from paixueji_app import _parse_hf_report, build_human_feedback_report
    from bridge_debug import build_bridge_trace_entry

    trace = build_bridge_trace_entry(
        node="driver:bridge_decision",
        state_before={},
        changes={"decision": "bridge_support"},
        time_ms=1.0,
    )

    report = build_human_feedback_report(
        object_name="cat food",
        age=6,
        session_id="sess",
        transcript=[{
            "role": "model",
            "content": (
                "That's okay! Sometimes it's hard to know if you haven't seen it happen before.\n\n"
                "When you open a bag of food, it has a really strong smell."
            ),
            "mode": "chat",
            "response_type": "bridge_support",
            "nodes_executed": [trace],
        }],
        all_exchanges=[],
        exchange_critiques=[],
        global_conclusion="",
        introduction=None,
        introduction_critique=None,
        key_concept="function",
        session_resolution_debug={
            "surface_object_name": "cat food",
            "anchor_object_name": "cat",
            "anchor_status": "anchored_high",
        },
    )
    path = tmp_path / "hf.md"
    path.write_text(report, encoding="utf-8")

    parsed = _parse_hf_report(path)
    intro_turn = next(turn for turn in parsed["transcript"] if turn["role"] == "model")

    assert "\n\nWhen you open a bag of food" in intro_turn["text"]
