"""Story 3.3 — `AnalysisGraphError` base + 4 서브클래스 ProblemDetail wire 단언 (AC9).

`FoodSeedError` / `GuidelineSeedError` 카탈로그 패턴 정합. 라우터 노출은 Story 3.7
책임이지만 RFC 7807 변환은 정의 시점에 검증 — 후속 스토리에서 wire drift 첫 hit.
"""

from __future__ import annotations

from app.core.exceptions import (
    AnalysisCheckpointerError,
    AnalysisGraphError,
    AnalysisNodeError,
    AnalysisRewriteLimitExceededError,
    AnalysisStateValidationError,
    BalanceNoteError,
)


def test_analysis_node_error_to_problem() -> None:
    exc = AnalysisNodeError("fetch_user_profile.user_not_found")
    problem = exc.to_problem(instance="/v1/analysis")
    assert problem.status == 503
    assert problem.code == "analysis.node.failed"
    assert problem.title == "Analysis Node Failed"
    assert problem.detail == "fetch_user_profile.user_not_found"


def test_analysis_checkpointer_error_to_problem() -> None:
    exc = AnalysisCheckpointerError("setup_failed")
    problem = exc.to_problem(instance="/lifespan")
    assert problem.status == 503
    assert problem.code == "analysis.checkpointer.failed"
    assert problem.title == "Analysis Checkpointer Failed"


def test_analysis_state_validation_error_to_problem() -> None:
    exc = AnalysisStateValidationError("ParseMealOutput.parsed_items invalid")
    problem = exc.to_problem(instance="/v1/analysis")
    assert problem.status == 422
    assert problem.code == "analysis.state.invalid"
    assert problem.title == "Analysis State Validation Failed"


def test_analysis_rewrite_limit_exceeded_to_problem() -> None:
    exc = AnalysisRewriteLimitExceededError("rewrite_attempts > 1")
    problem = exc.to_problem(instance="/v1/analysis")
    assert problem.status == 422
    assert problem.code == "analysis.rewrite.limit_exceeded"
    assert problem.title == "Self-RAG Rewrite Limit Exceeded"


def test_analysis_graph_error_base_status() -> None:
    """base 직접 raise는 권장 X지만 default 단언 — leak 시 500 위장 회피."""
    exc = AnalysisGraphError("internal")
    problem = exc.to_problem(instance="/v1/analysis")
    assert problem.status == 500
    assert problem.code == "analysis.graph.error"
    assert problem.title == "Analysis Graph Error"


def test_analysis_inheritance() -> None:
    assert issubclass(AnalysisGraphError, BalanceNoteError)
    assert issubclass(AnalysisNodeError, AnalysisGraphError)
    assert issubclass(AnalysisCheckpointerError, AnalysisGraphError)
    assert issubclass(AnalysisStateValidationError, AnalysisGraphError)
    assert issubclass(AnalysisRewriteLimitExceededError, AnalysisGraphError)


def test_analysis_node_error_caught_by_base() -> None:
    """`raise AnalysisNodeError(...) ` → `except AnalysisGraphError:` 매칭."""
    try:
        raise AnalysisNodeError("x")
    except AnalysisGraphError as e:
        assert e.detail == "x"
