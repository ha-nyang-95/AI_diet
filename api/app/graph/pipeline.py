"""Story 3.3 — `compile_pipeline` SOT (AC5, D8).

`StateGraph(MealAnalysisState)` 빌드 + 7 노드(`functools.partial`로 deps 주입) +
Self-RAG 조건부 분기 + AsyncPostgresSaver checkpointer 부착. lifespan 1회 호출 SOT.

노드 시퀀스 (architecture line 922 정합):
    START → parse_meal → retrieve_nutrition → evaluate_retrieval_quality
        → (분기) → [rewrite_query → retrieve_nutrition] OR fetch_user_profile
        → evaluate_fit → generate_feedback → END

Self-RAG 1회 한도 강제: `evaluate_retrieval_quality`의 결정 로직(노드 자체)이
`rewrite_attempts < 1` 가드. 2회 도달 시 강제 `"continue"` → `fetch_user_profile`.
무한 루프 차단 SOT.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.graph.deps import NodeDeps
from app.graph.edges import route_after_evaluate
from app.graph.nodes import (
    evaluate_fit,
    evaluate_retrieval_quality,
    fetch_user_profile,
    generate_feedback,
    parse_meal,
    retrieve_nutrition,
    rewrite_query,
)
from app.graph.state import MealAnalysisState

if TYPE_CHECKING:  # pragma: no cover
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def compile_pipeline(checkpointer: AsyncPostgresSaver, deps: NodeDeps) -> Any:
    """`StateGraph` 빌드 + 컴파일 — 라우터에서는 `app.state.graph` 재사용.

    `deps`는 `functools.partial(node, deps=deps)` closure로 컴파일 시점 주입 (D8).
    LangGraph는 노드 시그니처 `(state) -> dict`만 알므로 `deps`는 wrapper의 cell
    variable로 캡처.
    """
    builder: StateGraph[MealAnalysisState] = StateGraph(MealAnalysisState)

    # 노드 등록 — partial로 deps 캡처.
    builder.add_node("parse_meal", partial(parse_meal, deps=deps))
    builder.add_node("retrieve_nutrition", partial(retrieve_nutrition, deps=deps))
    builder.add_node(
        "evaluate_retrieval_quality",
        partial(evaluate_retrieval_quality, deps=deps),
    )
    builder.add_node("rewrite_query", partial(rewrite_query, deps=deps))
    builder.add_node("fetch_user_profile", partial(fetch_user_profile, deps=deps))
    builder.add_node("evaluate_fit", partial(evaluate_fit, deps=deps))
    builder.add_node("generate_feedback", partial(generate_feedback, deps=deps))

    # 엣지 — START → parse_meal → retrieve_nutrition → evaluate_retrieval_quality.
    builder.add_edge(START, "parse_meal")
    builder.add_edge("parse_meal", "retrieve_nutrition")
    builder.add_edge("retrieve_nutrition", "evaluate_retrieval_quality")

    # Self-RAG 분기 — `route_after_evaluate`가 "rewrite_query" 또는 "fetch_user_profile"
    # 중 하나로 분기. 1회 한도는 `evaluate_retrieval_quality` 노드 자체 결정 로직이 강제
    # (`rewrite_attempts < 1` 가드).
    builder.add_conditional_edges(
        "evaluate_retrieval_quality",
        route_after_evaluate,
        {
            "rewrite_query": "rewrite_query",
            "fetch_user_profile": "fetch_user_profile",
        },
    )

    # `rewrite_query` 후 unconditional `retrieve_nutrition` 재실행 — `evaluate_retrieval_quality`
    # 가 한 번 더 평가하고 `rewrite_attempts >= 1`이라 강제 `"continue"` 반환.
    builder.add_edge("rewrite_query", "retrieve_nutrition")

    # 정상 흐름 종단.
    builder.add_edge("fetch_user_profile", "evaluate_fit")
    builder.add_edge("evaluate_fit", "generate_feedback")
    builder.add_edge("generate_feedback", END)

    return builder.compile(
        checkpointer=checkpointer,
        debug=settings.langgraph_debug,
    )


__all__ = ["compile_pipeline", "MealAnalysisState"]
