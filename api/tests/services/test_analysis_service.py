"""Story 3.3 — `AnalysisService` 종단 + 인터페이스 테스트 (AC8)."""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient

from app.core.config import settings
from app.graph.checkpointer import build_checkpointer, dispose_checkpointer
from app.graph.deps import NodeDeps
from app.graph.pipeline import compile_pipeline
from app.services.analysis_service import AnalysisService
from tests.conftest import UserFactory


@pytest_asyncio.fixture
async def analysis_service(client: AsyncClient) -> AnalysisService:
    """별 checkpointer pool 빌드 + 컴파일된 graph로 service 인스턴스화."""
    _ = client  # ensure lifespan started
    from app.main import app

    deps = NodeDeps(
        session_maker=app.state.session_maker,
        redis=app.state.redis,
        settings=settings,
    )
    checkpointer, pool = await build_checkpointer(settings.database_url)
    graph = compile_pipeline(checkpointer, deps)
    service = AnalysisService(graph=graph, deps=deps)
    yield service  # type: ignore[misc]
    await dispose_checkpointer(pool)


async def test_run_returns_state_with_stub_feedback(
    user_factory: UserFactory,
    analysis_service: AnalysisService,
) -> None:
    user = await user_factory(profile_completed=True)
    state = await analysis_service.run(
        meal_id=uuid.uuid4(),
        user_id=user.id,
        raw_text="짜장면",
    )
    assert state["feedback"].used_llm == "stub"
    assert state["feedback"].text == "(분석 준비 중)"
    assert state["fit_evaluation"].fit_score == 50


async def test_run_default_thread_id_uses_meal_prefix(
    user_factory: UserFactory,
    analysis_service: AnalysisService,
) -> None:
    """`thread_id` 미지정 시 `meal:{meal_id}` — checkpoint 멱등 가드."""
    user = await user_factory(profile_completed=True)
    meal_id = uuid.uuid4()
    await analysis_service.run(meal_id=meal_id, user_id=user.id, raw_text="짜장면")
    snap = await analysis_service.aget_state(thread_id=f"meal:{meal_id}")
    assert snap["user_profile"].user_id == user.id


async def test_aget_state_unknown_thread_returns_empty(
    analysis_service: AnalysisService,
) -> None:
    """unknown thread_id → 빈 state — graceful (Story 3.4 흐름 정합)."""
    snap = await analysis_service.aget_state(thread_id=f"unknown-{uuid.uuid4()}")
    # graph.aget_state는 unknown thread에서 비어있는 StateSnapshot.values 반환
    assert snap == {} or snap.get("user_profile") is None


async def test_aresume_passes_through_to_ainvoke(
    user_factory: UserFactory,
    analysis_service: AnalysisService,
) -> None:
    """`aresume`은 본 스토리 *인터페이스 박기*만 — thin pass-through."""
    user = await user_factory(profile_completed=True)
    thread_id = f"thread-{uuid.uuid4()}"
    initial_state = {
        "meal_id": uuid.uuid4(),
        "user_id": user.id,
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
        "needs_clarification": False,
    }
    state = await analysis_service.aresume(thread_id=thread_id, user_input=initial_state)
    assert state["fit_evaluation"].fit_score == 50
