"""Story 3.3 — `retrieve_nutrition` 노드 단위 테스트 (AC3)."""

from __future__ import annotations

import uuid

from app.graph.deps import NodeDeps
from app.graph.nodes import retrieve_nutrition
from app.graph.state import FoodItem, MealAnalysisState


def _state(name: str, *, rewrite_attempts: int = 0) -> MealAnalysisState:
    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": name,
        "parsed_items": [FoodItem(name=name, confidence=0.5)],
        "rewrite_attempts": rewrite_attempts,
        "node_errors": [],
    }


async def test_retrieve_nutrition_high_confidence(fake_deps: NodeDeps) -> None:
    out = await retrieve_nutrition(_state("짜장면"), deps=fake_deps)
    assert out["retrieval"].retrieval_confidence == 0.7
    assert len(out["retrieval"].retrieved_foods) == 1
    assert out["retrieval"].retrieved_foods[0].name == "짜장면"


async def test_retrieve_nutrition_low_confidence(fake_deps: NodeDeps) -> None:
    out = await retrieve_nutrition(_state("low_confidence_food"), deps=fake_deps)
    assert out["retrieval"].retrieval_confidence == 0.3
    assert out["retrieval"].retrieved_foods == []


async def test_retrieve_nutrition_boost_after_rewrite(fake_deps: NodeDeps) -> None:
    """`rewrite_attempts > 0` 시 0.85 boost — Self-RAG 1회 재검색 후 신뢰도 회복."""
    out = await retrieve_nutrition(
        _state("low_confidence_food", rewrite_attempts=1),
        deps=fake_deps,
    )
    assert out["retrieval"].retrieval_confidence == 0.85


async def test_retrieve_nutrition_empty_parsed_items(fake_deps: NodeDeps) -> None:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "",
        "parsed_items": [],
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await retrieve_nutrition(state, deps=fake_deps)
    assert out["retrieval"].retrieved_foods == []
    assert out["retrieval"].retrieval_confidence == 0.0
