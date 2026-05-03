"""Story 3.5 — ``app.domain.bmr`` 단위 테스트 (AC1).

Mifflin-St Jeor + Harris-Benedict 활동 계수 SOT 검증. 입력 검증 + 5 activity
multiplier × 2 baseline 케이스 ≥ 12건(epic L650 ≥ 10 충족).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import get_args

import pytest

from app.domain.bmr import ACTIVITY_MULTIPLIERS, compute_bmr_mifflin, compute_tdee
from app.domain.health_profile import ActivityLevel


def test_bmr_male_baseline_30y_70kg_175cm() -> None:
    """남성 30세 70kg 175cm — ``10*70 + 6.25*175 - 5*30 + 5 = 1648.75``."""
    bmr = compute_bmr_mifflin(sex="male", age=30, weight_kg=70.0, height_cm=175.0)
    assert bmr == pytest.approx(1648.75)


def test_bmr_female_baseline_30y_60kg_165cm() -> None:
    """여성 30세 60kg 165cm — ``10*60 + 6.25*165 - 5*30 - 161 = 1320.25``."""
    bmr = compute_bmr_mifflin(sex="female", age=30, weight_kg=60.0, height_cm=165.0)
    assert bmr == pytest.approx(1320.25)


def test_bmr_returns_positive_float() -> None:
    bmr = compute_bmr_mifflin(sex="female", age=25, weight_kg=55.0, height_cm=160.0)
    assert isinstance(bmr, float)
    assert bmr > 0


def test_bmr_age_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"invalid bmr inputs"):
        compute_bmr_mifflin(sex="female", age=0, weight_kg=60.0, height_cm=165.0)


def test_bmr_age_negative_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"invalid bmr inputs"):
        compute_bmr_mifflin(sex="female", age=-1, weight_kg=60.0, height_cm=165.0)


def test_bmr_age_over_150_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"invalid bmr inputs"):
        compute_bmr_mifflin(sex="female", age=151, weight_kg=60.0, height_cm=165.0)


def test_bmr_weight_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"invalid bmr inputs"):
        compute_bmr_mifflin(sex="female", age=30, weight_kg=0.0, height_cm=165.0)


def test_bmr_weight_negative_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"invalid bmr inputs"):
        compute_bmr_mifflin(sex="female", age=30, weight_kg=-1.0, height_cm=165.0)


def test_bmr_height_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"invalid bmr inputs"):
        compute_bmr_mifflin(sex="female", age=30, weight_kg=60.0, height_cm=0.0)


def test_activity_multipliers_5_levels_sot() -> None:
    """Harris-Benedict 표준 5단계 — sedentary 1.2 ~ very_active 1.9."""
    assert ACTIVITY_MULTIPLIERS["sedentary"] == 1.2
    assert ACTIVITY_MULTIPLIERS["light"] == 1.375
    assert ACTIVITY_MULTIPLIERS["moderate"] == 1.55
    assert ACTIVITY_MULTIPLIERS["active"] == 1.725
    assert ACTIVITY_MULTIPLIERS["very_active"] == 1.9


def test_activity_multipliers_covers_all_activity_levels() -> None:
    """``ACTIVITY_MULTIPLIERS`` 가 ``ActivityLevel`` Literal 5종 모두 포함 — drift 가드."""
    expected = set(get_args(ActivityLevel))
    actual = set(ACTIVITY_MULTIPLIERS.keys())
    assert actual == expected


def test_activity_multipliers_is_mapping_type() -> None:
    """``Mapping[ActivityLevel, float]`` immutable view — runtime mutation 의도 X."""
    assert isinstance(ACTIVITY_MULTIPLIERS, Mapping)


def test_compute_tdee_sedentary() -> None:
    bmr = 1500.0
    tdee = compute_tdee(bmr=bmr, activity_level="sedentary")
    assert tdee == pytest.approx(1500.0 * 1.2)


def test_compute_tdee_light() -> None:
    bmr = 1500.0
    tdee = compute_tdee(bmr=bmr, activity_level="light")
    assert tdee == pytest.approx(1500.0 * 1.375)


def test_compute_tdee_moderate() -> None:
    bmr = 1500.0
    tdee = compute_tdee(bmr=bmr, activity_level="moderate")
    assert tdee == pytest.approx(1500.0 * 1.55)


def test_compute_tdee_active() -> None:
    bmr = 1500.0
    tdee = compute_tdee(bmr=bmr, activity_level="active")
    assert tdee == pytest.approx(1500.0 * 1.725)


def test_compute_tdee_very_active_female_age_50_baseline() -> None:
    """여성 50세 65kg 160cm + very_active baseline 종단 검증.

    BMR = ``10*65 + 6.25*160 - 5*50 - 161 = 650 + 1000 - 250 - 161 = 1239``
    TDEE = ``1239 * 1.9 = 2354.1``.
    """
    bmr = compute_bmr_mifflin(sex="female", age=50, weight_kg=65.0, height_cm=160.0)
    assert bmr == pytest.approx(1239.0)
    tdee = compute_tdee(bmr=bmr, activity_level="very_active")
    assert tdee == pytest.approx(2354.1)
