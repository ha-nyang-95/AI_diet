"""Story 4.2 AC2 — `app.workers.scheduler` 단위 테스트.

``build_scheduler``의 timezone SOT + ``start/shutdown`` running 상태 transition.
``environment="test"``에서 ``start_scheduler``는 즉시 return(잡 등록 skip 가드).
"""

from __future__ import annotations

import zoneinfo
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.workers.scheduler import build_scheduler, shutdown_scheduler, start_scheduler


def test_build_scheduler_timezone_kst() -> None:
    """``timezone='Asia/Seoul'`` SOT — Story 4.1 ``notification_timezone`` default 컬럼 정합."""
    scheduler = build_scheduler()
    assert isinstance(scheduler, AsyncIOScheduler)
    # APScheduler는 IANA tz string을 ``zoneinfo.ZoneInfo`` 또는 pytz 객체로 보관.
    tz = scheduler.timezone
    tz_name = getattr(tz, "key", None) or getattr(tz, "zone", None) or str(tz)
    assert tz_name == "Asia/Seoul"
    assert isinstance(tz, zoneinfo.ZoneInfo)


@pytest.mark.asyncio
async def test_start_scheduler_skipped_in_test_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``environment="test"``는 ``start_scheduler`` 즉시 return — scheduler.start 호출 X.

    *Why*: pytest 격리 — APScheduler 백그라운드 thread/loop가 다른 테스트로 leak되지
    않게 fail-closed. ``app.state.scheduler``는 lifespan에서 None 유지.
    """
    fake_app = SimpleNamespace(state=SimpleNamespace(scheduler=build_scheduler()))
    # `settings.environment`는 conftest가 `test`로 강제하지 않지만, env_file에서 dev로
    # 로드 가능 — monkeypatch으로 명시.
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "test")
    await start_scheduler(fake_app)
    assert fake_app.state.scheduler.running is False


@pytest.mark.asyncio
async def test_start_and_shutdown_scheduler_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``environment != "test"|"ci"``에서 start → running True / shutdown → running False.

    AsyncIOScheduler의 ``shutdown``은 ``@run_in_event_loop`` 데코레이션이라 asyncio
    schedule 후 동기 return — 실제 state 전환을 보려면 event loop tick 한 번 필요.
    """
    import asyncio

    fake_app = SimpleNamespace(state=SimpleNamespace(scheduler=build_scheduler()))
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "dev")
    try:
        await start_scheduler(fake_app)
        assert fake_app.state.scheduler.running is True
    finally:
        await shutdown_scheduler(fake_app)
        # shutdown은 event loop schedule 후 return — tick으로 실 state 전환 대기.
        for _ in range(10):
            if not fake_app.state.scheduler.running:
                break
            await asyncio.sleep(0.01)
    assert fake_app.state.scheduler.running is False
