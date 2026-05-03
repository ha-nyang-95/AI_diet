"""Story 3.3 — `app/main.py` lifespan에서 LangGraph 4 자원 init 검증 (AC11)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.adapters.openai_adapter import (
    ClarificationVariants,
    ParsedMeal,
    ParsedMealItem,
    RewriteVariants,
)
from app.core.exceptions import AnalysisCheckpointerError
from app.graph.state import ClarificationOption
from app.main import app, lifespan
from app.services.analysis_service import AnalysisService


@pytest.fixture
def _mock_llm_adapters() -> Iterator[None]:
    parsed = ParsedMeal(
        items=[ParsedMealItem(name="__test_low_confidence__", quantity="1인분", confidence=0.9)]
    )
    rewrite = RewriteVariants(variants=["v1"])
    clarify = ClarificationVariants(options=[ClarificationOption(label="옵션", value="옵션 1인분")])
    with (
        patch(
            "app.graph.nodes.parse_meal.parse_meal_text",
            new=AsyncMock(return_value=parsed),
        ),
        patch(
            "app.graph.nodes.rewrite_query.rewrite_food_query",
            new=AsyncMock(return_value=rewrite),
        ),
        patch(
            "app.graph.nodes.request_clarification.generate_clarification_options",
            new=AsyncMock(return_value=clarify),
        ),
    ):
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
