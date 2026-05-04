"""Shared fixtures + SSE parsing helper for /v1/analysis/* router tests (Story 3.7)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.meal import Meal
from app.db.models.user import User
from app.graph.state import (
    Citation,
    FeedbackOutput,
    FitEvaluation,
    FoodItem,
    MealAnalysisState,
    NodeError,
    RetrievalResult,
    RetrievedFood,
)
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _clear_rate_limit_keys(client: AsyncClient) -> AsyncIterator[None]:
    """매 테스트 *시작 전* analysis rate limit Redis 키 정리(테스트 간 분당 10회 누적 차단).

    fixed-window 키 패턴 ``rl:analysis:langgraph:*`` 만 SCAN+DEL — 다른 테스트 데이터
    영향 X. Redis 미설정 환경에서는 graceful skip(`app.state.redis is None`).
    """
    _ = client
    redis_client = getattr(app.state, "redis", None)
    if redis_client is None:
        yield
        return
    try:
        async for key in redis_client.scan_iter(match="rl:analysis:langgraph:*"):
            await redis_client.delete(key)
    except Exception:  # noqa: BLE001 — graceful, Redis 장애 시 fixture가 fail 막지 않음.
        pass
    yield


@pytest_asyncio.fixture
async def mock_analysis_service(client: AsyncClient) -> AsyncIterator[AsyncMock]:
    """``app.state.analysis_service``를 AsyncMock으로 교체 — SSE generator deterministic.

    teardown 시 원본 서비스로 복원(다른 테스트 간 leak 차단).
    """
    _ = client  # ensure lifespan started
    original = app.state.analysis_service
    mock = AsyncMock()
    mock.run = AsyncMock()
    mock.aget_state = AsyncMock()
    mock.aresume = AsyncMock()
    app.state.analysis_service = mock
    try:
        yield mock
    finally:
        app.state.analysis_service = original


@pytest_asyncio.fixture
async def meal_factory(client: AsyncClient):
    """test DB에 meals row를 INSERT하는 async factory."""
    _ = client
    session_maker: async_sessionmaker = app.state.session_maker

    async def _make(
        user: User,
        *,
        raw_text: str = "오늘 점심 김치찌개와 공깃밥",
        deleted: bool = False,
    ) -> Meal:
        async with session_maker() as session:
            meal = Meal(
                user_id=user.id,
                raw_text=raw_text,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            session.add(meal)
            await session.commit()
            await session.refresh(meal)
            return meal

    return _make


def parse_sse_text(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Raw SSE response body → list of (event_name, parsed_data dict).

    sse_starlette 표준 인코딩(``\\r\\n`` 구분, ``event: NAME\\ndata: JSON\\n\\n``) 파싱.
    """
    events: list[tuple[str, dict[str, Any]]] = []
    current_event = ""
    current_data_lines: list[str] = []
    # \r\n 또는 \n 양쪽 호환.
    normalized = text.replace("\r\n", "\n")
    for line in normalized.split("\n"):
        if line == "":
            if current_event:
                payload: dict[str, Any] = {}
                if current_data_lines:
                    # SSE spec: 다중 ``data:`` 라인은 ``\n``으로 결합 (RFC 8895 §9.2.4).
                    # CR Wave 1 #13 — 이전 ``"".join``은 멀티라인 JSON에서 silent
                    # corruption 가능 (e.g. multi-line message body).
                    raw = "\n".join(current_data_lines)
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {"_raw": raw}
                events.append((current_event, payload))
            current_event = ""
            current_data_lines = []
            continue
        if line.startswith("event: "):
            current_event = line[len("event: ") :]
        elif line.startswith("data: "):
            current_data_lines.append(line[len("data: ") :])
        # ``: ``(comment) / ``id: ``/``retry: ``는 무시.
    return events


def make_done_state(
    *,
    fit_score: int = 72,
    fit_label: str = "caution",
    fit_reason: str = "ok",
    feedback_text: str = "오늘 식단은 단백질 보충이 필요해요.",
    citations: list[Citation] | None = None,
    used_llm: str = "gpt-4o-mini",
) -> MealAnalysisState:
    """Helper — feedback 정상 종료 상태(stream 라우터의 done 분기 입력)."""
    if citations is None:
        citations = [
            Citation(source="MFDS", doc_title="알레르기 22종", published_year=2022),
        ]
    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "테스트 raw text",
        "rewrite_attempts": 0,
        "node_errors": [],
        "needs_clarification": False,
        "parsed_items": [
            FoodItem(name="김치찌개", quantity="1인분", confidence=0.9),
        ],
        "retrieval": RetrievalResult(
            retrieved_foods=[
                RetrievedFood(
                    name="김치찌개",
                    food_id=None,
                    score=0.9,
                    nutrition={
                        "energy_kcal": 250.0,
                        "carbohydrate_g": 30.0,
                        "protein_g": 15.0,
                        "fat_g": 8.0,
                        "fiber_g": 4.0,
                    },
                )
            ],
            retrieval_confidence=0.9,
        ),
        "fit_evaluation": FitEvaluation(
            fit_score=fit_score,
            reasons=["macro 양호"],
            fit_reason=fit_reason,
            fit_label=fit_label,
        ),
        "feedback": FeedbackOutput(
            text=feedback_text,
            citations=citations,
            used_llm=used_llm,
        ),
    }


def make_clarify_state() -> MealAnalysisState:
    """Helper — needs_clarification=True 분기 입력."""
    from app.graph.state import ClarificationOption

    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "포케",
        "rewrite_attempts": 1,
        "node_errors": [],
        "needs_clarification": True,
        "clarification_options": [
            ClarificationOption(label="연어 포케", value="연어 포케 1인분"),
            ClarificationOption(label="참치 포케", value="참치 포케 1인분"),
        ],
    }


def make_node_error_state() -> MealAnalysisState:
    """Helper — node_errors 진입 + feedback 부재(error edge)."""
    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "테스트",
        "rewrite_attempts": 0,
        "needs_clarification": False,
        "node_errors": [
            NodeError(
                node_name="generate_feedback",
                error_class="LLMRouterExhaustedError",
                message="dual exhausted",
                attempts=2,
            )
        ],
    }
