"""Story 3.4 — `request_clarification` 노드 신규 (FR20 재질문 UX, AC9).

Self-RAG 재검색 후에도 신뢰도 미달 시 진입 — ``generate_clarification_options`` LLM
호출로 2-4건 옵션 생성 + state에 ``needs_clarification=True`` + ``clarification_options``
박음. 다음 edge는 ``END`` (분석 일시 정지) — checkpointer가 thread_id별 state 영속화 →
``analysis_service.aget_state(thread_id)``로 조회 가능.

흐름:
- (i) 입력 — ``parsed_items[0].name`` 또는 ``state["raw_text"]``(parsed 빈 fallback).
- (ii) ``generate_clarification_options(name)`` 호출 → ``ClarificationVariants(options)``.
- (iii) ``settings.clarification_max_options`` 상한 truncate (디폴트 4).
- (iv) ``{"needs_clarification": True, "clarification_options": [...].model_dump()}`` 반환.
- (v) graceful 빈 옵션 — fallback ``[ClarificationOption(label="알 수 없음", value=name)]``
  1건 강제 (UI 깨짐 방지).
- (vi) CR fix #4 — LLM 영구 실패 시 본 노드 *내부에서* fallback option 강제 반환
  (``needs_clarification=True`` + 1건). wrapper fallback이 ``needs_clarification`` 미설정
  으로 graph END idle dead state(UI 카드 미렌더링)에 빠지지 않도록 노드 자체가 contract
  보장. tenacity 1회 retry는 어댑터 자체에 있음 — 본 노드는 *최종 응답 contract* 책임.

NFR-S5 — name/option raw 출력 X. options_count + latency_ms만.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.adapters.openai_adapter import generate_clarification_options
from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import ClarificationOption, MealAnalysisState, get_state_field

logger = structlog.get_logger(__name__)


@_node_wrapper("request_clarification")
async def request_clarification(
    state: MealAnalysisState,
    *,
    deps: NodeDeps,
) -> dict[str, Any]:
    parsed = state.get("parsed_items", []) or []
    raw_text = state.get("raw_text", "") or ""

    # (i) 입력 추출 — parsed 우선, 빈 시 raw_text fallback.
    # CR fix #6 — checkpointer round-trip 시 parsed_items가 list[dict]로 deserialize
    # 가능 → `get_state_field`로 양 형태(Pydantic instance / dict) 안전 access.
    raw_first = get_state_field(parsed[0], "name", "") if parsed else ""
    first_name = str(raw_first) if raw_first else ""
    name = first_name.strip() or raw_text.strip()
    if not name:
        name = "unknown"

    max_options = max(1, deps.settings.clarification_max_options)

    # (ii)(vi) LLM 호출 + 영구 실패 시 self-fallback (UI dead state 차단).
    options: list[ClarificationOption]
    try:
        variants = await generate_clarification_options(name)
        options = list(variants.options[:max_options])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "node.request_clarification.llm_failed",
            error_class=type(exc).__name__,
        )
        options = []

    # (v) graceful 빈 옵션 — LLM 빈 응답 또는 LLM 실패 모두 흡수.
    if not options:
        options = [ClarificationOption(label="다시 입력", value=name)]

    logger.info(
        "node.request_clarification.summary",
        options_count=len(options),
        max_options=max_options,
    )

    return {
        "needs_clarification": True,
        "clarification_options": [opt.model_dump() for opt in options],
    }
