from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HF_DIR = REPO_ROOT / "reports" / "HF"
REPORTS_JS = (REPO_ROOT / "static" / "reports.js").read_text(encoding="utf-8")
STYLE_CSS = (REPO_ROOT / "static" / "style.css").read_text(encoding="utf-8")


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
    expected_count = len(list(HF_DIR.glob("*/*.md")))

    assert expected_count >= 90
    assert len(reports) == expected_count
    assert reports[0]["date"] >= reports[-1]["date"]

    first = reports[0]
    assert set(first) == {"date", "filename", "meta"}
    assert first["filename"].endswith(".md")
    assert {"object", "date", "key_concept", "exchanges_critiqued", "exchanges_total"} <= set(first["meta"])


def test_hf_report_detail_exposes_transcript_and_critique_data(client):
    response = client.get("/api/reports/hf/2026-03-20/banana_20260320_191624.md")

    assert response.status_code == 200

    report = response.get_json()
    assert report["date"] == "2026-03-20"
    assert report["filename"] == "banana_20260320_191624.md"
    assert report["meta"]["object"] == "banana"
    assert report["meta"]["age"] is None
    assert report["meta"]["exchanges_critiqued"] == 1
    assert report["meta"]["exchanges_total"] == 1
    assert report["global_conclusion"] == "Test"

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
    report_path = HF_DIR / "2026-03-05" / "apple_20260305_101258.md"
    parsed = client.get("/api/reports/hf/2026-03-05/apple_20260305_101258.md").get_json()
    response = client.get("/api/reports/hf/2026-03-05/apple_20260305_101258.md/raw")

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
    assert "crit.problematic.toLowerCase() !== 'none'" in REPORTS_JS
    assert "No issues ✓" in REPORTS_JS
    assert "rv-panel-green" in REPORTS_JS
    assert "showRvRawModal" in REPORTS_JS

    assert "@keyframes rv-critique-pulse" in STYLE_CSS
    assert ".rv-bubble-critiqued" in STYLE_CSS
    assert "#rvRawModal" in STYLE_CSS
