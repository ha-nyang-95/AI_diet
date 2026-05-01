"""Story 3.2 — alembic 0011 schema 회귀 (knowledge_chunks + HNSW + GIN + composite btree).

신규 테이블 ``knowledge_chunks`` + UNIQUE 제약 + HNSW + GIN + composite btree 4개
인덱스 + alembic round-trip(upgrade head → downgrade 0010 → upgrade head)이 정상인지
단언. 마이그레이션이 ORM ``__table_args__``와 drift하면 첫 hit.

``client`` fixture 의존성 — lifespan 트리거로 ``app.state.session_maker`` 초기화 보장.
"""

from __future__ import annotations

import asyncio

from alembic.config import Config as AlembicConfig
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command as alembic_command
from app.core.config import settings
from app.main import app


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


async def test_knowledge_chunks_table_and_indexes_exist(client: AsyncClient) -> None:
    """``information_schema.columns`` + ``pg_indexes`` — 테이블 컬럼 NOT NULL 정합 +
    HNSW + GIN + composite btree 인덱스 4건 모두 존재 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        col_result = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name='knowledge_chunks' "
                "ORDER BY ordinal_position"
            )
        )
        col_rows = list(col_result.all())
        idx_result = await session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='knowledge_chunks'")
        )
        idx_rows = list(idx_result.all())

    assert col_rows, "knowledge_chunks table missing — alembic 0011 unapplied?"
    columns = {r.column_name: (r.data_type, r.is_nullable) for r in col_rows}
    assert columns["source"] == ("text", "NO")
    assert columns["source_id"] == ("text", "NO")
    assert columns["chunk_index"] == ("integer", "NO")
    assert columns["chunk_text"] == ("text", "NO")
    # embedding은 USER-DEFINED type (vector) — D4 NULL 허용.
    assert "embedding" in columns
    assert columns["embedding"][1] == "YES"
    assert columns["authority_grade"] == ("text", "NO")
    assert columns["topic"] == ("text", "NO")
    # applicable_health_goals는 ARRAY type (text[]).
    assert columns["applicable_health_goals"] == ("ARRAY", "NO")
    # published_year NULL 허용.
    assert columns["published_year"] == ("integer", "YES")
    assert columns["doc_title"] == ("text", "NO")

    # 인덱스 4건 모두 존재 — HNSW + GIN + composite btree + 자동 unique constraint 인덱스.
    indexes = {r.indexname: r.indexdef for r in idx_rows}
    assert "idx_knowledge_chunks_embedding" in indexes
    assert "hnsw" in indexes["idx_knowledge_chunks_embedding"].lower()
    assert "vector_cosine_ops" in indexes["idx_knowledge_chunks_embedding"]
    assert "idx_knowledge_chunks_applicable_health_goals" in indexes
    assert "gin" in indexes["idx_knowledge_chunks_applicable_health_goals"].lower()
    assert "idx_knowledge_chunks_source" in indexes
    assert "(source, authority_grade)" in indexes["idx_knowledge_chunks_source"]


async def test_knowledge_chunks_unique_constraint(client: AsyncClient) -> None:
    """``uq_knowledge_chunks_source_source_id_chunk_index`` UNIQUE 존재 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname='uq_knowledge_chunks_source_source_id_chunk_index' "
                "AND contype='u'"
            )
        )
        row = result.first()
    assert row is not None, "UNIQUE(source, source_id, chunk_index) constraint missing"


async def test_knowledge_chunks_default_empty_array(client: AsyncClient) -> None:
    """``applicable_health_goals`` server default ``'{}'::text[]`` — INSERT 생략 시 빈 배열."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(source, source_id, chunk_index, chunk_text, authority_grade, topic, doc_title) "
                "VALUES ('MFDS', 'TEST-DEFAULT', 0, '본문', 'A', 'general', '테스트 문서')"
            )
        )
        await session.commit()

        row = (
            await session.execute(
                text(
                    "SELECT applicable_health_goals FROM knowledge_chunks "
                    "WHERE source='MFDS' AND source_id='TEST-DEFAULT'"
                )
            )
        ).first()
        assert row is not None
        assert row.applicable_health_goals == []
        # cleanup — 다음 테스트 영향 X.
        await session.execute(
            text("DELETE FROM knowledge_chunks WHERE source='MFDS' AND source_id='TEST-DEFAULT'")
        )
        await session.commit()


async def test_alembic_0011_round_trip(client: AsyncClient) -> None:
    """alembic upgrade head → downgrade 0010 → upgrade head round-trip 정상 단언."""
    _ = client
    cfg = _alembic_config()
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0010_food_nutrition_and_aliases")
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name='knowledge_chunks'"
            )
        )
        rows = list(result.all())
    try:
        assert rows == [], f"knowledge_chunks table still exists after downgrade: {rows}"
    finally:
        # 다음 테스트에 영향 X — head로 복구.
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
