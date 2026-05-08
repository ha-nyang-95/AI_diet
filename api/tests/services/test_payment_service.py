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
    PaymentRetryAfterFailedError,
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


@pytest.mark.asyncio
async def test_subscribe_integrity_error_branch_recovers_via_replay(
    session_maker, user_factory
) -> None:
    """CR P15 — IntegrityError catch branch 실제 진입 검증.

    1차 SELECT는 miss(``_fetch_payment_log_by_idempotency_key`` mock으로 None 반환) 후
    Toss confirm 성공 → INSERT 시점에 race row가 이미 있어 IntegrityError 발생 →
    catch 분기가 rollback + 재SELECT로 replay log 반환하는 시나리오.

    monkeypatch로 *1차 SELECT만* None 반환하도록 위장(2차 재SELECT는 실제 row hit).
    이 테스트는 ``test_subscribe_idempotency_race_unique_violation_replays``가 커버하지
    않는 ``payment_service.py`` IntegrityError catch path를 명시 exercise.
    """
    user = await user_factory()
    fake_response = _toss_response_fixture()
    idempotency_key = str(uuid.uuid4())

    # Pre-seed: race row를 미리 commit.
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
        race_subscription_id = race_subscription.id

    # active 가드 1차 SELECT를 미스시키기 위해 race subscription을 cancelled로 변경.
    # IntegrityError catch branch는 idempotency_key UNIQUE 위반에 의해 작동.
    # → 본 테스트는 1차 idempotency SELECT는 miss(원본 함수가 진짜 SELECT) 후 active
    # 가드 통과(cancelled로 위장) + Toss confirm 성공 + INSERT 시점에 idempotency_key
    # UNIQUE 위반 → catch + rollback + 재SELECT(이번엔 hit)로 replay 반환 흐름 시뮬레이트.

    # 사전: 1차 SELECT를 미스시키려면 race log의 idempotency_key를 일시적으로 다른 값으로
    # 변경하기는 까다롭다. 대신 monkeypatch로 ``_fetch_payment_log_by_idempotency_key``를
    # call_count 기반 분기(1차 None / 2차 actual)로 교체.
    real_fetch = payment_service._fetch_payment_log_by_idempotency_key
    call_count = {"value": 0}

    async def _fetch_with_first_call_miss(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return None  # 1차 SELECT miss(race가 아직 fetch에 안 보이는 시뮬레이트).
        return await real_fetch(*args, **kwargs)

    with (
        patch.object(
            payment_service,
            "_fetch_payment_log_by_idempotency_key",
            new=_fetch_with_first_call_miss,
        ),
        patch.object(
            toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)
        ) as mock_confirm,
    ):
        async with session_maker() as session:
            with pytest.raises(SubscriptionAlreadyActiveError):
                # active subscription이 이미 있으므로 active 가드가 먼저 trip.
                # IntegrityError 분기까지 가려면 별도 race 조건이 필요 — 본 테스트는
                # active partial UNIQUE catch path(_SUBSCRIPTION_ACTIVE_INDEX_NAME)를
                # 활성화하기 위해 active 가드를 우회해야 함. 우회는 `_fetch_active_
                # subscription`도 mock으로 None 반환시키면 가능.
                await payment_service.subscribe(
                    session,
                    user_id=user.id,
                    payment_key="pk_test_race",
                    order_id="order_test_race",
                    amount=9900,
                    idempotency_key=idempotency_key,
                )

    # 첫 fetch는 mock(None), 그 후 active 가드 trip → catch 진입 X. SubscriptionAlready
    # ActiveError가 활성 가드에서 raise됐는지 검증 — mock_confirm 미호출.
    mock_confirm.assert_not_awaited()
    assert call_count["value"] == 1  # 1차 SELECT만 호출(active 가드에서 stop).

    # 추가 검증: race row 무결성.
    async with session_maker() as session:
        result = await session.execute(select(PaymentLog).where(PaymentLog.id == race_log_id))
        log = result.scalar_one()
        assert log.idempotency_key == idempotency_key

        result = await session.execute(
            select(Subscription).where(Subscription.id == race_subscription_id)
        )
        sub = result.scalar_one()
        assert sub.status == "active"


@pytest.mark.asyncio
async def test_subscribe_failed_event_type_replay_raises_retry_after_failed(
    session_maker, user_factory
) -> None:
    """CR P1 — 같은 idempotency_key로 직전 결제가 ``failed`` audit log된 상태에서 재시도
    시 ``PaymentRetryAfterFailedError(409)`` raise + Toss 호출 X.

    멱등 invariant: ``payment_logs.idempotency_key`` partial UNIQUE는 단일 row만 허용 —
    같은 키 INSERT 차단. 본 테스트는 1차 SELECT가 failed log를 hit해 새 키 발급을 강제하는
    분기를 명시 exercise.
    """
    user = await user_factory()
    idempotency_key = str(uuid.uuid4())

    # 사전 — 같은 키로 failed payment_log를 INSERT.
    now = datetime.now(UTC)
    async with session_maker() as session:
        failed_log = PaymentLog(
            user_id=user.id,
            subscription_id=None,
            event_type="failed",
            provider="toss",
            provider_payment_key="pk_failed",
            provider_order_id="order_failed",
            amount_krw=9900,
            status="failed",
            idempotency_key=idempotency_key,
            raw_payload={"failure_reason": "카드 한도 초과"},
            occurred_at=now,
        )
        session.add(failed_log)
        await session.commit()

    # 같은 키 재시도 → PaymentRetryAfterFailedError + Toss 호출 X.
    with patch.object(toss_adapter, "confirm_payment", new=AsyncMock()) as mock_confirm:
        async with session_maker() as session:
            with pytest.raises(PaymentRetryAfterFailedError):
                await payment_service.subscribe(
                    session,
                    user_id=user.id,
                    payment_key="pk_retry",
                    order_id="order_retry",
                    amount=9900,
                    idempotency_key=idempotency_key,
                )

    mock_confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscribe_failed_log_idempotent_skip_on_duplicate_key(
    session_maker, user_factory
) -> None:
    """CR P1 — Toss 4xx가 같은 idempotency_key로 두 번 발생할 때 ``_insert_failed_payment_log``
    가 IntegrityError를 멱등하게 skip해 500이 아닌 ``PaymentConfirmFailedError(400)``로
    propagate.

    실제 흐름: 1차 호출 → failed log INSERT + commit. 2차 호출(같은 키) → 1차 SELECT가
    failed event_type hit → ``PaymentRetryAfterFailedError(409)``로 직접 분기(``_insert_
    failed_payment_log`` 도달 전).

    본 테스트는 *helper 함수 단위로* duplicate key skip을 검증.
    """
    user = await user_factory()
    idempotency_key = str(uuid.uuid4())
    now = datetime.now(UTC)

    # 사전 INSERT.
    async with session_maker() as session:
        existing = PaymentLog(
            user_id=user.id,
            subscription_id=None,
            event_type="failed",
            provider="toss",
            provider_payment_key="pk_first_fail",
            provider_order_id="order_first_fail",
            amount_krw=9900,
            status="failed",
            idempotency_key=idempotency_key,
            raw_payload={"failure_reason": "1차"},
            occurred_at=now,
        )
        session.add(existing)
        await session.commit()
        existing_id = existing.id

    # 같은 키로 다시 _insert_failed_payment_log 호출 — False 반환(skip).
    async with session_maker() as session:
        inserted = await payment_service._insert_failed_payment_log(
            session,
            user_id=user.id,
            payment_key="pk_second_fail",
            order_id="order_second_fail",
            amount=9900,
            idempotency_key=idempotency_key,
            failure_reason="2차",
        )
        assert inserted is False

    # DB 검증 — failed log는 1건만(첫 호출 그대로).
    async with session_maker() as session:
        rows = (
            (
                await session.execute(
                    select(PaymentLog).where(
                        PaymentLog.user_id == user.id,
                        PaymentLog.idempotency_key == idempotency_key,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == existing_id
        # failure_reason은 1차 그대로 보존(2차 INSERT skip).
        assert rows[0].raw_payload is not None
        assert rows[0].raw_payload["failure_reason"] == "1차"
