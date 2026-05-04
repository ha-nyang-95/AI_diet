"""Story 3.6 — 가이드라인 검색 helper (HNSW + applicable_health_goals 필터, AC1).

`generate_feedback` 노드의 인용 컨텍스트 입력 — `app/rag/food/search.py:search_by_embedding`
parallel 패턴. 사용자 건강 목표(``health_goal``)별 filtered top-K 검색.

설계:
- ``applicable_health_goals`` 필터 — 빈 배열(``'{}'``)은 *전 사용자 적용*(예: 식약처
  22종 알레르기) → 모든 호출자에게 노출. 비-빈 배열은 ``ANY()`` 매칭(예: ``"weight_loss"``
  목표 사용자에게는 ``applicable_health_goals = '{weight_loss}'`` chunks만 매칭).
- ``embedding IS NOT NULL`` — Story 3.2 D4 정합(부분 시드 NULL 임베딩 자동 제외).
- ``ORDER BY embedding <=> :q LIMIT :k`` — pgvector cosine HNSW.
- ``chunk_text``는 token 비용 보호로 LLM 주입 시점에 cap(`KnowledgeChunkContext` 자체는
  본문 보존 — Story 3.6 정합. 호출자 프롬프트 빌더가 cap 책임).

NFR-S5 — query/source raw 출력 X. items_count + health_goal + latency_ms만.
"""

from __future__ import annotations

import math
import time
from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.openai_adapter import embed_texts
from app.domain.health_profile import HealthGoal
from app.graph.state import KnowledgeChunkContext

logger = structlog.get_logger(__name__)

# 인용 본문은 LLM 입력에서 token 비용 보호로 사전 truncate. 300자는 한국어 문장 1-2개 분량.
# 인용 *맥락*은 충분히 보존하면서 prompt token cost 안전 — ``app.graph.prompts.feedback``
# 4-tuple 압축과 정합.
_CHUNK_TEXT_MAX_LENGTH: Final[int] = 300

_DEFAULT_TOP_K: Final[int] = 5


def _format_vector_literal(values: list[float]) -> str:
    """pgvector ``vector`` 입력 literal — ``app.rag.food.search`` 패턴 정합 (NaN/Inf 가드 포함).

    중복 정의 사유: ``app.rag.food.search._format_vector_literal``은 module-private —
    cross-package import는 *encapsulation 깨짐*. inline은 ~5 LoC로 독립 + Story 3.4
    NaN/Inf graceful 패턴 동일.
    """
    if not all(math.isfinite(v) for v in values):
        raise ValueError("embedding contains non-finite values (NaN/Inf)")
    return "[" + ",".join(format(v, ".7g") for v in values) + "]"


async def search_guideline_chunks(
    session: AsyncSession,
    *,
    health_goal: HealthGoal,
    query_text: str,
    top_k: int = _DEFAULT_TOP_K,
) -> list[KnowledgeChunkContext]:
    """``knowledge_chunks`` HNSW + applicable_health_goals 필터 top-K 검색.

    절차:
    1. ``embed_texts([query_text])`` 1건 임베딩 — ``app.rag.food.search`` 패턴 정합.
    2. ``WHERE embedding IS NOT NULL`` + applicable_health_goals 빈 배열 OR ANY 매칭 +
       ``ORDER BY embedding <=> :q LIMIT :k`` HNSW.
    3. ORM row → ``KnowledgeChunkContext`` 매핑(chunk_text 사전 truncate).

    빈 입력 / 임베딩 미설정 / HNSW miss → 빈 리스트(graceful — 노드 측 fallback 분기).
    """
    if not query_text or not query_text.strip():
        return []

    start = time.monotonic()
    embeddings = await embed_texts([query_text])
    if not embeddings:
        return []
    try:
        vec_literal = _format_vector_literal(embeddings[0])
    except ValueError:
        logger.warning("guideline.search.embedding.invalid_vector", reason="non_finite_values")
        return []

    stmt = text(
        """
        SELECT source, doc_title, published_year, chunk_text, authority_grade
        FROM knowledge_chunks
        WHERE embedding IS NOT NULL
          AND (applicable_health_goals = '{}'::text[]
               OR :goal = ANY(applicable_health_goals))
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
        """
    ).bindparams(q=vec_literal, goal=str(health_goal), k=top_k)
    result = await session.execute(stmt)
    rows = result.all()

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "guideline.search.embedding",
        items_count=len(rows),
        health_goal=str(health_goal),
        top_k=top_k,
        latency_ms=latency_ms,
    )

    chunks: list[KnowledgeChunkContext] = []
    for row in rows:
        chunk_text_truncated = row.chunk_text[:_CHUNK_TEXT_MAX_LENGTH] if row.chunk_text else ""
        chunks.append(
            KnowledgeChunkContext(
                source=row.source,
                doc_title=row.doc_title,
                published_year=row.published_year,
                chunk_text=chunk_text_truncated,
                authority_grade=row.authority_grade,
            )
        )
    return chunks


__all__ = ["search_guideline_chunks"]
