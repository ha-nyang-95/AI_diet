"""Story 3.3 — `parse_meal` 노드 (결정성 stub, AC3).

Story 3.4가 실 LLM parse + `meals.parsed_items` JSONB 우선 읽기로 대체. 본 스토리는
결정성 mapping만 — `state["raw_text"]` → 단일 `FoodItem(name=raw_text[:50],
quantity=None, confidence=0.5)`. 빈 텍스트 시 `parsed_items=[]` 반환(downstream
은 빈 retrieval로 진행 → fit_score=0).
"""

from __future__ import annotations

from typing import Any

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import FoodItem, MealAnalysisState, ParseMealOutput


@_node_wrapper("parse_meal")
async def parse_meal(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    _ = deps  # stub — Story 3.4가 LLM adapter 호출
    raw = state.get("raw_text", "") or ""
    if not raw.strip():
        out = ParseMealOutput(parsed_items=[])
    else:
        out = ParseMealOutput(
            parsed_items=[FoodItem(name=raw[:50], quantity=None, confidence=0.5)],
        )
    return {"parsed_items": out.parsed_items}
