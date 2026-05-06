"""APScheduler ``AsyncIOScheduler`` SOT — Story 4.2 (AC2).

`architecture.md:1088` *APScheduler in-process AsyncIOScheduler + FastAPI lifespan SOT*
정합. 1인 8주 단일 노드 정합 — multi-replica는 Story 8.5 hardening forward.

3 helper:
- ``build_scheduler()`` — ``timezone='Asia/Seoul'`` SOT(Story 4.1 ``notification_timezone``
  default 컬럼 정합) + ``AsyncIOExecutor`` + ``coalesce=True`` / ``max_instances=1`` /
  ``misfire_grace_time=600``(10분 grace — 짧은 downtime 보정).
- ``start_scheduler(app)`` / ``shutdown_scheduler(app)`` — lifespan 통합. ``environment in
  {"ci","test"}``는 init 즉시 return(테스트 안정성).

scheduler 자체는 in-process라 Redis/DB 의존성 X — 부팅 차단 X. 잡 등록은
``register_nudge_job(scheduler, session_maker, redis)``(``nudge_scheduler.py`` 책임).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger(__name__)

# Story 4.2 — 1인 8주 단일 노드 정합. multi-replica 시점에는 ``apscheduler-postgres``
# JobStore 도입 또는 cron 외부화(Railway Cron / GitHub Actions schedule) 검토 — Story 8.5
# hardening forward.
_SCHEDULER_TIMEZONE = "Asia/Seoul"

# coalesce=True — 컨테이너 재시작 시 missed window를 1회로 합쳐 발사(중복 방지).
# max_instances=1 — 동시 실행 1건 cap(이전 sweep이 길어져도 다음 cycle이 겹치지 않음).
# misfire_grace_time=600 — 10분 grace(짧은 downtime 보정 / 이를 초과한 missed는 skip).
_JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 600,
}

# environment 분기 — pytest 격리 보장 + CI 안정성.
_DISABLED_ENVIRONMENTS = frozenset({"ci", "test"})


def build_scheduler() -> AsyncIOScheduler:
    """``AsyncIOScheduler`` 단일 인스턴스 생성 — KST + AsyncIOExecutor + 안전 defaults."""
    return AsyncIOScheduler(
        timezone=_SCHEDULER_TIMEZONE,
        executors={"default": AsyncIOExecutor()},
        job_defaults=_JOB_DEFAULTS,
    )


async def start_scheduler(app: FastAPI) -> None:
    """``app.state.scheduler.start()`` 호출 — environment 분기 반영.

    test/ci 환경은 즉시 return(``app.state.scheduler``는 None 유지, 잡 등록도 skip).
    """
    if settings.environment in _DISABLED_ENVIRONMENTS:
        logger.info(
            "scheduler.start.disabled_for_environment",
            environment=settings.environment,
        )
        return
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        logger.warning("scheduler.start.skipped_no_instance")
        return
    if scheduler.running:
        logger.warning("scheduler.start.already_running")
        return
    scheduler.start()
    logger.info("scheduler.started", timezone=_SCHEDULER_TIMEZONE)


async def shutdown_scheduler(app: FastAPI) -> None:
    """graceful shutdown — ``wait=False``로 진행 중인 잡을 중단(짧은 lifespan 종료).

    이미 멈춰있거나 instance가 None이면 no-op.
    """
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return
    if not scheduler.running:
        return
    try:
        scheduler.shutdown(wait=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduler.shutdown_failed", error=str(exc))
    else:
        logger.info("scheduler.shutdown")


__all__ = [
    "build_scheduler",
    "shutdown_scheduler",
    "start_scheduler",
]
