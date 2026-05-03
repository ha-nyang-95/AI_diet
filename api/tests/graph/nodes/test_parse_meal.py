"""Story 3.4 — `parse_meal` 노드 *실 비즈니스 로직* 단위 테스트 (AC5).

mock session_maker + monkeypatch ``parse_meal_text`` — DB / OpenAI 도달 X.

케이스:
1. ``meals.parsed_items`` JSONB 시드된 케이스 → DB 우선 + LLM 호출 X.
2. ``parsed_items IS NULL`` + ``raw_text="짜장면 1인분"`` → ``parse_meal_text`` 호출 +
   items 매핑.
3. 빈 ``raw_text`` + DB row 없음 → 빈 리스트 + LLM 호출 X.
4. ``parse_meal_text``가 transient 후 ``MealOCRUnavailableError`` raise → wrapper
   retry 1회 → fallback NodeError + 빈 ``parsed_items`` (downstream graceful).
5. 잘못된 jsonb 형태(``parsed_items``가 list 아닌 string) → Pydantic ValidationError
   → wrapper retry → fallback.
"""

from __future__ import annotations

import contextlib
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import MealOCRUnavailableError
from app.graph.deps import NodeDeps
from app.graph.nodes.parse_meal import parse_meal
from app.graph.state import FoodItem, MealAnalysisState

parse_meal_module = sys.modules["app.graph.nodes.parse_meal"]


def _build_session_maker_with_first(row: object) -> MagicMock:
    """``deps.session_maker()`` async with 컨텍스트 → ``session.execute().first()`` 체인."""
    session = MagicMock()
    result = MagicMock()
    result.first.return_value = row
    session.execute = AsyncMock(return_value=result)

    @contextlib.asynccontextmanager
    async def _maker() -> Any:
        yield session

    maker = MagicMock(side_effect=_maker)
    return maker


def _make_deps(session_maker: MagicMock) -> NodeDeps:
    from app.core.config import settings as _settings

    return NodeDeps(session_maker=session_maker, redis=None, settings=_settings)


# ---------------------------------------------------------------------------
# (i) DB 우선 — meals.parsed_items 시드된 케이스
# ---------------------------------------------------------------------------


async def test_parse_meal_db_first_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """meals.parsed_items 시드된 케이스 → DB 우선 + LLM 호출 X (cost 0)."""
    row = MagicMock()
    row.parsed_items = [
        {"name": "짜장면", "quantity": "1인분", "confidence": 0.92},
        {"name": "군만두", "quantity": "4개", "confidence": 0.88},
    ]
    maker = _build_session_maker_with_first(row)
    deps = _make_deps(maker)

    llm_mock = AsyncMock()
    monkeypatch.setattr(parse_meal_module, "parse_meal_text", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "ignored — DB takes precedence",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=deps)

    assert "parsed_items" in out
    items = out["parsed_items"]
    assert len(items) == 2
    assert isinstance(items[0], FoodItem)
    assert items[0].name == "짜장면"
    assert llm_mock.await_count == 0  # LLM 호출 X — DB 우선.


# ---------------------------------------------------------------------------
# (ii) LLM fallback — parsed_items IS NULL
# ---------------------------------------------------------------------------


async def test_parse_meal_llm_fallback_when_db_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parsed_items IS NULL + raw_text 입력 → parse_meal_text 호출."""
    row = MagicMock()
    row.parsed_items = None
    maker = _build_session_maker_with_first(row)
    deps = _make_deps(maker)

    from app.adapters.openai_adapter import ParsedMeal, ParsedMealItem

    parsed = ParsedMeal(
        items=[
            ParsedMealItem(name="짜장면", quantity="1인분", confidence=0.9),
        ]
    )
    llm_mock = AsyncMock(return_value=parsed)
    monkeypatch.setattr(parse_meal_module, "parse_meal_text", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면 1인분",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=deps)
    assert llm_mock.await_count == 1
    items = out["parsed_items"]
    assert len(items) == 1
    assert items[0].name == "짜장면"
    assert items[0].quantity == "1인분"


# ---------------------------------------------------------------------------
# (iii) 빈 텍스트 — graceful 빈 리스트
# ---------------------------------------------------------------------------


async def test_parse_meal_empty_text_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 raw_text + DB row 없음 → 빈 리스트 + LLM 호출 X."""
    maker = _build_session_maker_with_first(None)  # row 없음
    deps = _make_deps(maker)

    llm_mock = AsyncMock()
    monkeypatch.setattr(parse_meal_module, "parse_meal_text", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=deps)
    assert out["parsed_items"] == []
    assert llm_mock.await_count == 0


# ---------------------------------------------------------------------------
# (iv) parse_meal_text 영구 실패 → wrapper fallback NodeError
# ---------------------------------------------------------------------------


async def test_parse_meal_llm_failure_falls_back_to_node_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parse_meal_text가 retry 후 영구 raise → wrapper가 NodeError append.

    `MealOCRUnavailableError`는 `_RETRY_TYPES`에 없어 즉시 fallback (cost 낭비 차단).
    """
    row = MagicMock()
    row.parsed_items = None
    maker = _build_session_maker_with_first(row)
    deps = _make_deps(maker)

    async def _raise(_: str) -> None:
        raise MealOCRUnavailableError("transient retry exhausted")

    monkeypatch.setattr(parse_meal_module, "parse_meal_text", _raise)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=deps)
    # wrapper fallback — node_errors append + parsed_items 미진행.
    assert "node_errors" in out
    assert len(out["node_errors"]) == 1
    assert out["node_errors"][0].node_name == "parse_meal"


# ---------------------------------------------------------------------------
# (v) jsonb 형태 위반 → Pydantic ValidationError → wrapper retry → fallback
# ---------------------------------------------------------------------------


async def test_parse_meal_invalid_jsonb_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parsed_items가 list 아닌 string → Pydantic ValidationError → fallback."""
    row = MagicMock()
    # 잘못된 형태 — list of dict 아닌 string
    row.parsed_items = "not_a_list"
    maker = _build_session_maker_with_first(row)
    deps = _make_deps(maker)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "x",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=deps)
    assert "node_errors" in out
    assert out["node_errors"][0].node_name == "parse_meal"


# ---------------------------------------------------------------------------
# CR fix #1 (BLOCKER) — `force_llm_parse=True` 시 DB skip + LLM 강제 호출
# ---------------------------------------------------------------------------


async def test_parse_meal_force_llm_parse_skips_db_uses_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`aresume`이 주입한 `force_llm_parse=True`는 DB stale `parsed_items`를 무시하고
    `parse_meal_text(raw_text)` 강제 호출. clarification 후 사용자 정제 텍스트가 alias
    1차 hit 가능성으로 흡수.
    """
    # DB row에는 stale parsed_items가 시드되어 있음.
    row = MagicMock()
    row.parsed_items = [{"name": "포케볼", "quantity": "1인분", "confidence": 0.4}]
    maker = _build_session_maker_with_first(row)
    deps = _make_deps(maker)

    from app.adapters.openai_adapter import ParsedMeal, ParsedMealItem

    parsed = ParsedMeal(items=[ParsedMealItem(name="연어 포케", quantity="1인분", confidence=0.95)])
    llm_mock = AsyncMock(return_value=parsed)
    monkeypatch.setattr(parse_meal_module, "parse_meal_text", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "연어 포케 1인분",  # 사용자 clarified text
        "rewrite_attempts": 0,
        "node_errors": [],
        "force_llm_parse": True,
    }
    out = await parse_meal(state, deps=deps)

    # LLM 강제 호출 + 사용자 텍스트 사용 — DB stale items 무시.
    assert llm_mock.await_count == 1
    assert llm_mock.await_args.args[0] == "연어 포케 1인분"
    items = out["parsed_items"]
    assert len(items) == 1
    assert items[0].name == "연어 포케"  # DB의 "포케볼" 아님


# ---------------------------------------------------------------------------
# CR fix #2 — DB row의 빈 parsed_items=[] 도 LLM fallback 진입 (truthy 검사)
# ---------------------------------------------------------------------------


async def test_parse_meal_db_empty_list_falls_back_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB `parsed_items = []` (OCR 0건 영속화)인데 사용자가 raw_text 보강한 시나리오:
    빈 리스트는 truthy False → LLM fallback 진입. 이전 `is not None` 가드는 빈 리스트
    를 권위로 인식해 LLM 호출이 영구 skip되어 retrieval 빈 결과 + 불필요한 clarification
    카드를 발동시켰음.
    """
    row = MagicMock()
    row.parsed_items = []  # OCR 0건 영속화 케이스
    maker = _build_session_maker_with_first(row)
    deps = _make_deps(maker)

    from app.adapters.openai_adapter import ParsedMeal, ParsedMealItem

    parsed = ParsedMeal(items=[ParsedMealItem(name="짜장면", quantity="1인분", confidence=0.9)])
    llm_mock = AsyncMock(return_value=parsed)
    monkeypatch.setattr(parse_meal_module, "parse_meal_text", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면 1인분",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=deps)
    assert llm_mock.await_count == 1
    assert out["parsed_items"][0].name == "짜장면"
