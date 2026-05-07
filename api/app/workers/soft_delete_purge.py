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

CR D1 결정 — *PIPA Art.21 30일 mandate 우선*: dump 실패는 inner try로 격리되어 cleanup +
DB DELETE는 계속 진행(stat["dump_errors"] + sentry capture로 운영자 즉시 인지). dump
bucket 영구 misconfig가 컴플라이언스를 차단하지 않도록.

Story 4.2 ``nudge_scheduler.py`` 패턴 1:1 정합 — ``register_*_job`` + per-job ``Final[str]``
ID 상수 + Sentry transaction(``op="purge.sweep"``) + per-user span(``op="purge.user"``) +
structlog NFR-S5 마스킹.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import sentry_sdk
import structlog
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import PURGE_GRACE_DAYS, settings
from app.db.models.user import User
from app.services.data_export_service import collect_user_export_payload

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger(__name__)

# 본 상수 SOT는 ``app.core.config.PURGE_GRACE_DAYS`` — auth.py(detail 합성)와 본 모듈
# (cutoff 계산) 공통 import. ``__all__``에서 재export하여 기존 callsite 호환 유지.

# APScheduler 잡 ID — lifespan 재등록 시 ``replace_existing=True``와 페어. nudge SOT 정합.
PURGE_JOB_ID: Final[str] = "soft_delete_purge_expired"

# R2 list_objects_v2 페이지 크기(R2/S3 표준 1000건 cap). meal images cleanup 페이지네이션
# 기준 — 단일 사용자가 1000건 이상의 meals 이미지를 보유한 시나리오 흡수.
_R2_DELETE_BATCH_SIZE: Final[int] = 1000

# CR P7 — daily cron은 컨테이너 짧은 down 시 sweep cycle 자체를 silent skip하지 않도록
# nudge SOT(600s)보다 큰 grace 부여. 6시간 = 03:00 ~ 09:00 KST 사이 부팅 복구분 흡수.
# sweep는 멱등(rowcount=0 가드 + cutoff 동일)이라 늦은 실행도 안전.
_PURGE_MISFIRE_GRACE_SECONDS: Final[int] = 6 * 60 * 60


def _mask_user_id(user_id: uuid.UUID) -> str:
    """NFR-S5 — ``user_id``를 ``u_{first8char}``로 마스킹(Story 1.5/4.2 패턴 정합)."""
    return f"u_{str(user_id)[:8]}"


# --- Per-user helpers ------------------------------------------------------
#
# Story 5.3 — JSON dump shape SOT는 ``app.services.data_export_service``로 이전됨.
# 본 worker는 ``collect_user_export_payload(..., include_soft_deleted_meals=True)`` 호출로
# 갈아끼움(DF136 forward-hook 즉시 해소) — *전체 set*(``meal_analyses`` 포함)으로
# PIPA Art.21 30일 grace 사용자 회복 권리 강화.


async def _dump_user_to_r2(
    r2_adapter: Any,
    user_id: uuid.UUID,
    dump_bucket: str,
    payload: dict[str, Any],
) -> None:
    """JSON dump → ``purge-dumps/{user_id}/{yyyy-mm-ddTHHMMSS}.json`` PUT.

    bucket lifecycle policy(30일 자동 삭제)는 Cloudflare 콘솔 측 SOT — 본 worker는
    PUT만 수행. ``r2_adapter``는 ``app.adapters.r2`` 모듈 자체(boto3 lazy singleton).

    CR P3 — key에 시각 suffix 포함하여 same-day 재시도 시 silent overwrite 차단(이전
    dump 보존 + 운영자가 history 식별 가능).
    CR P2 — boto3 sync put_object는 event loop 차단 → ``asyncio.to_thread`` 위임.
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    key = f"purge-dumps/{user_id}/{timestamp}.json"
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    client = r2_adapter._get_client()  # noqa: SLF001 — 인접 worker는 어댑터 lazy singleton 직접 사용.
    await asyncio.to_thread(
        client.put_object,
        Bucket=dump_bucket,
        Key=key,
        Body=body,
        ContentType="application/json; charset=utf-8",
    )


async def _cleanup_user_r2_images(
    r2_adapter: Any,
    user_id: uuid.UUID,
) -> int:
    """``meals/{user_id}/`` prefix list_objects_v2 + delete_objects(batch 1000건 cap).

    Returns 삭제된 객체 수. R2/S3 표준 paginator 패턴 — ``ContinuationToken``으로 다음
    페이지 진입. r2_adapter None 또는 R2 미설정은 호출 측에서 가드(본 함수는 client 가져옴).

    CR P2 — boto3 sync 호출(list_objects_v2/delete_objects)은 event loop 차단 →
    ``asyncio.to_thread`` 위임. 새벽 3시 sweep 동안 HTTP 요청 차단 회피.
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
        response = await asyncio.to_thread(client.list_objects_v2, **kwargs)
        objects = response.get("Contents", [])
        if objects:
            keys = [{"Key": obj["Key"]} for obj in objects]
            await asyncio.to_thread(
                client.delete_objects,
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

    Returns per-user stats(dump=0|1, images=N, purged=0|1, dump_errors=0|1,
    cleanup_errors=0|1, errors=0|1). 실패는 격리되어 sweep 전체를 중단시키지 않음.

    CR D1 — dump 실패는 inner try로 격리 + ``stats["dump_errors"]+=1`` + sentry capture
    후 cleanup + DB DELETE 계속 진행(PIPA Art.21 30일 mandate 우선). 운영자는 sentry로
    즉시 인지.
    """
    masked = _mask_user_id(user_id)
    stats = {
        "dumped": 0,
        "images_cleaned": 0,
        "purged": 0,
        "dump_errors": 0,
        "cleanup_errors": 0,
        "errors": 0,
    }

    try:
        with sentry_sdk.start_span(op="purge.user", name="purge.user") as span:
            span.set_tag("user_id_masked", masked)

            # 1) R2 dump (선택 — bucket 미설정 시 skip).
            #    CR D1 — dump 실패도 inner try로 isolated → cleanup + DELETE는 계속 진행
            #    (PIPA 컴플라이언스 우선 + sentry로 운영자 즉시 인지).
            if dump_bucket and r2_adapter is not None:
                try:
                    async with session_maker() as session:
                        # Story 5.3 — service SOT 갈아끼움(DF136). worker는 *전체 set*
                        # (meal_analyses 포함 + soft-deleted meals 포함)으로 dump — PIPA
                        # Art.21 30일 grace 사용자 *전체 history* 회복 권리.
                        payload = await collect_user_export_payload(
                            session, user_id, include_soft_deleted_meals=True
                        )
                    if payload is not None:
                        await _dump_user_to_r2(r2_adapter, user_id, dump_bucket, payload)
                        stats["dumped"] = 1
                        logger.info("purge.user.dumped", user_id=masked, bucket=dump_bucket)
                    else:
                        # CR P11 — race(이미 다른 sweep cycle이 hard-deleted) 명시 신호.
                        logger.warning("purge.dump_user_missing", user_id=masked)
                except Exception as exc:  # noqa: BLE001 — dump 실패는 DB DELETE를 막지 않음(PIPA).
                    sentry_sdk.capture_exception(exc)
                    stats["dump_errors"] = 1
                    logger.error(
                        "purge.user.dump_failed",
                        user_id=masked,
                        bucket=dump_bucket,
                        reason=type(exc).__name__,
                    )
            else:
                logger.info(
                    "purge.dump_skipped",
                    user_id=masked,
                    reason="bucket_unset" if not dump_bucket else "adapter_none",
                )

            # 2) R2 meal images cleanup (선택 — adapter 미주입 시 skip).
            if r2_adapter is not None:
                try:
                    cleaned = await _cleanup_user_r2_images(r2_adapter, user_id)
                    stats["images_cleaned"] = cleaned
                    logger.info("purge.user.images_cleaned", user_id=masked, count=cleaned)
                except Exception as exc:  # noqa: BLE001 — R2 transient 실패는 DB delete를 막지 않음.
                    sentry_sdk.capture_exception(exc)
                    # CR P6 — cleanup 실패도 stats["cleanup_errors"]에 기록(운영자가 sweep
                    # stats만 보고도 R2 orphan 위험 인지 가능). dump_errors와 분리 — 원인 분리.
                    stats["cleanup_errors"] = 1
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
    ``r2_dumps_count`` / ``r2_images_cleaned_count`` / ``dump_errors_count`` /
    ``cleanup_errors_count`` / ``errors_count``.
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
        "dump_errors_count": 0,
        "cleanup_errors_count": 0,
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
            stats["dump_errors_count"] += user_stats["dump_errors"]
            stats["cleanup_errors_count"] += user_stats["cleanup_errors"]
            stats["errors_count"] += user_stats["errors"]

        transaction.set_tag("users_purged_count", stats["users_purged_count"])
        transaction.set_tag("dump_errors_count", stats["dump_errors_count"])
        transaction.set_tag("cleanup_errors_count", stats["cleanup_errors_count"])
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
        dump_errors_count=stats["dump_errors_count"],
        cleanup_errors_count=stats["cleanup_errors_count"],
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

    CR P7 — daily cron이라 nudge SOT 600s grace가 너무 짧음. 컨테이너 10분+ 재기동 시
    sweep cycle 자체 silent skip 회피 위해 6h(_PURGE_MISFIRE_GRACE_SECONDS) override.
    sweep 멱등성(rowcount=0 가드 + cutoff 동일)이 늦은 실행을 안전하게 흡수.
    """
    _ = redis  # forward use
    scheduler.add_job(
        purge_expired_soft_deleted_users,
        trigger=CronTrigger(hour=3, minute=0, timezone="Asia/Seoul"),
        args=[session_maker, r2_adapter],
        id=PURGE_JOB_ID,
        replace_existing=True,
        misfire_grace_time=_PURGE_MISFIRE_GRACE_SECONDS,
    )
    logger.info("purge.job.registered", job_id=PURGE_JOB_ID)


__all__ = [
    "PURGE_GRACE_DAYS",
    "PURGE_JOB_ID",
    "purge_expired_soft_deleted_users",
    "register_purge_job",
]
