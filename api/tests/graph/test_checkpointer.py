"""Story 3.3 — `app/graph/checkpointer.py` 단위 + 통합 테스트 (AC2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from psycopg import errors as pg_errors
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.exceptions import AnalysisCheckpointerError
from app.graph.checkpointer import (
    _to_psycopg_dsn,
    build_checkpointer,
    dispose_checkpointer,
)


def test_to_psycopg_dsn_strips_asyncpg_driver() -> None:
    src = "postgresql+asyncpg://app:app@localhost:5432/app"
    assert _to_psycopg_dsn(src) == "postgresql://app:app@localhost:5432/app"


def test_to_psycopg_dsn_passthrough_postgresql() -> None:
    src = "postgresql://user:pass@host:5432/db?sslmode=require"
    assert _to_psycopg_dsn(src) == src


def test_to_psycopg_dsn_passthrough_postgres_short_scheme() -> None:
    src = "postgres://user:pass@host:5432/db"
    # 정규화 결과는 항상 postgresql://.
    assert _to_psycopg_dsn(src) == "postgresql://user:pass@host:5432/db"


def test_to_psycopg_dsn_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported scheme"):
        _to_psycopg_dsn("mysql://user:pass@host/db")


async def test_build_checkpointer_round_trip_and_schema_isolation() -> None:
    """schema 사전 생성 + setup() 후 `lg_checkpoints` schema에 3 테이블 존재."""
    checkpointer, pool = await build_checkpointer(settings.database_url)
    try:
        # `lg_checkpoints` schema에 3 테이블 (checkpoints / blobs / writes) 생성 검증.
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT table_schema, table_name FROM information_schema.tables "
                        "WHERE table_schema = 'lg_checkpoints' AND table_name LIKE 'checkpoint%'",
                    ),
                )
                rows = result.all()
                schemas = {row[0] for row in rows}
                table_names = {row[1] for row in rows}
                assert schemas == {"lg_checkpoints"}
                # langgraph-checkpoint-postgres 3.x는 checkpoints/checkpoint_blobs/
                # checkpoint_writes 3 테이블 (idempotent).
                assert "checkpoints" in table_names
                # public schema에는 checkpoint 테이블 0건 (격리 검증).
                public_check = await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name LIKE 'checkpoint%'",
                    ),
                )
                assert public_check.scalar() == 0
        finally:
            await engine.dispose()

        # round-trip — 미존재 thread_id 조회 → None (saver 자체는 정상 동작).
        # 실 `aput`은 LangGraph StateGraph가 `checkpoint_ns`/`checkpoint_id` 자동
        # 채움 (Story 3.3 AC5의 pipeline 테스트가 종단 검증). 본 테스트는 *checkpointer
        # 인프라*만 — schema 격리 + setup() 멱등성 + aget의 None-safe 동작.
        config = {"configurable": {"thread_id": "test-thread-missing"}}
        got = await checkpointer.aget(config)
        assert got is None

    finally:
        await dispose_checkpointer(pool)


async def test_dispose_checkpointer_idempotent() -> None:
    """2회 호출도 안전 (shutdown 경로 graceful)."""
    _, pool = await build_checkpointer(settings.database_url)
    await dispose_checkpointer(pool)
    # 두 번째 호출은 이미 closed pool — warn 로그만, 예외 X.
    await dispose_checkpointer(pool)


async def test_build_checkpointer_maps_operational_error() -> None:
    """psycopg `OperationalError` → `AnalysisCheckpointerError` 매핑."""

    async def _boom(*args: object, **kwargs: object) -> None:
        raise pg_errors.OperationalError("conn refused")

    with patch("app.graph.checkpointer._ensure_schema", new=AsyncMock(side_effect=_boom)):
        with pytest.raises(AnalysisCheckpointerError) as exc_info:
            await build_checkpointer(settings.database_url)
        assert "checkpointer.setup_failed" in str(exc_info.value)
        # cause 보존 — Sentry stack trace 정상.
        assert isinstance(exc_info.value.__cause__, pg_errors.OperationalError)
