"""Story 3.3 — `retrieve_nutrition` 노드 (결정성 stub, AC3).

Story 3.4가 실 alias lookup → HNSW top-3 + retrieval_confidence 산출로 대체. 본
스토리는 결정성 분기:
- `parsed_items` 비어있음 → 빈 retrieval + confidence 0.0,
- 첫 item name에 `"low_confidence"` 포함 → `retrieved_foods=[]`, confidence 0.3
  (Self-RAG 분기 트리거),
- 그 외 → 단일 stub `RetrievedFood(score=0.7, ...)` + confidence 0.7.

`rewrite_attempts > 0` 시 *신뢰도 boost 0.85* — Self-RAG 1회 재검색 후 신뢰도 회복
시뮬레이션(`evaluate_retrieval_quality`가 `"continue"` 라우트로 분기 검증 정합).
"""

from __future__ import annotations

from typing import Any

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import MealAnalysisState, RetrievalResult, RetrievedFood


@_node_wrapper("retrieve_nutrition")
async def retrieve_nutrition(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    _ = deps
    parsed = state.get("parsed_items", []) or []
    if not parsed:
        result = RetrievalResult(retrieved_foods=[], retrieval_confidence=0.0)
        return {"retrieval": result}

    name = parsed[0].name
    rewrite_attempts = state.get("rewrite_attempts", 0) or 0

    if "low_confidence" in name and rewrite_attempts == 0:
        result = RetrievalResult(retrieved_foods=[], retrieval_confidence=0.3)
        return {"retrieval": result}

    base_confidence = 0.85 if rewrite_attempts > 0 else 0.7
    result = RetrievalResult(
        retrieved_foods=[
            RetrievedFood(
                name=name,
                food_id=None,
                score=base_confidence,
                nutrition={"energy_kcal": 0},
            ),
        ],
        retrieval_confidence=base_confidence,
    )
    return {"retrieval": result}
