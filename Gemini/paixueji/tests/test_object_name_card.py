from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
STYLE_CSS = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_object_name_card_markup_and_styles_exist():
    assert 'class="object-card"' in INDEX_HTML
    assert 'class="object-card-label"' in INDEX_HTML
    assert 'class="object-input-shell"' in INDEX_HTML
    assert 'class="object-example-list"' in INDEX_HTML
    assert 'class="object-example-chip"' in INDEX_HTML

    assert 'id="objectName"' in INDEX_HTML
    assert 'list="objectSuggestions"' in INDEX_HTML
    assert 'class="object-input-row"' in INDEX_HTML

    assert ">apple<" in INDEX_HTML
    assert ">butterfly<" in INDEX_HTML
    assert ">bicycle<" in INDEX_HTML

    assert ".object-card" in STYLE_CSS
    assert ".object-card-label" in STYLE_CSS
    assert ".object-input-shell" in STYLE_CSS
    assert ".object-example-list" in STYLE_CSS
    assert ".object-example-chip" in STYLE_CSS
