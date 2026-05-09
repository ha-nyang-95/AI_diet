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

import base64 as _b64
import hashlib as _hashlib
import hmac as _hmac
import json as _json
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


# ---------------------------------------------------------------------------
# Story 6.3 — POST /v1/payments/webhook 단위 테스트 (~7건) + DF135 회귀 가드 (~2건)
# ---------------------------------------------------------------------------


def _build_webhook_signature(*, raw_body: bytes, secret: str, timestamp: int) -> str:
    """webhook 시그니처 헤더 합성 helper."""
    signed = f"{timestamp}.".encode() + raw_body
    digest = _hmac.new(secret.encode(), signed, _hashlib.sha256).digest()
    v1 = _b64.b64encode(digest).decode()
    return f"t={timestamp},v1={v1}"


def _webhook_body_dict(
    *,
    event_id: str = "evt_router_1",
    event_type: str = "PAYMENT.STATUS_CHANGED",
    payment_key: str = "pk_router_renew",
    order_id: str = "order_router_renew",
    status_str: str = "DONE",
    total_amount: int = 9900,
) -> dict:
    return {
        "eventId": event_id,
        "eventType": event_type,
        "createdAt": "2026-05-09T12:00:00+09:00",
        "data": {
            "paymentKey": payment_key,
            "orderId": order_id,
            "status": status_str,
            "totalAmount": total_amount,
            "approvedAt": "2026-05-09T12:00:00+09:00",
        },
    }


async def _seed_subscribe_log_for_webhook(user_id: uuid.UUID, payment_key: str) -> uuid.UUID:
    """webhook payment_key 매칭에 필요한 baseline subscribe row INSERT."""
    session_maker = app.state.session_maker
    now = datetime.now(UTC)
    async with session_maker() as session:
        sub = Subscription(
            user_id=user_id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=now,
            expires_at=now + timedelta(days=30),
            provider="toss",
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)

        log = PaymentLog(
            user_id=user_id,
            subscription_id=sub.id,
            event_type="subscribe",
            provider="toss",
            provider_payment_key=payment_key,
            provider_order_id="order_seed",
            amount_krw=9900,
            status="success",
            occurred_at=now,
            raw_payload={"seed": True},
        )
        session.add(log)
        await session.commit()
        return sub.id


@pytest.mark.asyncio
async def test_webhook_secret_key_missing_returns_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1. ``TOSS_WEBHOOK_SECRET_KEY`` 미설정 → 503 + secret_key_missing 코드."""
    monkeypatch.setattr("app.core.config.settings.toss_webhook_secret_key", "")

    response = await client.post(
        "/v1/payments/webhook",
        json=_webhook_body_dict(),
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "payments.webhook.secret_key_missing"


@pytest.mark.asyncio
async def test_webhook_signature_header_missing_returns_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2. 시그니처 헤더 missing → 401 + ``code=payments.webhook.signature_invalid``."""
    monkeypatch.setattr("app.core.config.settings.toss_webhook_secret_key", "whsec_test")

    response = await client.post(
        "/v1/payments/webhook",
        json=_webhook_body_dict(),
    )
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "payments.webhook.signature_invalid"


@pytest.mark.asyncio
async def test_webhook_signature_mismatch_returns_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3. 시그니처 mismatch(다른 secret으로 sign) → 401 + sentry warning."""
    secret = "whsec_real"
    monkeypatch.setattr("app.core.config.settings.toss_webhook_secret_key", secret)

    body_dict = _webhook_body_dict()
    raw = _json.dumps(body_dict).encode()
    # 다른 secret으로 sign.
    bad_header = _build_webhook_signature(
        raw_body=raw, secret="whsec_attacker", timestamp=int(datetime.now(UTC).timestamp())
    )

    with patch("app.api.v1.payments.sentry_sdk") as mock_sentry:
        response = await client.post(
            "/v1/payments/webhook",
            content=raw,
            headers={
                toss_adapter.TOSS_WEBHOOK_SIGNATURE_HEADER: bad_header,
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 401
    assert response.json()["code"] == "payments.webhook.signature_invalid"

    # sentry capture 호출 검증.
    assert any(
        call.args[0] == "payments.webhook.signature_invalid"
        for call in mock_sentry.capture_message.call_args_list
    )


@pytest.mark.asyncio
async def test_webhook_renew_happy_path_returns_200_extends_expires_at(
    client: AsyncClient, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4. happy-path renew → 200 + expires_at +30일 + ``event_type='renew'`` row INSERT."""
    secret = "whsec_test_happy"
    monkeypatch.setattr("app.core.config.settings.toss_webhook_secret_key", secret)

    user = await user_factory()
    payment_key = "pk_webhook_happy"
    sub_id = await _seed_subscribe_log_for_webhook(user.id, payment_key)

    # original expires_at 기록.
    async with app.state.session_maker() as session:
        sub_row = await session.get(Subscription, sub_id)
        assert sub_row is not None
        original_expires = sub_row.expires_at

    body_dict = _webhook_body_dict(payment_key=payment_key, event_type="PAYMENT.STATUS_CHANGED")
    raw = _json.dumps(body_dict).encode()
    timestamp = int(datetime.now(UTC).timestamp())
    sig = _build_webhook_signature(raw_body=raw, secret=secret, timestamp=timestamp)

    response = await client.post(
        "/v1/payments/webhook",
        content=raw,
        headers={
            toss_adapter.TOSS_WEBHOOK_SIGNATURE_HEADER: sig,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    # Toss ack 표준 — 빈 body.
    assert response.text == ""

    # subscription.expires_at +30일 검증.
    async with app.state.session_maker() as session:
        sub_after = await session.get(Subscription, sub_id)
    assert sub_after is not None
    assert original_expires is not None
    assert sub_after.expires_at == original_expires + timedelta(days=30)

    # renew row INSERT 검증.
    async with app.state.session_maker() as session:
        renew_logs = (
            (
                await session.execute(
                    select(PaymentLog).where(
                        PaymentLog.user_id == user.id, PaymentLog.event_type == "renew"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(list(renew_logs)) == 1


@pytest.mark.asyncio
async def test_webhook_replay_same_event_id_returns_200_no_extra_row(
    client: AsyncClient, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5. 같은 ``event_id`` 재전송 → 200 + 추가 row INSERT X (replay 분기)."""
    secret = "whsec_test_replay"
    monkeypatch.setattr("app.core.config.settings.toss_webhook_secret_key", secret)

    user = await user_factory()
    payment_key = "pk_webhook_replay"
    await _seed_subscribe_log_for_webhook(user.id, payment_key)

    body_dict = _webhook_body_dict(
        event_id="evt_router_replay_xyz",
        payment_key=payment_key,
        event_type="PAYMENT.STATUS_CHANGED",
    )
    raw = _json.dumps(body_dict).encode()
    timestamp = int(datetime.now(UTC).timestamp())
    sig = _build_webhook_signature(raw_body=raw, secret=secret, timestamp=timestamp)
    headers = {
        toss_adapter.TOSS_WEBHOOK_SIGNATURE_HEADER: sig,
        "Content-Type": "application/json",
    }

    first = await client.post("/v1/payments/webhook", content=raw, headers=headers)
    assert first.status_code == 200

    second = await client.post("/v1/payments/webhook", content=raw, headers=headers)
    assert second.status_code == 200

    # renew row count = 1 (replay은 추가 INSERT 없음).
    async with app.state.session_maker() as session:
        renew_logs = (
            (
                await session.execute(
                    select(PaymentLog).where(
                        PaymentLog.user_id == user.id, PaymentLog.event_type == "renew"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(list(renew_logs)) == 1


@pytest.mark.asyncio
async def test_webhook_payload_schema_violation_returns_400(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """6. body schema 위반(``eventType`` 누락) → 400 + ``code=payments.webhook.payload_invalid``."""
    secret = "whsec_test_invalid_body"
    monkeypatch.setattr("app.core.config.settings.toss_webhook_secret_key", secret)

    invalid_body = {
        "eventId": "evt_invalid",
        # eventType 누락.
        "createdAt": "2026-05-09T12:00:00+09:00",
        "data": {
            "paymentKey": "pk_x",
            "orderId": "order_x",
            "status": "DONE",
            "totalAmount": 9900,
        },
    }
    raw = _json.dumps(invalid_body).encode()
    timestamp = int(datetime.now(UTC).timestamp())
    sig = _build_webhook_signature(raw_body=raw, secret=secret, timestamp=timestamp)

    response = await client.post(
        "/v1/payments/webhook",
        content=raw,
        headers={
            toss_adapter.TOSS_WEBHOOK_SIGNATURE_HEADER: sig,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "payments.webhook.payload_invalid"


@pytest.mark.asyncio
async def test_webhook_payment_key_missing_returns_200_with_no_log_row(
    client: AsyncClient, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """7. paymentKey 미매칭(subscribe row 부재) → 200 + sentry warning + payment_logs row 0건.

    Toss 재시도 회피(200 ack) — 외주 운영 incident 신호로 sentry warning만.
    """
    secret = "whsec_test_no_match"
    monkeypatch.setattr("app.core.config.settings.toss_webhook_secret_key", secret)

    user = await user_factory()  # subscribe row 미생성.
    body_dict = _webhook_body_dict(payment_key="pk_unknown_router")
    raw = _json.dumps(body_dict).encode()
    timestamp = int(datetime.now(UTC).timestamp())
    sig = _build_webhook_signature(raw_body=raw, secret=secret, timestamp=timestamp)

    response = await client.post(
        "/v1/payments/webhook",
        content=raw,
        headers={
            toss_adapter.TOSS_WEBHOOK_SIGNATURE_HEADER: sig,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.text == ""

    # payment_logs row 0건.
    async with app.state.session_maker() as session:
        rows = (
            (await session.execute(select(PaymentLog).where(PaymentLog.user_id == user.id)))
            .scalars()
            .all()
        )
    assert len(list(rows)) == 0


# --- DF135 회귀 가드 (~2건) -------------------------------------------------


@pytest.mark.asyncio
async def test_get_subscription_active_but_expired_returns_404(
    client: AsyncClient, user_factory
) -> None:
    """DF135 흡수 — ``GET /subscription`` active branch에
    ``(expires_at IS NULL OR expires_at > now())`` lazy gate 추가. ``status='active'`` AND
    ``expires_at < now()`` row는 *비정상 race window* 상태로 *유효 구독 노출 X* → 404.

    sweep cron이 expired 전이 전이라도 lazy gate가 차단.
    """
    user = await user_factory()

    # active-but-expired row 직접 INSERT.
    async with app.state.session_maker() as session:
        sub = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=datetime.now(UTC) - timedelta(days=60),
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # 과거.
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
async def test_get_subscription_active_normal_returns_200(
    client: AsyncClient, user_factory
) -> None:
    """DF135 회귀 0건 — 정상 active(``expires_at > now()``)는 그대로 200 반환."""
    user = await user_factory()

    async with app.state.session_maker() as session:
        sub = Subscription(
            user_id=user.id,
            status="active",
            plan="monthly",
            plan_price_krw=9900,
            started_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
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
    assert body["status"] == "active"
