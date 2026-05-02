"""Story 3.3 — `_node_wrapper` retry + Sentry span + NodeError fallback (AC6, AC7)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import httpx

from app.graph.deps import NodeDeps
from app.graph.nodes._wrapper import _node_wrapper
from app.graph.state import MealAnalysisState


def _state() -> MealAnalysisState:
    return {
        "meal_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "raw_text": "짜장면",
        "rewrite_attempts": 0,
        "node_errors": [],
    }


async def test_wrapper_first_failure_then_success(fake_deps: NodeDeps) -> None:
    """첫 호출 httpx.TimeoutException → tenacity 1회 retry 발동 → 두 번째 정상."""
    call_count = {"n": 0}

    @_node_wrapper("test_node")
    async def _flaky(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("transient")
        return {"feedback": None}

    out = await _flaky(_state(), deps=fake_deps)
    assert call_count["n"] == 2
    assert out == {"feedback": None}


async def test_wrapper_two_failures_appends_node_error(fake_deps: NodeDeps) -> None:
    """2회 모두 실패 → NodeError 1건 누적 + 정상 종료(예외 X)."""

    @_node_wrapper("flaky_node")
    async def _always_fail(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
        raise httpx.TimeoutException("permanent")

    out = await _always_fail(_state(), deps=fake_deps)
    assert "node_errors" in out
    errs = out["node_errors"]
    assert len(errs) == 1
    assert errs[0].node_name == "flaky_node"
    assert errs[0].attempts == 2
    assert errs[0].error_class == "TimeoutException"


async def test_wrapper_pydantic_validation_retried_once(fake_deps: NodeDeps) -> None:
    """Pydantic ValidationError도 retry 발동 — 첫 실패 후 두 번째 성공."""
    from pydantic import BaseModel

    class _M(BaseModel):
        x: int

    call_count = {"n": 0}

    @_node_wrapper("validate_node")
    async def _node(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            _M(x="not_int")  # type: ignore[arg-type]
        return {"feedback": None}

    out = await _node(_state(), deps=fake_deps)
    assert call_count["n"] == 2
    assert out == {"feedback": None}


async def test_wrapper_analysis_node_error_skipped_retry(fake_deps: NodeDeps) -> None:
    """`AnalysisNodeError`는 retry skip — 즉시 fallback (1회 attempt)."""
    from app.core.exceptions import AnalysisNodeError

    call_count = {"n": 0}

    @_node_wrapper("immediate_fail")
    async def _node(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
        call_count["n"] += 1
        raise AnalysisNodeError("user_not_found")

    out = await _node(_state(), deps=fake_deps)
    assert call_count["n"] == 1  # retry skip
    assert len(out["node_errors"]) == 1
    assert out["node_errors"][0].error_class == "AnalysisNodeError"


async def test_wrapper_sentry_span_called(fake_deps: NodeDeps) -> None:
    """Sentry `start_span(op="langgraph.node", name=node_name)` 호출 검증.

    NOTE: spec naming line 315의 `description=`은 Sentry SDK 1.x 컨벤션. SDK 2.x
    에서 `description` deprecated → span은 `name`이 SOT (transaction과 동일 키).
    Debug Log line 545 정합.
    """

    @_node_wrapper("traced_node")
    async def _node(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
        return {"feedback": None}

    with patch("app.graph.nodes._wrapper.sentry_sdk") as mock_sdk:
        mock_span = mock_sdk.start_span.return_value.__enter__.return_value
        await _node(_state(), deps=fake_deps)

        mock_sdk.start_span.assert_called_once()
        kwargs = mock_sdk.start_span.call_args.kwargs
        assert kwargs.get("op") == "langgraph.node"
        assert kwargs.get("name") == "traced_node"
        mock_span.set_data.assert_called_once_with("rewrite_attempts", 0)
        mock_sdk.add_breadcrumb.assert_called_once()


async def test_wrapper_appends_to_existing_node_errors(fake_deps: NodeDeps) -> None:
    """이전 노드의 NodeError를 보존 — `state.node_errors` 누적."""
    from app.graph.state import NodeError

    @_node_wrapper("second_fail")
    async def _node(state: MealAnalysisState, *, deps: NodeDeps) -> dict[str, Any]:
        raise TimeoutError("transient")

    pre_existing = NodeError(
        node_name="prior_node",
        error_class="X",
        message="msg",
        attempts=2,
    )
    state = _state()
    state["node_errors"] = [pre_existing]

    out = await _node(state, deps=fake_deps)
    errs = out["node_errors"]
    assert len(errs) == 2
    assert errs[0].node_name == "prior_node"
    assert errs[1].node_name == "second_fail"
