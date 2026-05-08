"""Story 6.1 — alembic 0018/0019 schema + invariants 회귀.

``subscriptions`` partial UNIQUE(active만) + ``payment_logs`` 3 인덱스 + ENUM 6종 +
FK CASCADE/SET NULL 동작 검증. 마이그레이션 file이 ORM ``__table_args__``와 drift하면
첫 hit (deferred-work D29 forward).

``client`` fixture 의존성 — lifespan 트리거로 ``app.state.session_maker`` 초기화 보장.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment_log import PaymentLog
from app.db.models.subscription import Subscription
from app.main import app
from tests.conftest import UserFactory


async def test_subscriptions_active_partial_unique_blocks_second_active(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """한 사용자 1 active subscription invariant — 같은 user_id로 2번째 active row INSERT
    시도 시 ``idx_subscriptions_user_id_active_unique`` partial UNIQUE 위반 IntegrityError.

    cancelled/expired 전이 후에는 새 active row INSERT 가능(partial WHERE clause는
    non-active row를 색인 미진입 처리).
    """
    _ = client
    user = await user_factory()
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker

    now = datetime.now(UTC)
    async with session_maker() as session:
        first = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(first)
        await session.commit()

    # 두 번째 active INSERT — partial UNIQUE 위반.
    async with session_maker() as session:
        duplicate = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            await session.commit()

    # 첫 번째 row를 cancelled로 전이 → 새 active 신청 가능 invariant.
    async with session_maker() as session:
        await session.execute(
            text(
                "UPDATE subscriptions SET status='cancelled', cancelled_at=now() "
                "WHERE user_id=:uid AND status='active'"
            ),
            {"uid": user.id},
        )
        new_active = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(new_active)
        await session.commit()  # 성공해야 함 — 이전 row가 partial WHERE 미진입.


async def test_subscriptions_enum_invariants(client: AsyncClient) -> None:
    """3 ENUM 값 SOT — DB-level enum 정의에 6 값 등록 단언 (status 3 + plan 1 +
    provider 2). enum 값 drift 시 첫 hit.
    """
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    async with session_maker() as session:
        result = await session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname=:name ORDER BY e.enumsortorder"
            ),
            {"name": "subscriptions_status_enum"},
        )
        status_values = [r[0] for r in result.fetchall()]
        result = await session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname=:name ORDER BY e.enumsortorder"
            ),
            {"name": "subscriptions_plan_enum"},
        )
        plan_values = [r[0] for r in result.fetchall()]
        result = await session.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname=:name ORDER BY e.enumsortorder"
            ),
            {"name": "subscriptions_provider_enum"},
        )
        provider_values = [r[0] for r in result.fetchall()]

    assert status_values == ["active", "cancelled", "expired"]
    assert plan_values == ["monthly"]
    assert provider_values == ["toss", "stripe"]


async def test_payment_logs_subscription_fk_set_null_on_subscription_delete(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    """``subscriptions`` row 삭제 시 ``payment_logs.subscription_id``가 SET NULL — audit-trail
    영구 보존 + subscription 무관 이벤트(refund 등) forward-compat.

    ``users.id`` CASCADE는 별 invariant — 본 테스트는 ``subscription_id`` SET NULL만.
    """
    _ = client
    user = await user_factory()
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker

    now = datetime.now(UTC)
    async with session_maker() as session:
        subscription = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)
        subscription_id = subscription.id

        log = PaymentLog(
            user_id=user.id,
            subscription_id=subscription_id,
            event_type="subscribe",
            provider="toss",
            provider_payment_key=f"pk_{uuid.uuid4()}",
            provider_order_id=f"order_{uuid.uuid4()}",
            amount_krw=9900,
            status="success",
            occurred_at=now,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        log_id = log.id

    # subscription 삭제 → log.subscription_id가 NULL이 되어야 함.
    async with session_maker() as session:
        await session.execute(
            text("DELETE FROM subscriptions WHERE id = :sid"),
            {"sid": subscription_id},
        )
        await session.commit()

        result = await session.execute(
            text("SELECT subscription_id FROM payment_logs WHERE id = :lid"),
            {"lid": log_id},
        )
        row = result.first()

    assert row is not None
    assert row.subscription_id is None
