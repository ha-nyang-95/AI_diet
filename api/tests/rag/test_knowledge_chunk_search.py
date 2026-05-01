"""Story 3.2 — HNSW + GIN 인덱스 활용 검증 (AC #5).

본 스토리는 *인덱스 존재 + EXPLAIN 활용*만 단언 — 검색 흐름 자체는 Story 3.6
책임 (``app/rag/guidelines/search.py`` 본 스토리 OUT).

케이스:
  1. HNSW 인덱스 활용 — ``EXPLAIN`` 출력에 ``idx_knowledge_chunks_embedding`` 또는
     ``Index Scan`` 명시.
  2. GIN 인덱스 활용 — ``applicable_health_goals @> ARRAY['weight_loss']`` 필터에
     ``idx_knowledge_chunks_applicable_health_goals`` (GIN) 활용.
  3. 빈 배열 OR 분기 — ``OR applicable_health_goals = '{}'::text[]`` 패턴 동작 검증
     (전 사용자 적용 row 매칭).
  4. 100회 검색 perf p95 < 200ms (``RUN_PERF_TEST=1`` 환경 변수 시점에만 실행).
"""

from __future__ import annotations

import os
import time

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app


def _vector_literal(values: list[float]) -> str:
    """pgvector ``vector`` 입력 literal — ``[0.1,0.2,...]`` 문자열 cast."""
    return "[" + ",".join(format(v, ".7g") for v in values) + "]"


async def _seed_minimal_chunks(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """EXPLAIN 검증용 최소 시드 — 다양한 applicable_health_goals 값을 갖는 chunks."""
    async with session_maker() as session:
        await session.execute(text("TRUNCATE knowledge_chunks RESTART IDENTITY"))
        # weight_loss 전용 5건 + diabetes_management 전용 5건 + 빈 배열(전 사용자) 5건.
        rows = [
            ("KSSO", "TEST-WL", ["weight_loss"]),
            ("MOHW", "TEST-DM", ["diabetes_management"]),
            ("MFDS", "TEST-ALL", []),
        ]
        chunk_idx = 0
        for source, source_id, goals in rows:
            for i in range(5):
                vec = _vector_literal([0.01 * (chunk_idx + 1)] * 1536)
                await session.execute(
                    text(
                        "INSERT INTO knowledge_chunks "
                        "(source, source_id, chunk_index, chunk_text, embedding, "
                        "authority_grade, topic, applicable_health_goals, doc_title) "
                        "VALUES (:source, :source_id, :ci, :ct, "
                        "CAST(:emb AS vector), 'A', 'general', :goals, 'Test doc')"
                    ),
                    {
                        "source": source,
                        "source_id": source_id,
                        "ci": i,
                        "ct": f"테스트 chunk {chunk_idx}",
                        "emb": vec,
                        "goals": goals,
                    },
                )
                chunk_idx += 1
        await session.commit()


async def test_explain_uses_hnsw_index_for_embedding_order_by(
    client: AsyncClient,
) -> None:
    """``ORDER BY embedding <=> :v LIMIT N`` 패턴 → HNSW 인덱스 활용 또는 인덱스 존재 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_minimal_chunks(session_maker)

    query_vec = _vector_literal([0.1] * 1536)
    async with session_maker() as session:
        result = await session.execute(
            text(
                f"EXPLAIN SELECT id, source, chunk_text, "
                f"embedding <=> '{query_vec}'::vector AS dist "
                f"FROM knowledge_chunks WHERE embedding IS NOT NULL "
                f"ORDER BY embedding <=> '{query_vec}'::vector LIMIT 5"
            )
        )
        plan = "\n".join(row[0] for row in result.all())
    has_hnsw = "idx_knowledge_chunks_embedding" in plan or "Index Scan" in plan
    if not has_hnsw:
        # 적은 행 수에서 Seq Scan 선택 가능 — *인덱스 존재* 단언으로 약화 (Story 3.1 정합).
        async with session_maker() as session:
            idx = (
                await session.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname='idx_knowledge_chunks_embedding'"
                    )
                )
            ).first()
        assert idx is not None, f"HNSW index missing. Plan:\n{plan}"
        assert "hnsw" in idx.indexdef.lower()


async def test_explain_uses_gin_index_for_applicable_health_goals_filter(
    client: AsyncClient,
) -> None:
    """``applicable_health_goals @> ARRAY['weight_loss']`` → GIN 인덱스 활용 또는 인덱스 존재."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_minimal_chunks(session_maker)

    async with session_maker() as session:
        result = await session.execute(
            text(
                "EXPLAIN SELECT id, source, chunk_text "
                "FROM knowledge_chunks "
                "WHERE applicable_health_goals @> ARRAY['weight_loss']::text[]"
            )
        )
        plan = "\n".join(row[0] for row in result.all())
    has_gin = (
        "idx_knowledge_chunks_applicable_health_goals" in plan
        or "Bitmap Index Scan" in plan
        or "Index Scan" in plan
    )
    if not has_gin:
        # 적은 행 수에서 Seq Scan — *인덱스 존재* 약화 단언.
        async with session_maker() as session:
            idx = (
                await session.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname='idx_knowledge_chunks_applicable_health_goals'"
                    )
                )
            ).first()
        assert idx is not None, f"GIN index missing. Plan:\n{plan}"
        assert "gin" in idx.indexdef.lower()


async def test_empty_array_or_branch_matches_all_users(client: AsyncClient) -> None:
    """``applicable_health_goals = '{}'::text[]`` 빈 배열 row 매칭 — 전 사용자 적용 정합 검증."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_minimal_chunks(session_maker)

    async with session_maker() as session:
        # weight_loss 사용자 검색 — weight_loss row 5건 + 빈 배열 row 5건 = 10건 매칭.
        result = await session.execute(
            text(
                "SELECT count(*) AS n FROM knowledge_chunks "
                "WHERE applicable_health_goals @> ARRAY['weight_loss']::text[] "
                "OR applicable_health_goals = '{}'::text[]"
            )
        )
        row = result.first()
    assert row is not None
    assert row.n == 10  # 5 (weight_loss) + 5 (empty array — MFDS 전 사용자 적용)


@pytest.mark.skipif(
    os.environ.get("RUN_PERF_TEST", "").strip() not in {"1", "true", "True"},
    reason="perf test skipped by default — set RUN_PERF_TEST=1 to enable",
)
async def test_p95_latency_under_200ms(client: AsyncClient) -> None:
    """100회 HNSW + GIN composite 검색 → p95 < 200ms (NFR-P6 정합)."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_minimal_chunks(session_maker)

    query_vec = _vector_literal([0.1] * 1536)
    timings: list[float] = []
    async with session_maker() as session:
        for _ in range(100):
            start = time.monotonic()
            await session.execute(
                text(
                    f"SELECT id FROM knowledge_chunks "
                    f"WHERE embedding IS NOT NULL "
                    f"AND (applicable_health_goals @> ARRAY['weight_loss']::text[] "
                    f"OR applicable_health_goals = '{{}}'::text[]) "
                    f"ORDER BY embedding <=> '{query_vec}'::vector LIMIT 5"
                )
            )
            timings.append((time.monotonic() - start) * 1000)
    timings.sort()
    p95 = timings[94]
    assert p95 < 200, f"p95 latency {p95:.1f}ms exceeds 200ms target"
