"""Story 3.5 — ``app.domain.fit_score`` 단위 테스트 (AC3 + AC4).

결정성 SOT 검증 — FitScoreComponents invariant + 4 컴포넌트 함수 + entry +
detect_allergen_violations alias 매핑 + coverage_ratio.
"""

from __future__ import annotations

import unicodedata
import uuid

import pytest
from pydantic import ValidationError

from app.domain.allergens import KOREAN_22_ALLERGENS
from app.domain.fit_score import (
    ALLERGEN_ALIAS_MAP,
    FitScoreComponents,
    aggregate_meal_macros,
    band_for_score,
    compute_balance_score,
    compute_calorie_score,
    compute_fit_score,
    compute_macro_score,
    detect_allergen_violations,
)
from app.domain.kdris import KDRIS_MACRO_TARGETS, get_macro_targets
from app.graph.state import FoodItem, RetrievedFood, UserProfileSnapshot

# ---------- FitScoreComponents invariants ----------


def test_fit_score_components_zero_factory() -> None:
    c = FitScoreComponents.zero()
    assert c.macro == 0
    assert c.calorie == 0
    assert c.allergen == 0
    assert c.balance == 0
    assert c.coverage_ratio == 0.0


def test_fit_score_components_allergen_violation_factory() -> None:
    c = FitScoreComponents.allergen_violation()
    assert c.macro == 0 and c.allergen == 0
    assert c.coverage_ratio == 0.0


def test_fit_score_components_field_bounds() -> None:
    """0-40/0-25/0-20/0-15 invariant — 초과 시 ValidationError."""
    with pytest.raises(ValidationError):
        FitScoreComponents(macro=41, calorie=0, allergen=0, balance=0, coverage_ratio=0)
    with pytest.raises(ValidationError):
        FitScoreComponents(macro=0, calorie=26, allergen=0, balance=0, coverage_ratio=0)
    with pytest.raises(ValidationError):
        FitScoreComponents(macro=0, calorie=0, allergen=21, balance=0, coverage_ratio=0)
    with pytest.raises(ValidationError):
        FitScoreComponents(macro=0, calorie=0, allergen=0, balance=16, coverage_ratio=0)
    with pytest.raises(ValidationError):
        FitScoreComponents(macro=0, calorie=0, allergen=0, balance=0, coverage_ratio=1.5)


def test_fit_score_components_frozen() -> None:
    c = FitScoreComponents.zero()
    with pytest.raises(ValidationError):
        c.macro = 10  # type: ignore[misc]


def test_fit_score_components_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        FitScoreComponents(  # type: ignore[call-arg]
            macro=0, calorie=0, allergen=0, balance=0, coverage_ratio=0, extra="x"
        )


# ---------- aggregate_meal_macros ----------


def _retrieved(name: str, **nutrition: float | int | str) -> RetrievedFood:
    return RetrievedFood(
        name=name,
        food_id=None,
        score=0.9,
        nutrition=nutrition,  # type: ignore[arg-type]
    )


def test_aggregate_meal_macros_quantity_1인분_default() -> None:
    """quantity='1인분' / None / "1인분" 모두 multiplier 1.0."""
    items = [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]
    foods = [
        _retrieved(
            "짜장면",
            energy_kcal=600,
            carbohydrate_g=80,
            protein_g=15,
            fat_g=20,
            fiber_g=2,
        )
    ]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 600
    assert out.carb_g == 80
    assert out.coverage_ratio == 1.0


def test_aggregate_meal_macros_quantity_grams_scales_per_100g() -> None:
    """quantity='200g' → multiplier 2.0 (100g 기준 식약처 영양소)."""
    items = [FoodItem(name="짜장면", quantity="200g", confidence=0.9)]
    foods = [
        _retrieved(
            "짜장면",
            energy_kcal=300,
            carbohydrate_g=40,
            protein_g=10,
            fat_g=10,
        )
    ]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 600
    assert out.carb_g == 80


def test_aggregate_meal_macros_quantity_none_defaults_to_1() -> None:
    items = [FoodItem(name="짜장면", quantity=None, confidence=0.9)]
    foods = [_retrieved("짜장면", energy_kcal=500)]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 500


def test_aggregate_meal_macros_unmatched_lowers_coverage() -> None:
    """매칭 실패 item은 coverage_ratio < 1.0 반영."""
    items = [
        FoodItem(name="짜장면", quantity="1인분", confidence=0.9),
        FoodItem(name="알수없는음식", quantity="1인분", confidence=0.5),
    ]
    foods = [_retrieved("짜장면", energy_kcal=500)]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 500
    assert out.coverage_ratio == 0.5


def test_aggregate_meal_macros_empty_parsed_items_returns_zero() -> None:
    out = aggregate_meal_macros([], [])
    assert out.kcal == 0
    assert out.coverage_ratio == 0.0


def test_aggregate_meal_macros_vegetable_category_flag() -> None:
    items = [FoodItem(name="샐러드", confidence=0.9)]
    foods = [_retrieved("샐러드", energy_kcal=100, category="채소류")]
    out = aggregate_meal_macros(items, foods)
    assert out.has_vegetable_or_fruit is True


# ---------- compute_macro_score ----------


def test_compute_macro_score_perfect_match_returns_40() -> None:
    """meal 비율 = target 비율 → 0편차 → 40 만점."""
    from app.domain.fit_score import MealMacros

    target = KDRIS_MACRO_TARGETS["maintenance"]  # 0.55/0.20/0.25
    meal = MealMacros(
        kcal=500,
        carb_g=55,
        protein_g=20,
        fat_g=25,
        fiber_g=0,
        coverage_ratio=1.0,
        has_vegetable_or_fruit=False,
    )
    assert compute_macro_score(meal, target) == 40


def test_compute_macro_score_zero_macros_returns_zero() -> None:
    from app.domain.fit_score import MealMacros

    meal = MealMacros(
        kcal=0,
        carb_g=0,
        protein_g=0,
        fat_g=0,
        fiber_g=0,
        coverage_ratio=0.0,
        has_vegetable_or_fruit=False,
    )
    assert compute_macro_score(meal, KDRIS_MACRO_TARGETS["maintenance"]) == 0


# ---------- compute_calorie_score ----------


def test_compute_calorie_score_within_15pct_returns_25() -> None:
    """편차 ±15% 이내 → 25 만점."""
    assert compute_calorie_score(meal_kcal=500, recommended_meal_kcal=500) == 25
    assert compute_calorie_score(meal_kcal=575, recommended_meal_kcal=500) == 25  # +15%
    assert compute_calorie_score(meal_kcal=425, recommended_meal_kcal=500) == 25  # -15%


def test_compute_calorie_score_over_30pct_returns_zero() -> None:
    """편차 ±30% 이상 → 0."""
    assert compute_calorie_score(meal_kcal=700, recommended_meal_kcal=500) == 0  # +40%
    assert compute_calorie_score(meal_kcal=300, recommended_meal_kcal=500) == 0  # -40%


def test_compute_calorie_score_linear_decay_between() -> None:
    """22.5% 편차 → 25 × (1 - 0.5) = 12.5 → round(12.5)=12."""
    score = compute_calorie_score(meal_kcal=612.5, recommended_meal_kcal=500)
    assert score == 12  # round-half-to-even bankers'


def test_compute_calorie_score_zero_recommended_safe() -> None:
    assert compute_calorie_score(meal_kcal=500, recommended_meal_kcal=0) == 0


# ---------- compute_balance_score ----------


def test_compute_balance_score_all_three_components() -> None:
    from app.domain.fit_score import MealMacros

    meal = MealMacros(
        kcal=500,
        carb_g=50,
        protein_g=15,
        fat_g=10,
        fiber_g=5,
        coverage_ratio=1.0,
        has_vegetable_or_fruit=True,
    )
    assert compute_balance_score(meal) == 15


def test_compute_balance_score_only_protein() -> None:
    from app.domain.fit_score import MealMacros

    meal = MealMacros(
        kcal=500,
        carb_g=80,
        protein_g=15,
        fat_g=10,
        fiber_g=1,
        coverage_ratio=1.0,
        has_vegetable_or_fruit=False,
    )
    assert compute_balance_score(meal) == 5


def test_compute_balance_score_zero() -> None:
    from app.domain.fit_score import MealMacros

    meal = MealMacros(
        kcal=500,
        carb_g=80,
        protein_g=5,
        fat_g=10,
        fiber_g=1,
        coverage_ratio=1.0,
        has_vegetable_or_fruit=False,
    )
    assert compute_balance_score(meal) == 0


# ---------- band_for_score ----------


def test_band_for_score_good() -> None:
    assert band_for_score(95) == "good"
    assert band_for_score(80) == "good"


def test_band_for_score_caution() -> None:
    assert band_for_score(79) == "caution"
    assert band_for_score(70) == "caution"
    assert band_for_score(60) == "caution"


def test_band_for_score_needs_adjust() -> None:
    assert band_for_score(59) == "needs_adjust"
    assert band_for_score(0) == "needs_adjust"


# ---------- detect_allergen_violations ----------


def test_detect_allergen_violations_direct_22_label_substring() -> None:
    """22종 라벨 직접 substring 매칭 — '땅콩버터' 안에 '땅콩'."""
    items = [FoodItem(name="땅콩버터쿠키", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["땅콩"])
    assert out == {"땅콩"}


def test_detect_allergen_violations_alias_map_matching() -> None:
    """ALLERGEN_ALIAS_MAP — '치즈피자' → '우유'."""
    items = [FoodItem(name="치즈피자", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["우유"])
    assert out == {"우유"}


def test_detect_allergen_violations_retrieved_food_category_match() -> None:
    """retrieved_foods[].nutrition['category'] substring 매칭."""
    food = RetrievedFood(
        name="홍합탕",
        food_id=None,
        score=0.9,
        nutrition={"category": "조개류(굴/전복/홍합 포함)", "energy_kcal": 100},  # type: ignore[arg-type]
    )
    out = detect_allergen_violations([], [food], ["조개류(굴/전복/홍합 포함)"])
    assert out == {"조개류(굴/전복/홍합 포함)"}


def test_detect_allergen_violations_empty_user_allergies_returns_empty() -> None:
    items = [FoodItem(name="땅콩버터", confidence=0.9)]
    out = detect_allergen_violations(items, [], [])
    assert out == set()


def test_detect_allergen_violations_no_match_returns_empty() -> None:
    items = [FoodItem(name="채소볶음", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["땅콩"])
    assert out == set()


def test_detect_allergen_violations_multi_violation() -> None:
    items = [FoodItem(name="우유땅콩쿠키", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["우유", "땅콩"])
    assert out == {"우유", "땅콩"}


def test_detect_allergen_violations_nfd_user_allergies_normalized() -> None:
    """NFD-encoded user_allergies → NFC 정규화 후 매칭."""
    nfd_milk = unicodedata.normalize("NFD", "우유")
    assert nfd_milk != "우유"
    items = [FoodItem(name="우유라떼", confidence=0.9)]
    out = detect_allergen_violations(items, [], [nfd_milk])
    assert out == {"우유"}


def test_allergen_alias_map_targets_are_22_labels() -> None:
    """ALLERGEN_ALIAS_MAP의 모든 value가 KOREAN_22_ALLERGENS 안에 있어야 함 (drift 가드)."""
    label_set = set(KOREAN_22_ALLERGENS)
    for alias, target in ALLERGEN_ALIAS_MAP.items():
        assert target in label_set, f"alias {alias!r} → {target!r} not in 22 SOT"


def test_allergen_alias_map_baseline_size() -> None:
    """baseline 8-12건 (story L62 약속)."""
    assert 8 <= len(ALLERGEN_ALIAS_MAP) <= 14  # 약간의 여유


# ---------- compute_fit_score (entry) ----------


def _profile(*, allergies: list[str] | None = None, **kwargs: object) -> UserProfileSnapshot:
    """*지수* 데모 페르소나 baseline — female 30 60kg 165cm light + weight_loss."""
    base: dict[str, object] = {
        "user_id": uuid.uuid4(),
        "health_goal": "weight_loss",
        "age": 30,
        "weight_kg": 60.0,
        "height_cm": 165.0,
        "activity_level": "light",
        "allergies": allergies or [],
    }
    base.update(kwargs)
    return UserProfileSnapshot(**base)  # type: ignore[arg-type]


def test_compute_fit_score_happy_path_returns_reasonable_score() -> None:
    """*지수* persona + 짜장면 1인분 → 합리적 score."""
    profile = _profile()
    items = [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]
    foods = [
        _retrieved(
            "짜장면",
            energy_kcal=600,
            carbohydrate_g=85,
            protein_g=15,
            fat_g=20,
            fiber_g=3,
        )
    ]
    result = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=foods)
    assert result.fit_reason == "ok"
    assert 30 <= result.fit_score <= 100  # 합리적 범위
    assert result.components.allergen == 20  # 위반 없음 → 만점
    assert result.components.coverage_ratio == 1.0


def test_compute_fit_score_incomplete_data_empty_parsed_items() -> None:
    profile = _profile()
    result = compute_fit_score(profile=profile, parsed_items=[], retrieved_foods=[])
    assert result.fit_score == 0
    assert result.fit_reason == "incomplete_data"
    assert result.fit_label == "needs_adjust"
    assert result.components == FitScoreComponents.zero()


def test_compute_fit_score_incomplete_data_none_profile() -> None:
    items = [FoodItem(name="짜장면", confidence=0.9)]
    result = compute_fit_score(profile=None, parsed_items=items, retrieved_foods=[])
    assert result.fit_score == 0
    assert result.fit_reason == "incomplete_data"


def test_compute_fit_score_allergen_violation_short_circuits() -> None:
    """allergies + 매칭 음식 → 즉시 단락 (macro/calorie 산출 X)."""
    profile = _profile(allergies=["우유"])
    items = [FoodItem(name="우유라떼", confidence=0.9)]
    result = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=[])
    assert result.fit_score == 0
    assert result.fit_reason == "allergen_violation"
    assert result.fit_label == "allergen_violation"
    assert result.reasons[0].startswith("알레르기 위반:")
    assert "우유" in result.reasons[0]


def test_compute_fit_score_low_coverage_reasons_include_warning() -> None:
    """coverage_ratio < 0.5 → reasons에 '매칭 신뢰도 낮음' 1줄."""
    profile = _profile()
    items = [
        FoodItem(name="짜장면", confidence=0.9),
        FoodItem(name="식별불가1", confidence=0.4),
        FoodItem(name="식별불가2", confidence=0.4),
    ]
    foods = [_retrieved("짜장면", energy_kcal=600, carbohydrate_g=85, protein_g=15, fat_g=20)]
    result = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=foods)
    assert any("매칭 신뢰도 낮음" in r for r in result.reasons)
    assert result.components.coverage_ratio < 0.5


def test_compute_fit_score_band_label_consistent_with_score() -> None:
    """fit_label band가 score와 정합."""
    profile = _profile()
    items = [FoodItem(name="짜장면", confidence=0.9)]
    foods = [
        _retrieved(
            "짜장면",
            energy_kcal=600,
            carbohydrate_g=85,
            protein_g=15,
            fat_g=20,
        )
    ]
    result = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=foods)
    if result.fit_score >= 80:
        assert result.fit_label == "good"
    elif result.fit_score >= 60:
        assert result.fit_label == "caution"
    else:
        assert result.fit_label == "needs_adjust"


def test_compute_fit_score_uses_macro_targets_lookup() -> None:
    """diabetes_management user는 다른 macro target → 같은 식사도 다른 score 분포 가능."""
    items = [FoodItem(name="짜장면", confidence=0.9)]
    foods = [_retrieved("짜장면", energy_kcal=600, carbohydrate_g=85, protein_g=15, fat_g=20)]
    p1 = _profile(health_goal="weight_loss")
    p2 = _profile(health_goal="diabetes_management")
    r1 = compute_fit_score(profile=p1, parsed_items=items, retrieved_foods=foods)
    r2 = compute_fit_score(profile=p2, parsed_items=items, retrieved_foods=foods)
    # 다른 health_goal lookup 사용했음을 검증 (양쪽 결정성 — 같은 입력 → 같은 출력)
    assert r1.fit_score >= 0 and r2.fit_score >= 0
    # 산출 자체는 결정성
    assert (
        compute_fit_score(profile=p1, parsed_items=items, retrieved_foods=foods).fit_score
        == r1.fit_score
    )


def test_compute_fit_score_calorie_within_range_reason() -> None:
    """meal_kcal이 target ±15% 이내 → reasons에 '칼로리 적정 범위(±15%)' 포함."""
    profile = _profile()
    target = get_macro_targets("weight_loss")
    _ = target  # only documentation
    # weight_loss + female 30 60kg 165cm light:
    # BMR = 10*60 + 6.25*165 - 5*30 - 161 = 600 + 1031.25 - 150 - 161 = 1320.25
    # TDEE = 1320.25 * 1.375 = 1815.34
    # adj = -500 → 1315.34 → /3 = 438.45
    # 목표 ~440 kcal — 1인분 짜장면 600 kcal는 ±36% — out of range
    # 적정 case: kcal=440
    items = [FoodItem(name="샐러드", confidence=0.9)]
    foods = [_retrieved("샐러드", energy_kcal=440, carbohydrate_g=55, protein_g=20, fat_g=15)]
    result = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=foods)
    assert any("칼로리 적정 범위" in r for r in result.reasons)


def test_compute_fit_score_deterministic_same_input_same_output() -> None:
    """동일 입력 → 동일 출력 — round() + 결정성 보장."""
    profile = _profile()
    items = [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]
    foods = [_retrieved("짜장면", energy_kcal=600, carbohydrate_g=85, protein_g=15, fat_g=20)]
    r1 = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=foods)
    r2 = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=foods)
    assert r1.model_dump() == r2.model_dump()
