"""Weekly report aggregation service + Pydantic 응답 모델 — Story 4.3.

``GET /v1/reports/weekly``의 단일 진입점 + 응답 schema SOT. ``meals`` LEFT JOIN
``meal_analyses`` 단일 SQL + KST ``ate_at`` group + 일별 7-요소 enumerate +
알레르기 노출 매칭(``contains_allergen`` SOT 재사용).

응답 모델(``WeeklyReportResponse`` / ``DailySummary`` / ``WeeklyMacros`` /
``AllergenExposure``)은 본 모듈에 정의 — 라우터(``api/v1/reports.py``)는 본 모듈에서
import. 순환 import 회피.

설계 정합:

- **N+1 회피**: 단일 SQL JOIN 1회 + KST 윈도우 SQL-side 필터(``ate_at`` UTC bracket).
  Story 3.7 ``idx_meal_analyses_user_id_created_at`` forward-compat 인덱스 hit. 추가
  라운드트립 0건(``current_user`` Dependency가 이미 hydrated User 모델을 forward).
- **TDEE 계산**: ``users.sex`` 컬럼 부재로 본 스토리 baseline은 ``tdee=None`` 항상 송신.
  Story 5.1 (건강 프로필 수정)에서 ``users.sex`` 컬럼 + 온보딩 흐름 추가 후 BMR 계산
  활성화 — 현 시점 잘못된 sex 디폴트 (~166 kcal 어긋남) 회귀 차단. 차트는 빈 라인 fallback.
- **Sentry transaction**: ``op="reports.weekly"`` + child span ``op="reports.aggregate"``
  (Story 3.3 ``op="analysis.pipeline"`` 패턴 정합) + unhandled 예외 시 ``set_status(
  "internal_error")`` (Story 4.2 retro 정합).
- **structlog**: ``report.weekly.start``/``report.weekly.complete`` 2 이벤트 — masked
  ``user_id u_{8char}``, ``from_date``/``to_date``/``meals_count``/``analyzed_meals_count``/
  ``allergen_exposures_count``/``latency_ms``. NFR-S5 정합 — raw allergies/parsed_items/
  feedback_text 로깅 X.
- **결정성**: 동일 입력 → 동일 출력. 시계 의존 X(KST 변환은 SQL 측 SOT). LLM 호출 0건.
"""

from __future__ import annotations

import time as time_module
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, get_args
from zoneinfo import ZoneInfo

import sentry_sdk
import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.exceptions import WeeklyReportInvalidDateRangeError
from app.db.models.meal import Meal
from app.db.models.user import User
from app.domain.allergens import KOREAN_22_ALLERGENS, contains_allergen
from app.domain.health_profile import HealthGoal, get_protein_target

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


log = structlog.get_logger(__name__)

_KST = ZoneInfo("Asia/Seoul")
_UTC = UTC

# Story 4.3 일반화 cap — 본 스토리는 7일 default, Story 4.4 인사이트가 14일 trailing
# window 활용 가능. 30일 초과는 Postgres index hit 효과 감소 + UX 가독성 저하 → 거부.
_MAX_REPORT_DAYS = 30


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
# 순서 정합 검증(import 시점 fail-fast). ``typing.get_args`` SOT 사용. ``assert``는
# ``python -O`` 시 strip되어 silent SOT drift 위험 — explicit ``raise``로 변경.
if get_args(AllergenLiteral) != KOREAN_22_ALLERGENS:
    raise RuntimeError(
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
        WeeklyReportInvalidDateRangeError: ``from_date > to_date`` 또는 (to-from)>30일.
            라우터의 글로벌 핸들러가 RFC 7807 ``code=reports.invalid_date_range``로 변환.
            본 service가 SOT — 라우터는 wrapper.
    """
    if from_date > to_date:
        raise WeeklyReportInvalidDateRangeError(
            f"from_date ({from_date}) must be <= to_date ({to_date})"
        )
    if (to_date - from_date).days > _MAX_REPORT_DAYS:
        raise WeeklyReportInvalidDateRangeError(
            f"date range exceeds {_MAX_REPORT_DAYS} days (got {(to_date - from_date).days})"
        )

    masked_user_id = _mask_user_id(user.id)
    log.info(
        "report.weekly.start",
        user_id=masked_user_id,
        from_date=str(from_date),
        to_date=str(to_date),
    )

    started_at = time_module.perf_counter()

    transaction = sentry_sdk.start_transaction(op="reports.weekly", name="weekly_report")
    with transaction:
        try:
            # 1) TDEE / 단백질 target 계산 — ``users.sex`` 컬럼 부재(Story 5.1/8.4 polish
            # forward)이므로 ``tdee`` 항상 None 송신. spec AC1 ``BMR 입력 5건 중 하나라도
            # None이면 tdee=None graceful`` 정합 — 잘못된 sex 디폴트로 50% 사용자에게
            # ~166 kcal 어긋난 TDEE 송신 회귀 차단.
            weight_kg = _to_float_or_none(user.weight_kg)
            health_goal = user.health_goal

            tdee_int: int | None = None
            # NOTE: Story 5.1에서 ``users.sex`` 컬럼 추가 후 본 분기 활성화.
            # ``compute_bmr_mifflin`` + ``compute_tdee`` 호출은 sex/age/weight/height/
            # activity_level 5건 모두 not None일 때만.

            protein_target = get_protein_target(health_goal)
            protein_lower = protein_target[0] if protein_target else None
            protein_upper = protein_target[1] if protein_target else None

            # 2) 단일 SQL — meals + LEFT JOIN meal_analyses(``selectinload`` SOT, Story 3.7
            # 패턴 정합) + KST 윈도우 SQL-side 필터(NFR-P8: 사용자 전체 history 로드 회피).
            # KST 윈도우 → UTC bracket 변환: from_date 00:00 KST = (from-9h) UTC,
            # to_date+1 00:00 KST = (to+1-9h) UTC. ``ate_at < to_exclusive_utc``로 inclusive
            # 종료일 정합.
            from_dt_utc = datetime.combine(from_date, time.min, tzinfo=_KST).astimezone(_UTC)
            to_dt_exclusive_utc = datetime.combine(
                to_date + timedelta(days=1), time.min, tzinfo=_KST
            ).astimezone(_UTC)

            with sentry_sdk.start_span(op="reports.aggregate"):
                stmt = (
                    select(Meal)
                    .options(selectinload(Meal.analysis))
                    .where(
                        Meal.user_id == user.id,
                        Meal.deleted_at.is_(None),
                        Meal.ate_at >= from_dt_utc,
                        Meal.ate_at < to_dt_exclusive_utc,
                    )
                    .order_by(Meal.ate_at.asc())
                )
                result = await db.execute(stmt)
                all_meals = list(result.scalars().all())

                grouped: dict[date, list[Meal]] = defaultdict(list)
                for meal in all_meals:
                    # Defensive: ``Meal.ate_at`` ORM은 TIMESTAMPTZ이지만 legacy 시드/테스트
                    # fixture가 naive datetime을 인입할 수 있어 ``astimezone()`` ValueError
                    # 회귀 차단(endpoint 500 방지).
                    ate_at = (
                        meal.ate_at
                        if meal.ate_at.tzinfo is not None
                        else meal.ate_at.replace(tzinfo=_UTC)
                    )
                    kst_date = ate_at.astimezone(_KST).date()
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
                    # ``a.energy_kcal``은 ORM ``Mapped[int]``지만 legacy NULL row 또는
                    # 미래 schema drift 방어 — ``or 0`` graceful + ``round(float(...))``로
                    # 절단(int(399.99)=399) 회귀 차단.
                    sum_kcal: int = sum(round(float(a.energy_kcal or 0)) for a in analyses)

                    avg_carb = sum_carb / analyzed_count
                    avg_protein = sum_protein / analyzed_count
                    avg_fat = sum_fat / analyzed_count

                    protein_per_kg: float | None = None
                    if weight_kg is not None and weight_kg > 0:
                        protein_per_kg = max(0.0, round(avg_protein / weight_kg, 3))

                    # ``Field(ge=0)`` ValidationError 회귀 차단(``round(-0.0001, 2) = -0.0``
                    # 등 부동소수 경계). ``max(0.0, ...)`` clamp.
                    macros = WeeklyMacros(
                        carbohydrate_g=max(0.0, round(avg_carb, 2)),
                        protein_g=max(0.0, round(avg_protein, 2)),
                        fat_g=max(0.0, round(avg_fat, 2)),
                        protein_g_per_kg=protein_per_kg,
                    )
                    energy_kcal_total = float(sum_kcal)

                # 4) 알레르기 노출 매칭 — ``parsed_items[].name`` + ``feedback_text``
                # substring 입력(NFR-S5 raw 텍스트 로깅 X). spec AC1 정합 — ``raw_text``는
                # 광고 가드 미통과 자유 입력이라 false-positive 벡터(예: "도넛 알레르기 없음"
                # → 호두/도넛 트리거)이므로 매칭 입력에서 제외. 사용자 ``allergies`` 22종
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
                from_date=str(from_date),
                to_date=str(to_date),
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
        except Exception:
            # Story 4.2 retro 패턴 — unhandled 예외 시 Sentry 대시보드에 명시적 실패 기록
            # (``with`` exit 전에 ``set_status`` 호출해야 effect). re-raise 후 글로벌
            # 핸들러가 RFC 7807 응답 변환.
            transaction.set_status("internal_error")
            raise


__all__ = [
    "AllergenExposure",
    "AllergenLiteral",
    "DailySummary",
    "WeeklyMacros",
    "WeeklyReportResponse",
    "get_weekly_report",
]
