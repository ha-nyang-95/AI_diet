"""Story 3.5 — ``app.domain.kdris`` 단위 테스트 (AC2).

KDRIs AMDR baseline + health_goal 별 매크로 비율 + invariant + fail-soft fallback.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.domain.health_profile import HealthGoal
from app.domain.kdris import (
    KDRIS_MACRO_TARGETS,
    MacroTargets,
    get_calorie_adjustment,
    get_macro_targets,
)


def test_macro_targets_sum_to_one_invariant_valid() -> None:
    """sum=1.0 정상 → 인스턴스 생성."""
    mt = MacroTargets(carb_pct=0.5, protein_pct=0.25, fat_pct=0.25)
    assert mt.carb_pct == 0.5


def test_macro_targets_sum_violation_raises_validation_error() -> None:
    """sum != 1.0 → ValidationError (model_validator 발화)."""
    with pytest.raises(ValidationError, match=r"macro targets must sum to 1.0"):
        MacroTargets(carb_pct=0.5, protein_pct=0.3, fat_pct=0.3)


def test_macro_targets_field_bounds_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        MacroTargets(carb_pct=-0.1, protein_pct=0.5, fat_pct=0.6)


def test_macro_targets_field_bounds_over_one_rejected() -> None:
    with pytest.raises(ValidationError):
        MacroTargets(carb_pct=1.5, protein_pct=0.0, fat_pct=0.0)


def test_macro_targets_frozen_blocks_reassignment() -> None:
    """frozen=True → instance attribute set 시 ValidationError."""
    mt = MacroTargets(carb_pct=0.5, protein_pct=0.25, fat_pct=0.25)
    with pytest.raises(ValidationError):
        mt.carb_pct = 0.6  # type: ignore[misc]


def test_macro_targets_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        MacroTargets(  # type: ignore[call-arg]
            carb_pct=0.5,
            protein_pct=0.25,
            fat_pct=0.25,
            extra_field="x",
        )


def test_kdris_macro_targets_covers_all_health_goals() -> None:
    """``KDRIS_MACRO_TARGETS`` 가 ``HealthGoal`` Literal 4종 모두 포함 — drift 가드."""
    expected = set(get_args(HealthGoal))
    actual = set(KDRIS_MACRO_TARGETS.keys())
    assert actual == expected


def test_kdris_macro_targets_weight_loss_baseline() -> None:
    """체중 감량 — 대한비만학회 9판 단백질 25% 우선 baseline."""
    mt = KDRIS_MACRO_TARGETS["weight_loss"]
    assert mt.carb_pct == 0.50
    assert mt.protein_pct == 0.25
    assert mt.fat_pct == 0.25


def test_kdris_macro_targets_muscle_gain_baseline() -> None:
    """근비대 — 단백질 30% 우선 baseline."""
    mt = KDRIS_MACRO_TARGETS["muscle_gain"]
    assert mt.protein_pct == 0.30


def test_kdris_macro_targets_maintenance_baseline() -> None:
    """유지 — KDRIs AMDR 중간값 (탄수 55%)."""
    mt = KDRIS_MACRO_TARGETS["maintenance"]
    assert mt.carb_pct == 0.55


def test_kdris_macro_targets_diabetes_baseline() -> None:
    """당뇨 — 대당학회 권고 — 탄수 45% + 지방 30%."""
    mt = KDRIS_MACRO_TARGETS["diabetes_management"]
    assert mt.carb_pct == 0.45
    assert mt.fat_pct == 0.30


def test_kdris_macro_targets_all_satisfy_invariant() -> None:
    """4 health_goal 모두 sum ≈ 1.0 invariant 통과 (정의 시점 검증 — 회귀 가드)."""
    for goal, mt in KDRIS_MACRO_TARGETS.items():
        total = mt.carb_pct + mt.protein_pct + mt.fat_pct
        assert abs(total - 1.0) < 0.001, f"{goal} macro sum {total} != 1.0"


def test_get_macro_targets_known_goal_returns_lookup() -> None:
    mt = get_macro_targets("weight_loss")
    assert mt is KDRIS_MACRO_TARGETS["weight_loss"]


def test_get_macro_targets_unknown_goal_falls_back_to_maintenance() -> None:
    """알 수 없는 enum → maintenance fail-soft fallback."""
    mt = get_macro_targets("unknown_goal")  # type: ignore[arg-type]
    assert mt is KDRIS_MACRO_TARGETS["maintenance"]


def test_get_macro_targets_none_falls_back_to_maintenance() -> None:
    """None → maintenance fail-soft fallback."""
    mt = get_macro_targets(None)
    assert mt is KDRIS_MACRO_TARGETS["maintenance"]


def test_get_calorie_adjustment_4_goals() -> None:
    """4 health_goal 칼로리 adjustment 정합."""
    assert get_calorie_adjustment("weight_loss") == -500
    assert get_calorie_adjustment("muscle_gain") == +300
    assert get_calorie_adjustment("maintenance") == 0
    assert get_calorie_adjustment("diabetes_management") == 0


def test_get_calorie_adjustment_unknown_returns_zero() -> None:
    assert get_calorie_adjustment("unknown") == 0  # type: ignore[arg-type]
    assert get_calorie_adjustment(None) == 0
