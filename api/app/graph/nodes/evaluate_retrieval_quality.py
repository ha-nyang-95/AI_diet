"""Story 3.3 + 3.4 — `evaluate_retrieval_quality` 노드 (실 결정 로직, AC8).

Self-RAG 분기 SOT — stub 아닌 실 비교 로직. 3-way 분기 (Story 3.4 AC8):
1. ``confidence = state["retrieval"].retrieval_confidence`` (부재 시 0.0 fail-soft).
2. ``attempts = state.get("rewrite_attempts", 0)`` + ``node_errors`` 내 ``rewrite_query``
   실패 횟수 합산 (Story 3.3 무한 루프 가드 SOT — 본 스토리 변경 X).
3. ``confidence < threshold`` 분기:
   - ``attempts < 1`` → ``route="rewrite"`` → ``rewrite_query`` 노드 진입.
   - ``attempts >= 1`` → **``route="clarify"`` (Story 3.4 신규)** → ``request_clarification``
     노드 진입 (재검색 후에도 미달 → 재질문 분기).
4. ``confidence >= threshold`` → ``route="continue"`` → ``fetch_user_profile``.

출력은 ``EvaluationDecision(...).model_dump()`` — checkpoint 직렬화 round-trip 안전.

본 노드 *이전*의 retry는 wrapper가 담당. 본 노드는 deterministic 비교라 retry 의미 X.
"""

from __future__ import annotations

from typing import Any, cast

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import EvaluationDecision, MealAnalysisState, get_state_field


@_node_wrapper("evaluate_retrieval_quality")
async def evaluate_retrieval_quality(
    state: MealAnalysisState,
    *,
    deps: NodeDeps,
) -> dict[str, Any]:
    threshold = deps.settings.self_rag_confidence_threshold
    # `retrieval`/`node_errors`는 체크포인터 직렬화 round-trip 시 Pydantic instance
    # 또는 dict 양 형태 가능 — `get_state_field`로 일관된 안전 access.
    retrieval = state.get("retrieval")
    confidence_raw = get_state_field(retrieval, "retrieval_confidence", 0.0)
    confidence = float(cast(float, confidence_raw)) if confidence_raw is not None else 0.0
    counter = state.get("rewrite_attempts", 0) or 0
    # wrapper fallback이 rewrite_query 실패 시 `rewrite_attempts` increment 누락 →
    # 무한 루프 방지로 node_errors 내 rewrite_query 실패도 attempts에 합산.
    node_errors = state.get("node_errors", []) or []
    rewrite_failures = sum(
        1 for e in node_errors if get_state_field(e, "node_name") == "rewrite_query"
    )
    attempts = counter + rewrite_failures

    if confidence < threshold:
        if attempts < 1:
            decision = EvaluationDecision(
                route="rewrite",
                reason=f"low_confidence_{confidence:.2f}",
            )
        else:
            # Story 3.4 AC8 — 재검색 후에도 미달 → 재질문 분기 (rewrite_limit_reached).
            decision = EvaluationDecision(
                route="clarify",
                reason=f"rewrite_limit_reached_low_confidence_{confidence:.2f}",
            )
    else:
        decision = EvaluationDecision(
            route="continue",
            reason="confidence_ok",
        )
    return {"evaluation_decision": decision.model_dump()}
