"""Async DB session — 테스트·스크립트용 sessionmaker 헬퍼.

본 모듈은 `app.state.session_maker`(main.py lifespan에서 생성)와 별개로,
Alembic env / 일회성 스크립트에서 사용할 수 있는 standalone session_maker를 제공한다.
FastAPI 라우터는 `app.api.deps.get_db_session`을 통해 lifespan 산출 sessionmaker를 사용해야 한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def _asyncpg_connect_args(url: str) -> dict[str, Any]:
    """Story 8.5 — pgbouncer transaction mode 호환 connect_args.

    Supabase Free의 Transaction mode pooler(port 6543, ``?pgbouncer=true``)는 PostgreSQL
    PREPARE statement를 cross-session으로 재사용하지 않는다. asyncpg 디폴트
    (``statement_cache_size=100``)는 prepared statement 캐싱을 시도해 "prepared statement
    \"__asyncpg_stmt_*\" does not exist" 에러를 일으킨다. URL에 ``pgbouncer=true``가 보이면
    캐시 비활성.

    direct connection(port 5432, dev/test) 또는 자체 Postgres는 캐싱 정상 작동 — 본 분기
    미발동.
    """
    if "pgbouncer=true" in url:
        return {"connect_args": {"statement_cache_size": 0}}
    return {}


def build_async_engine(url: str | None = None) -> AsyncEngine:
    target_url = url or settings.database_url
    return create_async_engine(target_url, pool_pre_ping=True, **_asyncpg_connect_args(target_url))


def build_async_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
