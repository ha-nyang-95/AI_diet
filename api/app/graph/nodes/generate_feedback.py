"""Story 3.3 — `generate_feedback` 노드 (결정성 stub, AC3).

Story 3.6이 실 인용형 피드백 + 광고 가드 + 듀얼-LLM router로 대체. 본 스토리 stub:
고정 placeholder 텍스트 + 빈 citations + `used_llm="stub"`.
"""

from __future__ import annotations

from typing import Any

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import FeedbackOutput, MealAnalysisState


@_node_wrapper("generate_feedback")
async def generate_feedback(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    _ = state, deps
    return {
        "feedback": FeedbackOutput(
            text="(분석 준비 중)",
            citations=[],
            used_llm="stub",
        ),
    }
