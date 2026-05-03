"""Story 3.4 — `parse_meal` 노드 *실 비즈니스 로직* (AC5).

Story 3.3 결정성 stub 폐지 + 실 흐름:
- (i) ``meals.parsed_items`` JSONB 우선 읽기 — Story 2.3 OCR 결과 영속화 재사용 (이미
  parse된 사진 입력은 LLM 재호출 X / cost 0).
- (ii) ``parsed_items IS NULL`` 시 ``state["raw_text"]`` → ``parse_meal_text(text)``
  LLM 호출 → ``ParsedMeal.items`` → ``FoodItem`` 매핑.
- (iii) 빈 텍스트 → 빈 리스트 (downstream 빈 retrieval로 진행 → fit_score=0 stub).

`_node_wrapper`가 (a) tenacity 1회 retry — Pydantic ValidationError 또는 transient,
(b) 2회 실패 시 NodeError append + 빈 ``parsed_items`` 반환(downstream graceful).

NFR-S5 — raw_text raw 출력 X. items_count + source(``"db"``/``"llm"``/``"empty"``)만.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text

from app.adapters.openai_adapter import parse_meal_text
from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import FoodItem, MealAnalysisState, ParseMealOutput

logger = structlog.get_logger(__name__)


async def _load_parsed_items_from_db(deps: NodeDeps, meal_id: uuid.UUID) -> list[FoodItem] | None:
    """``meals.parsed_items`` JSONB 1차 우선 읽기 — None 또는 미존재 row 시 None 반환.

    raw SQL — ORM은 jsonb를 dict로 자동 deserialize.
    """
    async with deps.session_maker() as session:
        result = await session.execute(
            text("SELECT parsed_items FROM meals WHERE id = :id").bindparams(id=meal_id)
        )
        row = result.first()
    if row is None:
        return None
    raw_items = row.parsed_items
    if raw_items is None:
        return None
    # `[{"name":..., "quantity":..., "confidence":...}]` 가정. Pydantic이 ValidationError
    # raise 시 wrapper가 retry → fallback NodeError append (downstream graceful).
    return [FoodItem(**item) for item in raw_items]


@_node_wrapper("parse_meal")
async def parse_meal(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    raw = state.get("raw_text", "") or ""
    meal_id = state.get("meal_id")
    # CR fix #1 (BLOCKER) — `aresume`이 True 주입 시 DB stale `parsed_items`를 무시하고
    # 사용자 정제 텍스트로 LLM parse 강제. neuw 분석은 False/missing이라 영향 없음.
    force_llm = bool(state.get("force_llm_parse"))

    # (i) DB 우선 읽기 — meals.parsed_items 영속화 재사용. force_llm 시 skip.
    if meal_id is not None and not force_llm:
        db_items = await _load_parsed_items_from_db(deps, meal_id)
        # CR fix #2 — truthy 검사 (빈 리스트 `[]`도 None과 동일하게 LLM fallback 진입,
        # OCR 0건 + 사용자 텍스트 보강 시나리오 정합).
        if db_items:
            logger.info(
                "node.parse_meal.source",
                source="db",
                items_count=len(db_items),
            )
            return {"parsed_items": db_items}

    # (iii) 빈 텍스트 — graceful 빈 리스트.
    if not raw.strip():
        logger.info("node.parse_meal.source", source="empty", items_count=0)
        out = ParseMealOutput(parsed_items=[])
        return {"parsed_items": out.parsed_items}

    # (ii) LLM fallback — parse_meal_text 호출.
    parsed = await parse_meal_text(raw)
    items = [
        FoodItem(name=p.name, quantity=p.quantity or None, confidence=p.confidence)
        for p in parsed.items
    ]
    logger.info("node.parse_meal.source", source="llm", items_count=len(items))
    return {"parsed_items": items}
