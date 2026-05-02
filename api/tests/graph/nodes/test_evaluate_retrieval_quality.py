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
    assert out["evaluation_decision"]["route"] == "rewrite"
    assert "low_confidence_0.30" in out["evaluation_decision"]["reason"]


async def test_low_conf_one_attempt_routes_continue_limit_reached(
    fake_deps: NodeDeps,
) -> None:
    """1회 한도 도달 — Self-RAG 무한 루프 회귀 가드 (D5)."""
    out = await evaluate_retrieval_quality(
        _state(confidence=0.3, rewrite_attempts=1),
        deps=fake_deps,
    )
    assert out["evaluation_decision"]["route"] == "continue"
    assert out["evaluation_decision"]["reason"] == "rewrite_limit_reached"


async def test_high_conf_zero_attempts_routes_continue(fake_deps: NodeDeps) -> None:
    out = await evaluate_retrieval_quality(
        _state(confidence=0.7, rewrite_attempts=0),
        deps=fake_deps,
    )
    assert out["evaluation_decision"]["route"] == "continue"
    assert out["evaluation_decision"]["reason"] == "confidence_ok"


async def test_high_conf_one_attempt_routes_continue(fake_deps: NodeDeps) -> None:
    out = await evaluate_retrieval_quality(
        _state(confidence=0.85, rewrite_attempts=1),
        deps=fake_deps,
    )
    assert out["evaluation_decision"]["route"] == "continue"


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
    assert out["evaluation_decision"]["route"] == "rewrite"


async def test_evaluate_handles_dict_form_retrieval_and_node_errors(
    fake_deps: NodeDeps,
) -> None:
    """체크포인터 직렬화 round-trip — `retrieval`/`node_errors`가 dict로 들어와도 처리.

    Gemini Code Assist 권고: 노드 access는 `get_state_field`로 Pydantic/dict 양
    형태 수용.
    """
    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "x",
        # dict 형태(체크포인터 역직렬화 시뮬레이션)
        "retrieval": {  # type: ignore[typeddict-item]
            "retrieved_foods": [],
            "retrieval_confidence": 0.3,
        },
        "rewrite_attempts": 0,
        # dict 형태
        "node_errors": [  # type: ignore[typeddict-item]
            {
                "node_name": "rewrite_query",
                "error_class": "TimeoutException",
                "message": "transient",
                "attempts": 2,
            }
        ],
    }
    out = await evaluate_retrieval_quality(state, deps=fake_deps)
    # rewrite_query NodeError 1건 → attempts >= 1 → 강제 "continue"
    assert out["evaluation_decision"]["route"] == "continue"
    assert out["evaluation_decision"]["reason"] == "rewrite_limit_reached"


async def test_node_errors_rewrite_query_count_toward_attempts(
    fake_deps: NodeDeps,
) -> None:
    """무한 루프 회귀 가드 — wrapper fallback이 `rewrite_attempts` increment를 누락한 시나리오.

    `rewrite_query`가 transient 실패로 wrapper fallback → `rewrite_attempts == 0`
    그대로지만 `node_errors`에 rewrite_query NodeError 1건 누적 → 본 노드는 그것을
    1회 attempt로 인정하여 `"continue"` route 강제.
    """
    from app.graph.state import NodeError, RetrievalResult

    state: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "x",
        "retrieval": RetrievalResult(retrieved_foods=[], retrieval_confidence=0.3),
        "rewrite_attempts": 0,
        "node_errors": [
            NodeError(
                node_name="rewrite_query",
                error_class="TimeoutException",
                message="transient",
                attempts=2,
            )
        ],
    }
    out = await evaluate_retrieval_quality(state, deps=fake_deps)
    assert out["evaluation_decision"]["route"] == "continue"
    assert out["evaluation_decision"]["reason"] == "rewrite_limit_reached"
