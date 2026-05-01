"""Story 3.2 — 3-format chunking 재사용 인터페이스 (AC #2 + Architecture 결정 1).

외주 인수 클라이언트가 자기 PDF/HTML/Markdown 자료를 *동일 호출 방식*으로 시드 추가
가능하도록 통일 시그니처:

    chunk_<format>(content, *, max_chars=1000, overlap=100) -> list[Chunk]

3 format 모두 ``Chunk(text, chunk_index, char_start, char_end)`` 데이터클래스 반환.
``frozen=True`` + ``slots=True`` — 불변 + 메모리 효율(50-100건 시드 메모리 무시).

D11 — ``langchain-text-splitters>=0.3`` ``RecursiveCharacterTextSplitter`` 채택.
한국어 단락 → 줄 → 단어 → 문자 fallback (separators ``["\\n\\n", "\\n", " ", ""]``).
``add_start_index=True``로 char offset 자동 부착(``metadata["start_index"]``).
``length_function=len`` 문자 단위 — 1000자 ≈ 500-700 tokens (text-embedding-3-small
8K context 안전치 ≈ 12-16배 여유).

D12 — ``Chunk`` 데이터클래스 + 통일 시그니처가 외주 인수 *인터페이스 박기*. MVP 시드
경로는 ``chunk_markdown``만 활성 — pdf/html은 단위 테스트로 동작 검증 + 외주 인수
클라이언트 자동 시드 파이프라인에서 활성화 (D1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 본 모듈 외부에 export되는 chunker 함수들은 markdown.py / pdf.py / html.py 모듈에서
# re-export. 외주 인수 클라이언트는 ``from app.rag.chunking import chunk_markdown,
# chunk_pdf, chunk_html, Chunk`` 패턴으로 import.

DEFAULT_MAX_CHARS: Final[int] = 1000
DEFAULT_OVERLAP: Final[int] = 100

# RecursiveCharacterTextSplitter separators — 한국어 텍스트 안전치 (단락 → 줄 → 단어 → 문자).
_SPLITTER_SEPARATORS: Final[list[str]] = ["\n\n", "\n", " ", ""]


@dataclass(frozen=True, slots=True)
class Chunk:
    """chunking 결과 단일 단위 — 불변 + slots 메모리 효율.

    - ``text``: chunk 본문 (max_chars 제한 적용 후).
    - ``chunk_index``: 문서 내 0-based 순번 (멱등 키 — UNIQUE(source, source_id, chunk_index)).
    - ``char_start``: 원본 문서 내 character offset (start, inclusive).
    - ``char_end``: ``char_start + len(text)`` (end, exclusive).
    """

    text: str
    chunk_index: int
    char_start: int
    char_end: int


def _split_text(
    text: str, *, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP
) -> list[Chunk]:
    """공용 splitter — ``RecursiveCharacterTextSplitter`` wrapper.

    - 빈 입력 (``text == ""`` or only whitespace) → 빈 리스트.
    - ``add_start_index=True`` — chunk별 ``start_index`` 자동 부착 → ``Chunk.char_start``
      매핑. ``char_end`` = ``char_start + len(chunk_text)`` 계산.
    - chunk_index는 0부터 enumerate (멱등 키 — D5 + anti-pattern 카탈로그 대응).

    NFR-S5 — chunk text raw 노출 X. ``chunks_count`` + ``total_chars``만 1줄.
    """
    if not text or not text.strip():
        return []

    splitter = RecursiveCharacterTextSplitter(
        separators=_SPLITTER_SEPARATORS,
        chunk_size=max_chars,
        chunk_overlap=overlap,
        length_function=len,
        add_start_index=True,
        is_separator_regex=False,
    )
    documents = splitter.create_documents([text])
    chunks: list[Chunk] = []
    for idx, doc in enumerate(documents):
        char_start = int(doc.metadata.get("start_index", 0))
        char_end = char_start + len(doc.page_content)
        chunks.append(
            Chunk(
                text=doc.page_content,
                chunk_index=idx,
                char_start=char_start,
                char_end=char_end,
            )
        )
    return chunks


# Re-export concrete chunker functions for the public API (
# ``from app.rag.chunking import chunk_markdown, chunk_pdf, chunk_html``).
# 본 import 순서는 module load 시 cyclic 회피 — concrete 모듈은 본 모듈의 ``Chunk``,
# ``_split_text``를 사용하므로 본 모듈 정의 *후* import.
from app.rag.chunking.html import chunk_html  # noqa: E402
from app.rag.chunking.markdown import chunk_markdown  # noqa: E402
from app.rag.chunking.pdf import chunk_pdf  # noqa: E402

__all__ = [
    "Chunk",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_OVERLAP",
    "chunk_html",
    "chunk_markdown",
    "chunk_pdf",
]
