"""Story 2.5 — alembic 0009 schema 회귀 (선택 — Idempotency-Key 처리).

``meals.idempotency_key`` TEXT NULL + ``idx_meals_user_id_idempotency_key_unique``
partial UNIQUE index 존재 단언. 마이그레이션 file이 ORM ``__table_args__``와 drift
하면 첫 hit (deferred-work D29 forward).

``client`` fixture 의존성 — lifespan 트리거로 ``app.state.session_maker`` 초기화 보장.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app


async def test_meals_idempotency_key_column_exists(client: AsyncClient) -> None:
    _ = client
    """``information_schema.columns``에서 nullable TEXT 컬럼 단언."""
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name='meals' AND column_name='idempotency_key'"
            )
        )
        row = result.first()
    assert row is not None, "meals.idempotency_key column missing — alembic 0009 unapplied?"
    assert row.data_type == "text"
    assert row.is_nullable == "YES"


async def test_meals_idempotency_key_partial_unique_index_exists(client: AsyncClient) -> None:
    """``pg_indexes``에서 partial UNIQUE index 존재 + WHERE 절 단언."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename='meals' AND indexname='idx_meals_user_id_idempotency_key_unique'"
            )
        )
        row = result.first()
    assert row is not None, "partial UNIQUE index missing — alembic 0009 unapplied?"
    indexdef = row.indexdef
    assert "UNIQUE" in indexdef.upper()
    assert "user_id" in indexdef
    assert "idempotency_key" in indexdef
    # partial WHERE 절 — NULL 제외 unique.
    assert "idempotency_key IS NOT NULL" in indexdef
