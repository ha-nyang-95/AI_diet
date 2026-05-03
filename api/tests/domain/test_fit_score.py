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


def test_aggregate_meal_macros_quantity_1인분_scales_by_2_5() -> None:
    """CR D-1: quantity='1인분' → multiplier 2.5 (한국 외식 1인분 ≈ 250g, 100g 베이시스).

    `RetrievedFood.nutrition`은 식약처 OpenAPI 100g 기준이므로 1인분(250g) → 2.5×.
    """
    items = [FoodItem(name="짜장면", quantity="1인분", confidence=0.9)]
    foods = [
        _retrieved(
            "짜장면",
            energy_kcal=240,  # per 100g (식약처 baseline 짜장면 ≈ 240 kcal/100g)
            carbohydrate_g=32,
            protein_g=6,
            fat_g=8,
            fiber_g=1.2,
        )
    ]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 600  # 240 * 2.5
    assert out.carb_g == 80  # 32 * 2.5
    assert out.protein_g == 15  # 6 * 2.5
    assert out.fat_g == 20  # 8 * 2.5
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


def test_aggregate_meal_macros_quantity_kg_scales_x10() -> None:
    """CR M-4: quantity='1kg' → multiplier 10.0 (1000g / 100g basis)."""
    items = [FoodItem(name="고구마", quantity="1kg", confidence=0.9)]
    foods = [_retrieved("고구마", energy_kcal=130)]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 1300  # 130 * 10


def test_aggregate_meal_macros_quantity_uppercase_units_recognized() -> None:
    """Gemini G-1: case-insensitive — '1KG'/'500G' 대문자 단위도 인식."""
    items_kg = [FoodItem(name="고구마", quantity="1KG", confidence=0.9)]
    foods = [_retrieved("고구마", energy_kcal=130)]
    out_kg = aggregate_meal_macros(items_kg, foods)
    assert out_kg.kcal == 1300  # 1KG → 10× — lower() 후 kg 분기

    items_g = [FoodItem(name="고구마", quantity="500G", confidence=0.9)]
    out_g = aggregate_meal_macros(items_g, foods)
    assert out_g.kcal == 650  # 500G → 5× — lower() 후 g 분기


def test_aggregate_meal_macros_exact_match_preferred_over_substring() -> None:
    """Gemini G-2: '밥' parsed + ['비빔밥','밥'] retrieved 시 exact match '밥' 선택.

    substring 1차 패스만 있던 이전 버전은 retrieved_foods 첫 substring 매칭(비빔밥)을
    선택해 정확도 저하. exact-match 우선 패스로 결정성 강화.
    """
    items = [FoodItem(name="밥", confidence=0.9)]
    foods = [
        _retrieved("비빔밥", energy_kcal=500),  # substring으로는 먼저 매칭 가능
        _retrieved("밥", energy_kcal=130),  # exact match — 우선 선택돼야
    ]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 130, f"exact match '밥' 우선 — 비빔밥(500) 선택 회귀: kcal={out.kcal}"


def test_aggregate_meal_macros_exact_match_skipped_when_absent_falls_back_to_substring() -> None:
    """Gemini G-2: exact match 부재 시 substring 패스로 fallback (회귀 가드)."""
    items = [FoodItem(name="짜장", confidence=0.9)]
    foods = [_retrieved("짜장면", energy_kcal=600)]
    out = aggregate_meal_macros(items, foods)
    # exact match X → substring으로 "짜장 in 짜장면" 매칭 → kcal=600
    assert out.kcal == 600
    assert out.coverage_ratio == 1.0


def test_aggregate_meal_macros_quantity_nan_g_falls_back_to_1() -> None:
    """CR M-3: quantity='NaNg' → multiplier 1.0 fallback (NaN 전파 차단)."""
    items = [FoodItem(name="짜장면", quantity="NaNg", confidence=0.9)]
    foods = [_retrieved("짜장면", energy_kcal=500)]
    out = aggregate_meal_macros(items, foods)
    # NaN 가드 → multiplier 1.0 → kcal 변화 X
    assert out.kcal == 500


def test_aggregate_meal_macros_quantity_none_defaults_to_1() -> None:
    items = [FoodItem(name="짜장면", quantity=None, confidence=0.9)]
    foods = [_retrieved("짜장면", energy_kcal=500)]
    out = aggregate_meal_macros(items, foods)
    assert out.kcal == 500


def test_aggregate_meal_macros_unmatched_lowers_coverage() -> None:
    """매칭 실패 item은 coverage_ratio < 1.0 반영."""
    items = [
        FoodItem(name="짜장면", confidence=0.9),
        FoodItem(name="알수없는음식", confidence=0.5),
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
    """baseline 8-13건 (story L62 8-12 + CR B-3 `기타알레르기성분` 추가)."""
    assert 8 <= len(ALLERGEN_ALIAS_MAP) <= 13


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
    """CR M-5: weight_loss vs diabetes_management — 다른 macro target → 다른 score.

    weight_loss(carb 0.50/protein 0.25/fat 0.25) vs diabetes_management
    (carb 0.45/protein 0.25/fat 0.30). 동일 식사(고탄수)에 대해 두 target은 *다른*
    macro deviation을 산출하므로 macro_score(따라서 fit_score)도 달라야 한다.
    """
    # 고탄수 식사 — weight_loss target(0.50)이 diabetes(0.45)보다 더 우호적.
    items = [FoodItem(name="짜장면", confidence=0.9)]
    foods = [_retrieved("짜장면", energy_kcal=600, carbohydrate_g=85, protein_g=15, fat_g=20)]
    p1 = _profile(health_goal="weight_loss")
    p2 = _profile(health_goal="diabetes_management")
    r1 = compute_fit_score(profile=p1, parsed_items=items, retrieved_foods=foods)
    r2 = compute_fit_score(profile=p2, parsed_items=items, retrieved_foods=foods)
    # 실제 lookup 분기 입증 — macro 또는 calorie(서로 다른 adj) 둘 중 하나는 달라야.
    different_macro = r1.components.macro != r2.components.macro
    different_calorie = r1.components.calorie != r2.components.calorie
    assert different_macro or different_calorie, (
        f"macro lookup이 분기 X — r1.macro={r1.components.macro} "
        f"r2.macro={r2.components.macro} "
        f"r1.calorie={r1.components.calorie} r2.calorie={r2.components.calorie}"
    )
    # 결정성 — 같은 입력 → 같은 출력
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


# ---------- CR substring false-positive 회귀 가드 ----------


def test_buckwheat_does_not_trigger_wheat_allergy() -> None:
    """CR B-1: 메밀(buckwheat, Fagopyrum)은 밀(wheat, Triticum)과 별개 알레르겐.

    user_allergies=["밀"]만 있을 때 메밀국수는 밀 위반으로 단락되면 안 됨 — 클리닉적으로
    밀 알레르기 환자는 메밀을 안전한 대체식으로 섭취.
    """
    items = [FoodItem(name="메밀국수", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["밀"])
    assert out == set(), f"메밀국수가 밀 알레르기를 false-trigger — detected={out}"


def test_buckwheat_food_with_buckwheat_allergy_still_triggers() -> None:
    """CR B-1 회귀 — 메밀 알레르기 환자가 메밀국수 → 정상 단락(false negative 방지)."""
    items = [FoodItem(name="메밀국수", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["메밀"])
    assert out == {"메밀"}


def test_donut_does_not_trigger_walnut_allergy() -> None:
    """CR B-2: 도넛(donut, no walnut)이 호두(walnut) 알레르기를 false-trigger 금지."""
    items = [FoodItem(name="도넛", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["호두"])
    assert out == set(), f"도넛이 호두 알레르기를 false-trigger — detected={out}"


def test_coconut_does_not_trigger_walnut_allergy() -> None:
    """CR B-2: 코코넛(coconut)은 호두(walnut)와 별개 식물 — false-trigger 금지."""
    items = [FoodItem(name="코코넛쉐이크", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["호두"])
    assert out == set(), f"코코넛이 호두 알레르기를 false-trigger — detected={out}"


def test_walnut_food_with_walnut_allergy_still_triggers() -> None:
    """CR B-2 회귀 — 호두 알레르기 환자가 호두강정 → 정상 단락."""
    items = [FoodItem(name="호두강정", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["호두"])
    assert out == {"호두"}


def test_food_category_기타가공식품_does_not_trigger_기타_allergy() -> None:
    """CR B-3: 식약처 nutrition.category='기타가공식품'이 generic 기타 라벨 false-trigger 금지."""
    food = RetrievedFood(
        name="치즈케이크",
        food_id=None,
        score=0.9,
        nutrition={"category": "기타가공식품", "energy_kcal": 350},  # type: ignore[arg-type]
    )
    out = detect_allergen_violations([], [food], ["기타"])
    assert out == set(), f"기타가공식품 카테고리가 기타 알레르기를 false-trigger — detected={out}"


def test_food_with_기타_substring_in_name_does_not_trigger_unless_alias_match() -> None:
    """CR B-3: 기타 substring 음식명(예: 기타치킨)도 alias 미등록이면 false-trigger 금지."""
    items = [FoodItem(name="기타치킨", confidence=0.9)]
    # 22-라벨 substring 매칭에서 '기타'는 SKIP — 닭고기는 alias로 매칭됨(치킨 → 닭고기).
    out = detect_allergen_violations(items, [], ["기타"])
    assert out == set(), f"기타치킨이 기타 알레르기를 false-trigger — detected={out}"
    # 닭고기 alias는 정상 동작 검증
    out2 = detect_allergen_violations(items, [], ["닭고기"])
    assert out2 == {"닭고기"}


def test_explicit_기타알레르기성분_food_with_기타_allergy_triggers_via_alias() -> None:
    """CR B-3 회귀 — 음식명이 '기타알레르기성분' alias substring을 포함 → 정상 단락(alias 경로)."""
    items = [FoodItem(name="기타알레르기성분 함유 푸딩", confidence=0.9)]
    out = detect_allergen_violations(items, [], ["기타"])
    assert out == {"기타"}
