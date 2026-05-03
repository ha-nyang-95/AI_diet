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

import structlog

from app.graph.state import MealAnalysisState, get_state_field

log = structlog.get_logger()


def _extract_route(decision: object) -> str:
    """`evaluation_decision`에서 `route` 추출 — Pydantic instance, dict, None 모두 수용.

    AC3 — 노드 출력은 `.model_dump()` 후 dict 저장이 SOT이지만, checkpoint
    직렬화/역직렬화 경계에서 형태가 바뀔 수 있으므로 양 형태 모두 수용 (defensive).
    """
    return str(get_state_field(decision, "route", "continue"))


def route_after_evaluate(
    state: MealAnalysisState,
) -> Literal["rewrite_query", "fetch_user_profile", "request_clarification"]:
    """`evaluate_retrieval_quality` 출력의 `route` 필드 분기 — 3-way (Story 3.4 AC8).

    - ``"rewrite"`` → ``rewrite_query`` (재검색 1회 시도),
    - ``"clarify"`` → ``request_clarification`` (재검색 후 재질문 — Story 3.4 신규),
    - ``"continue"`` 또는 알 수 없는 값 → ``fetch_user_profile`` (fail-soft).

    알 수 없는 값은 ``route.unknown`` warn 로그 — 디버깅 용이성.
    """
    decision = state.get("evaluation_decision")
    route = _extract_route(decision)
    if route not in {"rewrite", "continue", "clarify"}:
        log.warning("route.unknown", route=route)
        route = "continue"
    if route == "rewrite":
        return "rewrite_query"
    if route == "clarify":
        return "request_clarification"
    return "fetch_user_profile"


def route_after_node_error(state: MealAnalysisState) -> Literal["next", "end"]:
    """노드 격리 fallback 라우터.

    디폴트 `"next"` — 부분 state로 다음 노드 진행. 치명적 케이스(`fetch_user_profile`이
    `AnalysisNodeError`로 실패)만 `"end"` 반환. `node_errors` 요소는 Pydantic instance
    또는 dict 양 형태 수용 (체크포인터 직렬화 round-trip 안전).
    """
    errors = state.get("node_errors", []) or []
    if not errors:
        return "next"
    last = errors[-1]
    if (
        get_state_field(last, "node_name") == "fetch_user_profile"
        and get_state_field(last, "error_class") == "AnalysisNodeError"
    ):
        return "end"
    return "next"


__all__ = ["route_after_evaluate", "route_after_node_error"]
