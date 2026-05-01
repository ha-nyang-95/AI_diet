"""Story 3.3 — LangGraph 분기 라우터 (AC4).

`route_after_evaluate`: `evaluate_retrieval_quality` 출력의 `route` 필드 분기. Self-RAG
재검색 트리거 SOT — 1회 한도는 `evaluate_retrieval_quality` 노드 자체 결정 로직이 강제,
본 라우터는 *결과 분기*만 담당.

`route_after_node_error`: 노드 격리 fallback 라우터. 디폴트 `"next"` (한 노드 실패가
전체 파이프라인을 멈추지 않음 — FR45 정합). 치명적 케이스(`fetch_user_profile`이
`AnalysisNodeError`로 실패)만 `"end"` 반환 — user 미존재/profile 미완성은 후속 노드가
의미 X 데이터로 진행하면 fit_score 계산 깨짐.

edges.py에 라우터만 — 노드 자체 코드는 nodes/ 책임. Architecture 결정 SOT 분리.
"""

from __future__ import annotations

from typing import Literal

from app.graph.state import MealAnalysisState


def route_after_evaluate(
    state: MealAnalysisState,
) -> Literal["rewrite_query", "fetch_user_profile"]:
    """`evaluate_retrieval_quality` 출력의 `route` 필드 분기.

    `state["evaluation_decision"]` 부재 시 디폴트 `"continue"` (fail-soft) →
    `fetch_user_profile`로 분기.
    """
    decision = state.get("evaluation_decision")
    route = decision.route if decision is not None else "continue"
    return "rewrite_query" if route == "rewrite" else "fetch_user_profile"


def route_after_node_error(state: MealAnalysisState) -> Literal["next", "end"]:
    """노드 격리 fallback 라우터.

    디폴트 `"next"` — 부분 state로 다음 노드 진행. 치명적 케이스(`fetch_user_profile`이
    `AnalysisNodeError`로 실패)만 `"end"` 반환.
    """
    errors = state.get("node_errors", []) or []
    if not errors:
        return "next"
    last = errors[-1]
    if last.node_name == "fetch_user_profile" and last.error_class == "AnalysisNodeError":
        return "end"
    return "next"


__all__ = ["route_after_evaluate", "route_after_node_error"]
