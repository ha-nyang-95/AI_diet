"""Story 5.1 AC1 — 0016_users_profile_updated_at 마이그레이션 검증.

본 모듈은 *DB 레벨* 검증 — alembic이 실제로 ``profile_updated_at`` DateTime(timezone=True)
nullable 컬럼을 박는지, default가 ``NULL`` 인지, ORM Mapped 직접 set/get이 동작하는지
회귀 가드.

Story 4.4 ``test_users_macro_goal.py`` 패턴 정합 — 0013/0014/0015 마이그레이션
테스트와 동일하게 *최종 head 상태*를 검증(alembic up/down roundtrip은 conftest의
session-scoped fixture가 실행 — 본 모듈은 그 결과만 검증).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.user import User
from app.main import app


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    """``app.state.session_maker``는 lifespan에서 init — `client` fixture가 lifespan 활성."""
    _ = client
    return app.state.session_maker


@pytest.mark.asyncio
async def test_profile_updated_at_default_null(session_maker: async_sessionmaker) -> None:
    """Story 5.1 AC1 — ``users`` 신규 row 생성 시 ``profile_updated_at`` default NULL.

    *Why*: 기존 사용자(Story 1.x baseline) 회귀 0건 — 본 컬럼은 PATCH 첫 호출 시점에만
    set이라야 하고, INSERT 직후·POST /me/profile 직후에는 NULL invariant.
    """
    async with session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, google_sub, email, email_verified) "
                "VALUES (:id, :sub, :email, true)"
            ),
            {
                "id": uuid.uuid4(),
                "sub": f"google-sub-{uuid.uuid4()}",
                "email": f"{uuid.uuid4().hex}@example.com",
            },
        )
        await session.commit()

        result = await session.execute(
            text("SELECT profile_updated_at FROM users ORDER BY created_at DESC LIMIT 1")
        )
        row = result.first()
        assert row is not None
        assert row[0] is None


@pytest.mark.asyncio
async def test_profile_updated_at_orm_set_get(session_maker: async_sessionmaker) -> None:
    """Story 5.1 AC1 — ORM ``User.profile_updated_at`` Mapped[datetime|None] 직접 set/get.

    *Why*: PATCH endpoint는 ``func.now()``로 set하지만 ORM 레벨 정합성도 필요 — Mapped
    annotation이 ``datetime | None``을 정확히 반영하고 timezone-aware 값이 round-trip
    가능해야 한다.
    """
    user_id = uuid.uuid4()
    set_at = datetime(2026, 5, 7, 12, 30, 0, tzinfo=UTC)
    async with session_maker() as session:
        user = User(
            id=user_id,
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex}@example.com",
            email_verified=True,
            profile_updated_at=set_at,
        )
        session.add(user)
        await session.commit()

        result = await session.execute(select(User).where(User.id == user_id))
        loaded = result.scalar_one()
        assert loaded.profile_updated_at is not None
        # asyncpg는 timezone-aware datetime을 그대로 round-trip — 마이크로초 정밀도까지 유지.
        assert loaded.profile_updated_at == set_at
