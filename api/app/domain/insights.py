"""주간 인사이트 카드 엔진 — Story 4.4 (AC3, AC9).

4 카드 종류(`protein_deficit` / `calorie_diff` / `macro_ratio_drift` /
`allergen_exposure`) + 결정성 룰(LLM 호출 0건 + 시계 의존 X) + FR24 인용 패턴
강제 + FR25 광고 가드 사전 검증.

설계:
- ``InsightCard`` Pydantic ``frozen=True`` — 결정성 + immutability 보장.
- 카드 *최대 4개* cap + kind 우선순위 정렬 + ``severity="warning"`` 우선.
  ``allergen_exposure``는 sub-cap 2개(다중 알레르기 노출 사용자도 cognitive overload 회피).
- 5 인용 SOT — 모듈 상수(``_CITATION_*``) + import-time ad guard 검증
  (광고 표현 5종 미포함 — 식약처 식품표시광고법 시행규칙 별표 9 정합).
- ``generate_weekly_insights`` 입력은 *Story 4.3에서 이미 계산된 daily_summaries* —
  재계산 0건(allergen_exposures, macros 모두 입력 그대로 활용).

NFR-S5 정합 — 본 모듈은 본문 raw text 로깅 X. 호출 측(``report_service``)도 카드
``insights_count`` + 종류 boolean만 Sentry attribute로 송신.

Story 4.3 CR P22 정합 — 주간 평균 분모는 *비기록일 제외*(``meal_count > 0``인 날만).
"""

from __future__ import annotations

import re
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.ad_expression_guard import find_violations
from app.domain.health_profile import HealthGoal, get_protein_target

# --- Type aliases ------------------------------------------------------------

InsightKind = Literal[
    "protein_deficit",
    "calorie_diff",
    "macro_ratio_drift",
    "allergen_exposure",
]

InsightSeverity = Literal["info", "warning"]

InsightCtaAction = Literal["adjust_macro_goal"]


# --- 인용 SOT 상수 ----------------------------------------------------------
#
# 5개 인용 SOT — FR24 ``(출처: ...)`` 패턴 강제. 본문(title + body) 광고 가드는
# ``_validate_template_ad_safety`` import-time 가드가 SOT drift 회귀 차단.

_CITATION_PROTEIN_KDRIS: Final[str] = (
    "(출처: 보건복지부 2020 KDRIs, 대한비만학회 2024 비만치료지침)"
)
_CITATION_PROTEIN_USER: Final[str] = "(출처: 본인 설정 매크로 목표)"
_CITATION_CALORIE_USER: Final[str] = "(출처: 본인 설정 칼로리 목표)"
_CITATION_RATIO_USER: Final[str] = "(출처: 본인 설정 매크로 비율)"
_CITATION_ALLERGEN_MFDS: Final[str] = "(출처: 식약처 식품등의 표시기준)"


# --- Pydantic 모델 ----------------------------------------------------------


class InsightCta(BaseModel):
    """카드 행동 유도 — 매크로 목표 조정 페이지로 라우팅."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: InsightCtaAction
    label: str = Field(min_length=1, max_length=80)


class InsightCard(BaseModel):
    """주간 인사이트 단일 카드 — Story 4.4 SOT.

    ``citation``은 FR24 ``(출처: ...)`` 패턴 contain 검증 — 모듈 import 시점에
    ``_CITATION_*`` 5 상수 모두 ``^\\(출처: .+\\)$`` regex 매칭으로 fail-fast 가드.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: InsightKind
    severity: InsightSeverity
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=400)
    citation: str = Field(min_length=1, max_length=200)
    cta: InsightCta | None = None


# --- 카드 우선순위 정렬 키 ---------------------------------------------------

_KIND_PRIORITY: Final[dict[InsightKind, int]] = {
    "protein_deficit": 0,
    "calorie_diff": 1,
    "macro_ratio_drift": 2,
    "allergen_exposure": 3,
}

_SEVERITY_PRIORITY: Final[dict[InsightSeverity, int]] = {
    "warning": 0,
    "info": 1,
}

_INSIGHT_TOTAL_CAP: Final[int] = 4
_ALLERGEN_SUB_CAP: Final[int] = 2

_DEFAULT_CTA_LABEL: Final[str] = "매크로/칼로리 목표 조정"


# --- 인사이트 생성 -----------------------------------------------------------


def _avg_protein_g(daily_summaries: list[dict[str, Any]]) -> tuple[float, int] | None:
    """비기록일 제외 단백질 평균 + 분석된 식단 수. 분석 식단 0건이면 None."""
    rows = [d for d in daily_summaries if d.get("macros") is not None]
    if not rows:
        return None
    total = sum(_to_float(d["macros"]["protein_g"]) for d in rows)
    return total / len(rows), len(rows)


def _avg_calorie(daily_summaries: list[dict[str, Any]]) -> tuple[float, int] | None:
    """비기록일 제외(``meal_count > 0``) 칼로리 평균 + 기록일 수.

    Story 4.3 CR P22 정합 — 분모 = 비기록일 제외(``filter(meal_count > 0)``).
    """
    rows = [d for d in daily_summaries if d.get("meal_count", 0) > 0]
    if not rows:
        return None
    total = sum(_to_float(d.get("energy_kcal_total", 0) or 0) for d in rows)
    return total / len(rows), len(rows)


def _avg_macros(
    daily_summaries: list[dict[str, Any]],
) -> tuple[float, float, float] | None:
    """비기록일 제외 carb/protein/fat 평균. 분석 식단 0건이면 None."""
    rows = [d for d in daily_summaries if d.get("macros") is not None]
    if not rows:
        return None
    avg_carb = sum(_to_float(d["macros"]["carbohydrate_g"]) for d in rows) / len(rows)
    avg_protein = sum(_to_float(d["macros"]["protein_g"]) for d in rows) / len(rows)
    avg_fat = sum(_to_float(d["macros"]["fat_g"]) for d in rows) / len(rows)
    return avg_carb, avg_protein, avg_fat


def _to_float(value: object) -> float:
    """안전 변환 — int/float/Decimal 외에는 0.0 fallback."""
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _build_protein_deficit_card(
    *,
    daily_summaries: list[dict[str, Any]],
    weight_kg: float | None,
    health_goal: HealthGoal | None,
    macro_goal: dict[str, Any] | None,
) -> InsightCard | None:
    """단백질 부족 카드 — 우선순위 ① user macro_goal × 3끼 / ② weight_kg × KDRIs.

    평균 < 80% → warning, 80-95% → info, ≥ 95% → 카드 미생성.
    """
    avg_pair = _avg_protein_g(daily_summaries)
    if avg_pair is None:
        return None
    avg_protein, _ = avg_pair

    target_g: float | None = None
    citation: str
    using_user_goal = False
    if (
        macro_goal
        and isinstance(macro_goal.get("protein_target_g_per_meal"), int)
        and 5 <= macro_goal["protein_target_g_per_meal"] <= 200
    ):
        target_g = float(macro_goal["protein_target_g_per_meal"]) * 3
        citation = _CITATION_PROTEIN_USER
        using_user_goal = True
    elif weight_kg is not None and weight_kg > 0 and health_goal is not None:
        protein_range = get_protein_target(health_goal)
        if protein_range is None:
            return None
        target_g = weight_kg * protein_range[0]
        citation = _CITATION_PROTEIN_KDRIS
    else:
        return None

    if target_g <= 0:
        return None

    ratio = avg_protein / target_g
    if ratio >= 0.95:
        return None
    severity: InsightSeverity = "warning" if ratio < 0.80 else "info"

    avg_int = round(avg_protein)
    target_int = round(target_g)
    deficit_per_meal = max(1, round((target_g - avg_protein) / 3))

    if using_user_goal:
        protein_per_meal = int(macro_goal["protein_target_g_per_meal"])  # type: ignore[index]
        title = f"단백질 평균 {avg_int}g/일 — 본인 목표 {target_int}g 미달"
        body = (
            f"본인 설정 매끼 단백질 {protein_per_meal}g × 3끼 = {target_int}g 대비 "
            f"평균 {avg_int}g 미달. 다음 주 매끼 +{deficit_per_meal}g 보완 권장."
        )
    else:
        title = f"단백질 평균 {avg_int}g/일 — 목표 {target_int}g 미달"
        body = (
            f"단백질 평균 {avg_int}g/일 — 목표 {target_int}g 미달. "
            f"다음 주 매끼 단백질 +{deficit_per_meal}g 시도해보세요."
        )

    return InsightCard(
        kind="protein_deficit",
        severity=severity,
        title=title,
        body=body,
        citation=citation,
        cta=InsightCta(action="adjust_macro_goal", label=_DEFAULT_CTA_LABEL),
    )


def _build_calorie_diff_card(
    *,
    daily_summaries: list[dict[str, Any]],
    macro_goal: dict[str, Any] | None,
) -> InsightCard | None:
    """칼로리 편차 카드 — user macro_goal.daily_calorie_target_kcal 우선순위 ①.

    편차 ≥ 25% → warning, 10-25% → info, < 10% → 카드 미생성. TDEE 비교
    우선순위 ②는 Story 5.1 ``users.sex`` 컬럼 추가 후 활성화(본 스토리 OUT).
    """
    if (
        macro_goal is None
        or not isinstance(macro_goal.get("daily_calorie_target_kcal"), int)
        or not (800 <= macro_goal["daily_calorie_target_kcal"] <= 6000)
    ):
        return None
    target_kcal = float(macro_goal["daily_calorie_target_kcal"])

    avg_pair = _avg_calorie(daily_summaries)
    if avg_pair is None:
        return None
    avg_kcal, _ = avg_pair

    diff = avg_kcal - target_kcal
    diff_pct = abs(diff) / target_kcal * 100
    if diff_pct < 10:
        return None
    severity: InsightSeverity = "warning" if diff_pct >= 25 else "info"

    direction_phrase = "보다 약" if diff < 0 else "초과"
    over = diff > 0
    if over:
        body_phrase = (
            f"이번 주 평균 섭취 {round(avg_kcal)} kcal — "
            f"목표 {round(target_kcal)} kcal보다 약 {round(diff_pct)}% 초과. "
            f"다음 주 한끼당 -{max(1, round(abs(diff) / 3))} kcal 절감 권장."
        )
        title = (
            f"이번 주 칼로리 평균 {round(avg_kcal)} kcal — "
            f"목표 {round(target_kcal)} kcal 초과 {round(diff_pct)}%"
        )
    else:
        body_phrase = (
            f"이번 주 평균 섭취 {round(avg_kcal)} kcal — "
            f"목표 {round(target_kcal)} kcal{direction_phrase} {round(diff_pct)}% 부족. "
            f"점심·저녁 한끼당 +{max(1, round(abs(diff) / 3))} kcal 보완 권장."
        )
        title = (
            f"이번 주 칼로리 평균 {round(avg_kcal)} kcal — "
            f"목표 {round(target_kcal)} kcal 부족 {round(diff_pct)}%"
        )

    return InsightCard(
        kind="calorie_diff",
        severity=severity,
        title=title,
        body=body_phrase,
        citation=_CITATION_CALORIE_USER,
        cta=InsightCta(action="adjust_macro_goal", label=_DEFAULT_CTA_LABEL),
    )


def _build_macro_ratio_drift_card(
    *,
    daily_summaries: list[dict[str, Any]],
    macro_goal: dict[str, Any] | None,
) -> InsightCard | None:
    """매크로 비율 편차 카드 — 3 필드 전부 set일 때만 활성화.

    어느 한 macro라도 ±10pp 이상 편차 → warning, ±5-10pp → info, < ±5pp → 카드 미생성.
    """
    if macro_goal is None:
        return None
    target_carb = macro_goal.get("macro_ratio_carb_pct")
    target_pro = macro_goal.get("macro_ratio_protein_pct")
    target_fat = macro_goal.get("macro_ratio_fat_pct")
    if not (
        isinstance(target_carb, int) and isinstance(target_pro, int) and isinstance(target_fat, int)
    ):
        return None

    avg_macros = _avg_macros(daily_summaries)
    if avg_macros is None:
        return None
    avg_carb, avg_protein, avg_fat = avg_macros
    total_g = avg_carb + avg_protein + avg_fat
    if total_g <= 0:
        return None
    # 그램 → kcal 비율 환산: carb 4 / protein 4 / fat 9 (Atwater).
    carb_kcal = avg_carb * 4
    pro_kcal = avg_protein * 4
    fat_kcal = avg_fat * 9
    total_kcal = carb_kcal + pro_kcal + fat_kcal
    if total_kcal <= 0:
        return None
    actual_carb_pct = round(carb_kcal / total_kcal * 100)
    actual_pro_pct = round(pro_kcal / total_kcal * 100)
    actual_fat_pct = max(0, 100 - actual_carb_pct - actual_pro_pct)

    drifts = {
        "carb": actual_carb_pct - target_carb,
        "protein": actual_pro_pct - target_pro,
        "fat": actual_fat_pct - target_fat,
    }
    biggest_macro, biggest_drift = max(drifts.items(), key=lambda kv: abs(kv[1]))
    abs_drift = abs(biggest_drift)
    if abs_drift < 5:
        return None
    severity: InsightSeverity = "warning" if abs_drift >= 10 else "info"

    macro_label_ko = {"carb": "탄수화물", "protein": "단백질", "fat": "지방"}[biggest_macro]
    sign = "+" if biggest_drift > 0 else "-"
    title = (
        f"이번 주 매크로 비율 {actual_carb_pct}/{actual_pro_pct}/{actual_fat_pct} — "
        f"목표 {target_carb}/{target_pro}/{target_fat}"
    )
    body = (
        f"이번 주 평균 매크로 비율 {actual_carb_pct}/{actual_pro_pct}/{actual_fat_pct} — "
        f"목표 {target_carb}/{target_pro}/{target_fat}에서 "
        f"{macro_label_ko} {sign}{abs_drift}pp 편차. "
        f"다음 주 {macro_label_ko} 균형 조정 권장."
    )
    return InsightCard(
        kind="macro_ratio_drift",
        severity=severity,
        title=title,
        body=body,
        citation=_CITATION_RATIO_USER,
        cta=InsightCta(action="adjust_macro_goal", label=_DEFAULT_CTA_LABEL),
    )


def _build_allergen_exposure_cards(
    *,
    daily_summaries: list[dict[str, Any]],
) -> list[InsightCard]:
    """알레르기 노출 카드 — 알레르기당 7일 합산 ≥ 3건 시 1 카드. cta는 None."""
    counts: dict[str, int] = {}
    for d in daily_summaries:
        for exp in d.get("allergen_exposures", []) or []:
            allergen = exp.get("allergen") if isinstance(exp, dict) else None
            cnt = exp.get("count", 0) if isinstance(exp, dict) else 0
            if not isinstance(allergen, str) or not isinstance(cnt, int):
                continue
            counts[allergen] = counts.get(allergen, 0) + cnt

    cards: list[InsightCard] = []
    # 결정성 — 카운트 desc, allergen asc.
    sorted_pairs = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    for allergen, count in sorted_pairs:
        if count < 3:
            continue
        title = f"{allergen} 알레르기 노출 {count}건 — 식단 점검 권장"
        body = (
            f"이번 주 {allergen} 알레르기 노출 {count}건. "
            f"다음 주 식단에서 {allergen} 함유 식품 점검 권장."
        )
        cards.append(
            InsightCard(
                kind="allergen_exposure",
                severity="warning",
                title=title,
                body=body,
                citation=_CITATION_ALLERGEN_MFDS,
                cta=None,
            )
        )
    return cards[:_ALLERGEN_SUB_CAP]


def generate_weekly_insights(
    *,
    daily_summaries: list[dict[str, Any]],
    weight_kg: float | None,
    health_goal: HealthGoal | None,
    macro_goal: dict[str, Any] | None,
) -> list[InsightCard]:
    """주간 인사이트 카드 list — 최대 4개 cap + 우선순위 정렬.

    Args:
        daily_summaries: ``DailySummary.model_dump()`` 결과 list (7-요소).
        weight_kg: 사용자 ``weight_kg`` (None graceful).
        health_goal: 사용자 ``health_goal`` (None graceful).
        macro_goal: 사용자 ``macro_goal`` JSONB (None graceful).

    Returns:
        ``list[InsightCard]`` — 최대 ``_INSIGHT_TOTAL_CAP=4``개. 빈 list 가능.
    """
    cards: list[InsightCard] = []
    protein_card = _build_protein_deficit_card(
        daily_summaries=daily_summaries,
        weight_kg=weight_kg,
        health_goal=health_goal,
        macro_goal=macro_goal,
    )
    if protein_card is not None:
        cards.append(protein_card)

    calorie_card = _build_calorie_diff_card(daily_summaries=daily_summaries, macro_goal=macro_goal)
    if calorie_card is not None:
        cards.append(calorie_card)

    ratio_card = _build_macro_ratio_drift_card(
        daily_summaries=daily_summaries, macro_goal=macro_goal
    )
    if ratio_card is not None:
        cards.append(ratio_card)

    allergen_cards = _build_allergen_exposure_cards(daily_summaries=daily_summaries)
    cards.extend(allergen_cards)

    cards.sort(
        key=lambda c: (
            _SEVERITY_PRIORITY[c.severity],
            _KIND_PRIORITY[c.kind],
        )
    )
    return cards[:_INSIGHT_TOTAL_CAP]


# --- Import-time SOT drift 가드 ---------------------------------------------
#
# 4 카드 종류 *템플릿 본문 SOT*에 광고 표현 5종(진단/치료/예방/완화/처방)이 포함되지
# 않았는지 import 시점 fail-fast. 템플릿 갱신 시점 회귀 즉시 차단(FR25 정합).

_TEMPLATE_SAMPLES_FOR_AD_GUARD: Final[tuple[str, ...]] = (
    # protein_deficit (KDRIs)
    "단백질 평균 50g/일 — 목표 80g 미달",
    "단백질 평균 50g/일 — 목표 80g 미달. 다음 주 매끼 단백질 +10g 시도해보세요.",
    # protein_deficit (user)
    "단백질 평균 50g/일 — 본인 목표 75g 미달",
    "본인 설정 매끼 단백질 25g × 3끼 = 75g 대비 평균 50g 미달. 다음 주 매끼 +9g 보완 권장.",
    # calorie_diff
    "이번 주 칼로리 평균 1450 kcal — 목표 1800 kcal 부족 19%",
    "이번 주 평균 섭취 1450 kcal — 목표 1800 kcal보다 약 19% 부족. "
    "점심·저녁 한끼당 +117 kcal 보완 권장.",
    # macro_ratio_drift
    "이번 주 매크로 비율 60/15/25 — 목표 50/25/25",
    "이번 주 평균 매크로 비율 60/15/25 — 목표 50/25/25에서 단백질 -10pp 편차. "
    "다음 주 단백질 균형 조정 권장.",
    # allergen_exposure
    "복숭아 알레르기 노출 4건 — 식단 점검 권장",
    "이번 주 복숭아 알레르기 노출 4건. 다음 주 식단에서 복숭아 함유 식품 점검 권장.",
    # CTA label
    _DEFAULT_CTA_LABEL,
)

for _sample in _TEMPLATE_SAMPLES_FOR_AD_GUARD:
    _violations = find_violations(_sample)
    if _violations:
        raise RuntimeError(
            f"insights template contains prohibited ad expression: "
            f"sample={_sample!r}, violations={_violations}"
        )


# --- FR24 인용 패턴 SOT 가드 -------------------------------------------------
#
# 5 인용 상수 모두 ``(출처: ...)`` 패턴 강제 — import 시점 fail-fast. 향후 SOT 갱신 시
# regex 위반 즉시 ImportError(template 코드 버그 차단).

_CITATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\(출처: .+\)$")

for _name, _citation in (
    ("_CITATION_PROTEIN_KDRIS", _CITATION_PROTEIN_KDRIS),
    ("_CITATION_PROTEIN_USER", _CITATION_PROTEIN_USER),
    ("_CITATION_CALORIE_USER", _CITATION_CALORIE_USER),
    ("_CITATION_RATIO_USER", _CITATION_RATIO_USER),
    ("_CITATION_ALLERGEN_MFDS", _CITATION_ALLERGEN_MFDS),
):
    if not _CITATION_PATTERN.match(_citation):
        raise RuntimeError(
            f"insights citation SOT violates FR24 pattern: name={_name}, value={_citation!r}"
        )


__all__ = [
    "InsightCard",
    "InsightCta",
    "InsightCtaAction",
    "InsightKind",
    "InsightSeverity",
    "generate_weekly_insights",
]
