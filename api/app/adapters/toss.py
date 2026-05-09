"""Toss Payments REST API 어댑터 — Story 6.1 (정기결제 sandbox 신청 + 1플랜) + Story 6.3
(webhook 시그니처 검증 + receipt 모델).

Toss Payments 공식 REST API ``POST /v1/payments/confirm`` 호출 — sandbox/prod 공통
``baseURL``(secret_key prefix ``test_sk_``/``live_sk_``로 환경 분리). architecture.md:693
``toss.py`` adapter SOT 정합.

오류 매핑 (CR D1+MJ-12 — adapter boundary에서 typed 변환 — Story 3.6 ``llm_router``
패턴 정합):

- ``settings.toss_secret_key`` 빈 문자열 — ``TossSecretKeyMissingError(503)`` 즉시
  raise (cost 0 / fail-fast — retry 무효).
- HTTP 4xx (Toss 카드 거절 / 한도 초과 / 잘못된 paymentKey 등) — ``PaymentProviderRejectedError
  (400)`` 즉시 raise + Toss 응답 ``message`` detail 보존(*"카드 한도가 초과되었습니다"* 등).
- HTTP 5xx + ``httpx.HTTPError`` *transient* — tenacity 3회 retry. 최종 실패는
  ``PaymentProviderUnavailableError(502)``.
- HTTP 2xx but Toss ``status != "DONE"`` (CANCELED/PARTIAL_CANCELED/ABORTED) —
  ``PaymentProviderRejectedError(400)``.
- 응답 schema 위반(Pydantic ValidationError) — ``PaymentProviderPayloadInvalidError(502)``.

NFR-S5 마스킹 — ``customerEmail``/``customerName``/``customerMobilePhone`` 키 제거 +
``card.number`` 마지막 4자리 보존 + ``secret``/``mId`` 머천트 식별자 제거. ``raw_payload``
영속화 시 ``_mask_payment_payload``를 거친 dict만 INSERT.

Story 6.3 추가:
- ``verify_webhook_signature`` — Toss webhook ``TossPayments-Webhook-Signature`` 헤더
  검증 SOT. HMAC-SHA256 + ``hmac.compare_digest``(timing-safe) + 5분 timestamp drift cap
  (replay attack 차단). Stripe webhook 표준 1:1 정합.
- ``TossWebhookEventBody`` / ``TossWebhookPaymentData`` — webhook body Pydantic 모델
  (외부 envelope + 내부 data sub-schema).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime
from typing import Any, Final, Literal

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import (
    PaymentProviderPayloadInvalidError,
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    TossSecretKeyMissingError,
    WebhookSignatureInvalidError,
)

logger = structlog.get_logger(__name__)

# Toss Payments REST API base URL — sandbox + prod 공통(Toss는 secret_key prefix
# ``test_sk_``/``live_sk_``로 환경 분리).
TOSS_API_BASE_URL: Final[str] = "https://api.tosspayments.com"
TOSS_CONFIRM_PATH: Final[str] = "/v1/payments/confirm"

# Toss API 응답은 ~3-5초 평균(card auth + clearing) — connect 5s + read 15s 정합.
# write/pool은 connect와 동일(5s) — httpx.Timeout 4 파라미터 모두 명시 의무.
_HTTP_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

# tenacity 3회 backoff — Story 3.6 ``llm_router`` 패턴 정합 (1s/2s/4s).
_RETRY_MIN_WAIT_SECONDS: Final[float] = 1.0
_RETRY_MAX_WAIT_SECONDS: Final[float] = 4.0
_RETRY_MAX_ATTEMPTS: Final[int] = 3

# Transient subset — 영구 4xx는 미포함(retry 무효 + cost 낭비 차단).
# ``llm_router`` CR P1 fix 패턴 정합.
_TRANSIENT_RETRY_TYPES: Final[tuple[type[BaseException], ...]] = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    PaymentProviderUnavailableError,
)

# Toss 응답에서 마스킹 제거 키 SOT — NFR-S5 정합.
_MASK_REMOVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "customerEmail",
        "customerName",
        "customerMobilePhone",
        # 머천트 식별자 — 외주 인수 시 클라이언트 머천트 ID 노출 회피.
        "secret",
        "mId",
    }
)


class TossConfirmResponse(BaseModel):
    """Toss ``POST /v1/payments/confirm`` 응답 schema (필요 필드만 채택, 모두 채택 시
    PII 노출 위험).

    ``raw``는 *전체 응답 dict*를 보존 — ``raw_payload`` INSERT 전 ``_mask_payment_payload``
    호출 의무.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    payment_key: str = Field(alias="paymentKey")
    order_id: str = Field(alias="orderId")
    # Toss 표준 status — ``DONE``만 success 분기, 그 외는 ``PaymentProviderRejectedError``.
    status: Literal["DONE", "CANCELED", "PARTIAL_CANCELED", "ABORTED"]
    # CR P4 — ``strict=True``로 string/float 자동 coerce 차단(보안 — 응답 위변조 방지).
    total_amount: int = Field(alias="totalAmount", strict=True)
    approved_at: datetime = Field(alias="approvedAt")
    method: str | None = None
    card: dict[str, Any] | None = None
    # *모든 필드* 원본 — payment_logs.raw_payload INSERT용. ``_mask_payment_payload``
    # 호출 후 영속화.
    raw: dict[str, Any]


def _build_basic_auth_header(secret_key: str) -> str:
    """Toss Basic Auth — ``Authorization: Basic base64(secret_key + ":")`` (Toss 표준).

    Toss는 secret_key 뒤 콜론 + 빈 password (HTTP Basic Auth ``user:password`` 표기).
    """
    creds = f"{secret_key}:".encode()
    return "Basic " + base64.b64encode(creds).decode()


def _mask_payment_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Toss 응답 raw_payload 마스킹 SOT — NFR-S5 정합.

    제거 키: ``customerEmail`` / ``customerName`` / ``customerMobilePhone`` /
    ``secret`` / ``mId`` (머천트 식별자).

    ``card.number``는 마지막 4자리만 보존 (``"433012******1234"`` → ``"****1234"``).
    ``easyPay.provider`` 등 일반 메타는 보존(영업 분석 hint).

    재귀 X — Toss 응답은 1-2 nesting level만이라 inline 분기로 충분.
    """
    masked: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _MASK_REMOVE_KEYS:
            continue
        if key == "card" and isinstance(value, dict):
            card_copy = dict(value)
            number = card_copy.get("number")
            if isinstance(number, str) and len(number) >= 4:
                card_copy["number"] = "****" + number[-4:]
            masked[key] = card_copy
        else:
            masked[key] = value
    return masked


def _is_transient_status(status_code: int) -> bool:
    """5xx + 408 + 429만 transient — 그 외 4xx는 영구(retry 무효)."""
    return status_code >= 500 or status_code in (408, 429)


async def _confirm_payment_once(
    *,
    payment_key: str,
    order_id: str,
    amount: int,
    secret_key: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """단일 시도 — tenacity wrapper(``confirm_payment``) 내부에서 호출.

    HTTP 응답 분기는 *adapter boundary typed 변환*만 — service 레이어로 propagate 의무.

    Gemini Code Assist 봇 review 정합 — ``client``는 ``confirm_payment`` 수준에서 한 번만
    생성, 본 함수에 인자로 전달. retry 시도마다 connection pool / TLS handshake 재사용.
    """
    headers = {
        "Authorization": _build_basic_auth_header(secret_key),
        "Content-Type": "application/json",
    }
    payload = {
        "paymentKey": payment_key,
        "orderId": order_id,
        "amount": amount,
    }

    started = httpx_perf_counter()
    try:
        response = await client.post(TOSS_CONFIRM_PATH, headers=headers, json=payload)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        # transient — tenacity retry 진입 신호.
        raise PaymentProviderUnavailableError(f"toss_network_error: {exc!r}") from exc

    latency_ms = int((httpx_perf_counter() - started) * 1000)

    if _is_transient_status(response.status_code):
        # 5xx / 408 / 429 — transient, retry 진입.
        logger.warning(
            "toss.confirm_payment.transient",
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        raise PaymentProviderUnavailableError(f"toss_transient_status: {response.status_code}")

    if response.status_code >= 400:
        # 영구 4xx — Toss 응답 본문에 ``code``/``message`` 포함 (Toss 표준).
        try:
            error_body = response.json()
        except ValueError:
            error_body = {"raw": response.text}
        toss_code = error_body.get("code") if isinstance(error_body, dict) else None
        toss_message = (
            error_body.get("message")
            if isinstance(error_body, dict)
            else f"unknown_toss_error_{response.status_code}"
        )
        logger.warning(
            "toss.confirm_payment.rejected",
            status_code=response.status_code,
            toss_code=toss_code,
            latency_ms=latency_ms,
        )
        raise PaymentProviderRejectedError(
            toss_message or f"toss_rejected_{toss_code or response.status_code}"
        )

    # 2xx — 정상 응답.
    try:
        body = response.json()
    except ValueError as exc:
        raise PaymentProviderPayloadInvalidError(f"toss_response_not_json: {exc!r}") from exc

    if not isinstance(body, dict):
        raise PaymentProviderPayloadInvalidError("toss_response_not_dict")

    return body


def httpx_perf_counter() -> float:
    """time.perf_counter() wrapper — pytest monkey-patch 용이."""
    import time  # noqa: PLC0415

    return time.perf_counter()


async def confirm_payment(*, payment_key: str, order_id: str, amount: int) -> TossConfirmResponse:
    """Toss ``POST /v1/payments/confirm`` 호출 + tenacity retry + typed 변환.

    Returns ``TossConfirmResponse`` — ``status="DONE"`` invariant 보장. ``status``가
    ``DONE``이 아니면 (HTTP 2xx but Toss 비-DONE 상태) ``PaymentProviderRejectedError``
    raise.

    오류 분기:
    - ``settings.toss_secret_key`` 빈 — ``TossSecretKeyMissingError(503)``.
    - 4xx — ``PaymentProviderRejectedError(400)`` (retry 무효).
    - 5xx + transient — 3회 retry 후 ``PaymentProviderUnavailableError(502)``.
    - 응답 schema 위반 — ``PaymentProviderPayloadInvalidError(502)``.
    """
    secret_key = settings.toss_secret_key
    if not secret_key:
        raise TossSecretKeyMissingError("toss_secret_key not configured")

    logger.info(
        "toss.confirm_payment.requested",
        order_id=order_id,
        amount=amount,
    )

    # tenacity AsyncRetrying — 3회 backoff(1s/2s/4s), transient만 retry.
    # ``httpx.AsyncClient``는 retry 루프 외부에서 한 번 생성 — 재시도 시 connection pool
    # / TLS handshake 재사용(Gemini Code Assist 봇 review 정합).
    raw_body: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, base_url=TOSS_API_BASE_URL) as client:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
            wait=wait_exponential(
                multiplier=1, min=_RETRY_MIN_WAIT_SECONDS, max=_RETRY_MAX_WAIT_SECONDS
            ),
            retry=retry_if_exception_type(_TRANSIENT_RETRY_TYPES),
            reraise=True,
        ):
            with attempt:
                raw_body = await _confirm_payment_once(
                    payment_key=payment_key,
                    order_id=order_id,
                    amount=amount,
                    secret_key=secret_key,
                    client=client,
                )

    assert raw_body is not None  # tenacity reraise=True invariant

    # Pydantic 검증 — schema 위반은 502.
    try:
        parsed = TossConfirmResponse.model_validate({**raw_body, "raw": raw_body})
    except ValidationError as exc:
        raise PaymentProviderPayloadInvalidError(f"toss_payload_invalid: {exc}") from exc

    # Toss ``status="DONE"`` 외 거절 분기 (HTTP 2xx but 비-DONE 상태).
    if parsed.status != "DONE":
        raise PaymentProviderRejectedError(f"toss_status_not_done: {parsed.status}")

    # CR P3 — Toss 응답 ``totalAmount``/``orderId``가 요청 값과 일치하는지 검증. 응답
    # 위변조 또는 Toss 버그로 인한 부분 capture / 다른 paymentKey 매핑 차단(보안).
    if parsed.total_amount != amount:
        logger.error(
            "toss.confirm_payment.amount_mismatch",
            order_id=order_id,
            requested_amount=amount,
            response_amount=parsed.total_amount,
        )
        raise PaymentProviderPayloadInvalidError(
            f"toss_amount_mismatch: requested={amount}, response={parsed.total_amount}"
        )
    if parsed.order_id != order_id:
        logger.error(
            "toss.confirm_payment.order_id_mismatch",
            requested_order_id=order_id,
            response_order_id=parsed.order_id,
        )
        raise PaymentProviderPayloadInvalidError(
            f"toss_order_id_mismatch: requested={order_id}, response={parsed.order_id}"
        )

    logger.info(
        "toss.confirm_payment.succeeded",
        order_id=order_id,
        payment_key_prefix=payment_key[:8],
        approved_at=parsed.approved_at.isoformat(),
    )
    return parsed


# ---------------------------------------------------------------------------
# Story 6.3 — Toss webhook 시그니처 검증 + Pydantic body 모델
# ---------------------------------------------------------------------------

# Toss 표준 webhook 시그니처 헤더 — ``t=<unix_ts>,v1=<base64_hmac_sha256>`` 형식.
TOSS_WEBHOOK_SIGNATURE_HEADER: Final[str] = "TossPayments-Webhook-Signature"

# Stripe 표준 정합 — replay attack 차단 window. 5분 drift cap.
_TIMESTAMP_TOLERANCE_SECONDS: Final[int] = 300


def verify_webhook_signature(
    *,
    raw_body: bytes,
    signature_header: str,
    secret: str,
    now_unix: int | None = None,
) -> None:
    """Toss webhook 시그니처 검증 SOT — HMAC-SHA256 + timing-safe + 5분 timestamp window.

    Stripe webhook 표준 1:1 정합 — ``t=<unix>.<raw_body>`` HMAC-SHA256 + ``hmac.compare_digest``
    (timing-attack 차단) + 5분 drift cap(replay attack 차단).

    Args:
        raw_body: HTTP request body raw bytes — *JSON 파싱 전*에 검증 의무(파싱 후 re-serialize는
            위변조 가능).
        signature_header: ``TossPayments-Webhook-Signature`` 헤더 값. 형식 ``t=<unix>,v1=<base64>``.
        secret: ``settings.toss_webhook_secret_key`` (Toss 콘솔에서 발급, ``whsec_*``/``wsk_*``
            prefix).
        now_unix: 현재 unix timestamp (테스트 mock 용). None이면 ``int(time.time())``.

    Returns:
        None: 시그니처 검증 통과(silent return).

    Raises:
        WebhookSignatureInvalidError: 헤더 형식 위반 / timestamp drift 초과 / HMAC mismatch.
            ``reason`` extras로 분기 신호(외부 응답은 단일 401 — enumeration 방지).
    """
    # Step 1 — header parse.
    header_parts = signature_header.split(",")
    parsed_t: str | None = None
    parsed_v1: str | None = None
    for part in header_parts:
        item = part.strip()
        if item.startswith("t="):
            parsed_t = item[2:]
        elif item.startswith("v1="):
            parsed_v1 = item[3:]
    if parsed_t is None or parsed_v1 is None or not parsed_t or not parsed_v1:
        logger.warning("toss.webhook.signature_invalid", reason="malformed")
        raise WebhookSignatureInvalidError("webhook signature header malformed")

    try:
        parsed_timestamp = int(parsed_t)
    except ValueError as exc:
        logger.warning("toss.webhook.signature_invalid", reason="malformed_timestamp")
        raise WebhookSignatureInvalidError("webhook signature header malformed") from exc

    # Step 2 — timestamp drift 검증.
    now = now_unix if now_unix is not None else int(time.time())
    if abs(now - parsed_timestamp) > _TIMESTAMP_TOLERANCE_SECONDS:
        logger.warning(
            "toss.webhook.signature_invalid",
            reason="outside_tolerance",
            drift_seconds=abs(now - parsed_timestamp),
        )
        raise WebhookSignatureInvalidError("webhook timestamp outside tolerance")

    # Step 3 — HMAC-SHA256 계산 + timing-safe compare.
    signed_payload = f"{parsed_timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).digest()
    try:
        actual = base64.b64decode(parsed_v1)
    except (ValueError, TypeError) as exc:
        logger.warning("toss.webhook.signature_invalid", reason="malformed_b64")
        raise WebhookSignatureInvalidError("webhook signature header malformed") from exc

    # ``hmac.compare_digest`` 의무 — ``==`` 비교는 timing-attack 취약. mismatch 시 단일 코드.
    if not hmac.compare_digest(expected, actual):
        logger.warning("toss.webhook.signature_invalid", reason="mismatch")
        raise WebhookSignatureInvalidError("webhook signature mismatch")

    logger.info("toss.webhook.signature_verified")


class TossWebhookEventBody(BaseModel):
    """Toss webhook body 외부 envelope (필요 필드만 채택, 모두 채택은 PII 노출 위험).

    내부 ``data`` dict는 *event_type별 의미가 다르므로* raw dict 유지 — service 레이어가
    ``TossWebhookPaymentData``로 sub-schema 검증.

    필드:
    - ``event_id``: Toss 측 unique event id, 멱등 키 1차 신호 (``event_type``별 namespace
      추가 분리는 service 레이어).
    - ``event_type``: 4 enum — 본 스토리는 ``PAYMENT.STATUS_CHANGED``/``PAYMENT_FAILED``/
      ``REFUND_COMPLETED``/``REFUND_PARTIAL``만 처리. 그 외는 Pydantic Literal 1차 차단 →
      ``WebhookPayloadInvalidError(400)``.
    - ``created_at``: Toss 표준 ISO 8601.
    - ``data``: 상세 dict — ``paymentKey``/``orderId``/``status``/``totalAmount`` 등 포함.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    event_id: str = Field(alias="eventId", min_length=1, max_length=64)
    event_type: Literal[
        "PAYMENT.STATUS_CHANGED",
        "PAYMENT_FAILED",
        "REFUND_COMPLETED",
        "REFUND_PARTIAL",
    ] = Field(alias="eventType")
    created_at: datetime = Field(alias="createdAt")
    data: dict[str, Any]


class TossWebhookPaymentData(BaseModel):
    """``TossWebhookEventBody.data`` sub-schema — service 레이어가 분기 시 검증.

    필드:
    - ``payment_key``: Toss ``paymentKey`` (36+자, 결제 식별자).
    - ``order_id``: Toss ``orderId`` (UUID v4 권장, 64자 cap).
    - ``status``: Toss 표준 4 enum — ``DONE``만 success 분기.
    - ``total_amount``: KRW integer + ``strict=True`` (응답 위변조 방지 — string/float 자동
      coerce 차단).
    - ``approved_at``: 환불 등 미수반 케이스 None 허용.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    payment_key: str = Field(alias="paymentKey", min_length=1, max_length=200)
    order_id: str = Field(alias="orderId", min_length=1, max_length=64)
    status: Literal["DONE", "CANCELED", "PARTIAL_CANCELED", "ABORTED"]
    total_amount: int = Field(alias="totalAmount", strict=True, ge=0)
    approved_at: datetime | None = Field(alias="approvedAt", default=None)
