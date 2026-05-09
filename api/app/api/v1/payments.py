"""``/v1/payments`` — 결제 신청 + 활성 구독 조회 + 해지 + 결제 이력 (Story 6.1 / 6.2).

4 endpoint:
- ``POST /v1/payments/subscribe``     — 정기결제 신청 (require_basic_consents)
- ``POST /v1/payments/cancel``        — 구독 해지 (current_user 단독 — PIPA Art.35)
- ``GET /v1/payments/subscription``   — 자기 active/cancelled 구독 조회 (current_user)
- ``GET /v1/payments/history``        — 자기 결제 이력 page (current_user)

핵심 결정:
- *작성 경로*(POST subscribe)에만 ``Depends(require_basic_consents)`` wire — 결제는
  자기 데이터 작성이라 동의 게이트 의무. *조회 + 해지* 경로는 ``current_user`` 단독 —
  PIPA Art.35 정보주체 권리 (해지권/이력 조회는 동의 철회와 독립).
- ``Idempotency-Key`` UUID v4 형식 강제 + race-free SELECT-INSERT-CATCH-SELECT
  (Story 2.5 ``meals.py`` SOT 1:1 정합).
- ``raw_text``/``image_key`` 같은 PII 미포함 — 본 라우터는 ``payment_key``/``order_id``/
  ``amount`` 만 받으므로 NFR-S5 마스킹 부담 낮음.
- ``orderId`` Toss 표준 alias — 클라이언트가 camelCase 송신, 서버는 snake_case 처리.
- RFC 7807 ``application/problem+json`` 글로벌 핸들러가 자동 변환.

Story 6.2 추가:
- cancel은 *DB-only* 전이(Toss API 호출 X — Story 6.1 baseline은 1회 결제 + billing
  key 미발급으로 자동 갱신 자체가 없음). epics.md:852 *"즉시 차단 X — 다음 결제일까지 활성"*.
- ``GET /subscription`` contract 변경 — ``status.in_(['active', 'cancelled'])`` AND
  ``(expires_at IS NULL OR expires_at > now())`` 1차 조회. cancelled-but-not-expired
  케이스도 200 반환(Story 6.1 deferred UX gap 흡수).
- ``GET /history``는 ``(occurred_at, id)`` 복합 row-value compare base64 cursor pagination.

scope 분리: webhook(자동 갱신) / 환불 자동화는 Story 6.3 forward.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Final, Literal

import structlog
from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from app.api.deps import DbSession, current_user, require_basic_consents
from app.core.exceptions import (
    NoActiveSubscriptionError,
    PaymentIdempotencyKeyInvalidError,
)
from app.db.models.payment_log import PaymentLog
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.services import payment_service

logger = structlog.get_logger(__name__)

router = APIRouter()


# Story 2.5 ``_IDEMPOTENCY_KEY_PATTERN`` SOT 1:1 정합 — UUID v4 regex + 길이 36.
# payments-specific 헬퍼 분리(``MealIdempotencyKeyInvalidError``와 catalog code 분리).
_IDEMPOTENCY_KEY_PATTERN: Final[str] = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_IDEMPOTENCY_KEY_REGEX: Final[re.Pattern[str]] = re.compile(_IDEMPOTENCY_KEY_PATTERN)
_IDEMPOTENCY_KEY_LENGTH: Final[int] = 36


def _validate_payment_idempotency_key(key: str | None) -> str | None:
    """``Idempotency-Key`` 헤더 형식 검증 + 정규화 (Story 2.5 SOT 1:1 정합).

    None / 빈 / 공백 패딩 → ``None`` 반환 (미송신과 동등). 비공백 패딩 후 형식 위반은
    ``PaymentIdempotencyKeyInvalidError(400)`` raise.

    Story 2.5 ``_validate_idempotency_key``와 동일 검증 로직이지만, *catalog code prefix*
    (``payments.*`` vs ``meals.*``)와 *후속 분기 차이* 때문에 함수 분리 (DF49 갱신 결정).
    """
    if key is None:
        return None
    stripped = key.strip()
    if not stripped:
        return None
    if len(stripped) != _IDEMPOTENCY_KEY_LENGTH or not _IDEMPOTENCY_KEY_REGEX.match(stripped):
        raise PaymentIdempotencyKeyInvalidError(
            "Idempotency-Key must be a valid UUID v4 (RFC 4122)"
        )
    return stripped


# --- Pydantic 스키마 ---------------------------------------------------------


class SubscribeRequest(BaseModel):
    """``POST /v1/payments/subscribe`` body — Toss 표준 camelCase alias 정합.

    클라이언트(Web Toss widget success callback)가 ``paymentKey``/``orderId``/``amount`` 송신.
    서버는 snake_case로 처리. ``model_config.populate_by_name=True``로 양방향 호환.

    ``extra="forbid"`` — silent unknown field 차단 (Story 1.4/2.x 패턴).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # Toss ``paymentKey``는 결제 식별자 — 36+자(Toss 표준).
    payment_key: str = Field(min_length=1, max_length=200, alias="paymentKey")
    # ``orderId``는 클라이언트 생성 UUID v4 권장(Toss 측 멱등 dedup 보조). 64자 cap.
    order_id: str = Field(min_length=1, max_length=64, alias="orderId")
    # KRW integer — 0 이하 차단 + 1억원 cap(과도한 클라이언트 입력 차단).
    amount: int = Field(ge=1, le=100_000_000)


class SubscriptionResponse(BaseModel):
    """``subscriptions`` row의 wire shape — ``provider_billing_key`` 응답 미포함
    (Toss billing key는 server-only 보안 정합).
    """

    id: uuid.UUID
    user_id: uuid.UUID
    status: Literal["active", "cancelled", "expired"]
    plan: Literal["monthly"]
    plan_price_krw: int
    started_at: datetime
    expires_at: datetime | None
    cancelled_at: datetime | None
    provider: Literal["toss", "stripe"]
    created_at: datetime


class PaymentLogResponse(BaseModel):
    """``payment_logs`` row의 wire shape — ``raw_payload``/``provider_payment_key`` 응답
    미포함 (PII / 머천트 식별자 보호).

    클라이언트가 영수증 표시에 필요한 *결제 시점 + 금액 + 상태*만 노출.
    """

    id: uuid.UUID
    event_type: Literal["subscribe", "cancel", "renew", "failed", "refund"]
    status: Literal["success", "failed", "pending"]
    amount_krw: int
    occurred_at: datetime
    provider: Literal["toss", "stripe"]


class SubscribeResponse(BaseModel):
    """``POST /v1/payments/subscribe`` 응답 wrapper — subscription + 1차 결제 log."""

    subscription: SubscriptionResponse
    payment: PaymentLogResponse


# --- Story 6.2 — cancel + history schemas ----------------------------------


class CancelSubscriptionRequest(BaseModel):
    """``POST /v1/payments/cancel`` body — 본문 0필드 (UI에서 명시 확인 처리).

    forward-compat — 향후 ``reason: str`` 추가 시 필드 추가만으로 확장. ``extra="forbid"``
    로 silent unknown field 차단(Story 1.4/2.x 패턴 정합).
    """

    model_config = ConfigDict(extra="forbid")


class CancelSubscriptionResponse(BaseModel):
    """``POST /v1/payments/cancel`` 응답 wrapper — cancelled subscription + cancel audit log."""

    subscription: SubscriptionResponse
    payment: PaymentLogResponse


class PaymentHistoryItem(BaseModel):
    """``GET /v1/payments/history`` row wire shape — ``PaymentLogResponse`` baseline +
    ``receipt_url`` 추출(Toss 표준 응답 ``raw_payload['receipt']['url']``).

    영수증 URL 부재 시 None(cancel/failed event는 일반적으로 receipt 부재).
    """

    id: uuid.UUID
    event_type: Literal["subscribe", "cancel", "renew", "failed", "refund"]
    status: Literal["success", "failed", "pending"]
    amount_krw: int
    occurred_at: datetime
    provider: Literal["toss", "stripe"]
    receipt_url: str | None


class PaymentHistoryResponse(BaseModel):
    """``GET /v1/payments/history`` page 응답 — items + opaque cursor.

    ``next_cursor=None``이면 마지막 페이지. 클라이언트는 cursor를 *opaque*로 취급
    (파싱 X — 그대로 다음 호출 ``?cursor=...`` 파라미터에 전달).
    """

    items: list[PaymentHistoryItem]
    next_cursor: str | None


def _subscription_to_response(subscription: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=subscription.id,
        user_id=subscription.user_id,
        status=subscription.status,
        plan=subscription.plan,
        plan_price_krw=subscription.plan_price_krw,
        started_at=subscription.started_at,
        expires_at=subscription.expires_at,
        cancelled_at=subscription.cancelled_at,
        provider=subscription.provider,
        created_at=subscription.created_at,
    )


def _payment_log_to_response(log: PaymentLog) -> PaymentLogResponse:
    return PaymentLogResponse(
        id=log.id,
        event_type=log.event_type,
        status=log.status,
        amount_krw=log.amount_krw,
        occurred_at=log.occurred_at,
        provider=log.provider,
    )


def _payment_log_to_history_item(log: PaymentLog) -> PaymentHistoryItem:
    """``PaymentLog`` → ``PaymentHistoryItem`` — ``receipt_url`` 추출 포함.

    ``_payment_log_to_response``와 *분리* — ``subscribe`` endpoint 응답은 ``receipt_url``
    없는 baseline 유지(스코프 분리). history endpoint만 영수증 URL 노출.

    Toss는 ``status='success'``인 결제에만 영수증 URL을 발급. defense in depth로
    실패/대기 row의 ``receipt_url``은 서버에서 ``None``으로 마스킹 — 클라이언트 status
    필터에 의존하지 않게 (모바일/웹 모두 안전).
    """
    receipt_url = (
        payment_service._extract_receipt_url(log.raw_payload) if log.status == "success" else None
    )
    return PaymentHistoryItem(
        id=log.id,
        event_type=log.event_type,
        status=log.status,
        amount_krw=log.amount_krw,
        occurred_at=log.occurred_at,
        provider=log.provider,
        receipt_url=receipt_url,
    )


# --- Endpoints -------------------------------------------------------------


@router.post(
    "/subscribe",
    status_code=status.HTTP_201_CREATED,
    response_model=SubscribeResponse,
    responses={
        # CR P7 — replay 200도 ``SubscribeResponse`` body 반환을 OpenAPI에 명시(generated
        # TS 클라이언트가 200 응답에서도 subscription/payment 필드를 typed로 인식).
        200: {
            "description": "Idempotent replay (same Idempotency-Key)",
            "model": SubscribeResponse,
        },
        400: {
            "description": (
                "Validation failed / Idempotency-Key invalid / amount mismatch / payment rejected"
            )
        },
        409: {
            "description": (
                "Subscription already active / previous payment failed (use new Idempotency-Key)"
            )
        },
        502: {"description": "Toss provider unavailable / payload invalid"},
        503: {"description": "Toss secret key not configured"},
    },
)
async def subscribe(
    body: SubscribeRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubscribeResponse:
    """정기결제 신청 — Toss API confirm + DB row 작성 (race-free 멱등 처리).

    ``Idempotency-Key`` 헤더 송신 시 같은 키 재송신은 ``200 OK`` 응답 (RFC 9110
    idempotent retry — resource는 이미 존재). 첫 INSERT는 그대로 ``201 Created``.

    오류 매핑(RFC 7807 ``application/problem+json``):
    - 400 ``code=payments.idempotency_key.invalid`` — UUID v4 형식 위반.
    - 400 ``code=payments.amount.invalid`` — ``amount != 9900``.
    - 400 ``code=payments.confirm_failed`` — Toss 카드 거절 / 한도 초과.
    - 409 ``code=payments.subscription.already_active`` — 기존 active 사용자.
    - 409 ``code=payments.idempotency_key.retry_after_failed`` — 같은 키로 직전 결제가
      실패 audit log된 상태에서 재시도 (CR P1 — 새 ``Idempotency-Key`` 발급 후 재호출).
    - 502 ``code=payments.provider.unavailable`` — Toss 5xx + retry 후 실패.
    - 502 ``code=payments.provider.payload_invalid`` — Toss 응답 amount/orderId mismatch.
    - 503 ``code=payments.toss.secret_key_missing`` — fail-fast.
    """
    # Story 2.5 패턴 — Idempotency-Key 형식 검증 + 정규화. 빈/공백 헤더는 미송신과 등가.
    validated_key = _validate_payment_idempotency_key(idempotency_key)

    subscription, payment_log, was_replay = await payment_service.subscribe(
        db,
        user_id=user.id,
        payment_key=body.payment_key,
        order_id=body.order_id,
        amount=body.amount,
        idempotency_key=validated_key,
    )

    await db.commit()

    # RFC 9110 정합 — replay는 200, 신규는 201.
    response.status_code = status.HTTP_200_OK if was_replay else status.HTTP_201_CREATED

    return SubscribeResponse(
        subscription=_subscription_to_response(subscription),
        payment=_payment_log_to_response(payment_log),
    )


@router.get(
    "/subscription",
    status_code=status.HTTP_200_OK,
    response_model=SubscriptionResponse,
    responses={
        200: {"description": "Active or cancelled-but-not-expired subscription found"},
        404: {"description": "No active subscription"},
    },
)
async def get_subscription(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> SubscriptionResponse:
    """자기 *유효* 구독 단일 조회 — PIPA Art.35 정합 (``current_user`` 단독, 동의 게이트 X).

    Story 6.2 contract 변경 (Story 6.1 deferred ``cancelled-but-not-expired`` UX gap 흡수):
    - ``status='active'`` 또는 ``status='cancelled' AND expires_at > now()`` 1차 조회.
    - ``expired`` row는 항상 미반환(과거 구독 — 신규 신청 가능 케이스 → 404).

    클라이언트는 ``status === "cancelled"`` 분기로 *"해지됨 — {expires_at}까지 이용 가능"*
    표시.

    오류:
    - 404 ``code=payments.subscription.not_found`` — 유효 구독 0건 (미신청 또는 expired만
      존재).
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            or_(
                Subscription.status == "active",
                # cancelled-but-not-expired는 *유효* 구독으로 노출 (Story 6.2 AC2).
                (Subscription.status == "cancelled") & (Subscription.expires_at > now),
            ),
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise NoActiveSubscriptionError("활성 구독이 없습니다")

    return _subscription_to_response(subscription)


@router.post(
    "/cancel",
    status_code=status.HTTP_200_OK,
    response_model=CancelSubscriptionResponse,
    responses={
        200: {"description": "Subscription cancelled (active until expires_at)"},
        404: {"description": "No active subscription"},
        409: {"description": "Subscription already cancelled"},
    },
)
async def cancel_subscription(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    body: CancelSubscriptionRequest = CancelSubscriptionRequest(),  # noqa: B008
) -> CancelSubscriptionResponse:
    """구독 해지 — DB-only ``status='cancelled'`` + cancel audit log INSERT.

    PIPA Art.35 정합 — ``current_user`` 단독(``require_basic_consents`` 미적용). *해지권은
    동의 철회와 독립*된 약관 명시 사용자 권리(epics.md:847).

    epics.md:852 invariant — *"즉시 차단 X — 다음 결제일까지 활성"*. ``expires_at`` 변경 0,
    Toss API cancel 호출 X. webhook(Story 6.3)이 ``expires_at`` 도래 시 ``status='expired'``
    전이.

    오류:
    - 404 ``code=payments.subscription.not_found`` — 활성 구독 0건 (미신청 또는 expired만).
    - 409 ``code=payments.subscription.already_cancelled`` — 이미 cancelled-but-not-expired.

    응답:
    - 200 — 신규 cancellation. ``status_code=200``(상태 전이 — RFC 9110 정합, 신규 리소스
      생성 아니라 201 X).
    """
    # ``body``는 forward-compat placeholder — 본 스토리는 0필드. lint 회피 명시 참조.
    _ = body

    subscription, cancel_log = await payment_service.cancel_subscription(db, user_id=user.id)
    await db.commit()

    return CancelSubscriptionResponse(
        subscription=_subscription_to_response(subscription),
        payment=_payment_log_to_response(cancel_log),
    )


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=PaymentHistoryResponse,
    responses={
        200: {"description": "Payment history page (most-recent-first)"},
        400: {"description": "Invalid cursor"},
    },
)
async def get_payment_history(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> PaymentHistoryResponse:
    """결제 이력 cursor pagination — ``(occurred_at DESC, id DESC)`` 정렬.

    PIPA Art.35 정합 — ``current_user`` 단독. 자기 결제 이력 조회는 동의 철회와 독립.

    cursor 부재 → 1페이지(최신 ``limit``건). cursor 송신 → 다음 페이지. ``next_cursor=None``
    이면 마지막 페이지. 클라이언트는 cursor를 *opaque*로 취급.

    오류:
    - 400 ``code=payments.history.cursor.invalid`` — cursor 형식 위반.
    - 422 — ``limit`` 또는 ``cursor`` Pydantic 검증 실패(``ge=1``/``le=50``/``max_length=200``).
    """
    # 빈 문자열 cursor (?cursor=) → 1페이지로 정규화 (decode 실패 400 회피).
    items, next_cursor = await payment_service.list_payment_history(
        db,
        user_id=user.id,
        limit=limit,
        cursor=cursor or None,
    )

    return PaymentHistoryResponse(
        items=[_payment_log_to_history_item(log) for log in items],
        next_cursor=next_cursor,
    )
