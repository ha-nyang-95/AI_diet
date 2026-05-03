"""Story 3.4 — `retrieve_nutrition` 노드 *실 비즈니스 로직* 단위 테스트 (AC6).

mock session_maker + monkeypatch ``lookup_canonical``/``search_by_name``/
``search_by_embedding`` — DB / OpenAI 도달 X. Story 3.3 sentinel 회귀 가드 보존.

케이스:
1. seeded ``"자장면"`` → alias hit → exact hit ``"짜장면"`` → confidence 1.0,
2. seeded ``"짜장면"`` (alias 미스 + exact hit) → confidence 1.0,
3. ``"임의의_음식_xyz"`` (alias 미스 + exact 미스) → HNSW top-3 + 정규화 score,
4. 빈 ``parsed_items`` → 빈 리스트 + 0.0,
5. sentinel ``"__test_low_confidence__"`` + ``rewrite_attempts=0`` → confidence 0.3,
6. sentinel + ``rewrite_attempts > 0`` → 0.85 boost,
7. multi-item + 한 항목 신뢰도 낮음 → ``compute_retrieval_confidence(min)`` 검증,
8. ``rewrite_attempts > 0`` + ``rewritten_query`` → alias/exact skip + 임베딩 직진.
"""

from __future__ import annotations

import contextlib
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.deps import NodeDeps
from app.graph.nodes.retrieve_nutrition import retrieve_nutrition
from app.graph.state import FoodItem, MealAnalysisState, RetrievedFood

retrieve_module = sys.modules["app.graph.nodes.retrieve_nutrition"]


def _state(
    *,
    items: list[FoodItem] | None = None,
    rewrite_attempts: int = 0,
    rewritten_query: str | None = None,
) -> MealAnalysisState:
    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "x",
        "parsed_items": items if items is not None else [FoodItem(name="짜장면", confidence=0.5)],
        "rewrite_attempts": rewrite_attempts,
        "rewritten_query": rewritten_query,
        "node_errors": [],
    }


def _build_session_maker() -> MagicMock:
    session = MagicMock()

    @contextlib.asynccontextmanager
    async def _maker() -> Any:
        yield session

    maker = MagicMock(side_effect=_maker)
    return maker


def _make_deps(maker: MagicMock, *, environment: str = "test") -> NodeDeps:
    from app.core.config import settings as _real_settings

    # `settings.environment`를 monkeypatch하지 않고 wrapping 객체 사용.
    settings_proxy = MagicMock(wraps=_real_settings)
    settings_proxy.environment = environment
    return NodeDeps(session_maker=maker, redis=None, settings=settings_proxy)


# ---------------------------------------------------------------------------
# 1. alias hit → exact hit
# ---------------------------------------------------------------------------


async def test_retrieve_alias_hit_then_exact_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """seeded "자장면" → alias hit → exact "짜장면" → confidence 1.0."""
    maker = _build_session_maker()
    deps = _make_deps(maker)

    monkeypatch.setattr(retrieve_module, "lookup_canonical", AsyncMock(return_value="짜장면"))
    food_id = uuid.uuid4()
    exact_match = RetrievedFood(
        name="짜장면", food_id=food_id, score=1.0, nutrition={"energy_kcal": 700}
    )
    monkeypatch.setattr(retrieve_module, "search_by_name", AsyncMock(return_value=exact_match))
    embedding_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(retrieve_module, "search_by_embedding", embedding_mock)

    state = _state(items=[FoodItem(name="자장면", confidence=0.5)])
    out = await retrieve_nutrition(state, deps=deps)

    assert out["retrieval"].retrieval_confidence == pytest.approx(1.0)
    assert len(out["retrieval"].retrieved_foods) == 1
    assert out["retrieval"].retrieved_foods[0].name == "짜장면"
    assert embedding_mock.await_count == 0  # exact hit — embedding skip


# ---------------------------------------------------------------------------
# 2. alias miss + exact hit
# ---------------------------------------------------------------------------


async def test_retrieve_alias_miss_exact_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """seeded "짜장면" (alias 미스 + exact hit) → confidence 1.0."""
    maker = _build_session_maker()
    deps = _make_deps(maker)

    monkeypatch.setattr(retrieve_module, "lookup_canonical", AsyncMock(return_value=None))
    exact = RetrievedFood(name="짜장면", food_id=None, score=1.0, nutrition={})
    monkeypatch.setattr(retrieve_module, "search_by_name", AsyncMock(return_value=exact))
    monkeypatch.setattr(retrieve_module, "search_by_embedding", AsyncMock(return_value=[]))

    state = _state(items=[FoodItem(name="짜장면", confidence=0.5)])
    out = await retrieve_nutrition(state, deps=deps)
    assert out["retrieval"].retrieval_confidence == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3. alias miss + exact miss → HNSW fallback
# ---------------------------------------------------------------------------


async def test_retrieve_hnsw_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """alias/exact 미스 → HNSW top-3 + 정규화 score."""
    maker = _build_session_maker()
    deps = _make_deps(maker)

    monkeypatch.setattr(retrieve_module, "lookup_canonical", AsyncMock(return_value=None))
    monkeypatch.setattr(retrieve_module, "search_by_name", AsyncMock(return_value=None))
    matches = [
        RetrievedFood(name="유사1", food_id=None, score=0.78, nutrition={}),
        RetrievedFood(name="유사2", food_id=None, score=0.65, nutrition={}),
    ]
    monkeypatch.setattr(retrieve_module, "search_by_embedding", AsyncMock(return_value=matches))

    state = _state(items=[FoodItem(name="임의의_음식_xyz", confidence=0.5)])
    out = await retrieve_nutrition(state, deps=deps)
    # top-1 score 0.78
    assert out["retrieval"].retrieval_confidence == pytest.approx(0.78)
    assert out["retrieval"].retrieved_foods[0].name == "유사1"


# ---------------------------------------------------------------------------
# 4. 빈 parsed_items
# ---------------------------------------------------------------------------


async def test_retrieve_empty_parsed_items() -> None:
    maker = _build_session_maker()
    deps = _make_deps(maker)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "",
        "parsed_items": [],
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await retrieve_nutrition(state, deps=deps)
    assert out["retrieval"].retrieved_foods == []
    assert out["retrieval"].retrieval_confidence == 0.0


# ---------------------------------------------------------------------------
# 5/6. sentinel 분기 + boost (Story 3.3 회귀)
# ---------------------------------------------------------------------------


async def test_retrieve_sentinel_low_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """sentinel + rewrite_attempts=0 → confidence 0.3."""
    maker = _build_session_maker()
    deps = _make_deps(maker, environment="test")

    state = _state(items=[FoodItem(name="__test_low_confidence__", confidence=0.5)])
    out = await retrieve_nutrition(state, deps=deps)
    assert out["retrieval"].retrieval_confidence == 0.3
    assert out["retrieval"].retrieved_foods == []


async def test_retrieve_sentinel_boost_after_rewrite() -> None:
    """sentinel + rewrite_attempts > 0 → confidence 0.85 boost."""
    maker = _build_session_maker()
    deps = _make_deps(maker, environment="test")

    state = _state(
        items=[FoodItem(name="__test_low_confidence__", confidence=0.5)],
        rewrite_attempts=1,
    )
    out = await retrieve_nutrition(state, deps=deps)
    assert out["retrieval"].retrieval_confidence == 0.85
    assert len(out["retrieval"].retrieved_foods) == 1


async def test_retrieve_low_confidence_substring_in_test_env() -> None:
    """dev/test/ci 환경 + name에 "low_confidence" 포함 → 0.3."""
    maker = _build_session_maker()
    deps = _make_deps(maker, environment="test")

    state = _state(items=[FoodItem(name="low_confidence_food", confidence=0.5)])
    out = await retrieve_nutrition(state, deps=deps)
    assert out["retrieval"].retrieval_confidence == 0.3


# ---------------------------------------------------------------------------
# 7. multi-item — compute_retrieval_confidence(min)
# ---------------------------------------------------------------------------


async def test_retrieve_multi_item_min_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """2 items: 한 항목 score=1.0 + 다른 0.4 → 최소값 0.4 채택 (보수적)."""
    maker = _build_session_maker()
    deps = _make_deps(maker, environment="prod")

    monkeypatch.setattr(retrieve_module, "lookup_canonical", AsyncMock(return_value=None))

    rf_high = RetrievedFood(name="짜장면", food_id=None, score=1.0, nutrition={})
    rf_low = RetrievedFood(name="모호한_음식", food_id=None, score=0.4, nutrition={})

    async def _exact(_: Any, name: str) -> RetrievedFood | None:
        return rf_high if name == "짜장면" else None

    async def _embedding(_: Any, query: str) -> list[RetrievedFood]:
        return [rf_low] if "임의" in query else []

    monkeypatch.setattr(retrieve_module, "search_by_name", _exact)
    monkeypatch.setattr(retrieve_module, "search_by_embedding", _embedding)

    state = _state(
        items=[
            FoodItem(name="짜장면", confidence=0.9),
            FoodItem(name="임의의_음식", confidence=0.5),
        ]
    )
    out = await retrieve_nutrition(state, deps=deps)
    assert len(out["retrieval"].retrieved_foods) == 2
    # multi-item — min(1.0, 0.4) = 0.4
    assert out["retrieval"].retrieval_confidence == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# 8. rewrite_attempts > 0 + rewritten_query → 임베딩 직진
# ---------------------------------------------------------------------------


async def test_retrieve_after_rewrite_uses_rewritten_query_embedding_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rewrite_attempts > 0 → alias/exact skip + rewritten_query 임베딩 직진."""
    maker = _build_session_maker()
    deps = _make_deps(maker, environment="prod")

    alias_mock = AsyncMock(return_value="should_not_be_called")
    exact_mock = AsyncMock(return_value=None)
    embed_match = RetrievedFood(name="연어 포케", food_id=None, score=0.82, nutrition={})
    embed_mock = AsyncMock(return_value=[embed_match])

    monkeypatch.setattr(retrieve_module, "lookup_canonical", alias_mock)
    monkeypatch.setattr(retrieve_module, "search_by_name", exact_mock)
    monkeypatch.setattr(retrieve_module, "search_by_embedding", embed_mock)

    state = _state(
        items=[FoodItem(name="포케볼", confidence=0.5)],
        rewrite_attempts=1,
        rewritten_query="연어 포케 / 참치 포케 / 베지 포케",
    )
    out = await retrieve_nutrition(state, deps=deps)

    assert out["retrieval"].retrieval_confidence == pytest.approx(0.82)
    assert alias_mock.await_count == 0  # alias skip
    assert exact_mock.await_count == 0  # exact skip
    assert embed_mock.await_count == 1
    # 임베딩 호출 인자 검증 — rewritten_query 사용
    call_query = embed_mock.await_args.args[1]
    assert call_query == "연어 포케 / 참치 포케 / 베지 포케"
