"""Payment service — Story 6.1 / 6.2 (정기결제 sandbox 신청 + 해지 + 결제 이력 조회).

Epic 6 결제 도메인 비즈니스 로직 SOT. ``app/api/v1/payments.py`` 라우터가 본 모듈을
호출 → (subscribe) Toss adapter ``confirm_payment`` 호출 → ``subscriptions``/``payment_
logs`` 양 row INSERT, 또는 (cancel) DB-only ``status='cancelled'`` 전이, 또는 (history)
``payment_logs`` 시계열 page 조회. architecture.md:704 *"`payment_service.py` (가설)"* 정합.

3 SOT 패턴:
1. **Idempotency-Key SOT** — Story 2.5 ``meals.py:_create_meal_idempotent_or_replay``
   race-free SELECT-INSERT-CATCH-SELECT 1:1 정합. ``_subscribe_idempotent_or_replay``
   헬퍼.
2. **RFC 7807 SOT** — adapter 레벨 예외(``PaymentProviderRejectedError``) → service 레벨
   변환(``PaymentConfirmFailedError`` 단일 사용자 코드).
3. **Sentry capture SOT** — Story 3.6 ``LLMRouterExhaustedError`` 패턴 정합. service
   레이어에서 ``sentry_sdk.capture_message("payment.confirm_failed")`` 명시 호출
   (운영 모니터링 명시 신호 — 카드 거절 빈도 abnormal 시 dashboard alert).

Story 6.2 추가 흐름:
- ``cancel_subscription`` — DB-only 해지 (Toss API cancel 호출 X — Story 6.1 baseline은
  1회 결제 + billing key 미발급으로 자동 갱신 자체가 없음). cancel audit ``payment_log``
  row 1건 INSERT(``event_type='cancel'`` + ``amount_krw=0``).
- ``list_payment_history`` — ``(occurred_at, id)`` 복합 row-value compare base64 cursor
  pagination. 인덱스 ``idx_payment_logs_user_id_occurred_at`` hit.
- ``_extract_receipt_url`` — ``raw_payload['receipt']['url']`` ``https://``/``http://``
  prefix 검증 (XSS hardening).

스코프: webhook(자동 갱신) / 환불 자동화는 Story 6.3 forward.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import sentry_sdk
import structlog
from pydantic import ValidationError
from sqlalchemy import insert, literal, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import toss as toss_adapter
from app.core.exceptions import (
    BalanceNoteError,
    NoActiveSubscriptionError,
    PaymentAmountInvalidError,
    PaymentConfirmFailedError,
    PaymentHistoryCursorInvalidError,
    PaymentProviderRejectedError,
    PaymentRetryAfterFailedError,
    SubscriptionAlreadyActiveError,
    SubscriptionAlreadyCancelledError,
    WebhookPayloadInvalidError,
)
from app.db.models.payment_log import PaymentLog
from app.db.models.subscription import Subscription

logger = structlog.get_logger(__name__)

# epics.md:832 *"월 9,900원"* literal SOT. 가격 변경 = 코드 PR + review 의무
# (환경 변수로 빼면 staging/prod 운영 사고 가능성).
MONTHLY_PLAN_PRICE_KRW: Final[int] = 9900

# ``expires_at = started_at + timedelta(days=30)`` 계산 SOT — Story 6.3 webhook이
# 갱신 시점에 동일 상수 참조.
MONTHLY_PLAN_PERIOD_DAYS: Final[int] = 30

# CR P3 (Story 2.5 정합) — partial UNIQUE 위반 catch를 인덱스 이름으로 한정. FK/CHECK
# 위반 등 비-멱등 IntegrityError를 잘못된 replay path로 진입시키지 않기 위함. DB-side
# 인덱스 이름은 마이그레이션 0018/0019와 동기 — 인덱스 rename 시 본 상수도 갱신 필수.
_IDEMPOTENCY_INDEX_NAME: Final[str] = "idx_payment_logs_user_id_idempotency_key_unique"
# Story 6.1 CR P2 — subscription active partial UNIQUE catch는 ``SubscriptionAlready
# ActiveError(409)``로 변환(race 진입 케이스). 인덱스 이름은 0018 마이그레이션과 동기.
_SUBSCRIPTION_ACTIVE_INDEX_NAME: Final[str] = "idx_subscriptions_user_id_active_unique"

# Story 6.3 — alembic 0020 composite UNIQUE 인덱스 이름. webhook INSERT 시 같은
# ``(provider, provider_payment_key, event_type)`` 충돌 catch 분기 SOT.
_PROVIDER_KEY_EVENT_TYPE_INDEX_NAME: Final[str] = (
    "idx_payment_logs_provider_payment_key_event_type_unique"
)


def _mask_user_id(user_id: uuid.UUID) -> str:
    """NFR-S5 정합 — user_id를 8자리 prefix만 노출."""
    return f"u_{str(user_id)[:8]}"


async def _fetch_active_subscription(
    session: AsyncSession, *, user_id: uuid.UUID
) -> Subscription | None:
    """현재 active subscription 1건 조회 — partial UNIQUE invariant로 0/1건 보장."""
    result = await session.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def _fetch_payment_log_by_idempotency_key(
    session: AsyncSession, *, user_id: uuid.UUID, idempotency_key: str
) -> PaymentLog | None:
    """``idempotency_key`` 1차 조회 — replay 분기 진입 신호.

    Story 6.1 CR P1 — ``event_type`` 필터 제거. ``payment_logs.idempotency_key`` partial
    UNIQUE가 (user_id, idempotency_key) 단일 row만 허용하므로 본 SELECT는 항상 0/1건.
    호출자가 ``event_type``으로 분기(``subscribe`` → 정상 replay, ``failed`` →
    ``PaymentRetryAfterFailedError(409)``).
    """
    result = await session.execute(
        select(PaymentLog).where(
            PaymentLog.user_id == user_id,
            PaymentLog.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def _fetch_subscription_for_log(
    session: AsyncSession, *, log: PaymentLog
) -> Subscription | None:
    """replay 분기 — 기존 payment_log의 subscription_id로 subscription 조회."""
    if log.subscription_id is None:
        return None
    result = await session.execute(
        select(Subscription).where(Subscription.id == log.subscription_id)
    )
    return result.scalar_one_or_none()


async def _insert_subscription_and_payment_log(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    toss_response: toss_adapter.TossConfirmResponse,
    amount: int,
    idempotency_key: str | None,
    started_at: datetime,
) -> tuple[Subscription, PaymentLog]:
    """양 row INSERT — 동일 트랜잭션. UNIQUE 위반은 호출 측에서 catch."""
    expires_at = started_at + timedelta(days=MONTHLY_PLAN_PERIOD_DAYS)
    subscription_result = await session.execute(
        insert(Subscription)
        .values(
            user_id=user_id,
            status="active",
            plan="monthly",
            plan_price_krw=MONTHLY_PLAN_PRICE_KRW,
            started_at=started_at,
            expires_at=expires_at,
            provider="toss",
        )
        .returning(Subscription)
    )
    subscription = subscription_result.scalar_one()

    masked_payload = toss_adapter._mask_payment_payload(toss_response.raw)
    log_result = await session.execute(
        insert(PaymentLog)
        .values(
            user_id=user_id,
            subscription_id=subscription.id,
            event_type="subscribe",
            provider="toss",
            provider_payment_key=toss_response.payment_key,
            provider_order_id=toss_response.order_id,
            amount_krw=amount,
            status="success",
            idempotency_key=idempotency_key,
            raw_payload=masked_payload,
            occurred_at=toss_response.approved_at,
        )
        .returning(PaymentLog)
    )
    payment_log = log_result.scalar_one()
    return subscription, payment_log


async def _insert_failed_payment_log(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    payment_key: str,
    order_id: str,
    amount: int,
    idempotency_key: str | None,
    failure_reason: str,
) -> bool:
    """결제 실패 시 audit-trail 1건 INSERT — ``subscription_id=NULL`` (구독 row 미생성).

    Returns ``True``이면 INSERT 성공, ``False``이면 같은 ``idempotency_key``로 이미 failed
    log가 존재해 INSERT 차단(CR P1 멱등 invariant — 같은 키 재시도는 추가 row 작성 없이
    같은 응답 의미론).
    """
    try:
        await session.execute(
            insert(PaymentLog).values(
                user_id=user_id,
                subscription_id=None,
                event_type="failed",
                provider="toss",
                provider_payment_key=payment_key or None,
                provider_order_id=order_id or None,
                amount_krw=amount,
                status="failed",
                idempotency_key=idempotency_key,
                raw_payload={"failure_reason": failure_reason},
                occurred_at=datetime.now(UTC),
            )
        )
    except IntegrityError as exc:
        # CR P1 — 같은 키로 이미 failed log가 있으면 중복 INSERT 시도 무시(멱등).
        if idempotency_key is not None and _IDEMPOTENCY_INDEX_NAME in str(exc.orig):
            await session.rollback()
            return False
        raise
    return True


async def _subscribe_idempotent_or_replay(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    payment_key: str,
    order_id: str,
    amount: int,
    idempotency_key: str | None,
) -> tuple[Subscription, PaymentLog, bool]:
    """Race-free SELECT-INSERT-CATCH-SELECT 패턴 (Story 2.5 SOT 1:1 정합).

    Returns ``(subscription, payment_log, was_replay)``. ``was_replay=True``이면
    라우터가 200 OK로 응답 분기(RFC 9110 idempotent retry).

    흐름:
    1. ``idempotency_key`` None → 정상 흐름 (active 가드 + Toss + INSERT).
    2. 헤더 송신 시 1차 SELECT — 기존 ``payment_log`` hit 시 ``(existing_subscription,
       existing_log, True)`` 반환 (Toss 호출 X).
    3. miss 시 정상 흐름 진입. INSERT 시점에 race 충돌(다른 worker가 동시 INSERT)이면
       UNIQUE 위반 catch + 재 SELECT → ``(_, _, True)`` 반환.

    soft-delete 분기는 *부재* — payment_logs는 audit-trail 성격이라 영구 보존
    (``Meal._create_meal_idempotent_or_replay``의 ``MealIdempotencyKeyConflictDeletedError``
    분기는 본 도메인에 없음).
    """
    # 1차 SELECT — replay 분기 신호. Story 6.1 CR P1 — failed 이력도 검출 대상.
    if idempotency_key is not None:
        existing_log = await _fetch_payment_log_by_idempotency_key(
            session, user_id=user_id, idempotency_key=idempotency_key
        )
        if existing_log is not None:
            if existing_log.event_type == "failed":
                # CR P1 — 직전 결제 실패 audit log가 같은 키로 존재. 같은 키 재시도는
                # ``payment_logs.idempotency_key`` UNIQUE에 막혀 INSERT 불가 — 사용자에게
                # 새 키 발급 요청. 클라이언트는 새 ``crypto.randomUUID()``로 재호출.
                raise PaymentRetryAfterFailedError(
                    "이전 결제가 실패했습니다 — 새 결제로 다시 시도해 주세요"
                )
            existing_subscription = await _fetch_subscription_for_log(session, log=existing_log)
            if existing_subscription is None:
                # subscription_id가 SET NULL 처리됐거나 (FK cascade) — 비정상 상태.
                # 5xx fallback (BalanceNoteError default 500).
                raise BalanceNoteError(
                    "idempotent replay: payment_log exists but subscription not found"
                )
            return existing_subscription, existing_log, True

    # 2차 — active subscription 중복 가드 (replay 진입 X 케이스).
    active = await _fetch_active_subscription(session, user_id=user_id)
    if active is not None:
        raise SubscriptionAlreadyActiveError(
            "이미 활성 구독이 있습니다 — 해지 후 다시 신청해 주세요"
        )

    # 3차 — Toss API 호출 (실패 분기는 호출 측 service 함수가 처리).
    toss_response = await toss_adapter.confirm_payment(
        payment_key=payment_key,
        order_id=order_id,
        amount=amount,
    )

    # 4차 — 양 row INSERT. INSERT 시점에 partial UNIQUE 충돌 race 차단.
    started_at = datetime.now(UTC)
    try:
        subscription, payment_log = await _insert_subscription_and_payment_log(
            session,
            user_id=user_id,
            toss_response=toss_response,
            amount=amount,
            idempotency_key=idempotency_key,
            started_at=started_at,
        )
    except IntegrityError as exc:
        # CR P2 — 인덱스 이름으로 분기. ``idempotency_key`` UNIQUE는 replay race
        # 회복(존재하던 row를 재조회). ``subscription`` active UNIQUE는 동시 신청 race
        # 진입 신호로 ``SubscriptionAlreadyActiveError(409)``. 그 외 IntegrityError(FK/
        # CHECK 등)는 비정상 상태이므로 그대로 propagate.
        exc_str = str(exc.orig)
        if idempotency_key is not None and _IDEMPOTENCY_INDEX_NAME in exc_str:
            # Race recovery: rollback 후 재조회. 본 함수 진입 시점에 caller transaction
            # 내 *별도 write*는 없음(라우터의 current_user는 SELECT only) → rollback이
            # 잃을 caller 작업 없음 (CR EH-7 dismiss).
            await session.rollback()
            replay_log = await _fetch_payment_log_by_idempotency_key(
                session, user_id=user_id, idempotency_key=idempotency_key
            )
            if replay_log is None:
                raise BalanceNoteError(
                    "idempotent replay race resolution failed (no row found after IntegrityError)"
                ) from None
            if replay_log.event_type == "failed":
                # 다른 worker가 같은 키로 failed log INSERT — 같은 응답 의미론.
                raise PaymentRetryAfterFailedError(
                    "이전 결제가 실패했습니다 — 새 결제로 다시 시도해 주세요"
                ) from None
            replay_subscription = await _fetch_subscription_for_log(session, log=replay_log)
            if replay_subscription is None:
                raise BalanceNoteError(
                    "idempotent replay race: payment_log found but subscription missing"
                ) from None
            return replay_subscription, replay_log, True
        if _SUBSCRIPTION_ACTIVE_INDEX_NAME in exc_str:
            # 동시 2건 subscribe race — 두 worker가 모두 active 가드 SELECT를 통과한 뒤
            # 두 번째가 partial UNIQUE에 걸린 상황. 9900원이 이미 결제됐을 가능성이 있어
            # 운영 sentry 신호 명시(refund 수동 처리 hint).
            await session.rollback()
            logger.error(
                "payments.subscribe.subscription_active_race",
                user_id=_mask_user_id(user_id),
                payment_key_prefix=payment_key[:8] if payment_key else "",
                order_id=order_id,
            )
            raise SubscriptionAlreadyActiveError(
                "이미 활성 구독이 있습니다 — 해지 후 다시 신청해 주세요"
            ) from None
        raise

    return subscription, payment_log, False


async def subscribe(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    payment_key: str,
    order_id: str,
    amount: int,
    idempotency_key: str | None,
) -> tuple[Subscription, PaymentLog, bool]:
    """결제 신청 비즈니스 로직 SOT.

    Returns ``(subscription, payment_log, was_replay)``. 라우터가 ``was_replay``로 200
    /201 분기.

    오류 분기:
    - ``amount != 9900`` → ``PaymentAmountInvalidError(400)`` (Toss 호출 X).
    - 기존 active 사용자 → ``SubscriptionAlreadyActiveError(409)`` (Toss 호출 X).
    - Toss 4xx 카드 거절 → *failed payment_log 1건 INSERT* + ``PaymentConfirmFailedError
      (400)``. Sentry ``capture_message("payment.confirm_failed")`` 명시 호출.
    - Toss 5xx → ``PaymentProviderUnavailableError(502)`` 그대로 propagate (DB row 0건).
    - ``TossSecretKeyMissingError(503)`` → 그대로 propagate.

    commit은 라우터 책임 — 본 함수는 INSERT만 (부분 commit 차단).
    """
    # Step 1 — input 검증 (race attack 방어 + epics.md:841 KRW integer invariant).
    if amount != MONTHLY_PLAN_PRICE_KRW:
        logger.warning(
            "payments.subscribe.amount_mismatch",
            user_id=_mask_user_id(user_id),
            expected=MONTHLY_PLAN_PRICE_KRW,
            received=amount,
        )
        raise PaymentAmountInvalidError(
            f"결제 금액이 플랜 금액과 일치하지 않습니다 "
            f"(예상 {MONTHLY_PLAN_PRICE_KRW}, 수신 {amount})"
        )

    logger.info(
        "payments.subscribe.requested",
        user_id=_mask_user_id(user_id),
        order_id=order_id,
        amount=amount,
    )

    # Step 2-5 — Idempotency replay → active 가드 → Toss → INSERT (race-free helper).
    try:
        subscription, payment_log, was_replay = await _subscribe_idempotent_or_replay(
            session,
            user_id=user_id,
            payment_key=payment_key,
            order_id=order_id,
            amount=amount,
            idempotency_key=idempotency_key,
        )
    except PaymentProviderRejectedError as exc:
        # Toss 카드 거절 — failed payment_log 1건 INSERT (audit-trail) + 사용자 응답
        # 단일 코드(``payments.confirm_failed``)로 변환.
        # ─── CR D1 ratify (2026-05-08) ──────────────────────────────────────────
        # spec 라인 117-120 commit 책임 분기: *성공 경로*는 라우터 commit. *실패 경로*는
        # 본 라인의 서비스 commit 의무. 라우터가 ``PaymentConfirmFailedError``를 catch
        # 하지 않고 글로벌 핸들러로 propagate하면 ``get_db_session`` 의존성이 rollback을
        # 수행해 audit-trail row가 사라지므로, failed 경로 INSERT는 별도 트랜잭션 단위로
        # 영속화 의무. (CR P1) 같은 idempotency_key로 이미 failed log가 있으면 INSERT를
        # 멱등하게 skip(``inserted=False``) — 이 경우 commit 호출은 no-op이므로 안전.
        inserted = await _insert_failed_payment_log(
            session,
            user_id=user_id,
            payment_key=payment_key,
            order_id=order_id,
            amount=amount,
            idempotency_key=idempotency_key,
            failure_reason=str(exc),
        )
        if inserted:
            await session.commit()
        # epics.md:842 *"Sentry 자동 수집"* 정합 — 명시 capture_message로 운영 dashboard
        # alert 신호 (글로벌 핸들러 자동 capture와 별 layer).
        sentry_sdk.capture_message(
            "payment.confirm_failed",
            level="warning",
            scope=None,
        )
        logger.warning(
            "payments.subscribe.confirm_failed",
            user_id=_mask_user_id(user_id),
            order_id=order_id,
            reason=str(exc),
        )
        raise PaymentConfirmFailedError(str(exc)) from exc

    logger.info(
        "payments.subscribe.succeeded",
        user_id=_mask_user_id(user_id),
        subscription_id=str(subscription.id),
        was_replay=was_replay,
    )
    return subscription, payment_log, was_replay


# ---------------------------------------------------------------------------
# Story 6.2 — cancel_subscription (DB-only 해지 + cancel audit log INSERT)
# ---------------------------------------------------------------------------


async def cancel_subscription(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[Subscription, PaymentLog]:
    """구독 해지 — DB-only ``status='cancelled'`` 전이 + cancel audit ``payment_log`` 1건.

    epics.md:852 invariant — *"즉시 차단 X — 다음 결제일까지 활성"*. Toss API cancel
    호출 X (Story 6.1 baseline은 1회 결제 + billing key 미발급으로 자동 갱신 없음).
    ``expires_at`` 변경 0 — webhook(Story 6.3)이 도래 시 ``status='expired'`` 전이.

    분기:
    - active row → ``status='cancelled'`` + ``cancelled_at=now()`` UPDATE +
      cancel audit log INSERT → ``(cancelled_subscription, cancel_log)`` 반환.
    - active row 부재 + cancelled-but-not-expired row 존재 →
      ``SubscriptionAlreadyCancelledError(409)``.
    - active row 부재 + cancelled-but-not-expired row 부재 →
      ``NoActiveSubscriptionError(404)`` (expired만 존재 또는 완전 미신청).

    commit은 라우터 책임.
    """
    logger.info(
        "payments.cancel.requested",
        user_id=_mask_user_id(user_id),
    )

    # 단일 timestamp — ``cancelled_at`` 와 cancel audit log ``occurred_at`` 정합 (µs drift X).
    now = datetime.now(UTC)

    # Step 1 — atomic state transition. UPDATE ... WHERE status='active' RETURNING은
    # 동시 cancel 2건이 들어와도 한 트랜잭션만 row를 가져가므로 race-free
    # (이전 SELECT-then-UPDATE 패턴은 두 트랜잭션이 모두 active를 보고 중복 cancel
    # audit log를 INSERT할 수 있었음).
    update_stmt = (
        update(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
        .values(status="cancelled", cancelled_at=now)
        .returning(Subscription)
        .execution_options(synchronize_session="fetch")
    )
    update_result = await session.execute(update_stmt)
    active = update_result.scalar_one_or_none()

    if active is None:
        # 분기 — cancelled-but-not-expired row 존재 시 409, 그 외 404.
        result = await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == "cancelled",
                Subscription.expires_at > now,
            )
            .limit(1)
        )
        already_cancelled = result.scalar_one_or_none()
        if already_cancelled is not None:
            raise SubscriptionAlreadyCancelledError(
                "이미 해지되었습니다 — 다음 결제일까지 이용 가능합니다"
            )
        raise NoActiveSubscriptionError("활성 구독이 없습니다")

    # Step 2 — cancel audit log INSERT. ``occurred_at`` 도 위 ``now`` 재사용.
    log_result = await session.execute(
        insert(PaymentLog)
        .values(
            user_id=user_id,
            subscription_id=active.id,
            event_type="cancel",
            provider=active.provider,
            provider_payment_key=None,
            provider_order_id=None,
            amount_krw=0,
            status="success",
            idempotency_key=None,
            raw_payload={"reason": "user_initiated"},
            occurred_at=now,
        )
        .returning(PaymentLog)
    )
    cancel_log = log_result.scalar_one()

    logger.info(
        "payments.cancel.succeeded",
        user_id=_mask_user_id(user_id),
        subscription_id=str(active.id),
    )
    return active, cancel_log


# ---------------------------------------------------------------------------
# Story 6.2 — list_payment_history (cursor pagination + receipt URL 추출)
# ---------------------------------------------------------------------------

# cursor 인코딩 SOT — base64 + ``:`` 분리로 ``(occurred_at_iso, id)`` 쌍 영속화.
# 클라이언트는 cursor를 *opaque*로 취급(파싱 X — 그대로 다음 호출에 전달).
_CURSOR_SEPARATOR: Final[str] = ":"


def _encode_history_cursor(occurred_at: datetime, log_id: uuid.UUID) -> str:
    """``(occurred_at, id)`` → base64(``<isoformat>:<uuid>``) 인코딩.

    안정 정렬 invariant — ``occurred_at_iso``는 microsecond 정밀도 보존(``.isoformat()``).
    같은 ``occurred_at`` row가 다수일 때 ``id`` tie-breaker로 결정성 보장.
    """
    payload = f"{occurred_at.isoformat()}{_CURSOR_SEPARATOR}{log_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_history_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """base64 cursor → ``(occurred_at, id)`` 디코딩 + Pydantic-수준 형식 검증.

    형식 위반은 모두 ``PaymentHistoryCursorInvalidError(400)``로 변환. base64 디코드 실패,
    ``:`` 분리 실패, ``datetime.fromisoformat`` ValueError, ``uuid.UUID`` ValueError 모두
    동일 응답(클라이언트는 cursor를 *opaque*로 취급해야 하므로 세분화 불필요).
    """
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise PaymentHistoryCursorInvalidError(f"cursor base64 decode failed: {exc!r}") from exc

    # ISO 8601 datetime은 ``T``/``:``를 포함하므로 *마지막* ``:``로 분리(``rsplit``).
    # UUID hex 표기에는 ``:`` 미포함이라 충돌 없음.
    parts = decoded.rsplit(_CURSOR_SEPARATOR, 1)
    if len(parts) != 2:
        raise PaymentHistoryCursorInvalidError("cursor format invalid (separator missing)")

    occurred_at_str, id_str = parts
    try:
        occurred_at = datetime.fromisoformat(occurred_at_str)
    except ValueError as exc:
        raise PaymentHistoryCursorInvalidError(f"cursor occurred_at invalid: {exc!r}") from exc

    try:
        log_id = uuid.UUID(id_str)
    except ValueError as exc:
        raise PaymentHistoryCursorInvalidError(f"cursor id invalid: {exc!r}") from exc

    return occurred_at, log_id


def _extract_receipt_url(raw_payload: dict[str, Any] | None) -> str | None:
    """Toss raw_payload에서 ``receipt.url`` 추출 + XSS hardening.

    Toss 표준 응답은 ``receipt.url`` 필드에 ``"https://dashboard.tosspayments.com/receipt/..."``
    포맷의 영수증 URL 노출. ``_mask_payment_payload``가 ``receipt`` 키를 보존하므로 ``payment_
    logs.raw_payload``에 그대로 영속화됨.

    검증:
    - ``raw_payload`` None 또는 dict 아니면 None.
    - ``receipt`` 키 부재 또는 dict 아니면 None.
    - ``receipt.url`` str 아니면 None.
    - prefix가 ``https://`` 또는 ``http://``가 아니면 None (``javascript:`` / ``data:`` URL
      차단 — 클라이언트 ``Linking.openURL`` / ``<a href>`` 클릭 시 XSS 방어).
    """
    if not isinstance(raw_payload, dict):
        return None
    receipt = raw_payload.get("receipt")
    if not isinstance(receipt, dict):
        return None
    url = receipt.get("url")
    if not isinstance(url, str):
        return None
    if not (url.startswith("https://") or url.startswith("http://")):
        return None
    return url


async def list_payment_history(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int,
    cursor: str | None,
) -> tuple[list[PaymentLog], str | None]:
    """결제 이력 cursor pagination — ``(occurred_at DESC, id DESC)`` 정렬.

    cursor 부재 → 1페이지(최신 ``limit``건). cursor 송신 → ``(occurred_at, id) <
    (cursor_occurred_at, cursor_id)`` 필터로 다음 페이지. ``len(rows) > limit`` 시 마지막
    row의 ``(occurred_at, id)``를 ``next_cursor``로 인코딩.

    인덱스: ``idx_payment_logs_user_id_occurred_at = (user_id, occurred_at DESC)`` hit
    (시계열 sort). ``id`` tie-breaker는 in-memory(드문 케이스라 비용 무시).

    오류:
    - cursor 형식 위반 → ``PaymentHistoryCursorInvalidError(400)``.
    """
    stmt = (
        select(PaymentLog)
        .where(PaymentLog.user_id == user_id)
        .order_by(PaymentLog.occurred_at.desc(), PaymentLog.id.desc())
        .limit(limit + 1)
    )

    if cursor is not None:
        cursor_occurred_at, cursor_id = _decode_history_cursor(cursor)
        # Postgres native row-value compare — ``(a, b) < (c, d)``는 ``a < c OR (a = c AND
        # b < d)`` 동등(SQL 표준). 인덱스 sort 정합. Python literal은 ``literal()``로 감싸
        # SQLAlchemy ColumnElement 타입 정합 (mypy stub 요구).
        stmt = stmt.where(
            tuple_(PaymentLog.occurred_at, PaymentLog.id)
            < tuple_(literal(cursor_occurred_at), literal(cursor_id))
        )

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    if len(rows) > limit:
        boundary = rows[limit - 1]
        next_cursor = _encode_history_cursor(boundary.occurred_at, boundary.id)
        items = rows[:limit]
    else:
        next_cursor = None
        items = rows

    return items, next_cursor


# ---------------------------------------------------------------------------
# Story 6.3 — webhook 처리 (renew/failed/refund + idempotency 다층 게이트)
# ---------------------------------------------------------------------------


async def _fetch_payment_log_by_idempotency_key_global(
    session: AsyncSession, *, idempotency_key: str
) -> PaymentLog | None:
    """``idempotency_key``만으로 SELECT — webhook은 ``user_id``를 미리 모름.

    *Why*: webhook event는 *DB-wide unique invariant 보장* — 별 namespace prefix
    (``toss:event:<event_id>``)로 충돌 가능성 0(같은 Toss event_id가 다른 사용자에 매핑되는
    케이스 부재). ``idx_payment_logs_user_id_idempotency_key_unique``는 ``(user_id,
    idempotency_key)`` 복합 UNIQUE이지만, namespace prefix 정합으로 정상 케이스 SELECT는
    0/1건. 다중 row 발견 시 *비정상 상태*(sentry error + 200 ack — 클라이언트 retry 무용).
    """
    result = await session.execute(
        select(PaymentLog)
        .where(PaymentLog.idempotency_key == idempotency_key)
        .order_by(PaymentLog.occurred_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _fetch_payment_log_by_provider_key_event_type(
    session: AsyncSession, *, provider: str, provider_payment_key: str, event_type: str
) -> PaymentLog | None:
    """0020 composite UNIQUE 위반 catch 후 replay row SELECT — webhook 분기 fallback."""
    result = await session.execute(
        select(PaymentLog)
        .where(
            PaymentLog.provider == provider,
            PaymentLog.provider_payment_key == provider_payment_key,
            PaymentLog.event_type == event_type,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _resolve_subscription_for_payment_key(
    session: AsyncSession, *, payment_key: str
) -> tuple[uuid.UUID, uuid.UUID | None] | None:
    """``data.payment_key`` → 첫 ``subscribe`` row의 ``user_id``/``subscription_id`` 결정.

    Returns ``(user_id, subscription_id)`` 또는 None(매칭 subscribe row 부재).
    """
    result = await session.execute(
        select(PaymentLog.user_id, PaymentLog.subscription_id)
        .where(
            PaymentLog.provider == "toss",
            PaymentLog.provider_payment_key == payment_key,
            PaymentLog.event_type == "subscribe",
        )
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    return row.user_id, row.subscription_id


async def _handle_renew_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subscription: Subscription | None,
    data: toss_adapter.TossWebhookPaymentData,
    event_body: toss_adapter.TossWebhookEventBody,
    key_used: str,
    now: datetime,
) -> PaymentLog:
    """renew(``PAYMENT.STATUS_CHANGED + DONE``) 처리 — ``expires_at +30일`` + audit row.

    분기:
    - subscription active → ``expires_at += 30d`` UPDATE + audit row.
    - subscription cancelled-but-not-expired → sentry error(*비정상 상태*) + audit row INSERT
      (``expires_at`` 변경 X, audit-trail은 보존 — Story 6.3 AC4 (a) invariant).
    - subscription expired/None → sentry warning + audit row INSERT(*subscription_id=NULL*).

    amount mismatch(``data.total_amount != MONTHLY_PLAN_PRICE_KRW``) →
    ``WebhookPayloadInvalidError(400)`` raise(race attack 방어).
    """
    if data.total_amount != MONTHLY_PLAN_PRICE_KRW:
        sentry_sdk.capture_message(
            "payments.webhook.amount_mismatch",
            level="warning",
        )
        logger.warning(
            "payments.webhook.amount_mismatch",
            user_id=_mask_user_id(user_id),
            expected=MONTHLY_PLAN_PRICE_KRW,
            received=data.total_amount,
        )
        raise WebhookPayloadInvalidError(
            f"webhook renew amount mismatch (expected {MONTHLY_PLAN_PRICE_KRW}, "
            f"received {data.total_amount})"
        )

    subscription_id_for_log: uuid.UUID | None = None
    if subscription is not None and subscription.status == "active":
        # 정상 renew — expires_at 갱신.
        subscription.expires_at = (subscription.expires_at or now) + timedelta(
            days=MONTHLY_PLAN_PERIOD_DAYS
        )
        subscription_id_for_log = subscription.id
    elif (
        subscription is not None
        and subscription.status == "cancelled"
        and subscription.expires_at is not None
        and subscription.expires_at > now
    ):
        # 비정상 — cancelled 구독에 자동 갱신 webhook 도래. audit-trail은 보존.
        sentry_sdk.capture_message(
            "payments.webhook.cancelled_subscription_renew",
            level="error",
        )
        logger.error(
            "payments.webhook.cancelled_subscription_renew",
            user_id=_mask_user_id(user_id),
            subscription_id=str(subscription.id),
        )
        subscription_id_for_log = subscription.id
    else:
        # expired / None 등 — audit-trail만 (subscription_id NULL).
        sentry_sdk.capture_message(
            "payments.webhook.renew_subscription_inactive",
            level="warning",
        )
        logger.warning(
            "payments.webhook.renew_subscription_inactive",
            user_id=_mask_user_id(user_id),
            subscription_status=(subscription.status if subscription else None),
        )

    masked_payload = toss_adapter._mask_payment_payload(event_body.data)
    log_result = await session.execute(
        insert(PaymentLog)
        .values(
            user_id=user_id,
            subscription_id=subscription_id_for_log,
            event_type="renew",
            provider="toss",
            provider_payment_key=data.payment_key,
            provider_order_id=data.order_id,
            amount_krw=data.total_amount,
            status="success",
            idempotency_key=key_used,
            raw_payload=masked_payload,
            occurred_at=data.approved_at or now,
        )
        .returning(PaymentLog)
    )
    return log_result.scalar_one()


async def _handle_failed_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    data: toss_adapter.TossWebhookPaymentData,
    event_body: toss_adapter.TossWebhookEventBody,
    key_used: str,
    now: datetime,
) -> PaymentLog:
    """``PAYMENT_FAILED`` (renew 실패) 처리 — subscription 변경 X + audit row.

    *"다음 시도까지 active 유지"* — 외주 클라이언트가 dunning 정책 결정. MVP는 audit log만.
    sentry warning(*"renew 실패 — dunning 정책 검토 필요"*).
    """
    sentry_sdk.capture_message(
        "payments.webhook.renew_failed",
        level="warning",
    )
    logger.warning(
        "payments.webhook.renew_failed",
        user_id=_mask_user_id(user_id),
        payment_key_prefix=data.payment_key[:8],
    )

    masked_payload = toss_adapter._mask_payment_payload(event_body.data)
    log_result = await session.execute(
        insert(PaymentLog)
        .values(
            user_id=user_id,
            subscription_id=None,  # 실패는 subscription 무관 audit.
            event_type="failed",
            provider="toss",
            provider_payment_key=data.payment_key,
            provider_order_id=data.order_id,
            amount_krw=data.total_amount,
            status="failed",
            idempotency_key=key_used,
            raw_payload=masked_payload,
            occurred_at=data.approved_at or now,
        )
        .returning(PaymentLog)
    )
    return log_result.scalar_one()


async def _handle_refund_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subscription_id: uuid.UUID | None,
    data: toss_adapter.TossWebhookPaymentData,
    event_body: toss_adapter.TossWebhookEventBody,
    key_used: str,
    now: datetime,
) -> PaymentLog:
    """``REFUND_COMPLETED`` / ``REFUND_PARTIAL`` 처리 — subscription 변경 X + audit row.

    즉시 환불은 OUT(Story 6.2 정합 + epics.md:825 *"PG 본 계약·세금정산은 OUT"*). 외주
    클라이언트가 자체 환불 정책 + Toss 환불 API 통합. 본 스토리는 audit-trail만.
    """
    masked_payload = toss_adapter._mask_payment_payload(event_body.data)
    log_result = await session.execute(
        insert(PaymentLog)
        .values(
            user_id=user_id,
            subscription_id=subscription_id,
            event_type="refund",
            provider="toss",
            provider_payment_key=data.payment_key,
            provider_order_id=data.order_id,
            amount_krw=data.total_amount,
            status="success",
            idempotency_key=key_used,
            raw_payload=masked_payload,
            occurred_at=data.approved_at or now,
        )
        .returning(PaymentLog)
    )
    return log_result.scalar_one()


async def handle_webhook_event(
    session: AsyncSession,
    *,
    event_body: toss_adapter.TossWebhookEventBody,
    idempotency_key: str | None,
) -> tuple[PaymentLog | None, bool]:
    """Toss webhook 처리 비즈니스 로직 SOT — Story 6.3 AC4.

    Returns ``(payment_log, was_replay)``:
    - ``payment_log=None``: 무시된 event (*활성 paymentKey 매칭 부재* 등 — *200 ack*).
    - ``was_replay=True``: 같은 idempotency_key로 이미 처리됨 (*Toss retry 정합*).

    *commit은 라우터 책임* — 본 함수는 INSERT/UPDATE만(부분 commit 차단).

    Idempotency 다층 게이트:
    1. body ``event_id`` namespace 정규화 (``toss:event:<event_id>``).
    2. Header ``Idempotency-Key`` 우선 (송신 시).
    3. 1차 SELECT (``payment_logs.idempotency_key``) → hit 시 replay 분기.
    4. INSERT 시점 ``idempotency_key`` UNIQUE 위반 catch → race recovery + replay.
    5. INSERT 시점 ``provider/payment_key/event_type`` composite UNIQUE 위반 catch →
       Toss retry 누락 케이스 fallback + replay.
    """
    # Step 1 — body sub-schema 검증 (event_type별 의미 분기 전 invariant 가드).
    try:
        data = toss_adapter.TossWebhookPaymentData.model_validate(event_body.data)
    except ValidationError as exc:
        raise WebhookPayloadInvalidError(f"webhook data sub-schema invalid: {exc}") from exc

    # Step 2 — idempotency key 결정. Header 우선, 미송신 시 body event_id namespace.
    if idempotency_key is not None:
        key_used = idempotency_key
    else:
        key_used = f"toss:event:{event_body.event_id}"

    logger.info(
        "payments.webhook.handle_event",
        event_type=event_body.event_type,
        event_id_prefix=event_body.event_id[:8],
        key_used_prefix=key_used[:16],
    )

    # Step 3 — 1차 SELECT (replay 분기).
    existing = await _fetch_payment_log_by_idempotency_key_global(session, idempotency_key=key_used)
    if existing is not None:
        logger.info(
            "payments.webhook.replay_detected",
            event_id_prefix=event_body.event_id[:8],
            payment_log_id=str(existing.id),
        )
        return existing, True

    # Step 4 — paymentKey로 user_id + subscription_id 결정 (subscribe row 의존).
    resolved = await _resolve_subscription_for_payment_key(session, payment_key=data.payment_key)
    if resolved is None:
        # *비정상 — subscribe row 부재 paymentKey*. 200 ack(Toss 재시도 회피).
        sentry_sdk.capture_message(
            "payments.webhook.subscribe_row_missing",
            level="warning",
        )
        logger.warning(
            "payments.webhook.subscribe_row_missing",
            event_id_prefix=event_body.event_id[:8],
            payment_key_prefix=data.payment_key[:8],
        )
        return None, False

    user_id, subscription_id = resolved
    now = datetime.now(UTC)

    # Step 5 — event_type 분기 + race-aware INSERT.
    try:
        if event_body.event_type == "PAYMENT.STATUS_CHANGED" and data.status == "DONE":
            subscription = (
                await session.get(Subscription, subscription_id) if subscription_id else None
            )
            payment_log = await _handle_renew_event(
                session,
                user_id=user_id,
                subscription=subscription,
                data=data,
                event_body=event_body,
                key_used=key_used,
                now=now,
            )
        elif event_body.event_type == "PAYMENT_FAILED":
            payment_log = await _handle_failed_event(
                session,
                user_id=user_id,
                data=data,
                event_body=event_body,
                key_used=key_used,
                now=now,
            )
        elif event_body.event_type in ("REFUND_COMPLETED", "REFUND_PARTIAL"):
            payment_log = await _handle_refund_event(
                session,
                user_id=user_id,
                subscription_id=subscription_id,
                data=data,
                event_body=event_body,
                key_used=key_used,
                now=now,
            )
        else:
            # Pydantic Literal로 1차 차단되므로 도달 불가(defensive 분기는 dead code 회피).
            sentry_sdk.capture_message(
                "payments.webhook.unsupported_event_type",
                level="error",
            )
            return None, False
    except IntegrityError as exc:
        exc_str = str(exc.orig)
        if _IDEMPOTENCY_INDEX_NAME in exc_str:
            # 동시 webhook 2건 race — 다른 worker가 같은 key로 INSERT. rollback + 재 SELECT.
            await session.rollback()
            replay_log = await _fetch_payment_log_by_idempotency_key_global(
                session, idempotency_key=key_used
            )
            if replay_log is None:
                raise BalanceNoteError(
                    "webhook idempotency replay race resolution failed"
                ) from None
            return replay_log, True
        if _PROVIDER_KEY_EVENT_TYPE_INDEX_NAME in exc_str:
            # Toss retry지만 우리 측 idempotency_key가 누락된 케이스(Toss 미일관 send).
            # 같은 (provider, payment_key, event_type) row 1건 SELECT → replay 분기.
            await session.rollback()
            sentry_sdk.capture_message(
                "payments.webhook.composite_unique_replay",
                level="warning",
            )
            event_type_for_replay = (
                "renew"
                if event_body.event_type == "PAYMENT.STATUS_CHANGED"
                else "failed"
                if event_body.event_type == "PAYMENT_FAILED"
                else "refund"
            )
            replay_log = await _fetch_payment_log_by_provider_key_event_type(
                session,
                provider="toss",
                provider_payment_key=data.payment_key,
                event_type=event_type_for_replay,
            )
            if replay_log is None:
                raise BalanceNoteError("webhook composite replay race resolution failed") from None
            return replay_log, True
        # 그 외 IntegrityError(FK/CHECK 등) — 비정상 상태, propagate.
        raise

    return payment_log, False
