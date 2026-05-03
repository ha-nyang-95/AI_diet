"""Story 3.4 — `retrieve_nutrition` 노드 *실 비즈니스 로직* (AC6).

Story 3.3 결정성 stub 부분 폐지(sentinel 분기는 회귀 가드로 보존). 3단 검색 흐름:
- (i) 빈 ``parsed_items`` → 빈 리스트 + ``retrieval_confidence=0.0``,
- (ii) per-item:
  - alias lookup(``lookup_canonical``) → matched 시 canonical 사용,
  - exact 매칭(``search_by_name``) → matched 시 score 1.0 + skip,
  - HNSW 임베딩 fallback(``search_by_embedding``) — top-K + score 정규화,
- (iii) ``rewrite_attempts > 0`` 시 ``state["rewritten_query"]``를 임베딩 fallback
  쿼리로 사용 (alias/exact 단계 skip — 재작성된 쿼리는 사전 미포함),
- (iv) sentinel ``__test_low_confidence__`` 또는 dev/test/ci 환경에서 ``"low_confidence"``
  포함 + ``rewrite_attempts == 0`` → confidence 0.3 즉시 반환 (Story 3.3 회귀 가드),
- (v) sentinel + ``rewrite_attempts > 0`` → confidence 0.85 boost (회귀),
- (vi) multi-item — 모든 ``RetrievedFood`` append + ``compute_retrieval_confidence(min)``.

DB 자원 — 단일 ``async with deps.session_maker()`` 컨텍스트 내부에서 모든 lookup/search
수행 (connection 1개 점유).

NFR-S5 — item.name/canonical_name raw 노출 X. items_count + path 분류 + confidence +
latency_ms만.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import (
    FoodItem,
    MealAnalysisState,
    RetrievalResult,
    RetrievedFood,
)
from app.rag.food.normalize import lookup_canonical
from app.rag.food.search import (
    compute_retrieval_confidence,
    search_by_embedding,
    search_by_name,
)

logger = structlog.get_logger(__name__)

_LOW_CONFIDENCE_SENTINEL = "__test_low_confidence__"
_TEST_ENVIRONMENTS = {"dev", "test", "ci"}


def _is_low_confidence_input(name: str, environment: str) -> bool:
    """Self-RAG 분기 트리거 — sentinel(prod 포함) 또는 dev/test/ci에서 substring 매칭."""
    if name == _LOW_CONFIDENCE_SENTINEL:
        return True
    return environment in _TEST_ENVIRONMENTS and "low_confidence" in name


async def _resolve_one_item(
    session: Any,
    item: FoodItem,
    *,
    rewrite_attempts: int,
    rewritten_query: str | None,
) -> tuple[RetrievedFood | None, str]:
    """단일 음식 → (RetrievedFood | None, path 분류).

    path 분류: ``"alias"`` / ``"exact"`` / ``"embedding"`` / ``"none"``.
    """
    if rewrite_attempts > 0 and rewritten_query:
        # Self-RAG 1회 재검색 후 — alias/exact skip + 재작성된 쿼리로 임베딩 fallback 직진.
        matches = await search_by_embedding(session, rewritten_query)
        if matches:
            return matches[0], "embedding"
        return None, "none"

    # (a) alias lookup
    canonical = await lookup_canonical(session, item.name)
    name_for_search = canonical if canonical is not None else item.name

    # (b) exact name 매칭
    exact = await search_by_name(session, name_for_search)
    if exact is not None:
        return exact, ("alias" if canonical is not None else "exact")

    # (c) HNSW 임베딩 fallback — 원문 item.name 그대로
    matches = await search_by_embedding(session, item.name)
    if matches:
        return matches[0], "embedding"
    return None, "none"


@_node_wrapper("retrieve_nutrition")
async def retrieve_nutrition(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    parsed = state.get("parsed_items", []) or []
    rewrite_attempts = state.get("rewrite_attempts", 0) or 0
    rewritten_query = state.get("rewritten_query")

    # (i) 빈 parsed_items
    if not parsed:
        result = RetrievalResult(retrieved_foods=[], retrieval_confidence=0.0)
        return {"retrieval": result}

    # (iv)(v) sentinel 분기 — 첫 item name 기준 (Story 3.3 회귀 가드).
    # CR fix #5 — `len(parsed) == 1` 가드 추가: multi-item 케이스는 실 검색 흐름으로
    # 진입(sentinel은 결정성 single-item fixture 전용 — 다중 음식 시 나머지 항목 skip 차단).
    first_name = parsed[0].name
    if len(parsed) == 1 and _is_low_confidence_input(first_name, deps.settings.environment):
        if rewrite_attempts == 0:
            # 재검색 진입 시뮬레이션 — confidence 0.3.
            result = RetrievalResult(retrieved_foods=[], retrieval_confidence=0.3)
            return {"retrieval": result}
        # 재검색 후 신뢰도 회복 시뮬레이션 — confidence 0.85.
        result = RetrievalResult(
            retrieved_foods=[
                RetrievedFood(
                    name=first_name,
                    food_id=None,
                    score=0.85,
                    nutrition={"energy_kcal": 0},
                ),
            ],
            retrieval_confidence=0.85,
        )
        return {"retrieval": result}

    # (ii)(vi) 실 3단 검색 — 단일 session 컨텍스트 내부.
    # CR(Gemini) fix G1 — multi-item rewrite 시 모든 item이 동일한 `rewritten_query`로
    # 검색되어 결과가 첫 매치로 복제되는 버그 차단. `rewrite_query` 노드는 `parsed[0]`
    # 만 rewrite하므로 *첫 item에만* rewritten_query 적용 + 나머지 item은 원래 name으로
    # 일반 alias→exact→HNSW 흐름 유지(정보 보존). 다중 음식 per-item rewrite는 후속
    # 스토리(8.4 polish)에서 rewrite_query 노드 자체가 항목별 변형 생성하도록 확장.
    retrieved_foods: list[RetrievedFood] = []
    paths: list[str] = []
    async with deps.session_maker() as session:
        for i, item in enumerate(parsed):
            match, path = await _resolve_one_item(
                session,
                item,
                rewrite_attempts=rewrite_attempts,
                rewritten_query=rewritten_query if i == 0 else None,
            )
            paths.append(path)
            if match is not None:
                retrieved_foods.append(match)

    # (vi) confidence aggregator — CR fix #3: expected_count=len(parsed) 전달로
    # missing 매칭(unmatched item)이 implicit 0 confidence로 min에 반영되어 보수적
    # 라우팅(spec line 70 정합 — 한 항목이라도 신뢰도 낮으면 Self-RAG 재검색 분기).
    confidence = compute_retrieval_confidence(retrieved_foods, expected_count=len(parsed))
    logger.info(
        "node.retrieve_nutrition.summary",
        items_count=len(retrieved_foods),
        paths=paths,
        confidence=round(confidence, 3),
        rewrite_attempts=rewrite_attempts,
    )
    result = RetrievalResult(
        retrieved_foods=retrieved_foods,
        retrieval_confidence=confidence,
    )
    return {"retrieval": result}
