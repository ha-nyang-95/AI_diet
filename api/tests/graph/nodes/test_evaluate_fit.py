"""Story 3.3 — `evaluate_fit` 노드 단위 테스트 (AC3)."""

from __future__ import annotations

import uuid

from app.graph.deps import NodeDeps
from app.graph.nodes import evaluate_fit
from app.graph.state import MealAnalysisState


async def test_evaluate_fit_stub_returns_50(fake_deps: NodeDeps) -> None:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await evaluate_fit(state, deps=fake_deps)
    assert out["fit_evaluation"].fit_score == 50
    assert out["fit_evaluation"].reasons == []
