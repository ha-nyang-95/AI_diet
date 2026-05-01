"""Story 3.3 — `generate_feedback` 노드 단위 테스트 (AC3)."""

from __future__ import annotations

import uuid

from app.graph.deps import NodeDeps
from app.graph.nodes import generate_feedback
from app.graph.state import MealAnalysisState


async def test_generate_feedback_stub(fake_deps: NodeDeps) -> None:
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await generate_feedback(state, deps=fake_deps)
    fb = out["feedback"]
    assert fb.text == "(분석 준비 중)"
    assert fb.citations == []
    assert fb.used_llm == "stub"
