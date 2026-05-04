"""Story 3.6 — `app.rag.guidelines.search.search_guideline_chunks` 단위 테스트 (4 케이스, AC1).

DB integration — `client` fixture로 lifespan 활성화. embed_texts는 monkeypatch로 결정성
1536-dim 벡터 주입(실 OpenAI 호출 X).
"""

from __future__ import annotations

import sys

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.rag.guidelines.search import search_guideline_chunks

_GS_MODULE = sys.modules["app.rag.guidelines.search"]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(v, ".7g") for v in values) + "]"


async def _seed_chunks(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """diverse `applicable_health_goals` + 일부 NULL embedding chunks 시드."""
    async with session_maker() as session:
        await session.execute(text("TRUNCATE knowledge_chunks RESTART IDENTITY"))
        # 1) weight_loss 전용 (embedding 있음)
        await session.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(source, source_id, chunk_index, chunk_text, embedding, "
                "authority_grade, topic, applicable_health_goals, doc_title, published_year) "
                "VALUES (:s, :si, :ci, :ct, CAST(:emb AS vector), 'A', 'general', :g, :dt, :y)"
            ),
            {
                "s": "KSSO",
                "si": "WL-1",
                "ci": 0,
                "ct": "체중 감량 1차 권고",
                "emb": _vector_literal([0.1] * 1536),
                "g": ["weight_loss"],
                "dt": "비만 진료지침",
                "y": 2022,
            },
        )
        # 2) 빈 배열 (전 사용자 적용)
        await session.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(source, source_id, chunk_index, chunk_text, embedding, "
                "authority_grade, topic, applicable_health_goals, doc_title, published_year) "
                "VALUES (:s, :si, :ci, :ct, CAST(:emb AS vector), 'A', 'general', :g, :dt, :y)"
            ),
            {
                "s": "MFDS",
                "si": "ALL-1",
                "ci": 0,
                "ct": "전 사용자 적용 권고",
                "emb": _vector_literal([0.11] * 1536),
                "g": [],
                "dt": "식약처 가이드",
                "y": 2023,
            },
        )
        # 3) diabetes_management 전용 (embedding 있음 — 매칭 X 검증)
        await session.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(source, source_id, chunk_index, chunk_text, embedding, "
                "authority_grade, topic, applicable_health_goals, doc_title, published_year) "
                "VALUES (:s, :si, :ci, :ct, CAST(:emb AS vector), 'A', 'general', :g, :dt, :y)"
            ),
            {
                "s": "MOHW",
                "si": "DM-1",
                "ci": 0,
                "ct": "당뇨 관리 권고",
                "emb": _vector_literal([0.12] * 1536),
                "g": ["diabetes_management"],
                "dt": "당뇨 가이드",
                "y": 2024,
            },
        )
        # 4) embedding NULL (자동 제외 — applicable_health_goals은 weight_loss)
        await session.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(source, source_id, chunk_index, chunk_text, "
                "authority_grade, topic, applicable_health_goals, doc_title, published_year) "
                "VALUES (:s, :si, :ci, :ct, 'A', 'general', :g, :dt, :y)"
            ),
            {
                "s": "KSSO",
                "si": "WL-NULL",
                "ci": 0,
                "ct": "체중 감량 NULL embedding (제외 대상)",
                "g": ["weight_loss"],
                "dt": "Test",
                "y": 2020,
            },
        )
        await session.commit()


@pytest.fixture
def fake_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_texts → 결정성 1536-dim 벡터 1건."""

    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1536]

    monkeypatch.setattr(_GS_MODULE, "embed_texts", _fake_embed)


async def test_health_goal_filter_matches_seeded_chunks(
    client: AsyncClient, fake_embed: None
) -> None:
    """weight_loss 시드 chunks 매칭 + 빈 배열 chunks 포함 (DM 전용 chunks 제외)."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_chunks(session_maker)

    async with session_maker() as session:
        chunks = await search_guideline_chunks(
            session,
            health_goal="weight_loss",
            query_text="체중 감량",
            top_k=10,
        )
    sources = {c.source for c in chunks}
    assert "KSSO" in sources  # weight_loss 전용
    assert "MFDS" in sources  # 빈 배열 (전 사용자 적용)
    assert "MOHW" not in sources  # diabetes_management 전용 → 제외


async def test_empty_applicable_health_goals_included(
    client: AsyncClient, fake_embed: None
) -> None:
    """빈 배열 chunks(전 사용자 적용)는 어떤 health_goal 쿼리에도 포함."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_chunks(session_maker)

    async with session_maker() as session:
        chunks = await search_guideline_chunks(
            session,
            health_goal="diabetes_management",
            query_text="당뇨 관리",
            top_k=10,
        )
    sources = {c.source for c in chunks}
    assert "MFDS" in sources  # 빈 배열 — 전 사용자 적용
    assert "MOHW" in sources  # diabetes_management 매칭


async def test_null_embedding_chunks_excluded(client: AsyncClient, fake_embed: None) -> None:
    """``embedding IS NULL`` chunks는 자동 제외."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_chunks(session_maker)

    async with session_maker() as session:
        chunks = await search_guideline_chunks(
            session,
            health_goal="weight_loss",
            query_text="체중 감량",
            top_k=10,
        )
    # source_id WL-NULL은 NULL embedding — 결과에 포함 X.
    chunk_titles = {c.chunk_text for c in chunks}
    assert "체중 감량 NULL embedding (제외 대상)" not in chunk_titles


async def test_empty_query_text_returns_empty(client: AsyncClient, fake_embed: None) -> None:
    """빈 query_text → 빈 리스트(graceful — DB 호출 X)."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _seed_chunks(session_maker)

    async with session_maker() as session:
        chunks = await search_guideline_chunks(
            session,
            health_goal="weight_loss",
            query_text="   ",
            top_k=5,
        )
    assert chunks == []
