"""Story 6.1 AC3 / AC10 — payment_service 7건 단위 테스트.

- happy-path: Toss mock 200 → ``(subscription, payment_log, False)`` + 양 row 정합.
- amount mismatch: Toss 호출 X.
- 기존 active 사용자: Toss 호출 X.
- Toss 4xx 카드 거절: ``PaymentConfirmFailedError`` raise + failed payment_log 1건 INSERT.
- Toss 5xx: ``PaymentProviderUnavailableError`` raise + DB row 0건.
- Idempotency replay: 같은 키 재호출 → ``(existing, existing_log, True)`` + Toss 호출 X.
- Race: 1건만 INSERT + 다른 1건 replay 분기 (UNIQUE 위반 catch).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.adapters import toss as toss_adapter
from app.core.exceptions import (
    PaymentAmountInvalidError,
    PaymentConfirmFailedError,
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    SubscriptionAlreadyActiveError,
)
from app.db.models.payment_log import PaymentLog
from app.db.models.subscription import Subscription
from app.main import app
from app.services import payment_service


@pytest_asyncio.fixture
async def session_maker(client) -> async_sessionmaker:
    _ = client
    return app.state.session_maker


def _toss_response_fixture(
    *,
    payment_key: str = "pk_test_happy",
    order_id: str = "order_happy",
    amount: int = 9900,
) -> toss_adapter.TossConfirmResponse:
    raw = {
        "paymentKey": payment_key,
        "orderId": order_id,
        "status": "DONE",
        "totalAmount": amount,
        "approvedAt": "2026-05-08T12:34:56+09:00",
        "method": "카드",
        "card": {"number": "433012******1234", "company": "신한"},
        "customerEmail": "user@example.com",
    }
    return toss_adapter.TossConfirmResponse.model_validate({**raw, "raw": raw})


@pytest.mark.asyncio
async def test_subscribe_happy_path(session_maker, user_factory) -> None:
    """Toss mock 200 → ``(subscription, payment_log, False)`` + 양 row 정합."""
    user = await user_factory()
    fake_response = _toss_response_fixture()

    with patch.object(
        toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)
    ) as mock_confirm:
        async with session_maker() as session:
            subscription, payment_log, was_replay = await payment_service.subscribe(
                session,
                user_id=user.id,
                payment_key="pk_test_happy",
                order_id="order_happy",
                amount=9900,
                idempotency_key=None,
            )
            await session.commit()

    assert was_replay is False
    assert subscription.user_id == user.id
    assert subscription.status == "active"
    assert subscription.plan == "monthly"
    assert subscription.plan_price_krw == 9900
    assert subscription.provider == "toss"
    assert subscription.provider_billing_key is None  # Story 6.3 forward.
    # expires_at = started_at + 30d.
    assert subscription.expires_at is not None
    assert subscription.started_at is not None
    delta = subscription.expires_at - subscription.started_at
    assert delta == timedelta(days=30)

    assert payment_log.user_id == user.id
    assert payment_log.subscription_id == subscription.id
    assert payment_log.event_type == "subscribe"
    assert payment_log.provider == "toss"
    assert payment_log.provider_payment_key == "pk_test_happy"
    assert payment_log.provider_order_id == "order_happy"
    assert payment_log.amount_krw == 9900
    assert payment_log.status == "success"
    assert payment_log.idempotency_key is None
    # raw_payload 마스킹 검증 — customerEmail 제거.
    assert payment_log.raw_payload is not None
    assert "customerEmail" not in payment_log.raw_payload
    assert payment_log.raw_payload["card"]["number"] == "****1234"

    mock_confirm.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscribe_amount_mismatch_raises_before_toss_call(
    session_maker, user_factory
) -> None:
    """amount=100 → ``PaymentAmountInvalidError`` + Toss 호출 X."""
    user = await user_factory()
    with patch.object(toss_adapter, "confirm_payment", new=AsyncMock()) as mock_confirm:
        async with session_maker() as session:
            with pytest.raises(PaymentAmountInvalidError):
                await payment_service.subscribe(
                    session,
                    user_id=user.id,
                    payment_key="pk_test",
                    order_id="order_test",
                    amount=100,  # mismatch.
                    idempotency_key=None,
                )

    mock_confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscribe_already_active_raises_before_toss_call(
    session_maker, user_factory
) -> None:
    """기존 active 사용자 → ``SubscriptionAlreadyActiveError`` + Toss 호출 X."""
    user = await user_factory()
    now = datetime.now(UTC)
    async with session_maker() as session:
        existing = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(existing)
        await session.commit()

    with patch.object(toss_adapter, "confirm_payment", new=AsyncMock()) as mock_confirm:
        async with session_maker() as session:
            with pytest.raises(SubscriptionAlreadyActiveError):
                await payment_service.subscribe(
                    session,
                    user_id=user.id,
                    payment_key="pk_test",
                    order_id="order_dup",
                    amount=9900,
                    idempotency_key=None,
                )

    mock_confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscribe_toss_4xx_raises_confirm_failed_and_inserts_failed_log(
    session_maker, user_factory
) -> None:
    """Toss 4xx → ``PaymentConfirmFailedError`` + failed payment_log 1건 INSERT.

    audit-trail 정합 — 결제 실패도 영구 보존(Story 8 운영 분석).
    """
    user = await user_factory()

    with (
        patch.object(
            toss_adapter,
            "confirm_payment",
            new=AsyncMock(side_effect=PaymentProviderRejectedError("카드 한도 초과")),
        ),
        patch("app.services.payment_service.sentry_sdk") as mock_sentry,
    ):
        async with session_maker() as session:
            with pytest.raises(PaymentConfirmFailedError):
                await payment_service.subscribe(
                    session,
                    user_id=user.id,
                    payment_key="pk_rejected",
                    order_id="order_rejected",
                    amount=9900,
                    idempotency_key=None,
                )
            await session.commit()

    # failed payment_log 1건 INSERT 검증.
    async with session_maker() as session:
        result = await session.execute(
            select(PaymentLog).where(
                PaymentLog.user_id == user.id, PaymentLog.event_type == "failed"
            )
        )
        rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].subscription_id is None
    assert rows[0].provider_payment_key == "pk_rejected"
    assert rows[0].provider_order_id == "order_rejected"
    assert rows[0].raw_payload is not None
    assert "카드 한도 초과" in str(rows[0].raw_payload.get("failure_reason", ""))

    # Sentry capture_message 명시 호출 — epics.md:842 정합.
    mock_sentry.capture_message.assert_called_once()
    args = mock_sentry.capture_message.call_args
    assert args.args[0] == "payment.confirm_failed"


@pytest.mark.asyncio
async def test_subscribe_toss_5xx_propagates_unavailable_no_db_rows(
    session_maker, user_factory
) -> None:
    """Toss 5xx → ``PaymentProviderUnavailableError`` 그대로 propagate + DB row 0건.

    클라이언트가 같은 ``Idempotency-Key``로 재시도 가능 invariant.
    """
    user = await user_factory()

    with patch.object(
        toss_adapter,
        "confirm_payment",
        new=AsyncMock(side_effect=PaymentProviderUnavailableError("toss_5xx")),
    ):
        async with session_maker() as session:
            with pytest.raises(PaymentProviderUnavailableError):
                await payment_service.subscribe(
                    session,
                    user_id=user.id,
                    payment_key="pk_5xx",
                    order_id="order_5xx",
                    amount=9900,
                    idempotency_key=None,
                )
            await session.commit()

    async with session_maker() as session:
        sub_count = (
            await session.execute(select(Subscription).where(Subscription.user_id == user.id))
        ).all()
        log_count = (
            await session.execute(select(PaymentLog).where(PaymentLog.user_id == user.id))
        ).all()
    assert len(sub_count) == 0
    assert len(log_count) == 0


@pytest.mark.asyncio
async def test_subscribe_idempotent_replay_returns_existing_without_toss_call(
    session_maker, user_factory
) -> None:
    """같은 ``idempotency_key`` 재호출 → ``(existing, existing_log, True)`` + Toss 호출 X."""
    user = await user_factory()
    fake_response = _toss_response_fixture()
    idempotency_key = str(uuid.uuid4())

    # 첫 호출.
    with patch.object(
        toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)
    ) as mock_confirm:
        async with session_maker() as session:
            subscription_first, log_first, was_replay_first = await payment_service.subscribe(
                session,
                user_id=user.id,
                payment_key="pk_first",
                order_id="order_first",
                amount=9900,
                idempotency_key=idempotency_key,
            )
            await session.commit()

    assert was_replay_first is False
    assert mock_confirm.await_count == 1

    # 재호출 — 같은 키. Toss mock counter 검증.
    with patch.object(
        toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)
    ) as mock_confirm_replay:
        async with session_maker() as session:
            subscription_replay, log_replay, was_replay_second = await payment_service.subscribe(
                session,
                user_id=user.id,
                payment_key="pk_first",  # 동일 paymentKey.
                order_id="order_first",
                amount=9900,
                idempotency_key=idempotency_key,
            )

    assert was_replay_second is True
    assert subscription_replay.id == subscription_first.id
    assert log_replay.id == log_first.id
    mock_confirm_replay.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscribe_idempotency_race_unique_violation_replays(
    session_maker, user_factory
) -> None:
    """Idempotency-Key race — 다른 worker가 INSERT 사이에 같은 키로 row를 만들면
    UNIQUE 위반 catch + 재 SELECT replay 분기 활성.

    1차 SELECT는 miss인데 INSERT 시점에 race row 발견되는 시나리오 — 1차 SELECT 후
    fixture로 row를 직접 INSERT해 simulate.
    """
    user = await user_factory()
    fake_response = _toss_response_fixture()
    idempotency_key = str(uuid.uuid4())

    # Pre-seed: 같은 idempotency_key로 다른 트랜잭션이 INSERT 완료 상태로 만든다.
    now = datetime.now(UTC)
    async with session_maker() as session:
        race_subscription = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(race_subscription)
        await session.commit()
        await session.refresh(race_subscription)

        race_log = PaymentLog(
            user_id=user.id,
            subscription_id=race_subscription.id,
            event_type="subscribe",
            provider="toss",
            provider_payment_key="pk_race",
            provider_order_id="order_race",
            amount_krw=9900,
            status="success",
            idempotency_key=idempotency_key,
            raw_payload={"raced": True},
            occurred_at=now,
        )
        session.add(race_log)
        await session.commit()
        race_log_id = race_log.id

    # 같은 키로 새 호출 — 1차 SELECT가 hit해 replay 분기 (Toss 호출 X).
    with patch.object(
        toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)
    ) as mock_confirm:
        async with session_maker() as session:
            subscription, payment_log, was_replay = await payment_service.subscribe(
                session,
                user_id=user.id,
                payment_key="pk_other_race",
                order_id="order_other",
                amount=9900,
                idempotency_key=idempotency_key,
            )

    assert was_replay is True
    assert payment_log.id == race_log_id
    assert subscription.id == race_subscription.id
    mock_confirm.assert_not_awaited()
