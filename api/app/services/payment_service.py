"""Payment service — Story 6.1 (정기결제 sandbox 신청 + 1플랜 + Idempotency-Key 멱등).

Epic 6 결제 도메인 비즈니스 로직 SOT. ``app/api/v1/payments.py`` 라우터가 본 모듈을
호출 → Toss adapter ``confirm_payment`` 호출 → ``subscriptions``/``payment_logs`` 양 row
INSERT (동일 트랜잭션). architecture.md:704 *"`payment_service.py` (가설)"* 정합.

3 SOT 패턴:
1. **Idempotency-Key SOT** — Story 2.5 ``meals.py:_create_meal_idempotent_or_replay``
   race-free SELECT-INSERT-CATCH-SELECT 1:1 정합. ``_subscribe_idempotent_or_replay``
   헬퍼.
2. **RFC 7807 SOT** — adapter 레벨 예외(``PaymentProviderRejectedError``) → service 레벨
   변환(``PaymentConfirmFailedError`` 단일 사용자 코드).
3. **Sentry capture SOT** — Story 3.6 ``LLMRouterExhaustedError`` 패턴 정합. service
   레이어에서 ``sentry_sdk.capture_message("payment.confirm_failed")`` 명시 호출
   (운영 모니터링 명시 신호 — 카드 거절 빈도 abnormal 시 dashboard alert).

흐름 (5단계):
1. **input 검증** — ``amount != MONTHLY_PLAN_PRICE_KRW`` → ``PaymentAmountInvalidError``.
2. **Idempotency-Key replay** — 헤더 송신 시 ``payment_logs.idempotency_key``로 1차 조회,
   있으면 기존 ``(subscription, log, was_replay=True)`` 반환.
3. **active subscription 중복 가드** — ``subscriptions.status='active'`` 1차 조회,
   있으면 ``SubscriptionAlreadyActiveError(409)``.
4. **Toss API 호출** — ``confirm_payment``. 거절 시 *failed payment_log INSERT* +
   ``PaymentConfirmFailedError`` raise. 5xx는 그대로 propagate(``PaymentProvider
   UnavailableError``).
5. **DB 작성** — ``subscription`` + ``payment_log`` 양 row INSERT (동일 트랜잭션).
   commit은 라우터 책임.

스코프: 자동 갱신 / webhook / 해지 / 환불은 Story 6.2/6.3 forward.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import sentry_sdk
import structlog
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import toss as toss_adapter
from app.core.exceptions import (
    BalanceNoteError,
    PaymentAmountInvalidError,
    PaymentConfirmFailedError,
    PaymentProviderRejectedError,
    SubscriptionAlreadyActiveError,
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
# 인덱스 이름은 마이그레이션 0019와 동기 — 인덱스 rename 시 본 상수도 갱신 필수.
_IDEMPOTENCY_INDEX_NAME: Final[str] = "idx_payment_logs_user_id_idempotency_key_unique"


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
    """``idempotency_key`` 1차 조회 — replay 분기 진입 신호."""
    result = await session.execute(
        select(PaymentLog).where(
            PaymentLog.user_id == user_id,
            PaymentLog.idempotency_key == idempotency_key,
            PaymentLog.event_type == "subscribe",
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
) -> None:
    """결제 실패 시 audit-trail 1건 INSERT — ``subscription_id=NULL`` (구독 row 미생성)."""
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
    # 1차 SELECT — replay 분기 신호.
    if idempotency_key is not None:
        existing_log = await _fetch_payment_log_by_idempotency_key(
            session, user_id=user_id, idempotency_key=idempotency_key
        )
        if existing_log is not None:
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

    # 4차 — 양 row INSERT. INSERT 시점에 idempotency_key UNIQUE 위반 race 차단.
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
        # idempotency_key UNIQUE 위반 (race) 만 replay path로 — 다른 INSERT 충돌(active
        # partial UNIQUE 등)은 그대로 raise.
        if idempotency_key is not None and _IDEMPOTENCY_INDEX_NAME in str(exc.orig):
            await session.rollback()
            replay_log = await _fetch_payment_log_by_idempotency_key(
                session, user_id=user_id, idempotency_key=idempotency_key
            )
            if replay_log is None:
                raise BalanceNoteError(
                    "idempotent replay race resolution failed (no row found after IntegrityError)"
                ) from None
            replay_subscription = await _fetch_subscription_for_log(session, log=replay_log)
            if replay_subscription is None:
                raise BalanceNoteError(
                    "idempotent replay race: payment_log found but subscription missing"
                ) from None
            return replay_subscription, replay_log, True
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
        # commit 명시 — 라우터가 ``PaymentConfirmFailedError``를 catch하지 않고 글로벌
        # 핸들러로 propagate하면 ``get_db_session`` dependency가 ``rollback``을 수행해
        # audit-trail row가 사라진다. 본 INSERT는 *별도 트랜잭션 단위*로 보존 의무.
        await _insert_failed_payment_log(
            session,
            user_id=user_id,
            payment_key=payment_key,
            order_id=order_id,
            amount=amount,
            idempotency_key=idempotency_key,
            failure_reason=str(exc),
        )
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
