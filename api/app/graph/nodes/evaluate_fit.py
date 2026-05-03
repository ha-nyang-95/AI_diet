"""Story 3.5 — `evaluate_fit` 노드 (결정성 fit_score 알고리즘 + 알레르기 단락, AC7).

Story 3.3/3.4 stub(``fit_score=50``) 폐지 → ``compute_fit_score`` 결정성 SOT 호출.

단계:
1. ``state["user_profile"]`` 또는 ``state["parsed_items"]`` 부재 → graceful
   ``incomplete_data`` 반환(downstream ``generate_feedback``이 fallback 텍스트 — Story 3.6).
2. 정상 — ``compute_fit_score(profile, parsed_items, retrieved_foods)`` 호출 → entry가
   알레르기 단락 / incomplete_data / 정상 3-way 처리.
3. ``model_dump()`` 반환 — LangGraph dict-merge + checkpointer round-trip 안전
   (Story 3.4 패턴 정합).

NFR-S5 마스킹: 진입/완료 INFO 로그 1줄 — fit_score/fit_label/coverage_ratio(2자리)/
violated_count/latency_ms 만. raw weight/height/age/allergies/parsed_items name X.
"""

from __future__ import annotations

import time
from typing import Any, cast

import structlog

from app.domain.fit_score import FitScoreComponents, compute_fit_score
from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import (
    FitEvaluation,
    FoodItem,
    MealAnalysisState,
    RetrievedFood,
    UserProfileSnapshot,
    get_state_field,
)

log = structlog.get_logger()


def _coerce_profile(raw: object) -> UserProfileSnapshot | None:
    """state[user_profile]이 dict 또는 Pydantic instance일 수 있음 — 안전 변환.

    CR m-2: 변환 실패 시 masked warning(예외 클래스명만, 필드 값 X) — silent
    swallow 회귀로 데이터 corruption을 디버깅 불가능하게 만드는 경로 차단.
    """
    if raw is None:
        return None
    if isinstance(raw, UserProfileSnapshot):
        return raw
    if isinstance(raw, dict):
        try:
            return UserProfileSnapshot(**raw)
        except Exception as e:  # noqa: BLE001
            log.warning("evaluate_fit.coerce_failed", kind="profile", error=type(e).__name__)
            return None
    return None


def _coerce_food_item(raw: object) -> FoodItem | None:
    if isinstance(raw, FoodItem):
        return raw
    if isinstance(raw, dict):
        try:
            return FoodItem(**raw)
        except Exception as e:  # noqa: BLE001
            log.warning("evaluate_fit.coerce_failed", kind="food_item", error=type(e).__name__)
            return None
    return None


def _coerce_retrieved_food(raw: object) -> RetrievedFood | None:
    if isinstance(raw, RetrievedFood):
        return raw
    if isinstance(raw, dict):
        try:
            return RetrievedFood(**raw)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "evaluate_fit.coerce_failed",
                kind="retrieved_food",
                error=type(e).__name__,
            )
            return None
    return None


@_node_wrapper("evaluate_fit")
async def evaluate_fit(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
    _ = deps  # 본 노드는 deps 미사용 (순수 결정성).

    start = time.monotonic()

    profile = _coerce_profile(state.get("user_profile"))
    parsed_raw = state.get("parsed_items") or []
    parsed_items_typed: list[FoodItem] = [
        item for item in (_coerce_food_item(it) for it in parsed_raw) if item is not None
    ]

    retrieval = state.get("retrieval")
    retrieved_raw = cast(list[object], get_state_field(retrieval, "retrieved_foods", []) or [])
    retrieved_foods_typed: list[RetrievedFood] = [
        food for food in (_coerce_retrieved_food(rf) for rf in retrieved_raw) if food is not None
    ]

    if profile is None or not parsed_items_typed:
        fit_evaluation = FitEvaluation(
            fit_score=0,
            fit_reason="incomplete_data",
            fit_label="needs_adjust",
            reasons=["프로필 또는 식사 정보 부재 — 분석 진행 불가"],
            components=FitScoreComponents.zero(),
        )
    else:
        fit_evaluation = compute_fit_score(
            profile=profile,
            parsed_items=parsed_items_typed,
            retrieved_foods=retrieved_foods_typed,
        )

    latency_ms = int((time.monotonic() - start) * 1000)
    # NFR-S5 마스킹 — fit_score/fit_label/components(int)/coverage_ratio/violated_count만.
    # CR m-3: self-emitted prefix 문자열 파싱(`"알레르기 위반:"`) 대신 reasons 길이를
    # 직접 사용 — `compute_fit_score`가 violation 케이스에서 `reasons = [f"알레르기 위반: {a}"
    # for a in sorted(violations)]`로 채우므로 `len(reasons)` 가 violation 카운트와 정합.
    violated_count = (
        len(fit_evaluation.reasons) if fit_evaluation.fit_reason == "allergen_violation" else 0
    )
    log.info(
        "node.evaluate_fit.complete",
        fit_score=fit_evaluation.fit_score,
        fit_label=fit_evaluation.fit_label,
        fit_reason=fit_evaluation.fit_reason,
        coverage_ratio=round(fit_evaluation.components.coverage_ratio, 2),
        violated_count=violated_count,
        latency_ms=latency_ms,
    )

    return {"fit_evaluation": fit_evaluation.model_dump()}
