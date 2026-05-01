"""Story 3.3 — `evaluate_retrieval_quality` 노드 단위 테스트 (AC3, *실 결정 로직*).

Self-RAG 분기 4 케이스 — 1회 한도 회귀 가드:
1. low confidence + 0회 → "rewrite",
2. low confidence + 1회 → "continue" (1회 한도 도달, "rewrite_limit_reached"),
3. high confidence + 0회 → "continue",
4. high confidence + 1회 → "continue".
"""

from __future__ import annotations

import uuid

from app.graph.deps import NodeDeps
from app.graph.nodes import evaluate_retrieval_quality
from app.graph.state import MealAnalysisState, RetrievalResult


def _state(*, confidence: float, rewrite_attempts: int) -> MealAnalysisState:
    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "retrieval": RetrievalResult(retrieved_foods=[], retrieval_confidence=confidence),
        "rewrite_attempts": rewrite_attempts,
        "node_errors": [],
    }


async def test_low_conf_zero_attempts_routes_rewrite(fake_deps: NodeDeps) -> None:
    out = await evaluate_retrieval_quality(
        _state(confidence=0.3, rewrite_attempts=0),
        deps=fake_deps,
    )
    assert out["evaluation_decision"].route == "rewrite"
    assert "low_confidence_0.30" in out["evaluation_decision"].reason


async def test_low_conf_one_attempt_routes_continue_limit_reached(
    fake_deps: NodeDeps,
) -> None:
    """1회 한도 도달 — Self-RAG 무한 루프 회귀 가드 (D5)."""
    out = await evaluate_retrieval_quality(
        _state(confidence=0.3, rewrite_attempts=1),
        deps=fake_deps,
    )
    assert out["evaluation_decision"].route == "continue"
    assert out["evaluation_decision"].reason == "rewrite_limit_reached"


async def test_high_conf_zero_attempts_routes_continue(fake_deps: NodeDeps) -> None:
    out = await evaluate_retrieval_quality(
        _state(confidence=0.7, rewrite_attempts=0),
        deps=fake_deps,
    )
    assert out["evaluation_decision"].route == "continue"
    assert out["evaluation_decision"].reason == "confidence_ok"


async def test_high_conf_one_attempt_routes_continue(fake_deps: NodeDeps) -> None:
    out = await evaluate_retrieval_quality(
        _state(confidence=0.85, rewrite_attempts=1),
        deps=fake_deps,
    )
    assert out["evaluation_decision"].route == "continue"


async def test_missing_retrieval_treated_as_zero(fake_deps: NodeDeps) -> None:
    """`retrieval` 부재(빈 텍스트 / 노드 fallback) → confidence 0.0 → rewrite (0회 한정)."""
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    out = await evaluate_retrieval_quality(state, deps=fake_deps)
    assert out["evaluation_decision"].route == "rewrite"
