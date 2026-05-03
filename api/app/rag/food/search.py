"""Story 3.4 — 음식 영양 검색 (exact + HNSW 임베딩 fallback + confidence aggregator).

`retrieve_nutrition` 노드 *실 비즈니스 로직* 입력. 3단 검색의 후반부:
- ``search_by_name(session, name)`` — ``food_nutrition.name = :n`` exact 매칭, score
  고정 1.0 (임베딩 호출 X / cost 절약).
- ``search_by_embedding(session, query, top_k)`` — ``embed_texts([query])`` 후 pgvector
  ``embedding <=> :q`` HNSW top-K (디폴트 ``settings.food_retrieval_top_k = 3``).
- ``compute_retrieval_confidence(matches, single_item)`` — top-1 score(single) 또는
  *최소값*(multi) 채택 — 한 항목이라도 신뢰도 낮으면 Self-RAG 재검색 분기(보수적).

design:
- ``ORDER BY embedding <=> :q LIMIT :k`` — pgvector cosine distance 기반 HNSW 검색.
  ``WHERE embedding IS NOT NULL``로 부분 시드(NULL 임베딩 row) 자동 제외(Story 3.1 D4).
- score 정규화 — pgvector `<=>`는 0(완전 일치)~2(반대) 범위 → ``1 - distance/2``
  0~1 정규화, ``[0, 1]`` clip.
- 빈 입력/빈 인덱스 graceful — 빈 리스트 또는 ``None`` 반환.
- NFR-P6 — Story 3.1 baseline DB p95 ≤ 200ms + 임베딩 round-trip ~500ms = p95 ≤ 800ms.
- NFR-S5 — query/name raw 노출 X. items_count + source/path + latency_ms만.
"""

from __future__ import annotations

import time
import uuid
from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.openai_adapter import embed_texts
from app.core.config import settings
from app.graph.state import RetrievedFood

logger = structlog.get_logger(__name__)

# pgvector cosine distance 범위는 0~2. score = 1 - (distance / 2) 정규화 후 clip.
_DISTANCE_NORMALIZATION_DENOMINATOR: Final[float] = 2.0


def _format_vector_literal(values: list[float]) -> str:
    """pgvector ``vector`` 입력 literal — ``[0.1,0.2,...]`` 문자열.

    text() bindparam으로 전달 후 SQL ``CAST(:q AS vector)``로 cast — pgvector ORM
    미지원 회피(Story 3.3 정합).
    """
    return "[" + ",".join(format(v, ".7g") for v in values) + "]"


def _normalize_score(distance: float) -> float:
    """pgvector cosine distance(0~2) → score(0~1) 정규화 + clip."""
    score = 1.0 - (distance / _DISTANCE_NORMALIZATION_DENOMINATOR)
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


async def search_by_name(session: AsyncSession, name: str) -> RetrievedFood | None:
    """``food_nutrition.name`` exact 매칭 (1 round-trip).

    매칭 시 ``RetrievedFood(score=1.0, ...)`` 반환 — exact 매칭은 신뢰도 최고. 미스
    또는 빈 입력 시 ``None``.

    NFR-S5 — name raw 출력 X. hit bool + name_length만.
    """
    if not name or not name.strip():
        return None

    start = time.monotonic()
    stmt = text(
        "SELECT id, name, nutrition FROM food_nutrition WHERE name = :n LIMIT 1"
    ).bindparams(n=name)
    result = await session.execute(stmt)
    row = result.first()

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "food.search.exact",
        hit=row is not None,
        name_length=len(name),
        latency_ms=latency_ms,
    )

    if row is None:
        return None

    return RetrievedFood(
        name=row.name,
        food_id=row.id if isinstance(row.id, uuid.UUID) else uuid.UUID(str(row.id)),
        score=1.0,
        nutrition=row.nutrition or {},
    )


async def search_by_embedding(
    session: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
) -> list[RetrievedFood]:
    """HNSW 임베딩 fallback — ``embed_texts([query])`` → pgvector top-K (1 round-trip + DB).

    단계:
    1. ``embed_texts([query])`` → 1536-dim 벡터 1건(빈 입력은 빈 리스트 반환 — DB 호출 X).
    2. ``ORDER BY embedding <=> :q LIMIT :k`` HNSW 검색 (``WHERE embedding IS NOT NULL``).
    3. distance → score 정규화 + ``RetrievedFood`` 매핑.

    빈 입력/빈 인덱스 → 빈 리스트(graceful). top_k 미지정 시 ``settings.food_retrieval_top_k``.

    NFR-S5 — query raw 출력 X. items_count + latency_ms만.
    """
    if not query or not query.strip():
        return []

    k = top_k if top_k is not None else settings.food_retrieval_top_k

    start = time.monotonic()
    embeddings = await embed_texts([query])
    if not embeddings:
        return []
    vec_literal = _format_vector_literal(embeddings[0])

    stmt = text(
        "SELECT id, name, nutrition, "
        "(embedding <=> CAST(:q AS vector)) AS distance "
        "FROM food_nutrition "
        "WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> CAST(:q AS vector) "
        "LIMIT :k"
    ).bindparams(q=vec_literal, k=k)
    result = await session.execute(stmt)
    rows = result.all()

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "food.search.embedding",
        items_count=len(rows),
        top_k=k,
        latency_ms=latency_ms,
    )

    matches: list[RetrievedFood] = []
    for row in rows:
        food_id = row.id if isinstance(row.id, uuid.UUID) else uuid.UUID(str(row.id))
        matches.append(
            RetrievedFood(
                name=row.name,
                food_id=food_id,
                score=_normalize_score(float(row.distance)),
                nutrition=row.nutrition or {},
            )
        )
    return matches


def compute_retrieval_confidence(
    matches: list[RetrievedFood], *, single_item: bool = True
) -> float:
    """`retrieved_foods` 리스트 → 0~1 retrieval confidence aggregator.

    - 빈 리스트 → 0.0.
    - ``single_item=True``(단일 음식) → top-1 score 그대로.
    - ``single_item=False``(multi-item meal) → *최소값* 채택. 한 항목이라도 신뢰도 낮으면
      Self-RAG 재검색 분기로 보수적 라우팅.
    """
    if not matches:
        return 0.0
    if single_item:
        return matches[0].score
    return min(m.score for m in matches)


__all__ = [
    "compute_retrieval_confidence",
    "search_by_embedding",
    "search_by_name",
]
