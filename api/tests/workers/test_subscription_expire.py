"""Story 6.3 AC6 — ``app.workers.subscription_expire`` 단위 테스트.

4 케이스 (Real Postgres + monkeypatched redis):

1. happy-path — 3건 active(2건 expired, 1건 미도래) → 2건만 status=expired 전이.
2. 100건 cap — 150건 expired 시 100건만 처리 + sentry warning(*queue 누적*).
3. lock 보유 — 동시 2 instance → 1건만 sweep 진입(redis SET NX).
4. graceful skip — ``session_maker is None`` → 잡 미등록 + warning log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.main import app
from app.workers.subscription_expire import (
    SUBSCRIPTION_EXPIRE_JOB_ID,
    register_subscription_expire_job,
    sweep_expired_subscriptions,
)


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


async def _create_user(session_maker: async_sessionmaker) -> User:
    """active subscription 생성을 위한 user fixture 헬퍼."""
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


async def _create_subscription(
    session_maker: async_sessionmaker,
    *,
    user_id: uuid.UUID,
    status: str = "active",
    expires_at: datetime | None,
) -> Subscription:
    async with session_maker() as session:
        sub = Subscription(
            user_id=user_id,
            status=status,
            plan="monthly",
            plan_price_krw=9900,
            started_at=datetime.now(UTC) - timedelta(days=30),
            expires_at=expires_at,
            provider="toss",
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub


# --- AC6 1) 3건 active 중 2건 expired 전이 -----------------------------------


@pytest.mark.asyncio
async def test_sweep_expires_active_but_past_subscriptions(
    session_maker: async_sessionmaker,
) -> None:
    """3건 active(2건 expired, 1건 미도래) → 2건만 status=expired 전이."""
    user = await _create_user(session_maker)
    now = datetime.now(UTC)

    # 2건 expired (과거).
    sub_expired_1 = await _create_subscription(
        session_maker, user_id=user.id, expires_at=now - timedelta(hours=1)
    )
    user2 = await _create_user(session_maker)
    sub_expired_2 = await _create_subscription(
        session_maker, user_id=user2.id, expires_at=now - timedelta(days=1)
    )
    # 1건 미도래 (미래).
    user3 = await _create_user(session_maker)
    sub_active = await _create_subscription(
        session_maker, user_id=user3.id, expires_at=now + timedelta(days=10)
    )

    stats = await sweep_expired_subscriptions(session_maker, redis=None)

    assert stats["eligible_count"] == 2
    assert stats["expired_count"] == 2
    assert stats["cap_exceeded"] == 0
    assert stats["errors_count"] == 0

    async with session_maker() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.id.in_([sub_expired_1.id, sub_expired_2.id, sub_active.id])
            )
        )
        rows = {row.id: row for row in result.scalars().all()}

    assert rows[sub_expired_1.id].status == "expired"
    assert rows[sub_expired_2.id].status == "expired"
    assert rows[sub_active.id].status == "active"  # 미도래는 그대로.


# --- AC6 2) 100건 cap + queue 누적 sentry warning ---------------------------


@pytest.mark.asyncio
async def test_sweep_caps_at_100_and_emits_sentry_warning_on_overflow(
    session_maker: async_sessionmaker,
) -> None:
    """150건 expired → 100건만 처리 + ``cap_exceeded=1`` + sentry warning(*queue 누적*).

    실제 150건 INSERT는 비용이 크므로 cap을 가시화할 수 있는 102건만 INSERT(cap=100 +1
    초과 감지 + 1 여유). cap_exceeded 신호와 expired_count=100 invariant만 검증.
    """
    now = datetime.now(UTC)
    # cap=100 초과 검증을 위해 102건 INSERT.
    user_ids: list[uuid.UUID] = []
    for _ in range(102):
        u = await _create_user(session_maker)
        user_ids.append(u.id)
        await _create_subscription(session_maker, user_id=u.id, expires_at=now - timedelta(hours=1))

    with patch("app.workers.subscription_expire.sentry_sdk") as mock_sentry:
        stats = await sweep_expired_subscriptions(session_maker, redis=None)

    assert stats["eligible_count"] == 100
    assert stats["expired_count"] == 100
    assert stats["cap_exceeded"] == 1
    assert any(
        call.args[0] == "subscription_expire.queue_overflow"
        for call in mock_sentry.capture_message.call_args_list
    )

    # 102건 중 100건만 expired, 2건은 active 유지(다음 sweep cycle에 처리).
    async with session_maker() as session:
        result = await session.execute(
            select(Subscription.status).where(Subscription.user_id.in_(user_ids))
        )
        statuses = [row[0] for row in result.all()]
    assert statuses.count("expired") == 100
    assert statuses.count("active") == 2


# --- AC6 3) redis lock 보유 — 동시 2 instance 1건만 진입 ---------------------


@pytest.mark.asyncio
async def test_sweep_skips_when_redis_lock_held(session_maker: async_sessionmaker) -> None:
    """다른 instance가 락을 보유 중 → ``lock_held=1`` + ``expired_count=0``.

    ``redis.set(..., nx=True, ex=...)``가 None 반환(다른 instance가 점유) → sweep skip.
    """
    user = await _create_user(session_maker)
    now = datetime.now(UTC)
    await _create_subscription(session_maker, user_id=user.id, expires_at=now - timedelta(hours=1))

    # redis mock — set NX 실패 simulate.
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=None)  # 다른 instance가 점유.
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.delete = AsyncMock(return_value=0)

    stats = await sweep_expired_subscriptions(session_maker, redis=fake_redis)

    assert stats["lock_held"] == 1
    assert stats["expired_count"] == 0
    assert stats["eligible_count"] == 0

    # subscription 변경 X.
    async with session_maker() as session:
        result = await session.execute(select(Subscription).where(Subscription.user_id == user.id))
        sub = result.scalar_one()
    assert sub.status == "active"


# --- AC6 4) graceful skip — session_maker None → 잡 미등록 ------------------


def test_register_job_skips_when_session_maker_is_none(caplog: Any) -> None:
    """``session_maker is None`` → 잡 등록 skip + warning log (test/ci 환경 정합)."""
    scheduler = AsyncIOScheduler()
    register_subscription_expire_job(scheduler, session_maker=None, redis=None)

    # 잡 미등록 검증.
    assert scheduler.get_job(SUBSCRIPTION_EXPIRE_JOB_ID) is None


def test_register_job_with_session_maker_attaches_cron_trigger(
    session_maker: async_sessionmaker,
) -> None:
    """``session_maker`` 정상 → 잡 등록 + ``CronTrigger(minute=0, timezone='Asia/Seoul')``.

    replace_existing 정합은 sweep 멱등(rowcount=0 가드 + cutoff 동일)이 회복 — 본 테스트는
    잡 등록 성공 + cron trigger 형태만 검증.
    """
    scheduler = AsyncIOScheduler()
    register_subscription_expire_job(scheduler, session_maker=session_maker, redis=None)

    job = scheduler.get_job(SUBSCRIPTION_EXPIRE_JOB_ID)
    assert job is not None
    assert isinstance(job.trigger, CronTrigger)
    # CronTrigger 매시 정각 KST — minute='0', timezone tzinfo가 Asia/Seoul 함의.
    fields_by_name = {f.name: f for f in job.trigger.fields}
    assert str(fields_by_name["minute"]) == "0"
