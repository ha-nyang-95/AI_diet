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
