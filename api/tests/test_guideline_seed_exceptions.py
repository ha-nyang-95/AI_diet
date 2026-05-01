"""Story 3.2 — GuidelineSeedError 3 서브클래스 ProblemDetail wire 단언 (AC #6).

라우터 노출은 Story 3.6+ 책임이지만, RFC 7807 변환은 정의 시점에 검증해 후속
스토리에서 wire drift 첫 hit. ``FoodSeedError`` 카탈로그 패턴 정합 — status/code/title
ClassVar 단언.
"""

from __future__ import annotations

from app.core.exceptions import (
    GuidelineSeedAdapterError,
    GuidelineSeedError,
    GuidelineSeedSourceUnavailableError,
    GuidelineSeedValidationError,
)


def test_guideline_seed_source_unavailable_to_problem() -> None:
    exc = GuidelineSeedSourceUnavailableError("OPENAI_API_KEY not configured")
    problem = exc.to_problem(instance="/v1/seed")
    assert problem.status == 503
    assert problem.code == "guideline_seed.source_unavailable"
    assert problem.title == "Guideline seed source unavailable"
    assert problem.detail == "OPENAI_API_KEY not configured"
    assert problem.instance == "/v1/seed"


def test_guideline_seed_adapter_error_to_problem() -> None:
    exc = GuidelineSeedAdapterError("PDF text extraction failed: invalid header")
    problem = exc.to_problem(instance="/v1/seed")
    assert problem.status == 503
    assert problem.code == "guideline_seed.adapter_error"
    assert problem.title == "Guideline seed adapter failure"


def test_guideline_seed_validation_error_to_problem() -> None:
    exc = GuidelineSeedValidationError("frontmatter validation failed for kdris-2020-amdr.md")
    problem = exc.to_problem(instance="/v1/seed")
    assert problem.status == 422
    assert problem.code == "guideline_seed.validation_failed"
    assert problem.title == "Guideline seed frontmatter validation failed"


def test_guideline_seed_base_inheritance() -> None:
    """``GuidelineSeedError`` base + 3 서브클래스가 모두 ``GuidelineSeedError`` 하위인지 단언."""
    assert issubclass(GuidelineSeedSourceUnavailableError, GuidelineSeedError)
    assert issubclass(GuidelineSeedAdapterError, GuidelineSeedError)
    assert issubclass(GuidelineSeedValidationError, GuidelineSeedError)
