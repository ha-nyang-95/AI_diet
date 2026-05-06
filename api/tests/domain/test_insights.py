"""Story 4.4 — ``app.domain.insights`` 단위 테스트 (AC #3, #9).

4 카드 종류(`protein_deficit` / `calorie_diff` / `macro_ratio_drift` /
`allergen_exposure`) + 결정성 룰 + 카드 우선순위 cap + 인용 SOT 검증.

import-time ad guard는 모듈 import 시점에 자동 실행 — 본 테스트는 호출 분기만.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.domain.insights import (
    InsightCard,
    generate_weekly_insights,
)


def _build_summaries(
    protein_g_list: list[float | None],
    *,
    energy_kcal_list: list[float | None] | None = None,
    carb_g_list: list[float | None] | None = None,
    fat_g_list: list[float | None] | None = None,
    allergen_exposures_list: list[list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """7일 daily_summaries dict list 빌더 — protein_g 기반 macros 채움."""
    base_date = date(2026, 5, 1)
    energy_kcal_list = energy_kcal_list or [None] * 7
    carb_g_list = carb_g_list or [50.0] * 7
    fat_g_list = fat_g_list or [20.0] * 7
    allergen_exposures_list = allergen_exposures_list or [[] for _ in range(7)]

    summaries: list[dict[str, Any]] = []
    for i in range(7):
        protein_g = protein_g_list[i]
        macros: dict[str, Any] | None
        meal_count = 0
        energy_total = energy_kcal_list[i]
        if protein_g is None:
            macros = None
        else:
            meal_count = 1
            macros = {
                "carbohydrate_g": carb_g_list[i],
                "protein_g": protein_g,
                "fat_g": fat_g_list[i],
                "protein_g_per_kg": None,
            }
        if energy_total is not None and meal_count == 0:
            meal_count = 1
        summaries.append(
            {
                "kst_date": base_date + timedelta(days=i),
                "meal_count": meal_count,
                "macros": macros,
                "energy_kcal_total": energy_total,
                "allergen_exposures": allergen_exposures_list[i],
            }
        )
    return summaries


# --- protein_deficit -------------------------------------------------------


def test_protein_deficit_user_goal_priority_warning() -> None:
    """우선순위 ① user macro_goal × 3끼 = 75g 대비 평균 50g(67%) — warning."""
    summaries = _build_summaries([50.0] * 7)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal={"protein_target_g_per_meal": 25},
    )
    assert any(c.kind == "protein_deficit" and c.severity == "warning" for c in cards)
    protein = next(c for c in cards if c.kind == "protein_deficit")
    assert "본인 설정" in protein.body
    assert protein.citation == "(출처: 본인 설정 매크로 목표)"
    assert protein.cta is not None


def test_protein_deficit_kdris_priority_info() -> None:
    """우선순위 ② weight_kg × KDRIs 1.2 = 72g 대비 평균 65g(90%) — info."""
    summaries = _build_summaries([65.0] * 7)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal=None,
    )
    protein = next((c for c in cards if c.kind == "protein_deficit"), None)
    assert protein is not None
    assert protein.severity == "info"
    assert "보건복지부 2020 KDRIs" in protein.citation


def test_protein_deficit_no_card_when_meets_goal() -> None:
    """평균 ≥ 95% 목표 — 카드 미생성."""
    summaries = _build_summaries([76.0] * 7)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal=None,
    )
    assert all(c.kind != "protein_deficit" for c in cards)


# --- calorie_diff ----------------------------------------------------------


def test_calorie_diff_under_target_warning() -> None:
    """평균 1450 vs 목표 1800 = 19% 부족 — info(>=10% <25%)."""
    summaries = _build_summaries(
        [50.0] * 7,
        energy_kcal_list=[1450.0] * 7,
    )
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=None,
        health_goal=None,
        macro_goal={"daily_calorie_target_kcal": 1800},
    )
    calorie = next((c for c in cards if c.kind == "calorie_diff"), None)
    assert calorie is not None
    assert calorie.severity == "info"
    assert calorie.citation == "(출처: 본인 설정 칼로리 목표)"


def test_calorie_diff_over_target_warning() -> None:
    """평균 2400 vs 목표 1800 = 33% 초과 — warning."""
    summaries = _build_summaries(
        [50.0] * 7,
        energy_kcal_list=[2400.0] * 7,
    )
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=None,
        health_goal=None,
        macro_goal={"daily_calorie_target_kcal": 1800},
    )
    calorie = next((c for c in cards if c.kind == "calorie_diff"), None)
    assert calorie is not None
    assert calorie.severity == "warning"
    assert "초과" in calorie.title


def test_calorie_diff_no_card_when_under_10pct() -> None:
    """편차 < 10% — 카드 미생성."""
    summaries = _build_summaries(
        [50.0] * 7,
        energy_kcal_list=[1750.0] * 7,
    )
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=None,
        health_goal=None,
        macro_goal={"daily_calorie_target_kcal": 1800},
    )
    assert all(c.kind != "calorie_diff" for c in cards)


# --- macro_ratio_drift -----------------------------------------------------


def test_macro_ratio_drift_partial_ratios_disabled() -> None:
    """ratio 3 필드 부분 set은 schema에서 막히지만 본 generate_*는 graceful skip."""
    summaries = _build_summaries([50.0] * 7)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal={"daily_calorie_target_kcal": 1800},  # ratio 미설정
    )
    assert all(c.kind != "macro_ratio_drift" for c in cards)


def test_macro_ratio_drift_warning() -> None:
    """평균 비율 vs 목표에서 ≥ 10pp drift — warning.

    평균 carb 200 / pro 25 / fat 20 g/일 (kcal: 800/100/180=1080) = 74/9/17 →
    목표 50/25/25에서 carb +24pp drift → warning.
    """
    summaries = _build_summaries([25.0] * 7, carb_g_list=[200.0] * 7, fat_g_list=[20.0] * 7)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal={
            "macro_ratio_carb_pct": 50,
            "macro_ratio_protein_pct": 25,
            "macro_ratio_fat_pct": 25,
        },
    )
    ratio = next((c for c in cards if c.kind == "macro_ratio_drift"), None)
    assert ratio is not None
    assert ratio.severity == "warning"
    assert ratio.citation == "(출처: 본인 설정 매크로 비율)"


def test_macro_ratio_drift_no_card_when_within_5pp() -> None:
    """평균 비율 ±5pp 이하 — 카드 미생성.

    평균 carb 100 / pro 50 / fat 22 g/일 (kcal: 400/200/198=798) = 50/25/25.
    """
    summaries = _build_summaries([50.0] * 7, carb_g_list=[100.0] * 7, fat_g_list=[22.0] * 7)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal={
            "macro_ratio_carb_pct": 50,
            "macro_ratio_protein_pct": 25,
            "macro_ratio_fat_pct": 25,
        },
    )
    assert all(c.kind != "macro_ratio_drift" for c in cards)


# --- allergen_exposure ----------------------------------------------------


def test_allergen_exposure_threshold_3_triggers() -> None:
    """알레르기 7일 합산 ≥ 3건 — 1 카드. cta is None."""
    exposures = [[]] * 7
    exposures[0] = [{"allergen": "복숭아", "count": 2}]
    exposures[1] = [{"allergen": "복숭아", "count": 2}]
    summaries = _build_summaries([50.0] * 7, allergen_exposures_list=exposures)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal=None,
    )
    allergen = next((c for c in cards if c.kind == "allergen_exposure"), None)
    assert allergen is not None
    assert allergen.cta is None
    assert "복숭아" in allergen.title
    assert allergen.citation == "(출처: 식약처 식품등의 표시기준)"


def test_allergen_exposure_below_threshold_no_card() -> None:
    """7일 합산 < 3건 — 카드 미생성."""
    exposures = [[]] * 7
    exposures[0] = [{"allergen": "복숭아", "count": 2}]
    summaries = _build_summaries([50.0] * 7, allergen_exposures_list=exposures)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal=None,
    )
    assert all(c.kind != "allergen_exposure" for c in cards)


def test_allergen_exposure_multiple_allergens_sub_cap_2() -> None:
    """다중 알레르기 ≥ 3건 — sub-cap 2개만 노출(sort by count desc + name asc)."""
    exposures: list[list[dict[str, Any]]] = [[] for _ in range(7)]
    exposures[0] = [
        {"allergen": "복숭아", "count": 5},
        {"allergen": "메밀", "count": 4},
        {"allergen": "땅콩", "count": 3},
    ]
    summaries = _build_summaries([50.0] * 7, allergen_exposures_list=exposures)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal=None,
    )
    allergens = [c for c in cards if c.kind == "allergen_exposure"]
    assert len(allergens) == 2  # sub-cap
    assert "복숭아" in allergens[0].title
    assert "메밀" in allergens[1].title


# --- 카드 우선순위 cap -----------------------------------------------------


def test_total_cap_enforced_priority_order() -> None:
    """4 카드 cap + warning 우선 + kind 우선순위 정렬."""
    exposures: list[list[dict[str, Any]]] = [[] for _ in range(7)]
    exposures[0] = [
        {"allergen": "복숭아", "count": 5},
        {"allergen": "메밀", "count": 4},
    ]
    # protein deficit warning + calorie diff warning + ratio drift warning + allergens(2)
    summaries = _build_summaries(
        [40.0] * 7,
        energy_kcal_list=[2500.0] * 7,
        carb_g_list=[200.0] * 7,
        fat_g_list=[20.0] * 7,
        allergen_exposures_list=exposures,
    )
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal={
            "daily_calorie_target_kcal": 1800,
            "protein_target_g_per_meal": 25,
            "macro_ratio_carb_pct": 50,
            "macro_ratio_protein_pct": 25,
            "macro_ratio_fat_pct": 25,
        },
    )
    assert len(cards) <= 4
    kinds = [c.kind for c in cards]
    # protein_deficit이 가장 우선(severity warning + priority 0).
    assert kinds[0] == "protein_deficit"


def test_empty_summaries_return_no_cards() -> None:
    """daily_summaries 모두 빈 날 — 카드 미생성."""
    summaries = _build_summaries([None] * 7)
    cards = generate_weekly_insights(
        daily_summaries=summaries,
        weight_kg=60.0,
        health_goal="weight_loss",
        macro_goal={"protein_target_g_per_meal": 25},
    )
    assert cards == []


def test_insight_card_frozen_immutable() -> None:
    """``InsightCard``는 frozen=True — 변경 시도 시 ValidationError."""
    card = InsightCard(
        kind="protein_deficit",
        severity="warning",
        title="title",
        body="body",
        citation="(출처: 보건복지부 2020 KDRIs)",
    )
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        card.title = "changed"  # type: ignore[misc]


def test_template_ad_guard_imports_clean() -> None:
    """import-time ad guard 통과 — 본 테스트는 import 자체로 검증."""
    from app.domain import insights  # noqa: F401

    # SOT samples는 모두 광고 가드 통과해야 import 성공.
    assert True
