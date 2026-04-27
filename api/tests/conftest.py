"""pytest fixtures — async test client + 인프라 precondition fail-fast.

본 스토리(1.1) 시점 전제: Postgres(+pgvector extension 등록) + Redis 가 실행 중.
- CI: service container + `CREATE EXTENSION vector` 사전 실행 (CI workflow에서)
- 로컬: docker compose up

pgvector extension이 누락된 환경에서 테스트가 cryptic 503으로 실패하지 않도록
session-scoped fixture로 한 번 검증하고, 실패 시 명확한 메시지로 즉시 abort.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.main import app


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _verify_pgvector_extension() -> None:
    """Fail fast if pgvector extension is missing — surface clear remediation."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname='vector'")
            )
            row = result.first()
        if row is None:
            pytest.fail(
                "pgvector extension not installed in target Postgres.\n"
                "  Local: `docker compose up` (postgres-init/01-pgvector.sql 자동 실행).\n"
                '  CI/manual: `psql -c "CREATE EXTENSION IF NOT EXISTS vector;"`',
                pytrace=False,
            )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # lifespan_context로 startup/shutdown 트리거 (engine, redis 초기화)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as ac,
        app.router.lifespan_context(app),
    ):
        yield ac
