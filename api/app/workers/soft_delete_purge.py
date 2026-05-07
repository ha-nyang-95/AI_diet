"""Story 5.2 — 회원 탈퇴 30일 grace 후 사용자 데이터 물리 파기 cron worker.

본 모듈은 *2 진입점*:

1. ``purge_expired_soft_deleted_users(session_maker, r2_adapter=None)`` async function
   — eligible SELECT(``users WHERE deleted_at IS NOT NULL AND deleted_at < cutoff``)
   per-user 격리 트랜잭션으로 R2 dump → R2 meal images cleanup → DB hard DELETE
   FROM users(자동 cascade). stats dict 반환.
2. ``register_purge_job(scheduler, session_maker, r2_adapter=None, redis=None)`` —
   APScheduler ``CronTrigger(hour=3, minute=0, timezone="Asia/Seoul")`` 등록 — 매일
   새벽 3시 KST 1회 sweep. ``replace_existing=True`` lifespan 재등록 race 차단.

3 cascade 자동 채널(코드 변경 0건):
- ``DELETE FROM users`` → ``consents``/``meals``/``meal_analyses``/``notifications``/
  ``refresh_tokens`` 모두 ``ondelete="CASCADE"`` 자동 cascade(FK level SOT).
- ``current_user``(``deps.py:94``) ``User.deleted_at.is_(None)`` 가드 baseline → 401.
- ``nudge_scheduler._build_eligible_users_query`` ``u.deleted_at IS NULL`` 필터 →
  push 자동 제외.

R2 dump bucket(``settings.r2_purge_dump_bucket``)는 미설정 시 graceful skip — 운영 SOP는
Cloudflare 콘솔 측 lifecycle policy(30일 자동 만료) SOT.

Story 4.2 ``nudge_scheduler.py`` 패턴 1:1 정합 — ``register_*_job`` + per-job ``Final[str]``
ID 상수 + Sentry transaction(``op="purge.sweep"``) + per-user span(``op="purge.user"``) +
structlog NFR-S5 마스킹.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import sentry_sdk
import structlog
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.consent import Consent
from app.db.models.meal import Meal
from app.db.models.notification import Notification
from app.db.models.user import User

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger(__name__)

# epics.md:798 + architecture.md:351 SOT — 회원 탈퇴 후 30일 grace, 31일째 sweep 진입.
PURGE_GRACE_DAYS: Final[int] = 30

# APScheduler 잡 ID — lifespan 재등록 시 ``replace_existing=True``와 페어. nudge SOT 정합.
PURGE_JOB_ID: Final[str] = "soft_delete_purge_expired"

# R2 list_objects_v2 페이지 크기(R2/S3 표준 1000건 cap). meal images cleanup 페이지네이션
# 기준 — 단일 사용자가 1000건 이상의 meals 이미지를 보유한 시나리오 흡수.
_R2_DELETE_BATCH_SIZE: Final[int] = 1000


def _mask_user_id(user_id: uuid.UUID) -> str:
    """NFR-S5 — ``user_id``를 ``u_{first8char}``로 마스킹(Story 1.5/4.2 패턴 정합)."""
    return f"u_{str(user_id)[:8]}"


# --- Per-user helpers ------------------------------------------------------


async def _build_user_dump_payload(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """R2 dump JSON shape SOT — *최소 set*(profile + consents + meals 메타 + notifications).

    Story 5.3(``data_export_service.py``) 추가 시 통합 검토 가능(deferred-work DF136 forward).
    본 스토리는 worker 내부 dump JSON shape를 명시 — 사용자 권리 행사 응답과 *별 모듈*.
    """
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return {}

    consents = (
        (await session.execute(select(Consent).where(Consent.user_id == user_id))).scalars().all()
    )
    meals = (await session.execute(select(Meal).where(Meal.user_id == user_id))).scalars().all()
    notifications = (
        (await session.execute(select(Notification).where(Notification.user_id == user_id)))
        .scalars()
        .all()
    )

    def _serialize_value(v: Any) -> Any:
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    def _serialize_row(row: Any) -> dict[str, Any]:
        return {col.name: _serialize_value(getattr(row, col.name)) for col in row.__table__.columns}

    return {
        "user_id": str(user.id),
        "exported_at": datetime.now(UTC).isoformat(),
        "user": _serialize_row(user),
        "consents": [_serialize_row(c) for c in consents],
        "meals": [_serialize_row(m) for m in meals],
        "notifications": [_serialize_row(n) for n in notifications],
    }


def _dump_user_to_r2(
    r2_adapter: Any,
    user_id: uuid.UUID,
    dump_bucket: str,
    payload: dict[str, Any],
) -> None:
    """JSON dump → ``purge-dumps/{user_id}/{yyyy-mm-dd}.json`` PUT.

    bucket lifecycle policy(30일 자동 삭제)는 Cloudflare 콘솔 측 SOT — 본 worker는
    PUT만 수행. ``r2_adapter``는 ``app.adapters.r2`` 모듈 자체(boto3 lazy singleton).
    """
    today = datetime.now(UTC).date().isoformat()
    key = f"purge-dumps/{user_id}/{today}.json"
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    client = r2_adapter._get_client()  # noqa: SLF001 — 인접 worker는 어댑터 lazy singleton 직접 사용.
    client.put_object(
        Bucket=dump_bucket,
        Key=key,
        Body=body,
        ContentType="application/json; charset=utf-8",
    )


def _cleanup_user_r2_images(
    r2_adapter: Any,
    user_id: uuid.UUID,
) -> int:
    """``meals/{user_id}/`` prefix list_objects_v2 + delete_objects(batch 1000건 cap).

    Returns 삭제된 객체 수. R2/S3 표준 paginator 패턴 — ``ContinuationToken``으로 다음
    페이지 진입. r2_adapter None 또는 R2 미설정은 호출 측에서 가드(본 함수는 client 가져옴).
    """
    client = r2_adapter._get_client()  # noqa: SLF001
    bucket = settings.r2_bucket
    prefix = f"meals/{user_id}/"
    deleted_count = 0
    continuation_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": _R2_DELETE_BATCH_SIZE,
        }
        if continuation_token is not None:
            kwargs["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**kwargs)
        objects = response.get("Contents", [])
        if objects:
            keys = [{"Key": obj["Key"]} for obj in objects]
            client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": keys, "Quiet": True},
            )
            deleted_count += len(keys)
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")
        if continuation_token is None:
            break

    return deleted_count


async def _process_single_user_purge(
    session_maker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    cutoff: datetime,
    *,
    r2_adapter: Any | None,
    dump_bucket: str,
) -> dict[str, int]:
    """단일 사용자 격리 트랜잭션 — dump → cleanup → DB hard DELETE.

    Returns per-user stats(dump=0|1, images=N, purged=0|1, errors=0|1). 실패는 격리되어
    sweep 전체를 중단시키지 않음.
    """
    masked = _mask_user_id(user_id)
    stats = {"dumped": 0, "images_cleaned": 0, "purged": 0, "errors": 0}

    try:
        with sentry_sdk.start_span(op="purge.user", name="purge.user") as span:
            span.set_tag("user_id_masked", masked)

            # 1) R2 dump (선택 — bucket 미설정 시 skip).
            if dump_bucket and r2_adapter is not None:
                async with session_maker() as session:
                    payload = await _build_user_dump_payload(session, user_id)
                if payload:
                    _dump_user_to_r2(r2_adapter, user_id, dump_bucket, payload)
                    stats["dumped"] = 1
                    logger.info("purge.user.dumped", user_id=masked, bucket=dump_bucket)
            else:
                logger.info(
                    "purge.dump_skipped",
                    user_id=masked,
                    reason="bucket_unset" if not dump_bucket else "adapter_none",
                )

            # 2) R2 meal images cleanup (선택 — adapter 미주입 시 skip).
            if r2_adapter is not None:
                try:
                    cleaned = _cleanup_user_r2_images(r2_adapter, user_id)
                    stats["images_cleaned"] = cleaned
                    logger.info("purge.user.images_cleaned", user_id=masked, count=cleaned)
                except Exception as exc:  # noqa: BLE001 — R2 transient 실패는 DB delete를 막지 않음.
                    sentry_sdk.capture_exception(exc)
                    logger.warning(
                        "purge.user.images_cleanup_failed",
                        user_id=masked,
                        reason=type(exc).__name__,
                    )
            else:
                logger.warning("purge.images_skipped", user_id=masked, reason="adapter_none")

            # 3) DB hard delete — ondelete="CASCADE"가 child rows 자동 cascade.
            async with session_maker() as session:
                result = await session.execute(
                    delete(User).where(
                        User.id == user_id,
                        User.deleted_at.is_not(None),
                        User.deleted_at < cutoff,
                    )
                )
                await session.commit()
                # CursorResult 서브타입에 ``rowcount``가 있으나 SQLAlchemy 정적 타입은
                # ``Result[Any]``로만 노출 — getattr 우회 + None default 0 분기.
                rowcount = getattr(result, "rowcount", 0) or 0
                if rowcount > 0:
                    stats["purged"] = 1
                    logger.info("purge.user.deleted", user_id=masked)
                else:
                    # rowcount=0 — 다른 sweep cycle이 처리, 또는 race로 cutoff 변경.
                    logger.info("purge.user.skipped", user_id=masked, reason="rowcount_zero")

    except Exception as exc:  # noqa: BLE001 — per-user 격리: 실패가 sweep 전체 중단 X.
        sentry_sdk.capture_exception(exc)
        stats["errors"] = 1
        logger.error(
            "purge.user.failed",
            user_id=masked,
            reason=type(exc).__name__,
        )

    return stats


# --- Sweep entrypoint ------------------------------------------------------


async def purge_expired_soft_deleted_users(
    session_maker: async_sessionmaker[AsyncSession],
    r2_adapter: Any | None = None,
) -> dict[str, int]:
    """30일 grace 경과 사용자 sweep — 매일 새벽 3시 KST cron entrypoint.

    Returns sweep 통계 dict — ``users_eligible_count`` / ``users_purged_count`` /
    ``r2_dumps_count`` / ``r2_images_cleaned_count`` / ``errors_count``.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=PURGE_GRACE_DAYS)
    dump_bucket = settings.r2_purge_dump_bucket

    logger.info(
        "purge.sweep.start",
        cutoff=cutoff.isoformat(),
        dump_bucket_configured=bool(dump_bucket),
    )

    stats = {
        "users_eligible_count": 0,
        "users_purged_count": 0,
        "r2_dumps_count": 0,
        "r2_images_cleaned_count": 0,
        "errors_count": 0,
    }

    transaction = sentry_sdk.start_transaction(op="purge.sweep", name="purge.sweep")
    try:
        # eligible SELECT — partial index ``idx_users_deleted_at_pending_purge`` hit.
        async with session_maker() as session:
            result = await session.execute(
                select(User.id).where(
                    User.deleted_at.is_not(None),
                    User.deleted_at < cutoff,
                )
            )
            user_ids = [row[0] for row in result.all()]

        stats["users_eligible_count"] = len(user_ids)
        transaction.set_tag("users_eligible_count", len(user_ids))
        logger.info("purge.sweep.eligible", user_count=len(user_ids))

        for user_id in user_ids:
            user_stats = await _process_single_user_purge(
                session_maker,
                user_id,
                cutoff,
                r2_adapter=r2_adapter,
                dump_bucket=dump_bucket,
            )
            stats["users_purged_count"] += user_stats["purged"]
            stats["r2_dumps_count"] += user_stats["dumped"]
            stats["r2_images_cleaned_count"] += user_stats["images_cleaned"]
            stats["errors_count"] += user_stats["errors"]

        transaction.set_tag("users_purged_count", stats["users_purged_count"])
        transaction.set_tag("errors_count", stats["errors_count"])

    except Exception:
        transaction.set_status("internal_error")
        raise
    finally:
        transaction.finish()

    logger.info(
        "purge.sweep.complete",
        users_eligible_count=stats["users_eligible_count"],
        users_purged_count=stats["users_purged_count"],
        r2_dumps_count=stats["r2_dumps_count"],
        r2_images_cleaned_count=stats["r2_images_cleaned_count"],
        errors_count=stats["errors_count"],
    )
    return stats


def register_purge_job(
    scheduler: AsyncIOScheduler,
    session_maker: async_sessionmaker[AsyncSession],
    r2_adapter: Any | None = None,
    redis: Any | None = None,
) -> None:
    """``AsyncIOScheduler``에 30일 grace purge 잡 등록 — 매일 새벽 3시 KST.

    사유: nudge sweep는 매 30분 cycle, 새벽 3시는 push 발사 ↓ DB load idle peak. 단일
    노드 정합으로 cron 충돌 0. ``redis`` 인자는 forward — 본 스토리 미사용.
    """
    _ = redis  # forward use
    scheduler.add_job(
        purge_expired_soft_deleted_users,
        trigger=CronTrigger(hour=3, minute=0, timezone="Asia/Seoul"),
        args=[session_maker, r2_adapter],
        id=PURGE_JOB_ID,
        replace_existing=True,
    )
    logger.info("purge.job.registered", job_id=PURGE_JOB_ID)


__all__ = [
    "PURGE_GRACE_DAYS",
    "PURGE_JOB_ID",
    "purge_expired_soft_deleted_users",
    "register_purge_job",
]
