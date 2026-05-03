"""Story 3.4 — `rewrite_query` 노드 *실 비즈니스 로직* (AC7).

Story 3.3 결정성 stub 폐지. 실 LLM 변형 흐름:
- (i) 빈 ``parsed_items`` → ``rewritten_query="unknown_food"`` + ``rewrite_attempts``
  increment (LLM 호출 X / cost 0).
- (ii) 정상 — ``parsed_items[0].name`` → ``rewrite_food_query(name)`` → 2-4 변형 →
  ``" / "`` join → ``rewritten_query``. ``rewrite_attempts`` increment.
- (iii) Self-RAG 1회 한도 — ``evaluate_retrieval_quality`` 노드 자체가
  ``rewrite_attempts < 1`` 가드 (Story 3.3 SOT 보존). 본 노드는 *카운터 increment*만.
- (iv) 무한 루프 가드 회귀 — wrapper fallback 시 increment 누락 가능 →
  ``evaluate_retrieval_quality``가 ``node_errors`` 내 ``rewrite_query`` 실패 카운트 합산
  (Story 3.3 보강 SOT — 본 스토리는 변경 X).

NFR-S5 — name/variants raw 출력 X. variants_count + latency_ms만.
"""

from __future__ import annotations

from typing import Any

from app.adapters.openai_adapter import rewrite_food_query
from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import MealAnalysisState


@_node_wrapper("rewrite_query")
async def rewrite_query(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    _ = deps  # LLM 호출은 어댑터 자체 client singleton — deps 미사용.
    parsed = state.get("parsed_items", []) or []
    attempts = state.get("rewrite_attempts", 0) or 0

    # (i) 빈 입력 — graceful fallback (LLM 호출 X).
    if not parsed:
        return {
            "rewritten_query": "unknown_food",
            "rewrite_attempts": attempts + 1,
        }

    name = parsed[0].name
    variants = await rewrite_food_query(name)
    rewritten = " / ".join(variants.variants) if variants.variants else name
    return {
        "rewritten_query": rewritten,
        "rewrite_attempts": attempts + 1,
    }
