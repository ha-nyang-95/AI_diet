"""Story 3.2 — ``chunk_pdf`` 단위 테스트 (AC #2).

4 케이스: 정상 fixture + 빈 PDF + 깨진 PDF + 다중 페이지 join.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import GuidelineSeedAdapterError
from app.rag.chunking import chunk_pdf

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample-guideline.pdf"


def test_chunk_pdf_normal_fixture_yields_chunks() -> None:
    """정상 PDF fixture → ≥ 1 chunk + char_start/end 양수 + 페이지 텍스트 추출."""
    content = _FIXTURE_PATH.read_bytes()
    chunks = chunk_pdf(content)
    assert chunks, "valid PDF fixture에서 chunk 0개는 어댑터 회귀"
    for ch in chunks:
        assert ch.char_start >= 0
        assert ch.char_end > ch.char_start
        assert ch.text  # 빈 chunk 회피
    # AMDR 또는 KSSO 키워드는 fixture text 일부 — 추출 정합 단언.
    joined = "\n".join(ch.text for ch in chunks)
    assert "AMDR" in joined or "KSSO" in joined


def test_chunk_pdf_empty_bytes_returns_empty_list() -> None:
    """빈 bytes → 빈 리스트 (raise X)."""
    assert chunk_pdf(b"") == []


def test_chunk_pdf_corrupt_bytes_raises_adapter_error() -> None:
    """깨진 PDF 헤더 → ``GuidelineSeedAdapterError``."""
    with pytest.raises(GuidelineSeedAdapterError) as exc_info:
        chunk_pdf(b"this is not a valid PDF byte sequence at all")
    assert "PDF text extraction failed" in str(exc_info.value)


def test_chunk_pdf_multi_page_joined_with_double_newline() -> None:
    """다중 페이지 PDF → 페이지 경계가 ``\\n\\n``으로 join되어 chunking 친화 (1순위 separator).

    Page 1 + Page 2 텍스트가 모두 포함되는지 단언 (chunk 단위는 max_chars에 종속).
    """
    content = _FIXTURE_PATH.read_bytes()
    chunks = chunk_pdf(content, max_chars=2000, overlap=50)
    joined = "\n".join(ch.text for ch in chunks)
    assert "AMDR" in joined  # page 1 텍스트
    assert "KSSO 2024" in joined  # page 2 텍스트
