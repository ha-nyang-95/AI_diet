"""Story 3.3 — `rewrite_query` 노드 단위 테스트 (AC3)."""

from __future__ import annotations

import uuid

from app.graph.deps import NodeDeps
from app.graph.nodes import rewrite_query
from app.graph.state import FoodItem, MealAnalysisState


async def test_rewrite_query_appends_suffix_and_increments(fake_deps: NodeDeps) -> None:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "low_confidence_food",
        "parsed_items": [FoodItem(name="low_confidence_food", confidence=0.5)],
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await rewrite_query(state, deps=fake_deps)
    assert out["rewritten_query"] == "low_confidence_food_rewritten"
    assert out["rewrite_attempts"] == 1


async def test_rewrite_query_empty_parsed_items_fallback_unknown(fake_deps: NodeDeps) -> None:
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
