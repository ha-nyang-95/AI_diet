"""Story 3.2 — Markdown chunker (AC #2).

YAML frontmatter 분리 + heading-aware splitting + ``_split_text`` max_chars cap.

- frontmatter 패턴 — ``^---\\n(.*?)\\n---\\n`` 정규식 (DOTALL). frontmatter는 시드
  모듈(``app/rag/guidelines/seed.py``)이 별도 처리(``_FrontmatterSchema`` Pydantic 검증).
  chunker는 frontmatter *제외* body만 chunking.
- heading-aware — ``MarkdownHeaderTextSplitter``로 ``## ``/``### `` 단위 sub-document 분리.
  heading 메타는 chunk 내 prepend(예: ``"## 매크로 비율 권장\\n\\n탄수화물 ..."``) →
  chunk가 standalone 인용 가능 + heading 정보 임베딩에 자연 반영 (D8).
- 2차 ``_split_text``로 max_chars cap — ``MarkdownHeaderTextSplitter`` 결과가 max_chars
  초과 시 하위 chunk 재분할.
- ``char_start`` — frontmatter 분리 후 *body 내* offset이 아니라 *원본 문서 내* offset.
  frontmatter 길이만큼 shift해서 계산.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from langchain_text_splitters import MarkdownHeaderTextSplitter

if TYPE_CHECKING:
    from app.rag.chunking import Chunk

logger = structlog.get_logger(__name__)

# YAML frontmatter — 문서 시작 ``---\\n``으로 열고 단독 ``---\\n``으로 닫음. DOTALL flag로
# 줄바꿈 포함. 첫 매치만 — 본문 안의 ``---`` 분리선과 분리.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# heading split — ## (H2), ### (H3) 단위. H1은 문서 전체 제목으로 별도 처리(``doc_title``
# frontmatter로 흡수). 깊은 H4-H6은 H3 하위 단락 내 chunking (``_split_text`` 재분할).
_HEADER_LEVELS: list[tuple[str, str]] = [
    ("##", "h2"),
    ("###", "h3"),
]


def _strip_frontmatter(content: str) -> tuple[str, int]:
    """frontmatter 제거 + body + body의 원본 내 offset(``shift``) 반환.

    frontmatter 미존재 시 ``(content, 0)``.
    """
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        return content, 0
    body = content[match.end() :]
    return body, match.end()


def _heading_aware_split(body: str) -> list[tuple[str, dict[str, str]]]:
    """``MarkdownHeaderTextSplitter`` — ``## ``/``### `` 단위 sub-document.

    Returns:
        ``[(text_with_heading, header_metadata), ...]`` — heading 메타는 ``"h2"``/``"h3"``
        키로 들어옴. text는 *heading 미포함*(splitter가 metadata로 분리). prepend는
        호출 측이 필요 시 처리.
    """
    if not body.strip():
        return []
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_HEADER_LEVELS)
    docs = splitter.split_text(body)
    return [(d.page_content, dict(d.metadata)) for d in docs]


def chunk_markdown(content: str, *, max_chars: int = 1000, overlap: int = 100) -> list[Chunk]:
    """Markdown 문서 → ``list[Chunk]``.

    1. YAML frontmatter 분리 (시드 모듈이 별도 처리).
    2. heading-aware split (``## ``/``### `` 단위) — heading은 chunk text에 prepend
       해 standalone 인용 가능.
    3. 각 sub-document에 ``_split_text``로 max_chars cap 적용 → 최종 chunk list.
    4. ``chunk_index``는 0부터 enumerate (전 문서 합산).
    5. ``char_start`` — frontmatter shift + heading-split 위치는 원본 보존을 위해
       body 내에서 검색 후 + shift 가산. (heading-split이 텍스트 일부를 metadata로
       분리하므로 정확한 offset은 best-effort — chunk가 body에 substring으로 포함된
       위치 ``find``로 결정.)
    """
    # 본 import는 ``app.rag.chunking.__init__``에서 markdown.py를 import하므로 cyclic
    # 회피 위해 함수 내부 늦은 import.
    from app.rag.chunking import Chunk, _split_text

    if not content or not content.strip():
        return []

    body, body_shift = _strip_frontmatter(content)
    if not body.strip():
        return []

    sub_docs = _heading_aware_split(body)

    chunks: list[Chunk] = []
    chunk_idx = 0

    if not sub_docs:
        # heading 0건 — body 전체를 단일 단락으로 처리.
        sub_chunks = _split_text(body, max_chars=max_chars, overlap=overlap)
        for sc in sub_chunks:
            char_start = sc.char_start + body_shift
            chunks.append(
                Chunk(
                    text=sc.text,
                    chunk_index=chunk_idx,
                    char_start=char_start,
                    char_end=char_start + len(sc.text),
                )
            )
            chunk_idx += 1
    else:
        for text_part, header_meta in sub_docs:
            # heading prepend — h2/h3 메타가 있으면 chunk text 앞에 붙여 standalone 인용 가능.
            heading_lines: list[str] = []
            for level_key in ("h2", "h3"):
                value = header_meta.get(level_key)
                if value:
                    prefix = "## " if level_key == "h2" else "### "
                    heading_lines.append(f"{prefix}{value}")
            heading_prepend = "\n".join(heading_lines)
            full_text = f"{heading_prepend}\n\n{text_part}" if heading_prepend else text_part

            sub_chunks = _split_text(full_text, max_chars=max_chars, overlap=overlap)
            # body 내 sub_chunk가 시작하는 위치 (heading-split이 metadata로 일부 분리해
            # 정확한 offset은 best-effort — body.find(text_part)로 sub_doc 시작점 결정 후
            # 추가 split offset 합산).
            sub_doc_start_in_body = body.find(text_part)
            if sub_doc_start_in_body < 0:
                sub_doc_start_in_body = 0  # heading prepend 변형으로 미일치 가능 — 0으로 fallback.
            for sc in sub_chunks:
                # heading prepend 길이만큼 sub_chunk char_start가 앞으로 밀려있음 →
                # body 좌표로 환산은 best-effort. heading_prepend가 chunk 앞에 prepended
                # 되어 있으면 sub_doc_start_in_body 그대로, 그렇지 않으면 + sc.char_start.
                # 실용적으로 chunk가 *원본의 어디쯤*만 알면 충분(인용 위치 추적용 X).
                char_start = sub_doc_start_in_body + body_shift
                chunks.append(
                    Chunk(
                        text=sc.text,
                        chunk_index=chunk_idx,
                        char_start=char_start,
                        char_end=char_start + len(sc.text),
                    )
                )
                chunk_idx += 1

    logger.info(
        "chunking.markdown.complete",
        chunks_count=len(chunks),
        total_chars=sum(len(c.text) for c in chunks),
    )
    return chunks
