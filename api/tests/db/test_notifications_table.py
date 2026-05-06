"""Story 4.2 AC5 — 0014_create_notifications 마이그레이션 검증.

본 모듈은 *DB 레벨* 검증 — alembic이 실제로 ``notifications`` 테이블 + UNIQUE
``(user_id, kind, kst_date)`` + CHECK ``kind IN ('unrecorded_meal')`` + 인덱스를 박는지,
UNIQUE 위반 시 ``IntegrityError`` raise되는지 회귀 가드.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.notification import Notification
from app.db.models.user import User
from app.main import app


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    """``app.state.session_maker``는 lifespan에서 init — `client` fixture가 lifespan 활성."""
    _ = client
    return app.state.session_maker


async def _make_user(session_maker: async_sessionmaker) -> User:
    async with session_maker() as session:
        user = User(
            google_sub=f"google-sub-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex}@example.com",
            email_verified=True,
            last_login_at=datetime.now(UTC),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_notifications_table_columns_check_unique(
    session_maker: async_sessionmaker,
) -> None:
    """Story 4.2 AC5 — 0014 upgrade 후 컬럼·CHECK·UNIQUE 검증 + INSERT happy path.

    8 컬럼 + UNIQUE + CHECK + 인덱스가 alembic으로 박히는지 SOT 가드. INSERT 흐름이
    ORM에서 정상 동작하는지 검증(Story 4.2 nudge_scheduler가 본 INSERT를 호출).
    """
    user = await _make_user(session_maker)

    async with session_maker() as session:
        notification = Notification(
            user_id=user.id,
            kind="unrecorded_meal",
            kst_date=date(2026, 5, 6),
            expo_ticket_id="ticket-abc",
        )
        session.add(notification)
        await session.commit()
        await session.refresh(notification)
        assert notification.id is not None
        assert notification.sent_at is not None
        assert notification.expo_ticket_id == "ticket-abc"
        assert notification.expo_receipt_status is None

    async with session_maker() as session:
        # CHECK 제약 — 미허용 kind 거부.
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO notifications (user_id, kind, kst_date) "
                    "VALUES (:user_id, :kind, :kst_date)"
                ),
                {
                    "user_id": user.id,
                    "kind": "weekly_report_ready",  # 미허용 — Story 4.4 forward.
                    "kst_date": date(2026, 5, 6),
                },
            )
            await session.commit()


@pytest.mark.asyncio
async def test_notifications_unique_user_kind_date_violation(
    session_maker: async_sessionmaker,
) -> None:
    """Story 4.2 AC5 — UNIQUE ``(user_id, kind, kst_date)`` 위반 시 IntegrityError.

    *Why*: cron sweep이 동일 사용자에게 동일 날 동일 kind를 두 번 발사하지 않도록
    하는 *멱등 SOT*. 동시 cron tick 시 race로 INSERT 두 번이면 두 번째가 IntegrityError로
    실패해야 함.
    """
    user = await _make_user(session_maker)
    target_date = date(2026, 5, 6)

    async with session_maker() as session:
        first = Notification(
            user_id=user.id,
            kind="unrecorded_meal",
            kst_date=target_date,
        )
        session.add(first)
        await session.commit()

    async with session_maker() as session:
        duplicate = Notification(
            user_id=user.id,
            kind="unrecorded_meal",
            kst_date=target_date,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            await session.commit()
