"""Weekly report aggregation service + Pydantic 응답 모델 — Story 4.3.

``GET /v1/reports/weekly``의 단일 진입점 + 응답 schema SOT. ``meals`` LEFT JOIN
``meal_analyses`` 단일 SQL + KST ``ate_at`` group + 일별 7-요소 enumerate +
알레르기 노출 매칭(``contains_allergen`` SOT 재사용).

응답 모델(``WeeklyReportResponse`` / ``DailySummary`` / ``WeeklyMacros`` /
``AllergenExposure``)은 본 모듈에 정의 — 라우터(``api/v1/reports.py``)는 본 모듈에서
import. 순환 import 회피.

설계 정합:

- **N+1 회피**: 단일 SQL JOIN 1회. Story 3.7 ``idx_meal_analyses_user_id_created_at``
  forward-compat 인덱스 hit. 추가 라운드트립 0건(``current_user`` Dependency가 이미
  hydrated User 모델을 forward).
- **TDEE 계산**: ``compute_bmr_mifflin`` + ``compute_tdee`` SOT 재사용. 프로필 5컬럼
  중 하나라도 None이면 graceful ``tdee=None`` (404 X — 빈 차트 fallback UX).
- **Sentry transaction**: ``op="reports.weekly"`` + child span ``op="reports.aggregate"``
  (Story 3.3 ``op="analysis.pipeline"`` 패턴 정합).
- **structlog**: ``report.weekly.start``/``report.weekly.complete`` 2 이벤트 — masked
  ``user_id u_{8char}``, ``from_date``/``to_date``/``meals_count``/``analyzed_meals_count``/
  ``allergen_exposures_count``/``latency_ms``. NFR-S5 정합 — raw allergies/parsed_items/
  feedback_text 로깅 X.
- **결정성**: 동일 입력 → 동일 출력. 시계 의존 X(KST 변환은 SQL 측 SOT). LLM 호출 0건.
"""

from __future__ import annotations

import time as time_module
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, get_args
from zoneinfo import ZoneInfo

import sentry_sdk
import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.meal import Meal
from app.db.models.user import User
from app.domain.allergens import KOREAN_22_ALLERGENS, contains_allergen
from app.domain.bmr import compute_bmr_mifflin, compute_tdee
from app.domain.health_profile import HealthGoal, get_protein_target

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


log = structlog.get_logger(__name__)

_KST = ZoneInfo("Asia/Seoul")


# Story 4.3 — 22종 알레르기 SOT는 ``KOREAN_22_ALLERGENS`` 순서. 응답 ``allergen_exposures``
# 라벨 enum은 본 SOT 재사용(Story 1.5 정합). 신규 enum 도입 X.
AllergenLiteral = Literal[
    "우유",
    "메밀",
    "땅콩",
    "대두",
    "밀",
    "고등어",
    "게",
    "새우",
    "돼지고기",
    "아황산류",
    "복숭아",
    "토마토",
    "호두",
    "닭고기",
    "난류(가금류)",
    "쇠고기",
    "오징어",
    "조개류(굴/전복/홍합 포함)",
    "잣",
    "아몬드",
    "잔류 우유 단백",
    "기타",
]

# 22종 SOT 무결성 가드 — ``AllergenLiteral`` Literal과 ``KOREAN_22_ALLERGENS`` tuple
# 순서 정합 검증(import 시점 fail-fast). ``typing.get_args`` SOT 사용.
assert get_args(AllergenLiteral) == KOREAN_22_ALLERGENS, (
    "AllergenLiteral mismatch with KOREAN_22_ALLERGENS — Story 1.5 SOT 정합 깨짐"
)


# --- Pydantic 응답 모델 -------------------------------------------------------


class WeeklyMacros(BaseModel):
    """일별 평균 매크로 — 분석된 식단(``meal_analyses`` row 존재) 평균.

    ``protein_g_per_kg`` SOT: 평균 ``protein_g`` / ``users.weight_kg``. ``weight_kg``
    미설정 시 ``None`` — ProteinChart 권장 영역 미렌더 신호.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    carbohydrate_g: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    protein_g_per_kg: float | None = Field(default=None, ge=0)


class AllergenExposure(BaseModel):
    """일별 알레르기 노출 카운트. ``count``는 매칭된 meal 수(같은 알레르기·같은 날
    다중 식단 매칭 시 식단별 1 count). 0 entry는 응답에 미포함(UI 빈 차트 분기 단순화).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    allergen: AllergenLiteral
    count: int = Field(ge=1)


class DailySummary(BaseModel):
    """일별 7-요소 entry — 빈 날 포함(``meal_count=0`` + ``macros=None``).

    ``energy_kcal_total``는 *총합*(평균 X) — CalorieChart의 일별 칼로리 vs TDEE 비교
    입력. 분석된 식단 ``ma.energy_kcal`` 합산.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kst_date: date
    meal_count: int = Field(ge=0)
    macros: WeeklyMacros | None
    energy_kcal_total: float | None = Field(default=None, ge=0)
    allergen_exposures: list[AllergenExposure]


class WeeklyReportResponse(BaseModel):
    """``GET /v1/reports/weekly`` 응답 — Story 4.4 forward-compat ``insights`` 슬롯 포함.

    ``insights`` 본 스토리 baseline: *항상 None*. Story 4.4가 ``list[InsightCard]``로
    type narrow + 단백질 평균 vs 목표 미달 인사이트 1차 출처 인용. Story 2.4
    ``analysis_summary`` forward-compat 패턴 정합 — *항상 None*만 송신해 잘못된 값
    노출 차단.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_date: date
    to_date: date
    tdee: int | None
    health_goal: HealthGoal | None
    protein_target_g_per_kg_lower: float | None
    protein_target_g_per_kg_upper: float | None
    weight_kg: float | None
    daily_summaries: list[DailySummary]
    # Story 4.4 forward-compat — *baseline 항상 None*. type narrow는 Story 4.4 책임.
    insights: None = None


# --- helpers ------------------------------------------------------------------


def _mask_user_id(user_id: object) -> str:
    """UUID → ``u_{8char}`` 마스킹 (Story 3.x/4.2 패턴 정합)."""
    return f"u_{str(user_id).replace('-', '')[:8]}"


def _to_float_or_none(value: object) -> float | None:
    """Numeric/Decimal/None → float | None — 안전 변환."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return None


# --- service entry point ------------------------------------------------------


async def get_weekly_report(
    *,
    user: User,
    from_date: date,
    to_date: date,
    db: AsyncSession,
) -> WeeklyReportResponse:
    """7일 (또는 일반화된 0..30일) 주간 리포트 build — 단일 SQL JOIN aggregation.

    Args:
        user: ``current_user`` Dependency가 hydrate한 User ORM. ``weight_kg``/``height_cm``/
            ``age``/``activity_level``/``health_goal``/``allergies`` 7컬럼 활용.
        from_date: KST 시작 날짜 (포함).
        to_date: KST 종료 날짜 (포함, ``from_date <= to_date``).
        db: AsyncSession (라우터 ``DbSession`` Dependency).

    Returns:
        ``WeeklyReportResponse`` — 라우터가 그대로 응답.

    Raises:
        ValueError: ``from_date > to_date`` (라우터에서 RFC 7807 ``code=
            reports.invalid_date_range`` 변환). 본 service는 fail-fast 가드만 — *날짜
            범위 cap*은 라우터 책임.
    """
    if from_date > to_date:
        raise ValueError("from_date must be <= to_date")

    masked_user_id = _mask_user_id(user.id)
    log.info(
        "report.weekly.start",
        user_id=masked_user_id,
        from_date=str(from_date),
        to_date=str(to_date),
    )

    started_at = time_module.perf_counter()

    with sentry_sdk.start_transaction(op="reports.weekly", name="weekly_report"):
        # 1) TDEE / 단백질 target 계산 — 5 BMR 입력 모두 not None일 때만 ``tdee`` set.
        weight_kg = _to_float_or_none(user.weight_kg)
        height_cm = _to_float_or_none(user.height_cm)
        age_value = user.age
        activity_level = user.activity_level
        health_goal = user.health_goal

        tdee_int: int | None = None
        if (
            weight_kg is not None
            and height_cm is not None
            and age_value is not None
            and activity_level is not None
        ):
            try:
                # Story 3.5 ``UserProfileSnapshot.sex`` 부재 정합 — default ``"female"``
                # (데모 페르소나 *지수* 정합, ``data/README.md`` SOP). ``users.sex`` 컬럼
                # 추가는 Story 8.4 polish forward.
                bmr = compute_bmr_mifflin(
                    sex="female",
                    age=age_value,
                    weight_kg=weight_kg,
                    height_cm=height_cm,
                )
                tdee_int = round(compute_tdee(bmr=bmr, activity_level=activity_level))
            except ValueError:
                # CHECK 제약 통과한 row가 ``compute_bmr_mifflin``에서 ValueError —
                # graceful None 송신, 차트는 빈 라인.
                tdee_int = None

        protein_target = get_protein_target(health_goal)
        protein_lower = protein_target[0] if protein_target else None
        protein_upper = protein_target[1] if protein_target else None

        # 2) 단일 SQL — meals + LEFT JOIN meal_analyses(``selectinload`` SOT, Story 3.7
        # 패턴 정합). KST 변환은 Python 측에서 group(zoneinfo).
        with sentry_sdk.start_span(op="reports.aggregate"):
            stmt = (
                select(Meal)
                .options(selectinload(Meal.analysis))
                .where(
                    Meal.user_id == user.id,
                    Meal.deleted_at.is_(None),
                )
                .order_by(Meal.ate_at.asc())
            )
            result = await db.execute(stmt)
            all_meals = list(result.scalars().all())

            grouped: dict[date, list[Meal]] = defaultdict(list)
            for meal in all_meals:
                kst_date = meal.ate_at.astimezone(_KST).date()
                if from_date <= kst_date <= to_date:
                    grouped[kst_date].append(meal)

            # 3) 일별 enumerate(빈 날 포함) + aggregation.
            user_allergies_normalized: list[str] = list(user.allergies or [])
            # invalid 라벨(legacy row)은 silently skip — Story 1.5 CHECK 제약이 baseline
            # 가드이고, 본 service는 *조회*라 fail-fast X(report 끊김 회귀 차단).
            user_allergies_valid = [
                a for a in user_allergies_normalized if a in KOREAN_22_ALLERGENS
            ]

            daily_summaries: list[DailySummary] = []
            total_meals_count = 0
            total_analyzed_count = 0
            total_allergen_exposures = 0

            current = from_date
            while current <= to_date:
                rows = grouped.get(current, [])
                meal_count = len(rows)
                total_meals_count += meal_count

                # 분석된 식단(meal.analysis 존재)만 macros 평균/총합 계산.
                analyzed_rows = [r for r in rows if r.analysis is not None]
                analyzed_count = len(analyzed_rows)
                total_analyzed_count += analyzed_count

                macros: WeeklyMacros | None = None
                energy_kcal_total: float | None = None
                if analyzed_count > 0:
                    # ``analyzed_rows``는 ``r.analysis is not None`` 필터 통과 — narrowing
                    # 로컬 list로 명시(mypy union-attr 가드). 동시에 sum의 generator 타입은
                    # iterable[float] | iterable[int]로 좁혀 ``Generator[bool]`` 추론 회피.
                    analyses = [r.analysis for r in analyzed_rows if r.analysis is not None]
                    sum_carb: float = sum(
                        (_to_float_or_none(a.carbohydrate_g) or 0.0) for a in analyses
                    )
                    sum_protein: float = sum(
                        (_to_float_or_none(a.protein_g) or 0.0) for a in analyses
                    )
                    sum_fat: float = sum((_to_float_or_none(a.fat_g) or 0.0) for a in analyses)
                    sum_kcal: int = sum(int(a.energy_kcal) for a in analyses)

                    avg_carb = sum_carb / analyzed_count
                    avg_protein = sum_protein / analyzed_count
                    avg_fat = sum_fat / analyzed_count

                    protein_per_kg: float | None = None
                    if weight_kg is not None and weight_kg > 0:
                        protein_per_kg = round(avg_protein / weight_kg, 3)

                    macros = WeeklyMacros(
                        carbohydrate_g=round(avg_carb, 2),
                        protein_g=round(avg_protein, 2),
                        fat_g=round(avg_fat, 2),
                        protein_g_per_kg=protein_per_kg,
                    )
                    energy_kcal_total = float(sum_kcal)

                # 4) 알레르기 노출 매칭 — parsed_items[].name + feedback_text + raw_text를
                # substring 입력으로(NFR-S5 raw 텍스트 로깅 X). 사용자 ``allergies`` 22종
                # 부분집합만 검사 — 22종 전체 검사는 미설정 알레르기 노출 노이즈.
                exposure_counts: dict[str, int] = defaultdict(int)
                if user_allergies_valid:
                    for meal in rows:
                        meal_texts: list[str] = []
                        if meal.parsed_items:
                            for item in meal.parsed_items:
                                name = item.get("name") if isinstance(item, dict) else None
                                if isinstance(name, str) and name:
                                    meal_texts.append(name)
                        if meal.analysis is not None and meal.analysis.feedback_text:
                            meal_texts.append(meal.analysis.feedback_text)
                        # raw_text 포함 — 텍스트-only 입력(parsed_items None) 케이스 보장.
                        if meal.raw_text:
                            meal_texts.append(meal.raw_text)

                        joined = " ".join(meal_texts)
                        if not joined:
                            continue
                        for allergen in user_allergies_valid:
                            if contains_allergen(joined, allergen):
                                exposure_counts[allergen] += 1

                allergen_exposures_list: list[AllergenExposure] = []
                # 출력 순서는 ``KOREAN_22_ALLERGENS`` 정의 순(결정성).
                for allergen in KOREAN_22_ALLERGENS:
                    cnt = exposure_counts.get(allergen, 0)
                    if cnt > 0:
                        allergen_exposures_list.append(
                            AllergenExposure(allergen=allergen, count=cnt)
                        )
                total_allergen_exposures += len(allergen_exposures_list)

                daily_summaries.append(
                    DailySummary(
                        kst_date=current,
                        meal_count=meal_count,
                        macros=macros,
                        energy_kcal_total=energy_kcal_total,
                        allergen_exposures=allergen_exposures_list,
                    )
                )
                current += timedelta(days=1)

        latency_ms = int((time_module.perf_counter() - started_at) * 1000)
        log.info(
            "report.weekly.complete",
            user_id=masked_user_id,
            meals_count=total_meals_count,
            analyzed_meals_count=total_analyzed_count,
            allergen_exposures_count=total_allergen_exposures,
            latency_ms=latency_ms,
        )

        return WeeklyReportResponse(
            from_date=from_date,
            to_date=to_date,
            tdee=tdee_int,
            health_goal=health_goal,
            protein_target_g_per_kg_lower=protein_lower,
            protein_target_g_per_kg_upper=protein_upper,
            weight_kg=weight_kg,
            daily_summaries=daily_summaries,
        )


__all__ = [
    "AllergenExposure",
    "AllergenLiteral",
    "DailySummary",
    "WeeklyMacros",
    "WeeklyReportResponse",
    "get_weekly_report",
]
