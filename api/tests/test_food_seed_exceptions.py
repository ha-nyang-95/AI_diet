"""Story 3.1 — FoodSeedError 3 서브클래스 ProblemDetail wire 단언 (AC #8).

라우터 노출은 Story 3.3+ 책임이지만, RFC 7807 변환은 정의 시점에 검증해 후속
스토리에서 wire drift 첫 hit. ``MealError`` 카탈로그 패턴 정합 — status/code/title
ClassVar 단언.
"""

from __future__ import annotations

from app.core.exceptions import (
    FoodSeedAdapterError,
    FoodSeedError,
    FoodSeedQuotaExceededError,
    FoodSeedSourceUnavailableError,
)


def test_food_seed_source_unavailable_to_problem() -> None:
    exc = FoodSeedSourceUnavailableError("MFDS_OPENAPI_KEY missing")
    problem = exc.to_problem(instance="/v1/seed")
    assert problem.status == 503
    assert problem.code == "food_seed.source_unavailable"
    assert problem.title == "Food seed source unavailable"
    assert problem.detail == "MFDS_OPENAPI_KEY missing"
    assert problem.instance == "/v1/seed"


def test_food_seed_adapter_error_to_problem() -> None:
    exc = FoodSeedAdapterError("Vision embeddings transient retry exhausted")
    problem = exc.to_problem(instance="/v1/seed")
    assert problem.status == 503
    assert problem.code == "food_seed.adapter_error"
    assert problem.title == "Food seed adapter failure"


def test_food_seed_quota_exceeded_to_problem() -> None:
    exc = FoodSeedQuotaExceededError("MFDS daily quota exceeded")
    problem = exc.to_problem(instance="/v1/seed")
    assert problem.status == 503
    assert problem.code == "food_seed.quota_exceeded"
    assert problem.title == "Food seed API quota exceeded"


def test_food_seed_base_inheritance() -> None:
    """``FoodSeedError`` base + 3 서브클래스가 모두 ``FoodSeedError`` 하위인지 단언."""
    assert issubclass(FoodSeedSourceUnavailableError, FoodSeedError)
    assert issubclass(FoodSeedAdapterError, FoodSeedError)
    assert issubclass(FoodSeedQuotaExceededError, FoodSeedError)
