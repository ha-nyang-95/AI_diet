"""Story 6.1 AC4 / AC5 / AC10 — `/v1/payments` router 12건 단위 테스트.

12 케이스 (AC10 정의):
1. POST /subscribe 인증 미통과 → 401.
2. POST /subscribe 미동의 사용자 → 403 + ``code=consent.basic.missing``.
3. POST /subscribe happy-path → 201 + ``SubscribeResponse`` shape + 양 row INSERT.
4. POST /subscribe ``Idempotency-Key`` 재호출 → 200 (replay) + Toss 호출 X.
5. POST /subscribe ``Idempotency-Key`` 형식 위반 → 400 +
   ``code=payments.idempotency_key.invalid``.
6. POST /subscribe ``amount=100`` mismatch → 400 + ``code=payments.amount.invalid``.
7. POST /subscribe 기존 active 사용자 → 409 +
   ``code=payments.subscription.already_active``.
8. POST /subscribe Toss 4xx 카드 거절 → 400 + ``code=payments.confirm_failed`` + failed
   payment_log INSERT 검증.
9. POST /subscribe Toss 5xx → 502 + ``code=payments.provider.unavailable`` + DB 0 rows.
10. POST /subscribe ``TOSS_SECRET_KEY`` 미설정 → 503 +
    ``code=payments.toss.secret_key_missing``.
11. GET /subscription 활성 구독 happy-path → 200 + ``status="active"``.
12. GET /subscription 활성 구독 0건 → 404 + ``code=payments.subscription.not_found``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.adapters import toss as toss_adapter
from app.core.exceptions import (
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    TossSecretKeyMissingError,
)
from app.db.models.payment_log import PaymentLog
from app.db.models.subscription import Subscription
from app.main import app
from tests.conftest import auth_headers


def _toss_response_fixture(
    *,
    payment_key: str = "pk_test_router",
    order_id: str = "order_router",
    amount: int = 9900,
) -> toss_adapter.TossConfirmResponse:
    raw = {
        "paymentKey": payment_key,
        "orderId": order_id,
        "status": "DONE",
        "totalAmount": amount,
        "approvedAt": "2026-05-08T12:34:56+09:00",
        "method": "카드",
        "card": {"number": "433012******1234"},
        "customerEmail": "user@example.com",
    }
    return toss_adapter.TossConfirmResponse.model_validate({**raw, "raw": raw})


@pytest.mark.asyncio
async def test_subscribe_unauthenticated_returns_401(client: AsyncClient) -> None:
    """1. 인증 미통과 → 401."""
    response = await client.post(
        "/v1/payments/subscribe",
        json={
            "paymentKey": "pk_test",
            "orderId": "order_test",
            "amount": 9900,
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_subscribe_without_basic_consent_returns_403(
    client: AsyncClient, user_factory
) -> None:
    """2. 미동의 사용자 → 403 + ``code=consent.basic.missing``."""
    user = await user_factory()  # consent 미생성.
    response = await client.post(
        "/v1/payments/subscribe",
        json={
            "paymentKey": "pk_test",
            "orderId": "order_test",
            "amount": 9900,
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "consent.basic.missing"


@pytest.mark.asyncio
async def test_subscribe_happy_path_returns_201(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """3. happy-path — 201 + ``SubscribeResponse`` shape + 양 row INSERT."""
    user = await user_factory()
    await consent_factory(user)
    fake_response = _toss_response_fixture(
        payment_key="pk_happy_router", order_id="order_happy_router"
    )

    with patch.object(toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)):
        response = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_happy_router",
                "orderId": "order_happy_router",
                "amount": 9900,
            },
            headers=auth_headers(user),
        )

    assert response.status_code == 201
    body = response.json()
    assert "subscription" in body
    assert "payment" in body
    assert body["subscription"]["status"] == "active"
    assert body["subscription"]["plan"] == "monthly"
    assert body["subscription"]["plan_price_krw"] == 9900
    assert body["subscription"]["provider"] == "toss"
    # provider_billing_key는 응답 미포함(보안 정합).
    assert "provider_billing_key" not in body["subscription"]
    assert body["payment"]["event_type"] == "subscribe"
    assert body["payment"]["status"] == "success"
    assert body["payment"]["amount_krw"] == 9900
    # raw_payload / provider_payment_key는 응답 미포함(PII 보호).
    assert "raw_payload" not in body["payment"]
    assert "provider_payment_key" not in body["payment"]

    # DB row 정합.
    session_maker = app.state.session_maker
    async with session_maker() as session:
        sub_count = (
            (await session.execute(select(Subscription).where(Subscription.user_id == user.id)))
            .scalars()
            .all()
        )
        log_count = (
            (await session.execute(select(PaymentLog).where(PaymentLog.user_id == user.id)))
            .scalars()
            .all()
        )
    assert len(sub_count) == 1
    assert len(log_count) == 1


@pytest.mark.asyncio
async def test_subscribe_idempotency_key_replay_returns_200_no_toss_call(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """4. ``Idempotency-Key`` 재호출 → 200 (replay) + Toss 호출 X (mock counter 검증)."""
    user = await user_factory()
    await consent_factory(user)
    fake_response = _toss_response_fixture(
        payment_key="pk_idem_router", order_id="order_idem_router"
    )
    idempotency_key = str(uuid.uuid4())

    # 첫 호출 → 201.
    with patch.object(
        toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)
    ) as mock_confirm:
        first = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_idem_router",
                "orderId": "order_idem_router",
                "amount": 9900,
            },
            headers={**auth_headers(user), "Idempotency-Key": idempotency_key},
        )
    assert first.status_code == 201
    assert mock_confirm.await_count == 1

    # 재호출 → 200 replay, Toss 호출 X.
    with patch.object(
        toss_adapter, "confirm_payment", new=AsyncMock(return_value=fake_response)
    ) as mock_confirm_replay:
        second = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_idem_router",
                "orderId": "order_idem_router",
                "amount": 9900,
            },
            headers={**auth_headers(user), "Idempotency-Key": idempotency_key},
        )

    assert second.status_code == 200
    assert second.json()["subscription"]["id"] == first.json()["subscription"]["id"]
    mock_confirm_replay.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscribe_invalid_idempotency_key_returns_400(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """5. ``Idempotency-Key`` 형식 위반 → 400 + ``code=payments.idempotency_key.invalid``."""
    user = await user_factory()
    await consent_factory(user)
    response = await client.post(
        "/v1/payments/subscribe",
        json={
            "paymentKey": "pk_test",
            "orderId": "order_test",
            "amount": 9900,
        },
        headers={**auth_headers(user), "Idempotency-Key": "not-a-uuid"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "payments.idempotency_key.invalid"


@pytest.mark.asyncio
async def test_subscribe_amount_mismatch_returns_400(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """6. ``amount=100`` mismatch → 400 + ``code=payments.amount.invalid``."""
    user = await user_factory()
    await consent_factory(user)
    with patch.object(toss_adapter, "confirm_payment", new=AsyncMock()) as mock_confirm:
        response = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_test",
                "orderId": "order_test",
                "amount": 100,  # mismatch.
            },
            headers=auth_headers(user),
        )
    assert response.status_code == 400
    assert response.json()["code"] == "payments.amount.invalid"
    mock_confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscribe_already_active_returns_409(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """7. 기존 active 사용자 → 409 + ``code=payments.subscription.already_active``."""
    user = await user_factory()
    await consent_factory(user)
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
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

    with patch.object(toss_adapter, "confirm_payment", new=AsyncMock()):
        response = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_test",
                "orderId": "order_dup",
                "amount": 9900,
            },
            headers=auth_headers(user),
        )

    assert response.status_code == 409
    assert response.json()["code"] == "payments.subscription.already_active"


@pytest.mark.asyncio
async def test_subscribe_toss_4xx_returns_400_confirm_failed(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """8. Toss 4xx 카드 거절 → 400 + ``code=payments.confirm_failed`` + failed log INSERT."""
    user = await user_factory()
    await consent_factory(user)

    with (
        patch.object(
            toss_adapter,
            "confirm_payment",
            new=AsyncMock(side_effect=PaymentProviderRejectedError("카드 한도 초과")),
        ),
        patch("app.services.payment_service.sentry_sdk"),
    ):
        response = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_rejected_router",
                "orderId": "order_rejected_router",
                "amount": 9900,
            },
            headers=auth_headers(user),
        )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "payments.confirm_failed"
    assert body["type"] == "https://balancenote.app/errors/payments-confirm-failed"

    # failed payment_log 1건 INSERT 검증.
    session_maker = app.state.session_maker
    async with session_maker() as session:
        rows = (
            (
                await session.execute(
                    select(PaymentLog).where(
                        PaymentLog.user_id == user.id, PaymentLog.event_type == "failed"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_subscribe_toss_5xx_returns_502_no_db_rows(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """9. Toss 5xx → 502 + ``code=payments.provider.unavailable`` + DB 0 rows."""
    user = await user_factory()
    await consent_factory(user)

    with patch.object(
        toss_adapter,
        "confirm_payment",
        new=AsyncMock(side_effect=PaymentProviderUnavailableError("toss_5xx")),
    ):
        response = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_5xx",
                "orderId": "order_5xx",
                "amount": 9900,
            },
            headers=auth_headers(user),
        )

    assert response.status_code == 502
    assert response.json()["code"] == "payments.provider.unavailable"

    # DB row 0건.
    session_maker = app.state.session_maker
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
async def test_subscribe_toss_secret_key_missing_returns_503(
    client: AsyncClient, user_factory, consent_factory
) -> None:
    """10. ``TOSS_SECRET_KEY`` 미설정 → 503 + ``code=payments.toss.secret_key_missing``."""
    user = await user_factory()
    await consent_factory(user)

    with patch.object(
        toss_adapter,
        "confirm_payment",
        new=AsyncMock(side_effect=TossSecretKeyMissingError("not configured")),
    ):
        response = await client.post(
            "/v1/payments/subscribe",
            json={
                "paymentKey": "pk_test",
                "orderId": "order_test",
                "amount": 9900,
            },
            headers=auth_headers(user),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "payments.toss.secret_key_missing"


@pytest.mark.asyncio
async def test_get_subscription_active_returns_200(client: AsyncClient, user_factory) -> None:
    """11. GET /subscription 활성 구독 happy-path → 200 + ``status="active"``."""
    user = await user_factory()  # consent 게이트 미적용 — PIPA Art.35.
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
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

    response = await client.get(
        "/v1/payments/subscription",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["plan"] == "monthly"
    assert body["plan_price_krw"] == 9900
    assert body["provider"] == "toss"


@pytest.mark.asyncio
async def test_get_subscription_no_active_returns_404(client: AsyncClient, user_factory) -> None:
    """12. GET /subscription 활성 구독 0건 → 404 + ``code=payments.subscription.not_found``."""
    user = await user_factory()
    response = await client.get(
        "/v1/payments/subscription",
        headers=auth_headers(user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "payments.subscription.not_found"


# ===========================================================================
# Story 6.2 — POST /cancel + GET /subscription contract + GET /history
# ===========================================================================


@pytest.mark.asyncio
async def test_cancel_unauthenticated_returns_401(client: AsyncClient) -> None:
    """Story 6.2 AC1 — POST /cancel 인증 미통과 → 401."""
    response = await client.post("/v1/payments/cancel", json={})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cancel_happy_path_returns_200(client: AsyncClient, user_factory) -> None:
    """Story 6.2 AC1 — POST /cancel happy-path:
    - 200 + ``status='cancelled'`` + ``cancelled_at != None`` + ``expires_at`` 변경 0.
    - cancel ``payment_log`` row 1건 INSERT(``event_type='cancel'`` + ``amount_krw=0``).
    """
    user = await user_factory()  # consent 미적용 — PIPA Art.35.
    now = datetime.now(UTC)
    expires_at_original = now + timedelta(days=30)

    session_maker = app.state.session_maker
    async with session_maker() as session:
        subscription = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=expires_at_original,
            provider="toss",
        )
        session.add(subscription)
        await session.commit()
        subscription_id = subscription.id

    response = await client.post(
        "/v1/payments/cancel",
        json={},
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["subscription"]["id"] == str(subscription_id)
    assert body["subscription"]["status"] == "cancelled"
    assert body["subscription"]["cancelled_at"] is not None
    assert body["payment"]["event_type"] == "cancel"
    assert body["payment"]["amount_krw"] == 0
    assert body["payment"]["status"] == "success"

    # DB row 검증 — expires_at 변경 0 + cancel log 1건.
    async with session_maker() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        sub = result.scalar_one()
        assert sub.status == "cancelled"
        assert sub.cancelled_at is not None
        assert sub.expires_at == expires_at_original  # epics.md:852 invariant.

        log_result = await session.execute(
            select(PaymentLog).where(
                PaymentLog.user_id == user.id, PaymentLog.event_type == "cancel"
            )
        )
        cancel_logs = list(log_result.scalars().all())
    assert len(cancel_logs) == 1


@pytest.mark.asyncio
async def test_cancel_no_active_returns_404(client: AsyncClient, user_factory) -> None:
    """Story 6.2 AC1/AC3 — 활성 미신청 → 404 + ``code=payments.subscription.not_found``."""
    user = await user_factory()
    response = await client.post(
        "/v1/payments/cancel",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "payments.subscription.not_found"


@pytest.mark.asyncio
async def test_cancel_already_cancelled_returns_409(client: AsyncClient, user_factory) -> None:
    """Story 6.2 AC3 — 이미 cancelled-but-not-expired → 409 +
    ``code=payments.subscription.already_cancelled``.
    """
    user = await user_factory()
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        sub = Subscription(
            user_id=user.id,
            status="cancelled",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now - timedelta(days=5),
            expires_at=now + timedelta(days=25),
            cancelled_at=now - timedelta(hours=1),
            provider="toss",
        )
        session.add(sub)
        await session.commit()

    response = await client.post(
        "/v1/payments/cancel",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "payments.subscription.already_cancelled"


@pytest.mark.asyncio
async def test_cancel_expired_only_returns_404(client: AsyncClient, user_factory) -> None:
    """Story 6.2 AC3 — expired만 존재 → 404 (*expired는 활성 미신청 동등*)."""
    user = await user_factory()
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        sub = Subscription(
            user_id=user.id,
            status="expired",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now - timedelta(days=60),
            expires_at=now - timedelta(days=30),
            provider="toss",
        )
        session.add(sub)
        await session.commit()

    response = await client.post(
        "/v1/payments/cancel",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "payments.subscription.not_found"


@pytest.mark.asyncio
async def test_cancel_without_basic_consent_succeeds(client: AsyncClient, user_factory) -> None:
    """Story 6.2 AC1 — 동의 미가입 사용자도 cancel 200 (PIPA Art.35 — 해지권은 동의 철회와
    독립). consent_factory 미호출 = ``basic_consents_complete=False``.
    """
    user = await user_factory()
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        sub = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(sub)
        await session.commit()

    response = await client.post(
        "/v1/payments/cancel",
        json={},
        headers=auth_headers(user),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_subscription_cancelled_but_not_expired_returns_200(
    client: AsyncClient, user_factory
) -> None:
    """Story 6.2 AC2 — cancelled-but-not-expired → 200 + ``status='cancelled'``
    (Story 6.1 deferred 흡수).
    """
    user = await user_factory()
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        sub = Subscription(
            user_id=user.id,
            status="cancelled",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now - timedelta(days=5),
            expires_at=now + timedelta(days=25),
            cancelled_at=now - timedelta(hours=1),
            provider="toss",
        )
        session.add(sub)
        await session.commit()

    response = await client.get(
        "/v1/payments/subscription",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None


@pytest.mark.asyncio
async def test_get_subscription_cancelled_and_expired_returns_404(
    client: AsyncClient, user_factory
) -> None:
    """Story 6.2 AC2 — cancelled-AND-expired → 404 (*expired는 미반환*)."""
    user = await user_factory()
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        sub = Subscription(
            user_id=user.id,
            status="cancelled",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now - timedelta(days=60),
            expires_at=now - timedelta(days=30),
            cancelled_at=now - timedelta(days=35),
            provider="toss",
        )
        session.add(sub)
        await session.commit()

    response = await client.get(
        "/v1/payments/subscription",
        headers=auth_headers(user),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "payments.subscription.not_found"


@pytest.mark.asyncio
async def test_get_payment_history_empty_returns_empty_items(
    client: AsyncClient, user_factory
) -> None:
    """Story 6.2 AC4 — 미신청 사용자 → 200 + ``items=[]`` + ``next_cursor=null``."""
    user = await user_factory()
    response = await client.get(
        "/v1/payments/history",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_get_payment_history_subscribe_with_receipt_url(
    client: AsyncClient, user_factory
) -> None:
    """Story 6.2 AC4 — subscribe log 1건 + raw_payload['receipt']['url'] 보존 →
    응답에 ``receipt_url`` 추출.
    """
    user = await user_factory()
    now = datetime.now(UTC)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        log = PaymentLog(
            user_id=user.id,
            subscription_id=None,
            event_type="subscribe",
            provider="toss",
            provider_payment_key="pk_receipt",
            provider_order_id="order_receipt",
            amount_krw=9900,
            status="success",
            idempotency_key=None,
            raw_payload={"receipt": {"url": "https://dashboard.tosspayments.com/receipt/abc"}},
            occurred_at=now,
        )
        session.add(log)
        await session.commit()

    response = await client.get(
        "/v1/payments/history",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["event_type"] == "subscribe"
    assert item["amount_krw"] == 9900
    assert item["receipt_url"] == "https://dashboard.tosspayments.com/receipt/abc"


@pytest.mark.asyncio
async def test_get_payment_history_pagination_round_trip(client: AsyncClient, user_factory) -> None:
    """Story 6.2 AC4 — limit=2 + 5건 fixture → 1페이지(2+cursor) → 2페이지(2+cursor) →
    3페이지(1+null cursor).
    """
    user = await user_factory()
    base = datetime.now(UTC).replace(microsecond=0)
    session_maker = app.state.session_maker
    async with session_maker() as session:
        for i in range(5):
            log = PaymentLog(
                user_id=user.id,
                subscription_id=None,
                event_type="subscribe",
                provider="toss",
                provider_payment_key=f"pk_page_{i}",
                provider_order_id=f"order_page_{i}",
                amount_krw=9900,
                status="success",
                idempotency_key=None,
                raw_payload=None,
                occurred_at=base - timedelta(minutes=10 - i),
            )
            session.add(log)
        await session.commit()

    # 1페이지.
    p1 = await client.get(
        "/v1/payments/history?limit=2",
        headers=auth_headers(user),
    )
    assert p1.status_code == 200
    p1_body = p1.json()
    assert len(p1_body["items"]) == 2
    assert p1_body["next_cursor"] is not None
    cursor1 = p1_body["next_cursor"]

    # 2페이지.
    p2 = await client.get(
        f"/v1/payments/history?limit=2&cursor={cursor1}",
        headers=auth_headers(user),
    )
    p2_body = p2.json()
    assert p2.status_code == 200
    assert len(p2_body["items"]) == 2
    assert p2_body["next_cursor"] is not None
    cursor2 = p2_body["next_cursor"]

    # 3페이지.
    p3 = await client.get(
        f"/v1/payments/history?limit=2&cursor={cursor2}",
        headers=auth_headers(user),
    )
    p3_body = p3.json()
    assert p3.status_code == 200
    assert len(p3_body["items"]) == 1
    assert p3_body["next_cursor"] is None


@pytest.mark.asyncio
async def test_get_payment_history_invalid_cursor_returns_400(
    client: AsyncClient, user_factory
) -> None:
    """Story 6.2 AC4 — cursor 형식 위반 → 400 + ``code=payments.history.cursor.invalid``."""
    user = await user_factory()
    response = await client.get(
        "/v1/payments/history?cursor=!!!not-base64!!!",
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "payments.history.cursor.invalid"


@pytest.mark.asyncio
async def test_get_payment_history_limit_over_50_returns_400(
    client: AsyncClient, user_factory
) -> None:
    """Story 6.2 AC4 — ``limit=51`` → 400 + ``code=validation.error`` (FastAPI Query
    ``le=50`` 자동 검증 → 글로벌 ``RequestValidationError`` 핸들러가 RFC 7807 400 매핑).

    프로젝트 SOT(``app/main.py:325``)가 모든 ``RequestValidationError``를 400으로 일원화 —
    스토리 명세의 *"422"*는 표준 FastAPI 동작 기준이지만, 본 프로젝트는 RFC 7807 catalog
    정합성을 위해 400 + ``code=validation.error``로 통일.
    """
    user = await user_factory()
    response = await client.get(
        "/v1/payments/history?limit=51",
        headers=auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation.error"
