"""Story 3.3 — `app/main.py` lifespan에서 LangGraph 4 자원 init 검증 (AC11)."""

from __future__ import annotations

from httpx import AsyncClient

from app.main import app
from app.services.analysis_service import AnalysisService


async def test_lifespan_initializes_analysis_resources(client: AsyncClient) -> None:
    """lifespan 진입 후 `app.state`에 4 자원이 채워졌는지."""
    _ = client  # ensure lifespan started
    assert getattr(app.state, "checkpointer", None) is not None
    assert getattr(app.state, "checkpointer_pool", None) is not None
    assert getattr(app.state, "graph", None) is not None
    assert isinstance(getattr(app.state, "analysis_service", None), AnalysisService)


async def test_lifespan_dispatch_to_analysis_service(client: AsyncClient) -> None:
    """`app.state.analysis_service.run`이 호출 가능 — `AnalysisService` 등록 정합."""
    import uuid

    from tests.conftest import auth_headers  # noqa: F401  ensure helper loadable

    _ = client
    service: AnalysisService = app.state.analysis_service
    # 미존재 user → fetch_user_profile NodeError, 그래도 stub 흐름 종료(node_errors 누적).
    state = await service.run(
        meal_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="짜장면",
    )
    assert state["feedback"].used_llm == "stub"
