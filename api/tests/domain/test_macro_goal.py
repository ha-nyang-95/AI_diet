"""Story 4.4 — ``app.domain.macro_goal`` 단위 테스트 (AC #2).

``MacroGoal`` Pydantic 모델 + ``MacroGoalPatchRequest`` at-least-one 가드.
``ratio`` all-or-none + sum=100 검증. ``extra="forbid"`` 정합.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.macro_goal import MacroGoal, MacroGoalPatchRequest


def test_macro_goal_happy_path_all_set() -> None:
    """5 필드 모두 set + ratio sum=100 — happy path."""
    goal = MacroGoal(
        daily_calorie_target_kcal=1800,
        protein_target_g_per_meal=25,
        macro_ratio_carb_pct=50,
        macro_ratio_protein_pct=25,
        macro_ratio_fat_pct=25,
    )
    assert goal.daily_calorie_target_kcal == 1800
    assert goal.protein_target_g_per_meal == 25
    assert goal.macro_ratio_carb_pct == 50


def test_macro_goal_happy_path_partial() -> None:
    """일부 필드만 set + ratio 3 필드 모두 None — partial happy path."""
    goal = MacroGoal(daily_calorie_target_kcal=1800)
    assert goal.daily_calorie_target_kcal == 1800
    assert goal.protein_target_g_per_meal is None
    assert goal.macro_ratio_carb_pct is None


def test_macro_goal_ratio_partial_set_rejected() -> None:
    """ratio 3 필드 중 일부만 set — ValidationError."""
    with pytest.raises(ValidationError, match="all-set or all-null"):
        MacroGoal(macro_ratio_carb_pct=50)


def test_macro_goal_ratio_sum_not_100_rejected() -> None:
    """ratio 3 필드 모두 set이지만 sum != 100 — ValidationError."""
    with pytest.raises(ValidationError, match="sum to 100"):
        MacroGoal(
            macro_ratio_carb_pct=50,
            macro_ratio_protein_pct=25,
            macro_ratio_fat_pct=20,  # sum=95
        )


def test_macro_goal_range_below_min() -> None:
    """``daily_calorie_target_kcal < 800`` — Pydantic ge 검증."""
    with pytest.raises(ValidationError):
        MacroGoal(daily_calorie_target_kcal=500)


def test_macro_goal_range_above_max() -> None:
    """``protein_target_g_per_meal > 200`` — Pydantic le 검증."""
    with pytest.raises(ValidationError):
        MacroGoal(protein_target_g_per_meal=300)


def test_macro_goal_extra_field_rejected() -> None:
    """extra="forbid" — unknown 필드 거부."""
    with pytest.raises(ValidationError):
        MacroGoal(unknown_field=42)  # type: ignore[call-arg]


def test_macro_goal_patch_request_at_least_one_required() -> None:
    """``MacroGoalPatchRequest`` 5 필드 모두 None — empty PATCH 거부."""
    with pytest.raises(ValidationError, match="at least one field required"):
        MacroGoalPatchRequest()


def test_macro_goal_patch_request_one_field_ok() -> None:
    """1 필드만 set이어도 OK — partial PATCH 정합."""
    req = MacroGoalPatchRequest(protein_target_g_per_meal=25)
    assert req.protein_target_g_per_meal == 25


def test_macro_goal_patch_request_inherits_ratio_validation() -> None:
    """``MacroGoalPatchRequest``도 ratio sum 검증 적용."""
    with pytest.raises(ValidationError):
        MacroGoalPatchRequest(
            macro_ratio_carb_pct=50,
            macro_ratio_protein_pct=25,
            macro_ratio_fat_pct=20,
        )


def test_macro_goal_zero_ratios_all_set_rejected() -> None:
    """ratio 3 필드 모두 0 — sum=0 != 100, 거부."""
    with pytest.raises(ValidationError, match="sum to 100"):
        MacroGoal(
            macro_ratio_carb_pct=0,
            macro_ratio_protein_pct=0,
            macro_ratio_fat_pct=0,
        )


def test_macro_goal_negative_value_rejected() -> None:
    """음수 — ge 게이트."""
    with pytest.raises(ValidationError):
        MacroGoal(macro_ratio_carb_pct=-1)
