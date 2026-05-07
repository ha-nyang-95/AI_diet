"""사용자 매크로 목표 도메인 SOT — Story 4.4 (AC2).

5개 partial 필드(`daily_calorie_target_kcal` / `protein_target_g_per_meal` /
`macro_ratio_carb_pct` / `macro_ratio_protein_pct` / `macro_ratio_fat_pct`) +
`@model_validator` ratio all-or-none + sum=100 가드.

본 모듈은 4 callsite SOT(라우터 / report_service / graph state / nudge_scheduler).
순환 import 회피 + DB CHECK ``ck_users_macro_goal_shape``와 1차 가드(double gate).

REST PATCH 표준 — `MacroGoalPatchRequest`는 *at-least-one* 가드 추가(빈 PATCH 거부).
``null`` 명시 송신은 *해당 키 삭제*(라우터 SQL `macro_goal - 'key'` 분기 처리).
"""

from __future__ import annotations

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# DB CHECK 제약 SQL — alembic 0015 + ``app/db/models/user.py`` __table_args__ 양쪽에서
# import하는 *단일 SOT*. Pydantic 1차 가드 통과 후 DB 2차 가드(double gate). ratio
# all-or-none + sum=100은 Pydantic-only(SQL JSONB 다중 키 expression 복잡 + DB
# 가드 목적은 *taint payload* shape 차단).
MACRO_GOAL_CHECK_SQL: Final[str] = (
    "macro_goal IS NULL OR ("
    "jsonb_typeof(macro_goal) = 'object' "
    "AND (NOT macro_goal ? 'daily_calorie_target_kcal' OR ("
    "jsonb_typeof(macro_goal->'daily_calorie_target_kcal') = 'number' "
    "AND (macro_goal->>'daily_calorie_target_kcal')::numeric BETWEEN 800 AND 6000"
    ")) "
    "AND (NOT macro_goal ? 'protein_target_g_per_meal' OR ("
    "jsonb_typeof(macro_goal->'protein_target_g_per_meal') = 'number' "
    "AND (macro_goal->>'protein_target_g_per_meal')::numeric BETWEEN 5 AND 200"
    ")) "
    "AND (NOT macro_goal ? 'macro_ratio_carb_pct' OR ("
    "jsonb_typeof(macro_goal->'macro_ratio_carb_pct') = 'number' "
    "AND (macro_goal->>'macro_ratio_carb_pct')::numeric BETWEEN 0 AND 100"
    ")) "
    "AND (NOT macro_goal ? 'macro_ratio_protein_pct' OR ("
    "jsonb_typeof(macro_goal->'macro_ratio_protein_pct') = 'number' "
    "AND (macro_goal->>'macro_ratio_protein_pct')::numeric BETWEEN 0 AND 100"
    ")) "
    "AND (NOT macro_goal ? 'macro_ratio_fat_pct' OR ("
    "jsonb_typeof(macro_goal->'macro_ratio_fat_pct') = 'number' "
    "AND (macro_goal->>'macro_ratio_fat_pct')::numeric BETWEEN 0 AND 100"
    "))"
    ")"
)


class MacroGoal(BaseModel):
    """사용자 매크로 목표 — 5 partial 필드 SOT.

    범위는 KDRIs 2020 일반 성인 EER 1700-2700 kcal + 보수적 cap(800-6000) /
    epics 예시 25g/매끼 + cap 5-200. ratio 3 필드는 *all-or-none* + sum=100.

    ``extra="forbid"``로 미래 필드 추가 시 schema drift 명시 차단.
    """

    model_config = ConfigDict(extra="forbid")

    daily_calorie_target_kcal: int | None = Field(default=None, ge=800, le=6000)
    protein_target_g_per_meal: int | None = Field(default=None, ge=5, le=200)
    macro_ratio_carb_pct: int | None = Field(default=None, ge=0, le=100)
    macro_ratio_protein_pct: int | None = Field(default=None, ge=0, le=100)
    macro_ratio_fat_pct: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _validate_ratio_completeness(self) -> Self:
        """매크로 비율 3 필드는 *all-or-none* + 합=100(정수, ±0).

        부분 set은 ``ValueError`` raise → 라우터의 ``MacroGoalInvalidError`` 변환.
        """
        ratios = (
            self.macro_ratio_carb_pct,
            self.macro_ratio_protein_pct,
            self.macro_ratio_fat_pct,
        )
        set_count = sum(1 for v in ratios if v is not None)
        if set_count == 0:
            return self
        if set_count != 3:
            raise ValueError("macro_ratio_*_pct must be all-set or all-null; got partial")
        ratio_sum = sum(v for v in ratios if v is not None)
        if ratio_sum != 100:
            raise ValueError(f"macro_ratio_*_pct must sum to 100; got {ratio_sum}")
        return self


class MacroGoalPatchRequest(MacroGoal):
    """``PATCH /v1/users/me/macro_goal`` body — 5 필드 partial + at-least-one 가드.

    ``MacroGoal`` 상속이라 ratio all-or-none + sum=100 검증 자동 포함. 본 클래스는
    *empty body* 거부만 추가(``{}`` 송신은 의미 없음 → 400). *명시적으로 송신된
    필드*가 1건 이상이어야 통과 — ``None`` 명시 송신은 *해당 키 삭제*로 valid 입력.
    """

    @model_validator(mode="after")
    def _validate_at_least_one_set(self) -> Self:
        """``model_fields_set``이 빈 set이면 empty PATCH — 거부."""
        if not self.model_fields_set:
            raise ValueError("at least one field required")
        return self


__all__ = ["MACRO_GOAL_CHECK_SQL", "MacroGoal", "MacroGoalPatchRequest"]
