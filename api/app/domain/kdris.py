"""Story 3.5 — KDRIs AMDR 매크로 룰 + ``health_goal`` 별 칼로리 adjustment SOT.

baseline 출처:
- 보건복지부 *2020 한국인 영양소 섭취기준* (KDRIs) — AMDR(Acceptable Macronutrient
  Distribution Range) 매크로 권장 비율.
- 대한비만학회 *비만 진료지침 9판 2024* — 체중 감량 시 단백질 우선 매크로 권고.
- 대한당뇨병학회 *당뇨병 진료지침* — 당뇨 탄수화물 절감 + 지방·식이섬유 우선 매크로 권고.

설계:
- ``MacroTargets`` Pydantic frozen — 탄/단/지 비율(0-1) + sum=1.0 invariant validator.
- ``KDRIS_MACRO_TARGETS`` lookup table — ``HealthGoal`` 4종 baseline.
- ``get_macro_targets`` / ``get_calorie_adjustment`` — 알 수 없는 enum/None은 fail-soft
  fallback(``maintenance`` / 0). ``fetch_user_profile``이 None을 막지만 회귀 가드.

본 baseline은 *MVP 데모 가능 정확도* 목표. Story 8.4 polish 슬롯에서 W2 spike 후
재튜닝(``age × sex × ethnicity`` 보정 등). 외주 인수 SOP는 ``api/data/README.md``.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.health_profile import HealthGoal

log = structlog.get_logger()


class MacroTargets(BaseModel):
    """탄/단/지 비율 SOT — sum ≈ 1.0 invariant validator로 drift 차단."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    carb_pct: float = Field(ge=0, le=1)
    protein_pct: float = Field(ge=0, le=1)
    fat_pct: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sum_to_one(self) -> MacroTargets:
        total = self.carb_pct + self.protein_pct + self.fat_pct
        if abs(total - 1.0) >= 0.001:
            raise ValueError("macro targets must sum to 1.0")
        return self


# KDRIs 2020 AMDR + 대비/대당학회 권고 baseline. Story 3.5 fit_score lookup의 SOT.
KDRIS_MACRO_TARGETS: dict[HealthGoal, MacroTargets] = {
    # 체중 감량 — 대한비만학회 9판 2024: 단백질 25% 우선 + 지방 25% 절제.
    "weight_loss": MacroTargets(carb_pct=0.50, protein_pct=0.25, fat_pct=0.25),
    # 근비대 — 단백질 1.6-2.0g/kg 권장 정합 (탄수 45 / 단 30 / 지 25).
    "muscle_gain": MacroTargets(carb_pct=0.45, protein_pct=0.30, fat_pct=0.25),
    # 유지 — KDRIs AMDR 중간값 (탄수 55 / 단 20 / 지 25).
    "maintenance": MacroTargets(carb_pct=0.55, protein_pct=0.20, fat_pct=0.25),
    # 당뇨 — 대한당뇨병학회 매크로 권고 — 탄수 절감 + 식이섬유 우선 (탄 45 / 단 25 / 지 30).
    "diabetes_management": MacroTargets(carb_pct=0.45, protein_pct=0.25, fat_pct=0.30),
}

# health_goal 별 1일 칼로리 adjustment(kcal/day). TDEE에 가산.
_CALORIE_ADJUSTMENT: dict[HealthGoal, int] = {
    "weight_loss": -500,
    "muscle_gain": +300,
    "maintenance": 0,
    "diabetes_management": 0,
}


def get_macro_targets(health_goal: HealthGoal | None) -> MacroTargets:
    """``KDRIS_MACRO_TARGETS[health_goal]`` lookup — 알 수 없는 enum / None은 fail-soft.

    ``maintenance`` fallback. ``fetch_user_profile``이 None을 차단(profile_incomplete)
    하지만 회귀 가드로 fallback.
    """
    if health_goal is None or health_goal not in KDRIS_MACRO_TARGETS:
        log.warning("kdris.unknown_health_goal", value=health_goal)
        return KDRIS_MACRO_TARGETS["maintenance"]
    return KDRIS_MACRO_TARGETS[health_goal]


def get_calorie_adjustment(health_goal: HealthGoal | None) -> int:
    """1일 칼로리 adjustment(kcal/day) lookup. 알 수 없는 enum / None → 0 fail-soft."""
    if health_goal is None or health_goal not in _CALORIE_ADJUSTMENT:
        return 0
    return _CALORIE_ADJUSTMENT[health_goal]
