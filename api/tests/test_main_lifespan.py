"""Story 3.3 — `app/main.py` lifespan에서 LangGraph 4 자원 init 검증 (AC11)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.exceptions import AnalysisCheckpointerError
from app.main import app, lifespan
from app.services.analysis_service import AnalysisService


@pytest.fixture
def _mock_llm_adapters() -> Iterator[None]:
    """Story 3.9 AC16 — conftest SOT(`make_llm_adapter_mocks`) 위임."""
    from tests.conftest import make_llm_adapter_mocks

    with make_llm_adapter_mocks():
        yield


async def test_lifespan_initializes_analysis_resources(client: AsyncClient) -> None:
    """lifespan 진입 후 `app.state`에 4 자원이 채워졌는지."""
    _ = client  # ensure lifespan started
    assert getattr(app.state, "checkpointer", None) is not None
    assert getattr(app.state, "checkpointer_pool", None) is not None
    assert getattr(app.state, "graph", None) is not None
    assert isinstance(getattr(app.state, "analysis_service", None), AnalysisService)


async def test_lifespan_dispatch_to_analysis_service(
    client: AsyncClient, _mock_llm_adapters: None
) -> None:
    """`app.state.analysis_service.run`이 호출 가능 — `AnalysisService` 등록 정합.

    미존재 user → `fetch_user_profile`이 `AnalysisNodeError` → `route_after_node_error`
    가 `"end"` 분기 → 후속 노드 미진행. node_errors 누적만 확인.
    """
    _ = client
    service: AnalysisService = app.state.analysis_service
    state = await service.run(
        meal_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="__test_low_confidence__",  # sentinel — DB lookup 회피, 0.85 boost
    )
    errs = state.get("node_errors", [])
    assert any(e.node_name == "fetch_user_profile" and "user_not_found" in e.message for e in errs)
    assert state.get("user_profile") is None
    assert state.get("feedback") is None


async def test_lifespan_graceful_when_checkpointer_init_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11 graceful — DB-down 시 `app.state.graph is None` + 앱 동작 유지 (D10).

    `build_checkpointer`를 `AnalysisCheckpointerError`로 강제 실패시킨 후 lifespan을
    수동 진입 — engine/redis는 정상 init되지만 checkpointer/graph/service는 None.
    """
    test_app = FastAPI(lifespan=lifespan)

    async def _fail(*args: object, **kwargs: object) -> tuple[None, None]:
        raise AnalysisCheckpointerError("checkpointer.setup_failed")

    monkeypatch.setattr("app.main.build_checkpointer", _fail)

    async with lifespan(test_app):
        # graceful — 앱 자체는 yield까지 도달.
        assert getattr(test_app.state, "checkpointer", "missing") is None
        assert getattr(test_app.state, "checkpointer_pool", "missing") is None
        assert getattr(test_app.state, "graph", "missing") is None
        assert getattr(test_app.state, "analysis_service", "missing") is None
        # engine/redis는 정상 init.
        assert getattr(test_app.state, "session_maker", None) is not None


async def test_lifespan_graceful_when_setup_raises_generic_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11 graceful — `setup()` 내부 generic Exception(스키마 mismatch / 버전 mismatch
    등)도 graceful로 흘려야 함. `AnalysisCheckpointerError` 외 분기."""
    test_app = FastAPI(lifespan=lifespan)

    async def _fail_generic(*args: object, **kwargs: object) -> tuple[None, None]:
        raise RuntimeError("schema mismatch — DuplicateTable equivalent")

    monkeypatch.setattr("app.main.build_checkpointer", _fail_generic)

    async with lifespan(test_app):
        assert getattr(test_app.state, "graph", "missing") is None
        assert getattr(test_app.state, "analysis_service", "missing") is None


# Story 4.2 — scheduler 5번째 자원 lifespan 검증 (AC4)


async def test_lifespan_scheduler_disabled_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``environment="test"``는 scheduler init skip — ``app.state.scheduler is None``.

    Story 4.2 AC2 — 분 단위 cron이 pytest 격리를 깨지 않도록 ci/test는 fail-closed 정합.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "test")
    test_app = FastAPI(lifespan=lifespan)
    async with lifespan(test_app):
        assert getattr(test_app.state, "scheduler", "missing") is None


async def test_lifespan_scheduler_initializes_in_dev_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``environment="dev"``는 scheduler init + nudge job 등록 검증.

    ``app.state.scheduler``가 존재 + ``running=True`` + ``nudge_sweep_unrecorded_meals``
    잡 등록.
    """
    from app.core.config import settings
    from app.workers.nudge_scheduler import NUDGE_JOB_ID

    monkeypatch.setattr(settings, "environment", "dev")
    test_app = FastAPI(lifespan=lifespan)
    async with lifespan(test_app):
        scheduler = getattr(test_app.state, "scheduler", None)
        assert scheduler is not None
        assert scheduler.running is True
        jobs = scheduler.get_jobs()
        assert any(job.id == NUDGE_JOB_ID for job in jobs)
    # cleanup 후 running=False (lifespan exit 시 ``shutdown_scheduler`` 호출).
    # Note: AsyncIOScheduler.shutdown은 event loop schedule이라 즉시 검증은 생략.
