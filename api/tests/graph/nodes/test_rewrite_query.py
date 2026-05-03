"""Story 3.4 — `rewrite_query` 노드 *실 LLM rewrite* 단위 테스트 (AC7)."""

from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock

import pytest

from app.adapters.openai_adapter import RewriteVariants
from app.core.exceptions import MealOCRUnavailableError
from app.graph.deps import NodeDeps
from app.graph.nodes.rewrite_query import rewrite_query
from app.graph.state import FoodItem, MealAnalysisState

# Note: `app.graph.nodes` __init__이 `rewrite_query` 함수를 export해서 submodule
# attribute access가 함수로 가려짐 — sys.modules로 실제 모듈 lookup.
rewrite_module = sys.modules["app.graph.nodes.rewrite_query"]


async def test_rewrite_query_calls_llm_and_increments(
    fake_deps: NodeDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정상 케이스 — LLM 변형 응답 → " / " join + rewrite_attempts increment."""
    llm_mock = AsyncMock(return_value=RewriteVariants(variants=["짜장면 곱빼기", "짜파게티"]))
    monkeypatch.setattr(rewrite_module, "rewrite_food_query", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "parsed_items": [FoodItem(name="짜장면", confidence=0.5)],
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await rewrite_query(state, deps=fake_deps)

    assert out["rewritten_query"] == "짜장면 곱빼기 / 짜파게티"
    assert out["rewrite_attempts"] == 1
    assert llm_mock.await_count == 1


async def test_rewrite_query_empty_parsed_items_skips_llm(
    fake_deps: NodeDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """빈 parsed_items → "unknown_food" + LLM 호출 X (graceful)."""
    llm_mock = AsyncMock()
    monkeypatch.setattr(rewrite_module, "rewrite_food_query", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "",
        "parsed_items": [],
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await rewrite_query(state, deps=fake_deps)
    assert out["rewritten_query"] == "unknown_food"
    assert out["rewrite_attempts"] == 1
    assert llm_mock.await_count == 0


async def test_rewrite_query_transient_failure_falls_back_to_node_error(
    fake_deps: NodeDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rewrite_food_query가 retry 후 영구 raise → wrapper fallback NodeError.

    `rewrite_attempts` increment 누락 가능 — 무한 루프 가드는
    `evaluate_retrieval_quality`가 `node_errors` 카운트 합산으로 강제 (Story 3.3 SOT).
    """

    async def _raise(_: str) -> None:
        raise MealOCRUnavailableError("transient retry exhausted")

    monkeypatch.setattr(rewrite_module, "rewrite_food_query", _raise)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "포케볼",
        "parsed_items": [FoodItem(name="포케볼", confidence=0.5)],
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await rewrite_query(state, deps=fake_deps)

    # wrapper fallback — node_errors append 만(rewrite_attempts increment 누락 정상).
    assert "node_errors" in out
    assert out["node_errors"][0].node_name == "rewrite_query"
    # rewrite_attempts/rewritten_query 미진행 (LangGraph dict-merge → 기존 state 유지).
    assert "rewrite_attempts" not in out
    assert "rewritten_query" not in out


async def test_rewrite_query_increments_existing_attempts(
    fake_deps: NodeDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rewrite_attempts 기존 값 1 → increment → 2 (Self-RAG 1회 한도 회귀 가드)."""
    llm_mock = AsyncMock(return_value=RewriteVariants(variants=["변형1"]))
    monkeypatch.setattr(rewrite_module, "rewrite_food_query", llm_mock)

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "x",
        "parsed_items": [FoodItem(name="x", confidence=0.5)],
        "rewrite_attempts": 1,
        "node_errors": [],
    }
    out = await rewrite_query(state, deps=fake_deps)
    assert out["rewrite_attempts"] == 2
