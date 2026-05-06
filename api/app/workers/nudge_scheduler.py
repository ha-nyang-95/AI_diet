"""미기록 식단 알림 sweep cron — Story 4.2 (AC3, AC6, AC8).

매 30분(KST) sweep — `notifications_enabled=true` AND `expo_push_token IS NOT NULL` AND
`deleted_at IS NULL` AND 당일 KST `meals` 0건 AND 동일 날 동일 kind ``notifications`` 행 미존재
사용자에게 *미기록 nudge* push 발송.

`architecture.md:704-705 / 1088-1092` 정합 — APScheduler in-process AsyncIOScheduler + 1인 8주
단일 노드. multi-replica는 Story 8.5 hardening forward.

Sentry transaction `op="nudge.sweep"` + 사용자별 child span `op="nudge.send"` — Story 3.3
``analysis.pipeline`` 패턴 정합. structlog는 NFR-S5 정합 — token raw 로깅 X, ``user_id``는
``u_{first8char}`` 마스킹.

DeviceNotRegistered 처리: ``revoke_push_token`` 호출(Story 4.1 SOT 재사용) → 다음 sweep
cycle은 ``expo_push_token IS NOT NULL`` 필터로 자동 제외.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

import sentry_sdk
import structlog
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters import expo_push
from app.core.exceptions import ExpoPushError
from app.db.models.notification import Notification
from app.db.models.user import User
from app.services.notification_service import revoke_push_token

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger(__name__)

# Story 4.2 AC8 — module-level 카피 SOT. epics.md:741 정합. i18n forward는 Story 8.6.
NUDGE_TITLE: Final[str] = "오늘 저녁 미기록"
NUDGE_BODY: Final[str] = "1분 안에 빠른 입력으로 일주일 일관성 유지하세요"

# Push payload data SOT — 백엔드/모바일 양방향 정합.
NUDGE_DATA: Final[dict[str, str]] = {
    "url": "balancenote://meals/input",
    "kind": "unrecorded_meal",
}

# 잡 ID — replace_existing=True로 lifespan 재등록 시 중복 방지.
NUDGE_JOB_ID: Final[str] = "nudge_sweep_unrecorded_meals"

# KST timezone SOT — Story 4.1 ``notification_timezone`` default 컬럼 정합.
_KST = ZoneInfo("Asia/Seoul")

# Sweep window — 30분 cycle. AC3 정합.
_SWEEP_WINDOW_MINUTES: Final[int] = 30


def _mask_user_id(user_id: uuid.UUID) -> str:
    """NFR-S5 — ``user_id``를 ``u_{first8char}``로 마스킹(Story 1.5 패턴 정합)."""
    return f"u_{str(user_id)[:8]}"


def _build_eligible_users_query(*, wrap_midnight: bool) -> str:
    """sweep query SOT.

    `wrap_midnight=True`면 자정 cross 윈도우(``lower > upper``) 처리 — OR 분기. False면
    표준 BETWEEN.
    """
    if wrap_midnight:
        time_predicate = (
            "(((u.notification_time + INTERVAL '30 minutes')::time >= :lower_time) "
            "OR ((u.notification_time + INTERVAL '30 minutes')::time <= :upper_time))"
        )
    else:
        time_predicate = (
            "((u.notification_time + INTERVAL '30 minutes')::time "
            "BETWEEN :lower_time AND :upper_time)"
        )
    return (
        "SELECT u.id, u.expo_push_token, u.notification_time "
        "FROM users u "
        "WHERE u.deleted_at IS NULL "
        "  AND u.notifications_enabled = true "
        "  AND u.expo_push_token IS NOT NULL "
        f"  AND {time_predicate} "
        "  AND NOT EXISTS ( "
        "    SELECT 1 FROM meals m "
        "    WHERE m.user_id = u.id "
        "      AND m.deleted_at IS NULL "
        "      AND (m.ate_at AT TIME ZONE 'Asia/Seoul')::date = :today_kst "
        "  ) "
        "  AND NOT EXISTS ( "
        "    SELECT 1 FROM notifications n "
        "    WHERE n.user_id = u.id "
        "      AND n.kind = 'unrecorded_meal' "
        "      AND n.kst_date = :today_kst "
        "  )"
    )


async def _fetch_eligible_users(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    now_kst: datetime,
) -> list[tuple[uuid.UUID, str, time]]:
    """30분 윈도우 + 당일 미기록 + 미발사 사용자 SELECT.

    ``now_kst``는 호출 시점의 KST datetime. 윈도우 = ``[now - 30min, now]``. 자정 cross
    처리는 lower > upper 분기. ``today_kst``는 ``now_kst.date()``.
    """
    upper_time = now_kst.time().replace(second=0, microsecond=0)
    lower_time = (
        (now_kst - timedelta(minutes=_SWEEP_WINDOW_MINUTES)).time().replace(second=0, microsecond=0)
    )
    today_kst = now_kst.date()
    wrap_midnight = lower_time > upper_time

    query = text(_build_eligible_users_query(wrap_midnight=wrap_midnight))
    async with session_maker() as session:
        result = await session.execute(
            query,
            {
                "lower_time": lower_time,
                "upper_time": upper_time,
                "today_kst": today_kst,
            },
        )
        return [(row.id, row.expo_push_token, row.notification_time) for row in result]


async def _record_notification(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    today_kst: Any,
    expo_ticket_id: str | None,
) -> bool:
    """``notifications`` row INSERT — UNIQUE 충돌은 멱등 정합으로 swallow.

    Returns True if inserted, False if duplicate (멱등 skip).
    """
    async with session_maker() as session:
        notification = Notification(
            user_id=user_id,
            kind="unrecorded_meal",
            kst_date=today_kst,
            expo_ticket_id=expo_ticket_id,
        )
        session.add(notification)
        try:
            await session.commit()
        except IntegrityError:
            # UNIQUE (user_id, kind, kst_date) 위반 — 동시 cron tick race. 멱등 정합.
            await session.rollback()
            return False
    return True


async def _revoke_token_for_user(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
) -> None:
    """``revoke_push_token`` 호출 — Story 4.1 SOT 재사용."""
    async with session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            # 사용자 row가 사라진 경우(soft-delete 또는 cascade 등) — no-op.
            return
        await revoke_push_token(session, user)


async def sweep_unrecorded_meals(
    session_maker: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    """미기록 식단 알림 sweep — every 30분 cron entrypoint.

    Returns sweep 통계 dict (``users_eligible_count`` / ``nudges_sent_count`` /
    ``device_not_registered_count`` / ``transient_error_count``). 테스트 verifications
    + Sentry transaction tags 양쪽 사용.
    """
    now_kst = datetime.now(_KST)
    today_kst = now_kst.date()

    logger.info(
        "nudge.sweep.start",
        now_kst=now_kst.isoformat(),
        today_kst=today_kst.isoformat(),
    )

    stats = {
        "users_eligible_count": 0,
        "nudges_sent_count": 0,
        "device_not_registered_count": 0,
        "transient_error_count": 0,
    }

    transaction = sentry_sdk.start_transaction(op="nudge.sweep", name="nudge.sweep")
    try:
        eligible = await _fetch_eligible_users(session_maker, now_kst=now_kst)
        stats["users_eligible_count"] = len(eligible)
        logger.info("nudge.sweep.eligible", user_count=len(eligible))
        transaction.set_tag("users_eligible_count", len(eligible))

        for user_id, token, _notification_time in eligible:
            masked = _mask_user_id(user_id)
            try:
                with sentry_sdk.start_span(op="nudge.send", name="nudge.send") as span:
                    span.set_tag("user_id_masked", masked)
                    ticket = await expo_push.send_nudge(
                        token=token,
                        title=NUDGE_TITLE,
                        body=NUDGE_BODY,
                        data=NUDGE_DATA,
                    )
            except ExpoPushError as exc:
                # adapter boundary error — Sentry capture + 다음 cycle 재시도 정합.
                sentry_sdk.capture_exception(exc)
                stats["transient_error_count"] += 1
                logger.warning(
                    "nudge.skipped",
                    user_id=masked,
                    reason=f"adapter_error:{type(exc).__name__}",
                )
                continue
            except Exception as exc:  # noqa: BLE001
                sentry_sdk.capture_exception(exc)
                stats["transient_error_count"] += 1
                logger.warning(
                    "nudge.skipped",
                    user_id=masked,
                    reason=f"unexpected:{type(exc).__name__}",
                )
                continue

            if ticket.status == "ok":
                inserted = await _record_notification(
                    session_maker,
                    user_id=user_id,
                    today_kst=today_kst,
                    expo_ticket_id=ticket.id,
                )
                if inserted:
                    stats["nudges_sent_count"] += 1
                    logger.info(
                        "nudge.sent",
                        user_id=masked,
                        ticket_id=ticket.id,
                    )
                else:
                    logger.warning(
                        "nudge.skipped",
                        user_id=masked,
                        reason="duplicate_unique",
                    )
                continue

            # ticket.status == "error" 분기
            error_code = (ticket.details or {}).get("error") if ticket.details else None
            if error_code == "DeviceNotRegistered":
                # Story 4.1 SOT 재사용 — token NULL set + 다음 cycle 자동 제외.
                await _revoke_token_for_user(session_maker, user_id=user_id)
                stats["device_not_registered_count"] += 1
                logger.warning(
                    "nudge.skipped",
                    user_id=masked,
                    reason="device_not_registered",
                )
                continue

            # 그 외 ticket error (MessageTooBig / MessageRateExceeded / 기타)
            sentry_sdk.capture_message(
                f"nudge.ticket_error: {error_code}",
                level="error",
            )
            stats["transient_error_count"] += 1
            logger.warning(
                "nudge.skipped",
                user_id=masked,
                reason=f"ticket_error:{error_code}",
            )

        transaction.set_tag("nudges_sent_count", stats["nudges_sent_count"])
        transaction.set_tag("device_not_registered_count", stats["device_not_registered_count"])
        transaction.set_tag("transient_error_count", stats["transient_error_count"])
    finally:
        transaction.finish()

    logger.info(
        "nudge.sweep.complete",
        success_count=stats["nudges_sent_count"],
        error_count=stats["transient_error_count"],
        device_not_registered=stats["device_not_registered_count"],
    )
    return stats


def register_nudge_job(
    scheduler: AsyncIOScheduler,
    session_maker: async_sessionmaker[AsyncSession],
    redis: Any | None = None,
) -> None:
    """``AsyncIOScheduler``에 nudge sweep 잡 등록 — every 30 min KST.

    ``redis`` 인자는 본 스토리에서 미사용(forward — Story 8.4 멱등 캐시 옵션 등 가능).
    """
    _ = redis  # forward use
    scheduler.add_job(
        sweep_unrecorded_meals,
        trigger=CronTrigger(minute="*/30", timezone="Asia/Seoul"),
        args=[session_maker],
        id=NUDGE_JOB_ID,
        replace_existing=True,
    )
    logger.info("nudge.job.registered", job_id=NUDGE_JOB_ID)


__all__ = [
    "NUDGE_BODY",
    "NUDGE_DATA",
    "NUDGE_JOB_ID",
    "NUDGE_TITLE",
    "register_nudge_job",
    "sweep_unrecorded_meals",
]
