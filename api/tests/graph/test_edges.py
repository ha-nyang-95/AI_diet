"""Story 3.3 — `app/graph/edges.py` 라우터 단위 테스트 (AC4)."""

from __future__ import annotations

import uuid

from app.graph.edges import route_after_evaluate, route_after_node_error
from app.graph.state import EvaluationDecision, MealAnalysisState, NodeError


def _state(**kwargs: object) -> MealAnalysisState:
    base: MealAnalysisState = {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "x",
        "rewrite_attempts": 0,
        "node_errors": [],
    }
    base.update(kwargs)  # type: ignore[typeddict-item]
    return base


def test_route_after_evaluate_rewrite() -> None:
    state = _state(
        evaluation_decision=EvaluationDecision(route="rewrite", reason="low"),
    )
    assert route_after_evaluate(state) == "rewrite_query"


def test_route_after_evaluate_continue() -> None:
    state = _state(
        evaluation_decision=EvaluationDecision(route="continue", reason="ok"),
    )
    assert route_after_evaluate(state) == "fetch_user_profile"


def test_route_after_evaluate_missing_decision_fail_soft() -> None:
    """`evaluation_decision` 부재 시 디폴트 `"continue"` — fail-soft."""
    state = _state()
    assert route_after_evaluate(state) == "fetch_user_profile"


def test_route_after_node_error_default_next() -> None:
    """노드 격리 — 한 노드 실패가 전체 파이프라인을 멈추지 않음."""
    state = _state(
        node_errors=[
            NodeError(node_name="parse_meal", error_class="X", message="m", attempts=2),
        ],
    )
    assert route_after_node_error(state) == "next"


def test_route_after_node_error_fetch_user_profile_terminates() -> None:
    """치명적 케이스 — `fetch_user_profile.user_not_found`만 `"end"` 반환."""
    state = _state(
        node_errors=[
            NodeError(
                node_name="fetch_user_profile",
                error_class="AnalysisNodeError",
                message="user_not_found",
                attempts=1,
            ),
        ],
    )
    assert route_after_node_error(state) == "end"


def test_route_after_node_error_fetch_user_profile_other_class_continues() -> None:
    """`fetch_user_profile`이라도 `AnalysisNodeError`가 아닌 transient류는 `"next"`."""
    state = _state(
        node_errors=[
            NodeError(
                node_name="fetch_user_profile",
                error_class="TimeoutException",
                message="db_slow",
                attempts=2,
            ),
        ],
    )
    assert route_after_node_error(state) == "next"


def test_route_after_node_error_empty_list_returns_next() -> None:
    state = _state(node_errors=[])
    assert route_after_node_error(state) == "next"
