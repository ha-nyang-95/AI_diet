"""Story 3.2 — ``chunk_markdown`` 단위 테스트 (AC #2).

5 케이스: frontmatter 분리 + heading-aware split + max_chars cap + 빈 입력 + chunk_index.
"""

from __future__ import annotations

from app.rag.chunking import Chunk, chunk_markdown


def test_chunk_markdown_strips_frontmatter_and_splits_headings() -> None:
    """frontmatter는 chunking 대상에서 제외 + heading-aware split (## / ###)."""
    content = """---
source: MOHW
source_id: KDRIS-2020-AMDR
---

# 본 문서 — H1 (제목)

## 매크로 비율 권장

탄수화물은 일반 성인 식이에서 총 에너지의 55-65%를 권장합니다.

## 단백질 권장량

단백질은 7-20% 범위가 한국인 영양소 섭취기준 AMDR 값입니다.
"""
    chunks = chunk_markdown(content)
    assert chunks, "frontmatter 분리 후에도 chunks 생성 필요"
    # frontmatter는 chunk text에 포함되지 않음 (source: MOHW가 추출되면 안 됨).
    for ch in chunks:
        assert "source: MOHW" not in ch.text
        assert "source_id: KDRIS-2020-AMDR" not in ch.text
    # heading prepend — 적어도 한 chunk는 ## heading text 포함.
    joined = "\n".join(ch.text for ch in chunks)
    assert "매크로 비율 권장" in joined or "단백질 권장량" in joined


def test_chunk_markdown_max_chars_cap() -> None:
    """max_chars=200으로 설정 시 모든 chunk가 약 200자 이하 + chunk 다수 생성."""
    long_body = "## 섹션\n\n" + ("탄수화물은 한국인 영양소 섭취기준 AMDR에서 55-65% 권장. " * 50)
    content = f"---\nsource: MOHW\n---\n\n{long_body}"
    chunks = chunk_markdown(content, max_chars=200, overlap=20)
    assert len(chunks) >= 2
    for ch in chunks:
        # overlap을 고려해 max_chars + overlap 정도까지는 허용.
        assert len(ch.text) <= 250


def test_chunk_markdown_empty_input_returns_empty_list() -> None:
    """빈 문자열 / whitespace only / frontmatter only → 빈 리스트."""
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n  ") == []
    # frontmatter only — body 없음.
    assert chunk_markdown("---\nsource: MOHW\n---\n") == []


def test_chunk_markdown_short_single_paragraph() -> None:
    """단일 단락 (< max_chars) → 1 chunk."""
    content = "## 짧은 섹션\n\n탄수화물 55-65% 권장."
    chunks = chunk_markdown(content)
    assert len(chunks) == 1
    assert isinstance(chunks[0], Chunk)
    assert chunks[0].chunk_index == 0


def test_chunk_markdown_chunk_index_sequential() -> None:
    """긴 입력 (다중 chunk) → chunk_index가 0..N 정합."""
    body = "## A\n\n" + ("탄수화물 권장 " * 200) + "\n\n## B\n\n" + ("단백질 권장 " * 200)
    content = f"---\nsource: MOHW\n---\n\n{body}"
    chunks = chunk_markdown(content, max_chars=300, overlap=30)
    assert len(chunks) >= 3
    for i, ch in enumerate(chunks):
        assert ch.chunk_index == i, f"chunk_index drift at {i}: {ch.chunk_index}"
