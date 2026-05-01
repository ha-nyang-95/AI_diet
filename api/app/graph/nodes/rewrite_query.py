"""Story 3.3 — `rewrite_query` 노드 (결정성 stub, AC3).

Story 3.4가 실 LLM rewrite로 대체. 본 스토리는 결정성:
- `parsed_items[0].name + "_rewritten"` 또는 빈 입력 시 `"unknown_food"`,
- `rewrite_attempts: state.get("rewrite_attempts", 0) + 1` 동시 갱신 — Self-RAG
  1회 한도 카운터 (LangGraph dict-merge 정합).
"""

from __future__ import annotations

from typing import Any

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import MealAnalysisState


@_node_wrapper("rewrite_query")
async def rewrite_query(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    _ = deps
    parsed = state.get("parsed_items", []) or []
    base = parsed[0].name if parsed else ""
    rewritten = f"{base}_rewritten" if base else "unknown_food"
    attempts = state.get("rewrite_attempts", 0) or 0
    return {
        "rewritten_query": rewritten,
        "rewrite_attempts": attempts + 1,
    }
