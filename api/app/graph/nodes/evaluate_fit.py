"""Story 3.3 — `evaluate_fit` 노드 (결정성 stub, AC3).

Story 3.5가 실 fit_score 알고리즘 + 알레르기 위반 단락(`fit_score=0`)으로 대체.
본 스토리 stub: 단순 `FitEvaluation(fit_score=50, reasons=[])`.
"""

from __future__ import annotations

from typing import Any

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import FitEvaluation, MealAnalysisState


@_node_wrapper("evaluate_fit")
async def evaluate_fit(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    _ = state, deps
    return {"fit_evaluation": FitEvaluation(fit_score=50, reasons=[])}
