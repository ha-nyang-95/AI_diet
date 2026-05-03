"""Story 3.3 — `AnalysisService` pipeline thin wrapper (AC8).

`compile_pipeline()` 결과 graph를 *서비스 레이어*에서 감싸 — 라우터는 본 service만
호출, 그래프 내부 SOT(노드/edges/state)는 직접 노출 X. Story 3.4의 `needs_clarification`
재개 흐름의 *현재 state 조회* + 사용자 응답 후 재개 진입점도 본 service가 SOT.

design:
- `run`: 새 분석 1회 — `thread_id` 미지정 시 `meal:{meal_id}` 기본. Sentry transaction
  진입점.
- `aget_state`: Story 3.4 needs_clarification 후 *현재 state*만 보고 싶을 때.
- `aresume`: needs_clarification 후 사용자 응답을 받아 그래프 재개. 본 스토리는
  *인터페이스 박기*만 — 실 사용자 응답 갱신 분기는 Story 3.4가 강화.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import sentry_sdk

from app.graph.deps import NodeDeps
from app.graph.state import MealAnalysisState

if TYPE_CHECKING:  # pragma: no cover
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph


@dataclass(frozen=True)
class AnalysisService:
    """LangGraph compiled pipeline의 thin wrapper — 라우터 진입점."""

    graph: CompiledStateGraph[Any, Any, Any, Any]
    deps: NodeDeps

    async def run(
        self,
        *,
        meal_id: uuid.UUID,
        user_id: uuid.UUID,
        raw_text: str,
        thread_id: str | None = None,
    ) -> MealAnalysisState:
        """단일 분석 호출 — Sentry transaction(`op="analysis.pipeline"`) 진입점.

        `thread_id` 미지정 시 `meal:{meal_id}` 기본 — checkpoint 자체가 동일 meal에
        대한 멱등 가드 역할. `graph.ainvoke`는 `dict[str, Any]`를 반환하지만 노드 출력의
        union이 그대로 들어오므로 SOT TypedDict로 cast (런타임 검증은 노드 wrapper의
        Pydantic이 1차 게이트 — D7).
        """
        actual_thread_id = thread_id or f"meal:{meal_id}"
        config: RunnableConfig = {"configurable": {"thread_id": actual_thread_id}}
        initial_state: MealAnalysisState = {
            "meal_id": meal_id,
            "user_id": user_id,
            "raw_text": raw_text,
            "rewrite_attempts": 0,
            "node_errors": [],
            "needs_clarification": False,
        }
        with sentry_sdk.start_transaction(
            op="analysis.pipeline",
            name="meal_analysis",
        ):
            final_state = await self.graph.ainvoke(initial_state, config=config)
        return cast(MealAnalysisState, final_state)

    async def aget_state(self, *, thread_id: str) -> MealAnalysisState:
        """현재 state 조회 — Story 3.4 needs_clarification 흐름 진입점.

        unknown thread_id의 경우 LangGraph는 빈 StateSnapshot 반환 — `.values`가
        `None`/missing이어도 빈 dict로 graceful 처리.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        snapshot = await self.graph.aget_state(config)
        if snapshot is None:
            return cast(MealAnalysisState, {})
        values = getattr(snapshot, "values", None) or {}
        return cast(MealAnalysisState, values)

    async def aresume(
        self,
        *,
        thread_id: str,
        user_input: dict[str, Any],
    ) -> MealAnalysisState:
        """Story 3.4 — needs_clarification 후 사용자 응답을 받아 재개 (AC10).

        ``Command(update=..., goto="parse_meal")`` 패턴 — 정제 텍스트를 ``raw_text``로
        주입하고 직전 시도의 state(parsed_items / retrieval / rewrite_attempts /
        node_errors / needs_clarification / clarification_options / evaluation_decision)
        를 *clean slate* 으로 reset. ``parse_meal``부터 새 흐름 진입(이번엔 사용자 정제
        텍스트 → LLM parse + alias 1차 hit 가능성 ↑).

        ``user_input`` 는 ``{"raw_text_clarified"|"selected_value": "정제 텍스트"}``.
        둘 다 비어있으면 ``ValueError`` raise — 라우터(Story 3.7)가 422로 변환.

        CR fix #10 — thread_id 미존재 시 LangGraph는 update 필드를 첫 state로 사용해
        ``goto="parse_meal"``에서 새 흐름 시작(checkpointer가 빈 snapshot 반환 + state
        부분 dict-merge가 base가 되는 LangGraph SOT). 라우터(Story 3.7)는 일반적으로
        ``aget_state``로 ``needs_clarification=True`` 확인한 thread_id를 그대로 전달함.
        CR fix #1 (BLOCKER) — ``force_llm_parse=True`` 주입 → ``parse_meal``이 DB stale
        ``parsed_items`` 무시하고 사용자 정제 텍스트를 LLM parse(alias 1차 hit 가능성 ↑).
        """
        from langgraph.types import Command

        clarified = user_input.get("raw_text_clarified") or user_input.get("selected_value")
        if not clarified or not str(clarified).strip():
            raise ValueError("aresume requires raw_text_clarified or selected_value (non-empty)")

        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        cmd: Command[Any] = Command(
            update={
                "raw_text": str(clarified),
                "parsed_items": None,
                "retrieval": None,
                "rewrite_attempts": 0,
                "node_errors": [],
                "needs_clarification": False,
                "clarification_options": [],
                "evaluation_decision": None,
                "rewritten_query": None,
                "force_llm_parse": True,
            },
            goto="parse_meal",
        )

        with sentry_sdk.start_transaction(
            op="analysis.pipeline",
            name="meal_analysis_resume",
        ):
            final_state = await self.graph.ainvoke(cmd, config=config)
        return cast(MealAnalysisState, final_state)


__all__ = ["AnalysisService"]
