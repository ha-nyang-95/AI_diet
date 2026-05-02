"""Story 3.3 — `evaluate_retrieval_quality` 노드 (*실 결정 로직* — D6, AC3).

Self-RAG 분기 SOT — stub 아닌 실 비교 로직. 단계:
1. `confidence = state["retrieval"].retrieval_confidence` 추출 (`retrieval` 부재
   시 0.0 — 빈 텍스트/노드 fallback 케이스에서도 fail-soft).
2. `attempts = state.get("rewrite_attempts", 0)` + `node_errors` 내 `rewrite_query`
   실패 횟수 합산 — wrapper fallback이 `rewrite_attempts` increment 누락 시에도
   1회 한도 강제(무한 루프 회귀 가드).
3. `confidence < settings.self_rag_confidence_threshold` AND `attempts < 1` 시
   `route="rewrite"` → `rewrite_query` 노드 진입.
4. 그 외(신뢰도 충족 또는 1회 한도 도달) → `route="continue"` →
   `fetch_user_profile` 노드 진입. 1회 한도 도달은 `reason="rewrite_limit_reached"`.

출력은 `EvaluationDecision(...).model_dump()` — checkpoint 직렬화 round-trip 후에도
dict 형태 유지(AC3 spec line 74-75 정합).

이 노드 *이전*의 retry는 wrapper가 담당(transient). 본 노드는 deterministic 비교라
retry 의미 X.
"""

from __future__ import annotations

from typing import Any

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import EvaluationDecision, MealAnalysisState


@_node_wrapper("evaluate_retrieval_quality")
async def evaluate_retrieval_quality(
    state: MealAnalysisState,
    *,
    deps: NodeDeps,
) -> dict[str, Any]:
    threshold = deps.settings.self_rag_confidence_threshold
    retrieval = state.get("retrieval")
    confidence = retrieval.retrieval_confidence if retrieval is not None else 0.0
    counter = state.get("rewrite_attempts", 0) or 0
    # wrapper fallback이 rewrite_query 실패 시 `rewrite_attempts` increment 누락 →
    # 무한 루프 방지로 node_errors 내 rewrite_query 실패도 attempts에 합산.
    node_errors = state.get("node_errors", []) or []
    rewrite_failures = sum(1 for e in node_errors if e.node_name == "rewrite_query")
    attempts = counter + rewrite_failures

    if confidence < threshold and attempts < 1:
        decision = EvaluationDecision(
            route="rewrite",
            reason=f"low_confidence_{confidence:.2f}",
        )
    else:
        decision = EvaluationDecision(
            route="continue",
            reason="confidence_ok" if confidence >= threshold else "rewrite_limit_reached",
        )
    return {"evaluation_decision": decision.model_dump()}
