"""Story 6.3 — ``subscriptions.status='active' AND expires_at < now()`` row를 *expired*로
정식 전이하는 sweep cron.

webhook 부재 케이스(Toss 미통보)에 대한 안전판. 매시 정각(KST) sweep + redis lock(30분 TTL)
+ 100건 cap. ``GET /v1/payments/subscription`` lazy gate(``payments.py:get_subscription``의
DF135 흡수)와 *이중 처리* — sweep은 *데이터 정합성*(다른 endpoint도 정상 active만 보게),
lazy gate는 *결정성*(polling 응답이 sweep 시점에 의존하지 않게).

2 진입점:

1. ``sweep_expired_subscriptions(session_maker, redis)`` async function — eligible SELECT
   (``status='active' AND expires_at < now() LIMIT 100``) → 각 row ``status='expired'`` UPDATE.
   stats dict 반환.
2. ``register_subscription_expire_job(scheduler, session_maker, redis) -> None`` —
   APScheduler ``CronTrigger(minute=0, timezone="Asia/Seoul")`` 등록 — 매시 정각 1회 sweep.
   ``replace_existing=True`` lifespan 재등록 race 차단.

graceful: ``session_maker is None`` → register 시점에 skip + warning (no job registered).
``redis is None`` → in-memory lock 대체(테스트/dev 안정성 우선, 단일 노드는 race 0).

Story 4.2 ``nudge_scheduler.py`` / Story 5.2 ``soft_delete_purge.py`` 패턴 1:1 정합 —
``register_*_job`` + per-job ``Final[str]`` ID 상수 + Sentry transaction
(``op="subscription_expire.sweep"``).

audit log INSERT *없음* — *expired 전이는 단순 timer event*, ``payment_logs``는 결제
이벤트 audit만(*expires_at 도래 = 이벤트 무*). cancelled-but-expired는 취급 X(이미
cancelled — 그대로 유지, 사용자 view에선 expired와 동등).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import sentry_sdk
import structlog
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.subscription import Subscription

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger(__name__)

# APScheduler 잡 ID — lifespan 재등록 시 ``replace_existing=True``와 페어. nudge SOT 정합.
SUBSCRIPTION_EXPIRE_JOB_ID: Final[str] = "subscription_expire_sweep"

# redis-backed lock 키 — 30분 TTL(같은 시간 다중 인스턴스 차단). 단일 노드 baseline에선
# race 0이지만 multi-replica forward(Story 8.5)에 forward-compat.
_LOCK_KEY: Final[str] = "cache:lock:subscription_expire_sweep"
_LOCK_TTL_SECONDS: Final[int] = 30 * 60

# Story 4.2 nudge SOT 600s grace보다 큰 grace(매시 cron이라 잠깐 down 시 cycle 자체 silent skip
# 회피). sweep 멱등(rowcount=0 가드 + cutoff 동일)이 늦은 실행 안전 흡수.
_SWEEP_MISFIRE_GRACE_SECONDS: Final[int] = 30 * 60

# 단일 sweep 1 cycle 처리 cap — 초과 시 다음 cycle에 처리(redis lock 동시 진입 방지).
_SWEEP_BATCH_LIMIT: Final[int] = 100


async def _try_acquire_lock(redis: Any | None) -> str | None:
    """redis ``SET NX EX`` 패턴 — 락 획득 성공 시 token, 실패 시 None.

    redis None → in-memory fallback("token-bypass" 반환 — 테스트/dev 단일 노드 안정성).
    """
    if redis is None:
        # in-memory fallback — single-process 테스트 안정성 우선.
        return "memory-bypass"
    token = secrets.token_hex(16)
    try:
        # SET ... NX EX ... — race-free lock 획득.
        acquired = await redis.set(_LOCK_KEY, token, nx=True, ex=_LOCK_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 — redis 장애는 sweep 진입 차단(다음 cycle 재시도).
        sentry_sdk.capture_exception(exc)
        logger.warning("subscription_expire.lock.redis_error", reason=type(exc).__name__)
        return None
    if not acquired:
        return None
    return token


async def _release_lock(redis: Any | None, token: str | None) -> None:
    """redis lock 해제 — token 일치 시에만 DEL(다른 instance 락 침범 방지)."""
    if redis is None or token is None or token == "memory-bypass":
        return
    try:
        # 다른 worker가 같은 키로 락을 다시 잡았을 수 있으므로 token 검증 후 DEL.
        # Lua atomic은 SOT — 본 구현은 단일 노드라 GET → DEL 분리도 충분 안전.
        current = await redis.get(_LOCK_KEY)
        if current == token:
            await redis.delete(_LOCK_KEY)
    except Exception as exc:  # noqa: BLE001
        sentry_sdk.capture_exception(exc)
        logger.warning("subscription_expire.lock.release_failed", reason=type(exc).__name__)


async def sweep_expired_subscriptions(
    session_maker: async_sessionmaker[AsyncSession],
    redis: Any | None = None,
) -> dict[str, int]:
    """``status='active' AND expires_at < now()`` row를 *expired*로 전이.

    Returns sweep 통계 dict — ``eligible_count`` / ``expired_count`` / ``cap_exceeded`` /
    ``lock_held`` / ``errors_count``.

    - ``eligible_count``: 100건 cap 안에서 SELECT된 row 수.
    - ``expired_count``: ``status='expired'`` UPDATE rowcount.
    - ``cap_exceeded``: 100건 cap 도달 시 1, 미만이면 0(*queue 누적 신호*).
    - ``lock_held``: redis lock 획득 실패 시 1(다른 instance가 sweep 중 — skip).
    - ``errors_count``: 1 이상이면 sweep 자체 실패(sentry capture 후 stats 반환).
    """
    stats = {
        "eligible_count": 0,
        "expired_count": 0,
        "cap_exceeded": 0,
        "lock_held": 0,
        "errors_count": 0,
    }

    token = await _try_acquire_lock(redis)
    if token is None:
        stats["lock_held"] = 1
        logger.info("subscription_expire.sweep.lock_held")
        return stats

    transaction = sentry_sdk.start_transaction(
        op="subscription_expire.sweep", name="subscription_expire.sweep"
    )
    try:
        now = datetime.now(UTC)

        # eligible SELECT (id만 — UPDATE에서 in_(ids) 대신 atomic UPDATE 사용).
        async with session_maker() as session:
            result = await session.execute(
                select(Subscription.id)
                .where(
                    Subscription.status == "active",
                    Subscription.expires_at.isnot(None),
                    Subscription.expires_at < now,
                )
                .limit(_SWEEP_BATCH_LIMIT + 1)  # +1로 cap 초과 감지.
            )
            eligible_ids = [row[0] for row in result.all()]

        if len(eligible_ids) > _SWEEP_BATCH_LIMIT:
            stats["cap_exceeded"] = 1
            sentry_sdk.capture_message(
                "subscription_expire.queue_overflow",
                level="warning",
            )
            logger.warning(
                "subscription_expire.cap_exceeded",
                eligible_count=len(eligible_ids),
                cap=_SWEEP_BATCH_LIMIT,
            )
            eligible_ids = eligible_ids[:_SWEEP_BATCH_LIMIT]

        stats["eligible_count"] = len(eligible_ids)
        transaction.set_tag("eligible_count", len(eligible_ids))

        if eligible_ids:
            async with session_maker() as session:
                update_result = await session.execute(
                    update(Subscription)
                    .where(
                        Subscription.id.in_(eligible_ids),
                        Subscription.status == "active",  # race 가드(같은 cycle에 중복 전이 차단).
                        Subscription.expires_at < now,
                    )
                    .values(status="expired")
                )
                rowcount = getattr(update_result, "rowcount", 0) or 0
                await session.commit()
                stats["expired_count"] = rowcount

        transaction.set_tag("expired_count", stats["expired_count"])
        logger.info(
            "subscription_expire.sweep.complete",
            eligible_count=stats["eligible_count"],
            expired_count=stats["expired_count"],
            cap_exceeded=stats["cap_exceeded"],
        )
    except Exception as exc:  # noqa: BLE001 — sweep 실패는 silent retry 다음 cycle.
        sentry_sdk.capture_exception(exc)
        stats["errors_count"] = 1
        transaction.set_status("internal_error")
        logger.error(
            "subscription_expire.sweep.failed",
            reason=type(exc).__name__,
        )
    finally:
        transaction.finish()
        await _release_lock(redis, token)

    return stats


def register_subscription_expire_job(
    scheduler: AsyncIOScheduler,
    session_maker: async_sessionmaker[AsyncSession] | None,
    redis: Any | None = None,
) -> None:
    """``AsyncIOScheduler``에 expires_at sweep 잡 등록 — 매시 정각 KST.

    graceful: ``session_maker is None`` → 잡 미등록 + warning log(test/ci 환경 등).
    ``redis is None`` → 잡은 등록(in-memory lock fallback — 단일 노드 baseline 안전).
    """
    if session_maker is None:
        logger.warning(
            "subscription_expire.job.skipped_no_session_maker",
            reason="session_maker_none",
        )
        return

    scheduler.add_job(
        sweep_expired_subscriptions,
        trigger=CronTrigger(minute=0, timezone="Asia/Seoul"),
        args=[session_maker, redis],
        id=SUBSCRIPTION_EXPIRE_JOB_ID,
        replace_existing=True,
        misfire_grace_time=_SWEEP_MISFIRE_GRACE_SECONDS,
    )
    logger.info(
        "subscription_expire.job.registered",
        job_id=SUBSCRIPTION_EXPIRE_JOB_ID,
    )


__all__ = [
    "SUBSCRIPTION_EXPIRE_JOB_ID",
    "register_subscription_expire_job",
    "sweep_expired_subscriptions",
]
