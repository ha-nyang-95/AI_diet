"""Story 2.4 — ``MealAnalysisSummary`` / ``MealMacros`` Pydantic 단위 테스트 (AC10).

Epic 3 forward-compat 슬롯 — Story 3.3 ``meal_analyses`` 테이블 wire 시점에 채움.
본 스토리 baseline은 *Pydantic 인터페이스*만 검증 — wire 자체는 ``analysis_summary``
*항상 None*.

4 케이스 (AC10 명시):
- fit_score 0-100 범위 강제 (FR21 정합).
- ``extra="forbid"`` 미등록 키 거부.
- ``MealMacros`` 모든 필드 ge=0 단언 (식약처 OpenAPI 표준 키).
- ``fit_score_label`` Literal 5단계 외 값 거부 (NFR-A4 색약 대응 텍스트 라벨 정합).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.meals import MealAnalysisSummary, MealMacros


def _valid_macros_payload() -> dict[str, float]:
    return {
        "carbohydrate_g": 25.0,
        "protein_g": 12.0,
        "fat_g": 4.0,
        "energy_kcal": 240.0,
    }


def _valid_summary_payload() -> dict[str, object]:
    return {
        "fit_score": 72,
        "fit_score_label": "good",
        "macros": _valid_macros_payload(),
        "feedback_summary": "단백질이 충분합니다.",
    }


def test_meal_analysis_summary_validates_fit_score_range() -> None:
    """``fit_score`` 0-100 범위 — 101은 거부."""
    payload = _valid_summary_payload()
    payload["fit_score"] = 101
    with pytest.raises(ValidationError):
        MealAnalysisSummary.model_validate(payload)

    payload["fit_score"] = -1
    with pytest.raises(ValidationError):
        MealAnalysisSummary.model_validate(payload)


def test_meal_analysis_summary_rejects_extra_field() -> None:
    """``extra="forbid"`` — 미등록 키 거부 (silent unknown field 차단)."""
    payload = _valid_summary_payload()
    payload["extra"] = "x"
    with pytest.raises(ValidationError):
        MealAnalysisSummary.model_validate(payload)


def test_meal_analysis_summary_validates_macros_non_negative() -> None:
    """``MealMacros`` 모든 필드 ge=0 — 음수 거부 (식약처 OpenAPI 표준 키 정합)."""
    macros_payload = _valid_macros_payload()
    macros_payload["protein_g"] = -1.0
    with pytest.raises(ValidationError):
        MealMacros.model_validate(macros_payload)

    # MealAnalysisSummary 통합 검증.
    summary_payload = _valid_summary_payload()
    summary_payload["macros"] = macros_payload
    with pytest.raises(ValidationError):
        MealAnalysisSummary.model_validate(summary_payload)


def test_meal_analysis_summary_validates_label_literal() -> None:
    """``fit_score_label`` Literal — 5단계 외 값 거부."""
    payload = _valid_summary_payload()
    payload["fit_score_label"] = "bad"  # 정의 외 라벨
    with pytest.raises(ValidationError):
        MealAnalysisSummary.model_validate(payload)

    # 5단계 라벨은 모두 통과 — 정상 케이스 회귀 차단.
    for valid_label in ("allergen_violation", "low", "moderate", "good", "excellent"):
        payload = _valid_summary_payload()
        payload["fit_score_label"] = valid_label
        instance = MealAnalysisSummary.model_validate(payload)
        assert instance.fit_score_label == valid_label
