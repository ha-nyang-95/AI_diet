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

NFR-S5 — name/option raw 출력 X. options_count + latency_ms만.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.adapters.openai_adapter import generate_clarification_options
from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import ClarificationOption, MealAnalysisState

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
    name = parsed[0].name if parsed else raw_text.strip()
    if not name:
        name = "unknown"

    # (ii) LLM 호출
    variants = await generate_clarification_options(name)

    # (iii) settings 상한 truncate
    max_options = max(1, deps.settings.clarification_max_options)
    options = variants.options[:max_options]

    # (v) graceful 빈 옵션
    if not options:
        options = [ClarificationOption(label="알 수 없음", value=name)]

    logger.info(
        "node.request_clarification.summary",
        options_count=len(options),
        max_options=max_options,
    )

    return {
        "needs_clarification": True,
        "clarification_options": [opt.model_dump() for opt in options],
    }
