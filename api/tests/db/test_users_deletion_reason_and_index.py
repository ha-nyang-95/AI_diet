"""Story 5.2 AC1 — 0017_users_deletion_reason_and_purge_index 마이그레이션 검증.

본 모듈은 *DB 레벨* 검증 — alembic이 실제로 ``deletion_reason`` Text nullable
컬럼과 ``idx_users_deleted_at_pending_purge`` partial index를 박는지, ORM Mapped
직접 set/get이 동작하는지, partial index가 ``deleted_at IS NOT NULL`` predicate
로 등록됐는지 회귀 가드.

Story 5.1 ``test_users_profile_updated_at.py`` 패턴 정합 — alembic up/down
roundtrip은 conftest의 session-scoped fixture가 실행 — 본 모듈은 *최종 head 상태*
만 검증.
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
async def test_deletion_reason_default_null_and_orm_set_get(
    session_maker: async_sessionmaker,
) -> None:
    """Story 5.2 AC1 — ``deletion_reason`` default NULL + ORM Mapped[str|None] 직접 set/get.

    *Why*: 기존 사용자(Story 1.x baseline) 회귀 0건 — 본 컬럼은 ``DELETE /v1/users/me``
    시점에만 set이라야 하고, INSERT 직후 NULL invariant. ORM Mapped annotation이
    ``str | None``을 정확히 반영하고 자유 텍스트 round-trip 가능해야 한다.
    """
    user_id = uuid.uuid4()
    async with session_maker() as session:
        # default NULL 검증
        await session.execute(
            text(
                "INSERT INTO users (id, google_sub, email, email_verified) "
                "VALUES (:id, :sub, :email, true)"
            ),
            {
                "id": user_id,
                "sub": f"google-sub-{uuid.uuid4()}",
                "email": f"{uuid.uuid4().hex}@example.com",
            },
        )
        await session.commit()

        result = await session.execute(
            text("SELECT deletion_reason FROM users WHERE id = :id"),
            {"id": user_id},
        )
        row = result.first()
        assert row is not None
        assert row[0] is None

        # ORM 레벨 set/get round-trip
        loaded = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        loaded.deletion_reason = "잘 모르겠음"
        loaded.deleted_at = datetime(2026, 5, 7, 12, 0, 0, tzinfo=UTC)
        await session.commit()

        result2 = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        assert result2.deletion_reason == "잘 모르겠음"


@pytest.mark.asyncio
async def test_idx_users_deleted_at_pending_purge_exists(
    session_maker: async_sessionmaker,
) -> None:
    """Story 5.2 AC1 — ``idx_users_deleted_at_pending_purge`` partial index 존재 검증.

    *Why*: 30일 grace cron worker(``soft_delete_purge``)의 eligible SELECT 성능 SOT.
    ``pg_indexes``를 직접 조회해 index가 ``deleted_at IS NOT NULL`` predicate로
    등록됐는지 검증 — predicate가 누락되면 활성 사용자 hot path 색인 비용이 0이
    아니게 됨(회귀 가드).
    """
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' "
                "AND tablename = 'users' "
                "AND indexname = 'idx_users_deleted_at_pending_purge'"
            )
        )
        row = result.first()
        assert row is not None, (
            "idx_users_deleted_at_pending_purge partial index missing — "
            "alembic 0017 upgrade가 실행되지 않았거나 회귀 발생."
        )
        indexdef = row[0]
        assert "deleted_at" in indexdef
        # partial index predicate — pg_indexes 출력에 ``WHERE`` 절이 포함되어야 함.
        # PostgreSQL은 ``deleted_at IS NOT NULL`` 표현을 그대로 보존 — substring 검증.
        assert "deleted_at IS NOT NULL" in indexdef.replace("(", "").replace(")", ""), (
            f"partial index predicate가 누락 — indexdef: {indexdef}"
        )
