"""Story 3.1 — alembic 0010 schema 회귀 (food_nutrition + food_aliases + HNSW 인덱스).

두 신규 테이블 + UNIQUE 제약 + HNSW 인덱스 + alembic round-trip(upgrade head →
downgrade 0009 → upgrade head)이 정상인지 단언. 마이그레이션 file이 ORM
``__table_args__``와 drift하면 첫 hit.

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


async def test_food_nutrition_table_exists(client: AsyncClient) -> None:
    """``information_schema.tables``에 food_nutrition 등록 + 핵심 컬럼 NOT NULL 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name='food_nutrition' "
                "ORDER BY ordinal_position"
            )
        )
        rows = list(result.all())
    assert rows, "food_nutrition table missing — alembic 0010 unapplied?"
    columns = {r.column_name: (r.data_type, r.is_nullable) for r in rows}
    # 핵심 컬럼 존재 + NOT NULL 단언.
    assert columns["id"][1] == "NO"
    assert columns["name"] == ("text", "NO")
    assert columns["category"] == ("text", "YES")
    assert columns["nutrition"] == ("jsonb", "NO")
    # embedding은 USER-DEFINED type (vector) — data_type은 "USER-DEFINED" 또는 "vector".
    assert "embedding" in columns
    assert columns["embedding"][1] == "YES"  # NULL 허용 (D4)
    assert columns["source"] == ("text", "NO")
    assert columns["source_id"] == ("text", "NO")


async def test_food_aliases_table_exists(client: AsyncClient) -> None:
    """food_aliases 테이블 + 컬럼 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name='food_aliases' "
                "ORDER BY ordinal_position"
            )
        )
        rows = list(result.all())
    assert rows, "food_aliases table missing — alembic 0010 unapplied?"
    columns = {r.column_name: (r.data_type, r.is_nullable) for r in rows}
    assert columns["alias"] == ("text", "NO")
    assert columns["canonical_name"] == ("text", "NO")


async def test_food_nutrition_unique_constraint(client: AsyncClient) -> None:
    """``uq_food_nutrition_source_source_id`` UNIQUE 존재 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname='uq_food_nutrition_source_source_id' "
                "AND contype='u'"
            )
        )
        row = result.first()
    assert row is not None, "uq_food_nutrition_source_source_id UNIQUE constraint missing"


async def test_food_aliases_unique_constraint(client: AsyncClient) -> None:
    """``uq_food_aliases_alias`` UNIQUE 존재 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname='uq_food_aliases_alias' "
                "AND contype='u'"
            )
        )
        row = result.first()
    assert row is not None, "uq_food_aliases_alias UNIQUE constraint missing"


async def test_food_nutrition_hnsw_index_exists(client: AsyncClient) -> None:
    """``idx_food_nutrition_embedding`` HNSW 인덱스 + cosine ops 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename='food_nutrition' "
                "AND indexname='idx_food_nutrition_embedding'"
            )
        )
        row = result.first()
    assert row is not None, "idx_food_nutrition_embedding HNSW index missing"
    indexdef = row.indexdef
    # USING hnsw + vector_cosine_ops 명시 (D3).
    assert "hnsw" in indexdef.lower()
    assert "vector_cosine_ops" in indexdef


async def test_alembic_0010_round_trip(client: AsyncClient) -> None:
    """alembic upgrade head → downgrade 0009 → upgrade head 정상 round-trip 단언.

    downgrade 후 두 테이블이 사라져야 하고, 재 upgrade 후 다시 존재해야 한다.
    이 테스트는 다음 테스트로 영향 X — 끝에 다시 head로 복구.
    """
    _ = client
    cfg = _alembic_config()
    # downgrade 0009
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0009_meals_idempotency_key")
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('food_nutrition', 'food_aliases')"
            )
        )
        rows = list(result.all())
    try:
        assert rows == [], (
            f"food_nutrition / food_aliases tables still exist after downgrade: {rows}"
        )
    finally:
        # 다음 테스트에 영향 X — head로 복구.
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
