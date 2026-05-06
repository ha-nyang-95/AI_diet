"""Story 4.1 AC1 / AC15 — 0013_users_notification_settings 마이그레이션 검증.

본 모듈은 *DB 레벨* 검증 — alembic이 실제로 4컬럼 + CHECK + partial UNIQUE index를
박는지, default 값이 ``notifications_enabled=true`` / ``notification_time='20:00:00'`` /
``notification_timezone='Asia/Seoul'`` / ``expo_push_token=NULL`` 인지, CHECK 제약
``ck_users_notification_time_kst_format``이 분 단위 정렬을 강제하는지(``IntegrityError``
raise) 회귀 가드.

ORM 레벨 검증(``api/tests/services/test_notification_service.py``)과 분리 — 본 모듈은
*마이그레이션 SOT*가 변경됐을 때 즉시 fail하도록.
"""

from __future__ import annotations

import uuid
from datetime import time

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.main import app


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    """``app.state.session_maker``는 lifespan에서 init — `client` fixture가 lifespan 활성."""
    _ = client
    return app.state.session_maker


@pytest.mark.asyncio
async def test_notification_columns_default_values(session_maker: async_sessionmaker) -> None:
    """Story 4.1 AC1 — ``users`` 신규 row 생성 시 4컬럼 default 값.

    *Why*: Story 1.2 OAuth 흐름이 ``users`` row를 INSERT할 때 본 4컬럼이 default로 채워지지
    않으면 ``NOT NULL`` 위반(``notifications_enabled``/``notification_time``/
    ``notification_timezone``)으로 가입 실패. ``expo_push_token``은 nullable이라 NULL OK.
    """
    async with session_maker() as session:
        # 4컬럼 모두 명시 미지정 — DB-side default 적용 검증.
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
            text(
                "SELECT notifications_enabled, notification_time::text, "
                "notification_timezone, expo_push_token "
                "FROM users ORDER BY created_at DESC LIMIT 1"
            )
        )
        row = result.first()
        assert row is not None
        notifications_enabled, notification_time, notification_timezone, expo_push_token = row
        assert notifications_enabled is True
        assert notification_time == "20:00:00"
        assert notification_timezone == "Asia/Seoul"
        assert expo_push_token is None


@pytest.mark.asyncio
async def test_ck_users_notification_time_kst_format_rejects_seconds(
    session_maker: async_sessionmaker,
) -> None:
    """Story 4.1 AC1 — ``ck_users_notification_time_kst_format`` CHECK 위반 시 IntegrityError.

    *Why*: APScheduler 일별 잡은 분 단위 SOT — 초 자유 입력(``20:00:30`` 등)이 들어가면
    cron 매칭이 어긋나 nudge 발송 시점이 흔들림. DB CHECK가 마지막 가드.

    ``20:30:45`` 시도 — regex ``^[0-2][0-9]:[0-5][0-9]:00$`` 위반(초가 ``:00`` 아님).
    ``IntegrityError`` raise 보장.
    """
    async with session_maker() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO users (id, google_sub, email, email_verified, "
                    "notification_time) "
                    "VALUES (:id, :sub, :email, true, :nt)"
                ),
                {
                    "id": uuid.uuid4(),
                    "sub": f"google-sub-{uuid.uuid4()}",
                    "email": f"{uuid.uuid4().hex}@example.com",
                    # asyncpg는 TIME 컬럼에 Python ``datetime.time`` 객체 요구.
                    "nt": time(20, 30, 45),
                },
            )
            await session.commit()
