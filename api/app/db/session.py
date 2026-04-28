"""Async DB session — 테스트·스크립트용 sessionmaker 헬퍼.

본 모듈은 `app.state.session_maker`(main.py lifespan에서 생성)와 별개로,
Alembic env / 일회성 스크립트에서 사용할 수 있는 standalone session_maker를 제공한다.
FastAPI 라우터는 `app.api.deps.get_db_session`을 통해 lifespan 산출 sessionmaker를 사용해야 한다.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def build_async_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or settings.database_url, pool_pre_ping=True)


def build_async_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
