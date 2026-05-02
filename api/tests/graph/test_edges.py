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


def test_route_after_evaluate_rewrite_dict() -> None:
    """AC3 정합 — 노드는 `.model_dump()`로 dict 저장."""
    state = _state(
        evaluation_decision=EvaluationDecision(route="rewrite", reason="low").model_dump(),
    )
    assert route_after_evaluate(state) == "rewrite_query"


def test_route_after_evaluate_continue_dict() -> None:
    state = _state(
        evaluation_decision=EvaluationDecision(route="continue", reason="ok").model_dump(),
    )
    assert route_after_evaluate(state) == "fetch_user_profile"


def test_route_after_evaluate_pydantic_instance_defensive() -> None:
    """defensive — 만약 노드가 instance를 흘리더라도 `_extract_route`가 처리."""
    state = _state(
        evaluation_decision=EvaluationDecision(route="rewrite", reason="low"),
    )
    assert route_after_evaluate(state) == "rewrite_query"


def test_route_after_evaluate_missing_decision_fail_soft() -> None:
    """`evaluation_decision` 부재 시 디폴트 `"continue"` — fail-soft."""
    state = _state()
    assert route_after_evaluate(state) == "fetch_user_profile"


def test_route_after_evaluate_unknown_route_logs_warning_and_continues(
    caplog: object,
) -> None:
    """알 수 없는 route 값 → `route.unknown` warning + `"continue"` 강제."""
    state = _state(evaluation_decision={"route": "abort", "reason": "tampered"})
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


def test_route_after_node_error_handles_dict_form_node_errors() -> None:
    """체크포인터 직렬화 round-trip — `node_errors` 요소가 dict로 들어와도 처리.

    Gemini Code Assist 권고: state 필드가 dict로 역직렬화 시에도 attribute access
    (`last.node_name`)가 깨지지 않도록 `get_state_field`로 양 형태 수용.
    """
    state = _state(
        node_errors=[
            {
                "node_name": "fetch_user_profile",
                "error_class": "AnalysisNodeError",
                "message": "user_not_found",
                "attempts": 1,
            },
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
