"""Story 3.4 — `search_by_embedding` p95 latency 검증 (NFR-P6 정합, AC13).

`@pytest.mark.perf` skip 디폴트 — `RUN_PERF_TESTS=1` opt-in. dev/test 환경 시드가
없거나 부분일 경우 측정 의미 X — N/A skip.

NFR-P6 baseline (Story 3.1 DB-only) ≤ 200ms + 임베딩 round-trip ~500ms = p95 ≤ 800ms
목표. NFR-P4 ≤ 3s 분석 budget 안에서 안전.
"""

from __future__ import annotations

import os
import time

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.main import app
from app.rag.food.search import search_by_embedding

pytestmark = pytest.mark.perf

P95_BUDGET_MS = 800.0


def _perf_enabled() -> bool:
    return os.environ.get("RUN_PERF_TESTS", "").lower() in {"1", "true", "yes", "on"}


@pytest.mark.skipif(not _perf_enabled(), reason="RUN_PERF_TESTS=1 opt-in 필요")
async def test_search_by_embedding_p95_under_800ms(client: AsyncClient) -> None:
    """30회 측정 → p95 ≤ 800ms.

    dev/test 환경 — `food_nutrition`이 비어있으면 N/A skip(빈 인덱스 측정 의미 X).
    """
    _ = client
    session_maker: async_sessionmaker = app.state.session_maker

    # 시드 검증 — 빈 인덱스에서는 측정 의미 X.
    async with session_maker() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM food_nutrition WHERE embedding IS NOT NULL")
        )
        seeded_count = result.scalar()
    if not seeded_count or seeded_count < 100:
        pytest.skip(
            f"food_nutrition seeded count {seeded_count} too small for perf — "
            "Story 3.1 시드 후 재실행"
        )

    latencies_ms: list[float] = []
    async with session_maker() as session:
        for i in range(30):
            start = time.perf_counter()
            await search_by_embedding(session, f"짜장면 {i}", top_k=3)
            latencies_ms.append((time.perf_counter() - start) * 1000.0)

    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    assert p95 <= P95_BUDGET_MS, f"p95 {p95:.1f}ms > {P95_BUDGET_MS}ms (NFR-P6 미달)"
