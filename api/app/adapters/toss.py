"""Toss Payments REST API 어댑터 — Story 6.1 (정기결제 sandbox 신청 + 1플랜).

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

본 어댑터는 *최초 1회 결제 confirm*만 — 자동 갱신·webhook은 Story 6.3 forward
(빌링키 발급은 ``requestBillingAuth`` 별 endpoint).
"""

from __future__ import annotations

import base64
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
    total_amount: int = Field(alias="totalAmount")
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
    *, payment_key: str, order_id: str, amount: int, secret_key: str
) -> dict[str, Any]:
    """단일 시도 — tenacity wrapper(``confirm_payment``) 내부에서 호출.

    HTTP 응답 분기는 *adapter boundary typed 변환*만 — service 레이어로 propagate 의무.
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
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, base_url=TOSS_API_BASE_URL) as client:
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
    raw_body: dict[str, Any] | None = None
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

    logger.info(
        "toss.confirm_payment.succeeded",
        order_id=order_id,
        payment_key_prefix=payment_key[:8],
        approved_at=parsed.approved_at.isoformat(),
    )
    return parsed
