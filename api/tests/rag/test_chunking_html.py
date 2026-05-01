"""Story 3.2 — ``chunk_html`` 단위 테스트 (AC #2).

4 케이스: 정상 + script/style 제거 + bytes 입력 + 빈 입력.
"""

from __future__ import annotations

from pathlib import Path

from app.rag.chunking import chunk_html

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample-guideline.html"


def test_chunk_html_normal_extracts_visible_text() -> None:
    """정상 HTML fixture → h1 + p 본문 추출."""
    content = _FIXTURE_PATH.read_text(encoding="utf-8")
    chunks = chunk_html(content)
    assert chunks
    joined = "\n".join(ch.text for ch in chunks)
    assert "탄수화물" in joined
    assert "55-65%" in joined or "55-65" in joined
    assert "체중 감량" in joined


def test_chunk_html_strips_script_and_style() -> None:
    """``<script>`` / ``<style>`` 내부 텍스트는 추출 X."""
    content = _FIXTURE_PATH.read_text(encoding="utf-8")
    chunks = chunk_html(content)
    joined = "\n".join(ch.text for ch in chunks)
    # script 내부 alert 텍스트는 제거되어야 함.
    assert "이 텍스트는 추출되면 안 됨" not in joined
    # style 내부 CSS는 제거되어야 함.
    assert "font-family" not in joined


def test_chunk_html_bytes_input_equals_str() -> None:
    """bytes 입력은 str 입력과 동일 결과 (BeautifulSoup 자동 디코드)."""
    text_content = _FIXTURE_PATH.read_text(encoding="utf-8")
    bytes_content = _FIXTURE_PATH.read_bytes()
    str_chunks = chunk_html(text_content)
    bytes_chunks = chunk_html(bytes_content)
    assert [c.text for c in str_chunks] == [c.text for c in bytes_chunks]


def test_chunk_html_empty_input_returns_empty_list() -> None:
    """빈 / whitespace HTML → 빈 리스트."""
    assert chunk_html("") == []
    assert chunk_html(b"") == []
    # head + script만 있는 HTML — body 비어있으면 빈 리스트.
    assert chunk_html("<html><head><style>x{}</style></head><body></body></html>") == []
