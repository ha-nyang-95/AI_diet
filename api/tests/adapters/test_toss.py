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

import base64 as _b64
import hashlib as _hashlib
import hmac as _hmac
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
    WebhookSignatureInvalidError,
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


def test_mask_payment_payload_preserves_receipt_url_for_history_endpoint() -> None:
    """Story 6.2 AC5 — ``receipt`` 키 보존 회귀 가드.

    Story 6.1 ``_mask_payment_payload`` baseline은 ``_MASK_REMOVE_KEYS``에 ``receipt``
    미포함 → 자동 보존. 본 테스트는 *invariant 가드* — 미래에 ``_MASK_REMOVE_KEYS``에
    ``receipt``를 잘못 추가하면 즉시 회귀 신호. ``GET /v1/payments/history``가 영수증 URL을
    노출하려면 ``payment_logs.raw_payload['receipt']['url']``이 마스킹 통과 후에도 보존돼야
    한다.
    """
    raw = {
        "paymentKey": "pk_receipt",
        "orderId": "order_receipt",
        "status": "DONE",
        "receipt": {"url": "https://dashboard.tosspayments.com/receipt/abc123"},
        "customerEmail": "user@example.com",  # 마스킹되어야 함.
    }
    masked = toss._mask_payment_payload(raw)

    # receipt 키 + 내부 url 무손실 보존.
    assert "receipt" in masked
    assert isinstance(masked["receipt"], dict)
    assert masked["receipt"]["url"] == "https://dashboard.tosspayments.com/receipt/abc123"

    # 동시에 customerEmail은 정상 마스킹.
    assert "customerEmail" not in masked


# ---------------------------------------------------------------------------
# Story 6.3 — webhook 시그니처 검증 + Pydantic body 모델 단위 테스트 (~6건)
# ---------------------------------------------------------------------------


def _build_signature_header(*, raw_body: bytes, secret: str, timestamp: int) -> str:
    """테스트 헬퍼 — 올바른 ``t=...,v1=...`` 시그니처 헤더 합성."""
    signed = f"{timestamp}.".encode() + raw_body
    digest = _hmac.new(secret.encode(), signed, _hashlib.sha256).digest()
    v1 = _b64.b64encode(digest).decode()
    return f"t={timestamp},v1={v1}"


def test_verify_webhook_signature_happy_path() -> None:
    """올바른 timestamp + signature → silent return (None)."""
    secret = "whsec_test"
    body = b'{"eventId":"evt_1","eventType":"PAYMENT_FAILED"}'
    now = 1_700_000_000
    header = _build_signature_header(raw_body=body, secret=secret, timestamp=now)

    # silent return — 예외 없음.
    assert (
        toss.verify_webhook_signature(
            raw_body=body, signature_header=header, secret=secret, now_unix=now
        )
        is None
    )


def test_verify_webhook_signature_malformed_header_raises() -> None:
    """``t=`` 또는 ``v1=`` key 부재 → ``WebhookSignatureInvalidError(401)``."""
    with pytest.raises(WebhookSignatureInvalidError):
        toss.verify_webhook_signature(
            raw_body=b"body",
            signature_header="v1=abcd",  # t= missing.
            secret="secret",
            now_unix=1_700_000_000,
        )

    with pytest.raises(WebhookSignatureInvalidError):
        toss.verify_webhook_signature(
            raw_body=b"body",
            signature_header="t=1700000000",  # v1= missing.
            secret="secret",
            now_unix=1_700_000_000,
        )

    # 빈 문자열도 거부.
    with pytest.raises(WebhookSignatureInvalidError):
        toss.verify_webhook_signature(
            raw_body=b"body",
            signature_header="",
            secret="secret",
            now_unix=1_700_000_000,
        )


def test_verify_webhook_signature_timestamp_outside_tolerance_raises() -> None:
    """timestamp drift 5분 초과 → ``WebhookSignatureInvalidError`` (replay attack 차단)."""
    secret = "whsec_test"
    body = b'{"eventId":"evt_1"}'
    past_timestamp = 1_700_000_000
    # 5분(300초) 초과 = 301초 후.
    now_outside = past_timestamp + 301
    header = _build_signature_header(raw_body=body, secret=secret, timestamp=past_timestamp)

    with pytest.raises(WebhookSignatureInvalidError, match="tolerance"):
        toss.verify_webhook_signature(
            raw_body=body, signature_header=header, secret=secret, now_unix=now_outside
        )


def test_verify_webhook_signature_mismatch_raises() -> None:
    """다른 secret으로 sign → mismatch → ``WebhookSignatureInvalidError``."""
    body = b'{"eventId":"evt_1"}'
    now = 1_700_000_000
    # 시그니처는 다른 secret으로 만들고, 검증은 진짜 secret으로.
    wrong_header = _build_signature_header(raw_body=body, secret="wrong_secret", timestamp=now)

    with pytest.raises(WebhookSignatureInvalidError, match="mismatch"):
        toss.verify_webhook_signature(
            raw_body=body, signature_header=wrong_header, secret="real_secret", now_unix=now
        )


def test_verify_webhook_signature_uses_compare_digest() -> None:
    """``hmac.compare_digest`` 사용 검증 — timing-safe 비교 invariant 가드.

    *Why*: ``==`` 비교는 timing attack에 취약. ``compare_digest`` 사용을 코드 mock으로 강제 검증
    (코드 회귀 시 이 테스트가 즉시 실패).
    """
    secret = "whsec_test"
    body = b'{"eventId":"evt_1"}'
    now = 1_700_000_000
    header = _build_signature_header(raw_body=body, secret=secret, timestamp=now)

    with patch("app.adapters.toss.hmac.compare_digest", return_value=True) as mock_compare:
        toss.verify_webhook_signature(
            raw_body=body, signature_header=header, secret=secret, now_unix=now
        )

    mock_compare.assert_called_once()


def test_toss_webhook_event_body_pydantic_validation() -> None:
    """``TossWebhookEventBody`` happy-path + 미지원 ``event_type`` 거부.

    Story 6.3 AC1 — 4 event_type만 허용 (PAYMENT.STATUS_CHANGED / PAYMENT_FAILED /
    REFUND_COMPLETED / REFUND_PARTIAL). 그 외는 Pydantic Literal 1차 차단.
    """
    from pydantic import ValidationError as _PydErr

    valid = {
        "eventId": "evt_test_123",
        "eventType": "PAYMENT.STATUS_CHANGED",
        "createdAt": "2026-05-09T12:00:00+09:00",
        "data": {"paymentKey": "pk_test", "orderId": "order_test"},
    }
    parsed = toss.TossWebhookEventBody.model_validate(valid)
    assert parsed.event_id == "evt_test_123"
    assert parsed.event_type == "PAYMENT.STATUS_CHANGED"
    assert isinstance(parsed.data, dict)
    assert parsed.data["paymentKey"] == "pk_test"

    # 미지원 event_type 거부.
    invalid = {**valid, "eventType": "ORDER_CREATED"}
    with pytest.raises(_PydErr):
        toss.TossWebhookEventBody.model_validate(invalid)

    # event_id 필수.
    invalid_missing = {k: v for k, v in valid.items() if k != "eventId"}
    with pytest.raises(_PydErr):
        toss.TossWebhookEventBody.model_validate(invalid_missing)
