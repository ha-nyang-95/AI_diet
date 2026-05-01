"""Story 3.3 — `parse_meal` 노드 단위 테스트 (AC3)."""

from __future__ import annotations

import uuid

from app.graph.deps import NodeDeps
from app.graph.nodes import parse_meal
from app.graph.state import FoodItem, MealAnalysisState


async def test_parse_meal_returns_single_food_item(fake_deps: NodeDeps) -> None:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면 1인분",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=fake_deps)
    assert "parsed_items" in out
    items = out["parsed_items"]
    assert len(items) == 1
    assert isinstance(items[0], FoodItem)
    assert items[0].confidence == 0.5


async def test_parse_meal_empty_text(fake_deps: NodeDeps) -> None:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await parse_meal(state, deps=fake_deps)
    assert out["parsed_items"] == []


async def test_parse_meal_deterministic(fake_deps: NodeDeps) -> None:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "사과",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out1 = await parse_meal(state, deps=fake_deps)
    out2 = await parse_meal(state, deps=fake_deps)
    assert out1["parsed_items"][0].name == out2["parsed_items"][0].name
