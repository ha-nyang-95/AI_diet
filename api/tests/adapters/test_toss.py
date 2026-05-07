"""Story 6.1 — Toss Payments adapter 단위 테스트 (AC2).

``httpx.MockTransport`` 기반 — Story 3.1 ``test_mfds_openapi.py`` 패턴 정합. 케이스:
  1. ``confirm_payment`` happy-path — 200 응답 → ``TossConfirmResponse`` 매핑.
  2. ``confirm_payment`` 4xx 카드 거절 → ``PaymentProviderRejectedError`` + Toss
     ``message`` detail 보존.
  3. ``confirm_payment`` 5xx 3회 retry 후 ``PaymentProviderUnavailableError``.
  4. ``confirm_payment`` ``status="ABORTED"`` (HTTP 2xx but Toss 비-DONE) →
     ``PaymentProviderRejectedError``.
  5. ``_mask_payment_payload`` 마스킹 — ``customerEmail`` / ``card.number`` 처리.
  6. ``settings.toss_secret_key`` 미설정 → ``TossSecretKeyMissingError`` (fail-fast).

NFR-S5 — secret_key는 logger 출력 X (어댑터 코드에서 차단). 테스트는 *동작* 검증만.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.adapters import toss
from app.core.config import settings
from app.core.exceptions import (
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    TossSecretKeyMissingError,
)


@pytest.fixture(autouse=True)
def _set_toss_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본 fixture — sandbox secret_key 주입. 테스트 1건은 명시적으로 unset."""
    monkeypatch.setattr(settings, "toss_secret_key", "test_sk_dummy_sandbox_key", raising=False)


@pytest.fixture(autouse=True)
def _disable_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """tenacity backoff 0초로 단축 — 5xx retry 테스트 wall-time 단축."""
    monkeypatch.setattr(toss, "_RETRY_MIN_WAIT_SECONDS", 0.0, raising=False)
    monkeypatch.setattr(toss, "_RETRY_MAX_WAIT_SECONDS", 0.0, raising=False)


def _patch_transport(transport: httpx.MockTransport) -> Any:
    """``httpx.AsyncClient`` 컨텍스트 매니저를 MockTransport로 교체."""

    class _MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, **kwargs: Any) -> None:  # noqa: D401
            kwargs.pop("transport", None)
            super().__init__(transport=transport, **kwargs)

    return patch.object(toss.httpx, "AsyncClient", _MockedAsyncClient)


async def test_confirm_payment_happy_path() -> None:
    """200 응답 → ``TossConfirmResponse`` 정상 매핑 + ``raw`` 보존."""
    toss_response = {
        "paymentKey": "pk_test_123456789012",
        "orderId": "order_abc",
        "status": "DONE",
        "totalAmount": 9900,
        "approvedAt": "2026-05-08T12:34:56+09:00",
        "method": "카드",
        "card": {"number": "433012******1234", "company": "신한"},
        "easyPay": {"provider": "토스결제"},
        "customerEmail": "user@example.com",  # 마스킹 대상 — raw에는 보존되어야 함.
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/payments/confirm"
        body = request.read().decode()
        assert "pk_test_123456789012" in body
        assert "order_abc" in body
        return httpx.Response(200, json=toss_response)

    with _patch_transport(httpx.MockTransport(handler)):
        result = await toss.confirm_payment(
            payment_key="pk_test_123456789012",
            order_id="order_abc",
            amount=9900,
        )

    assert result.payment_key == "pk_test_123456789012"
    assert result.order_id == "order_abc"
    assert result.status == "DONE"
    assert result.total_amount == 9900
    assert result.method == "카드"
    assert result.card == {"number": "433012******1234", "company": "신한"}
    # raw에는 모든 키 보존 (마스킹은 _mask_payment_payload 호출 시점에서만).
    assert result.raw["customerEmail"] == "user@example.com"


async def test_confirm_payment_4xx_card_rejected() -> None:
    """Toss 4xx 카드 거절 → ``PaymentProviderRejectedError`` + 한국어 message detail 보존."""
    error_body = {
        "code": "REJECT_CARD_COMPANY",
        "message": "카드 한도가 초과되었습니다",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=error_body)

    with (
        _patch_transport(httpx.MockTransport(handler)),
        pytest.raises(PaymentProviderRejectedError) as exc_info,
    ):
        await toss.confirm_payment(payment_key="pk_test", order_id="order_xyz", amount=9900)

    # detail에 Toss message 한국어 보존.
    assert "카드 한도가 초과되었습니다" in str(exc_info.value)


async def test_confirm_payment_5xx_3retries_then_unavailable() -> None:
    """5xx 3회 retry 후 ``PaymentProviderUnavailableError`` raise + retry 카운트 검증."""
    call_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(503, json={"code": "INTERNAL_ERROR", "message": "Toss internal"})

    with (
        _patch_transport(httpx.MockTransport(handler)),
        pytest.raises(PaymentProviderUnavailableError),
    ):
        await toss.confirm_payment(payment_key="pk_test", order_id="order_5xx", amount=9900)

    # 3회 시도 후 단념.
    assert call_count["value"] == toss._RETRY_MAX_ATTEMPTS


async def test_confirm_payment_status_aborted_not_done() -> None:
    """HTTP 2xx but ``status="ABORTED"`` (Toss 비-DONE 상태) → ``PaymentProviderRejectedError``.

    Toss 결제 흐름에서 사용자가 결제 중단 후에도 confirm 호출이 일어나는 시나리오 방어.
    """
    aborted_response = {
        "paymentKey": "pk_aborted",
        "orderId": "order_aborted",
        "status": "ABORTED",
        "totalAmount": 9900,
        "approvedAt": "2026-05-08T12:00:00+09:00",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=aborted_response)

    with (
        _patch_transport(httpx.MockTransport(handler)),
        pytest.raises(PaymentProviderRejectedError) as exc_info,
    ):
        await toss.confirm_payment(payment_key="pk_aborted", order_id="order_aborted", amount=9900)

    assert "ABORTED" in str(exc_info.value)


def test_mask_payment_payload_removes_customer_pii_and_masks_card_number() -> None:
    """``_mask_payment_payload`` 단위 검증:
    - ``customerEmail`` / ``customerName`` / ``customerMobilePhone`` / ``mId`` /
      ``secret`` 키 제거.
    - ``card.number``는 마지막 4자리만 보존(``****1234``).
    - ``method`` / ``easyPay`` 등 일반 메타는 보존.
    """
    raw = {
        "paymentKey": "pk_test",
        "orderId": "order_test",
        "status": "DONE",
        "totalAmount": 9900,
        "method": "카드",
        "card": {"number": "433012******1234", "company": "신한", "ownerType": "개인"},
        "easyPay": {"provider": "토스결제"},
        "customerEmail": "user@example.com",
        "customerName": "홍길동",
        "customerMobilePhone": "010-1234-5678",
        "mId": "balancenote-merchant-id",
        "secret": "shared-secret-with-toss",
    }
    masked = toss._mask_payment_payload(raw)

    # 제거 키 확인.
    assert "customerEmail" not in masked
    assert "customerName" not in masked
    assert "customerMobilePhone" not in masked
    assert "mId" not in masked
    assert "secret" not in masked

    # 일반 메타 보존.
    assert masked["paymentKey"] == "pk_test"
    assert masked["status"] == "DONE"
    assert masked["totalAmount"] == 9900
    assert masked["method"] == "카드"
    assert masked["easyPay"] == {"provider": "토스결제"}

    # card.number 마스킹 — 마지막 4자리만 보존.
    assert masked["card"]["number"] == "****1234"
    assert masked["card"]["company"] == "신한"
    assert masked["card"]["ownerType"] == "개인"


async def test_confirm_payment_secret_key_missing_raises_toss_secret_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``settings.toss_secret_key`` 빈 문자열 → ``TossSecretKeyMissingError(503)`` fail-fast.

    HTTP 호출 *전* raise — retry 무효 + cost 0.
    """
    monkeypatch.setattr(settings, "toss_secret_key", "", raising=False)

    call_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        return httpx.Response(200, json={})

    with _patch_transport(httpx.MockTransport(handler)), pytest.raises(TossSecretKeyMissingError):
        await toss.confirm_payment(payment_key="pk_test", order_id="order_test", amount=9900)

    # HTTP 호출 자체 발생 X.
    assert call_count["value"] == 0
