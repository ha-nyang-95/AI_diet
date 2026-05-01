"""Story 3.2 — PDF chunker (AC #2 + Architecture 결정 1).

D1 — *MVP 시드 경로는 호출 X*. 외주 인수 클라이언트 자동 시드 파이프라인에서 활성화.
본 모듈은 *인터페이스 박기* + 단위 테스트로 동작 검증만.

- ``pypdf>=5.1`` ``PdfReader(io.BytesIO(content))`` → 페이지별 ``page.extract_text()``
  호출 → ``"\\n\\n".join(pages)``로 join → ``_split_text`` 적용. 페이지 경계는 ``\\n\\n``
  separator로 chunking 친화 (RecursiveCharacterTextSplitter 1순위 separator).
- 깨진 PDF / 텍스트 추출 실패 → ``GuidelineSeedAdapterError`` raise.
- 빈 페이지(``extract_text()`` returns ``""``) skip.
- 한글 폰트 + CID 매핑 깨짐 위험 — pypdf 텍스트 추출 한계 (D1 운영자 SOP 흡수).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import structlog
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PyPdfError

from app.core.exceptions import GuidelineSeedAdapterError

if TYPE_CHECKING:
    from app.rag.chunking import Chunk

logger = structlog.get_logger(__name__)


def chunk_pdf(content: bytes, *, max_chars: int = 1000, overlap: int = 100) -> list[Chunk]:
    """PDF bytes → ``list[Chunk]``.

    Raises:
        ``GuidelineSeedAdapterError`` — PDF 헤더 invalid / pypdf 추출 실패.
    """
    from app.rag.chunking import Chunk, _split_text

    if not content:
        return []

    try:
        reader = PdfReader(io.BytesIO(content))
    except (PdfReadError, PyPdfError, ValueError) as exc:
        raise GuidelineSeedAdapterError(f"PDF text extraction failed: {exc}") from exc

    pages_text: list[str] = []
    for page in reader.pages:
        try:
            extracted = page.extract_text()
        except (PdfReadError, PyPdfError, ValueError, KeyError) as exc:
            # 한 페이지 실패는 전체 abort보다 skip이 안전 (운영자 검수 SOP 흡수).
            logger.warning("chunking.pdf.page_extract_failed", error=str(exc))
            continue
        if extracted:
            pages_text.append(extracted)

    if not pages_text:
        return []

    joined = "\n\n".join(pages_text)
    sub_chunks = _split_text(joined, max_chars=max_chars, overlap=overlap)
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
        "chunking.pdf.complete",
        chunks_count=len(chunks),
        total_chars=sum(len(c.text) for c in chunks),
    )
    return chunks
