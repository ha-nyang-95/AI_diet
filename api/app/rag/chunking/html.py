"""Story 3.2 — HTML chunker (AC #2 + Architecture 결정 1).

D1 — *MVP 시드 경로는 호출 X*. 외주 인수 클라이언트 자동 시드 파이프라인에서 활성화.

- ``beautifulsoup4>=4.12`` ``BeautifulSoup(content, "html.parser")`` — pure Python
  파서 (lxml 별 의존 X — perf보다 라이선스/의존성 단순성 우선).
- ``<script>`` / ``<style>`` 제거 → ``soup.get_text(separator="\\n", strip=True)`` 추출.
- DOCTYPE / 잘못된 인코딩 → ``GuidelineSeedAdapterError`` raise.
- bytes 입력은 BeautifulSoup이 자동 디코딩.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.core.exceptions import GuidelineSeedAdapterError

if TYPE_CHECKING:
    from app.rag.chunking import Chunk

logger = structlog.get_logger(__name__)


def chunk_html(content: str | bytes, *, max_chars: int = 1000, overlap: int = 100) -> list[Chunk]:
    """HTML 문자열 또는 bytes → ``list[Chunk]``.

    Raises:
        ``GuidelineSeedAdapterError`` — HTML 파싱 실패.
    """
    from app.rag.chunking import Chunk, _split_text

    if not content:
        return []

    # bs4 import는 함수 내부 — D1 외주 인수 인터페이스 토대로 *호출 시점*에만 import 비용 지불.
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover — pyproject 의존성 변경 회귀 방어
        raise GuidelineSeedAdapterError(f"beautifulsoup4 import failed: {exc}") from exc

    try:
        soup = BeautifulSoup(content, "html.parser")
    except Exception as exc:  # noqa: BLE001 — bs4는 다양한 파싱 예외 raise 가능
        raise GuidelineSeedAdapterError(f"HTML parse failed: {exc}") from exc

    # script / style 제거 — 본문만 추출.
    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    if not text:
        return []

    sub_chunks = _split_text(text, max_chars=max_chars, overlap=overlap)
    chunks = [
        Chunk(
            text=sc.text,
            chunk_index=idx,
            char_start=sc.char_start,
            char_end=sc.char_end,
        )
        for idx, sc in enumerate(sub_chunks)
    ]
    logger.info(
        "chunking.html.complete",
        chunks_count=len(chunks),
        total_chars=sum(len(c.text) for c in chunks),
    )
    return chunks
