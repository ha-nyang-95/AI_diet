"""Story 3.5 — fit_score 결정성 알고리즘 + 22종 알레르기 단락 SOT.

가중치(epic L652 + prd.md L819 정합):
- Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 = 100.
- 알레르기 위반 1건 이상 → ``fit_score=0`` 즉시 단락(매크로/칼로리/균형 무시).
- ``fit_label`` band(NFR-A4 색약 대응 백엔드 신호):
  - ``score >= 80`` → ``"good"``,
  - ``60 <= score < 80`` → ``"caution"``,
  - ``score < 60`` → ``"needs_adjust"``,
  - 알레르기 위반 → ``"allergen_violation"`` (단락 케이스 우선).

설계 원칙:
- 순수 결정성 함수 — 동일 입력 → 동일 출력. 부동소수 미세 변동은 ``round()`` 정수 출력.
- LLM 호출 X — Story 3.6 듀얼-LLM router 책임 영역 외.
- DB 호출 X — ``evaluate_fit`` 노드도 DB X (state 읽기만).
- NFR-S5 마스킹 — 함수 자체는 logging X. caller(``evaluate_fit``)이 PII 마스킹 SOT.

순환 import 회피:
- 본 모듈이 ``app.graph.state`` 모델(FoodItem/RetrievedFood/UserProfileSnapshot/
  FitEvaluation)을 type 힌트로만 사용 — ``TYPE_CHECKING``으로 import 차단.
- ``compute_fit_score`` 본문 내부에서 ``FitEvaluation``만 lazy import.
- ``state.py``는 ``FitScoreComponents``를 본 모듈에서 re-export.

UserProfileSnapshot.sex 부재 (Story 1.5 baseline):
- 본 SOT는 BMR 산출 시 default ``sex="female"``를 적용(데모 페르소나 *지수* 정합 —
  prd.md L275). ``users.sex`` 컬럼 추가는 OUT(Story 8.4 polish 슬롯).
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.allergens import KOREAN_22_ALLERGENS
from app.domain.bmr import compute_bmr_mifflin, compute_tdee
from app.domain.kdris import (
    MacroTargets,
    get_calorie_adjustment,
    get_macro_targets,
)

if TYPE_CHECKING:
    from app.graph.state import (
        FitEvaluation,
        FoodItem,
        RetrievedFood,
        UserProfileSnapshot,
    )

FitLabel = Literal["good", "caution", "needs_adjust", "allergen_violation"]
FitReason = Literal["ok", "allergen_violation", "incomplete_data"]


class FitScoreComponents(BaseModel):
    """fit_score 4 컴포넌트 분해 노출 — Story 3.6 인용 피드백 입력 + Story 4.3 차트 입력.

    필드 bound는 가중치 SOT 정합:
    - ``macro: 0-40``, ``calorie: 0-25``, ``allergen: 0-20``, ``balance: 0-15``.
    - ``coverage_ratio: 0-1`` — 매칭 성공 item 비율(< 0.5 → 신뢰도 낮음 신호).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    macro: int = Field(ge=0, le=40)
    calorie: int = Field(ge=0, le=25)
    allergen: int = Field(ge=0, le=20)
    balance: int = Field(ge=0, le=15)
    coverage_ratio: float = Field(ge=0, le=1)

    @classmethod
    def zero(cls) -> FitScoreComponents:
        """incomplete_data fallback용 — 모든 필드 0."""
        return cls(macro=0, calorie=0, allergen=0, balance=0, coverage_ratio=0.0)

    @classmethod
    def allergen_violation(cls) -> FitScoreComponents:
        """단락 케이스 표준 직렬화 — 매크로/칼로리/균형 산출 X 의미."""
        return cls(macro=0, calorie=0, allergen=0, balance=0, coverage_ratio=0.0)


# 한국 외식·배달 메뉴 alias → 22종 표준 라벨 baseline (8-12건).
# 외주 인수 시 클라이언트가 자사 메뉴별 보강 — SOP는 ``api/data/README.md``.
ALLERGEN_ALIAS_MAP: dict[str, str] = {
    "계란": "난류(가금류)",
    "달걀": "난류(가금류)",
    "오믈렛": "난류(가금류)",
    "마요네즈": "난류(가금류)",
    "치즈": "우유",
    "요구르트": "우유",
    "버터": "우유",
    "쉬림프": "새우",
    "포크": "돼지고기",
    "비프": "쇠고기",
    "치킨": "닭고기",
    "넛": "호두",
}


class MealMacros(BaseModel):
    """``aggregate_meal_macros`` 출력 — meal 합산 매크로 + coverage_ratio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kcal: float
    carb_g: float
    protein_g: float
    fat_g: float
    fiber_g: float
    coverage_ratio: float = Field(ge=0, le=1)
    has_vegetable_or_fruit: bool


def _quantity_multiplier(quantity: str | None) -> float:
    """``quantity`` 문자열 → multiplier 휴리스틱.

    - ``None`` 또는 비어있음 → 1.0 (1인분 가정),
    - ``"200g"`` 같은 ``Ng`` 패턴 → 100g 기준 식약처 영양소 → ``N/100``,
    - ``"1.5인분"`` 같은 ``N인분`` → ``N``,
    - 그 외 → 1.0 fallback.
    """
    if not quantity:
        return 1.0
    text = quantity.strip()
    if text.endswith("g") and not text.endswith("kg"):
        try:
            grams = float(text[:-1].strip())
            return max(grams / 100.0, 0.0)
        except ValueError:
            return 1.0
    if "인분" in text:
        head = text.split("인분", 1)[0].strip()
        try:
            return max(float(head), 0.0) if head else 1.0
        except ValueError:
            return 1.0
    return 1.0


def _is_vegetable_or_fruit(food: RetrievedFood) -> bool:
    """``RetrievedFood.nutrition``에서 category 키 substring으로 채소·과일 판정."""
    category = food.nutrition.get("category") if food.nutrition else None
    if not isinstance(category, str):
        return False
    return any(token in category for token in ("채소", "과일"))


def aggregate_meal_macros(
    parsed_items: list[FoodItem],
    retrieved_foods: list[RetrievedFood],
) -> MealMacros:
    """parsed_items 별 nutrition을 합산. 매칭 실패 item은 0(coverage_ratio에 반영).

    매칭 룰: ``parsed_items[i].name``과 ``retrieved_foods[j].name`` substring(양방향)
    1차 매칭. 첫 매칭만 사용(중복 카운팅 회피). 매칭 실패 item은 매크로 0 + coverage
    비율에서 차감.
    """
    if not parsed_items:
        return MealMacros(
            kcal=0,
            carb_g=0,
            protein_g=0,
            fat_g=0,
            fiber_g=0,
            coverage_ratio=0.0,
            has_vegetable_or_fruit=False,
        )

    kcal = carb = protein = fat = fiber = 0.0
    matched = 0
    has_veg_fruit = False

    for item in parsed_items:
        item_name = unicodedata.normalize("NFC", item.name)
        match: RetrievedFood | None = None
        for food in retrieved_foods:
            food_name = unicodedata.normalize("NFC", food.name)
            if item_name in food_name or food_name in item_name:
                match = food
                break
        if match is None:
            continue
        matched += 1
        mult = _quantity_multiplier(item.quantity)
        nutri = match.nutrition or {}
        kcal += float(nutri.get("energy_kcal", 0.0)) * mult
        carb += float(nutri.get("carbohydrate_g", 0.0)) * mult
        protein += float(nutri.get("protein_g", 0.0)) * mult
        fat += float(nutri.get("fat_g", 0.0)) * mult
        fiber += float(nutri.get("fiber_g", 0.0)) * mult
        if _is_vegetable_or_fruit(match):
            has_veg_fruit = True

    return MealMacros(
        kcal=kcal,
        carb_g=carb,
        protein_g=protein,
        fat_g=fat,
        fiber_g=fiber,
        coverage_ratio=matched / len(parsed_items),
        has_vegetable_or_fruit=has_veg_fruit,
    )


def compute_macro_score(meal: MealMacros, target: MacroTargets) -> int:
    """meal의 탄/단/지 비율을 target과 비교 — 0-40 정수.

    ``score = round(40 × (1 - min(2.0, total_deviation) / 2.0))``.
    total_deviation = sum(|meal_pct - target_pct|) — 각 카테고리 절대 편차 합.
    매크로 g 합이 0이면 0 반환(분기 안전).
    """
    total_g = meal.carb_g + meal.protein_g + meal.fat_g
    if total_g <= 0:
        return 0
    carb_pct = meal.carb_g / total_g
    protein_pct = meal.protein_g / total_g
    fat_pct = meal.fat_g / total_g
    deviation = (
        abs(carb_pct - target.carb_pct)
        + abs(protein_pct - target.protein_pct)
        + abs(fat_pct - target.fat_pct)
    )
    bounded = min(2.0, deviation)
    return round(40 * (1 - bounded / 2.0))


def compute_calorie_score(meal_kcal: float, recommended_meal_kcal: float) -> int:
    """편차 비율 — ``±15%`` 만점 25, ``±30%`` 0점, 그 사이 선형 감소.

    recommended가 0 이하면 0 반환(분기 안전).
    """
    if recommended_meal_kcal <= 0:
        return 0
    deviation = abs(meal_kcal - recommended_meal_kcal) / recommended_meal_kcal
    if deviation <= 0.15:
        return 25
    if deviation >= 0.30:
        return 0
    # 선형: 0.15 → 25, 0.30 → 0.
    fraction = (deviation - 0.15) / 0.15
    return round(25 * (1 - fraction))


def compute_balance_score(meal: MealMacros) -> int:
    """0-15 — 단백질 ≥ 10g(+5), 식이섬유 ≥ 3g(+5), 채소·과일 카테고리 매칭 1+(+5)."""
    score = 0
    if meal.protein_g >= 10:
        score += 5
    if meal.fiber_g >= 3:
        score += 5
    if meal.has_vegetable_or_fruit:
        score += 5
    return score


def detect_allergen_violations(
    parsed_items: list[FoodItem],
    retrieved_foods: list[RetrievedFood],
    user_allergies: list[str],
) -> set[str]:
    """22종 라벨 substring + ``ALLERGEN_ALIAS_MAP`` 매핑 → user_allergies 교집합 set.

    NFC 정규화: macOS 클립보드 NFD 호환 (Story 1.5 패턴 정합). user_allergies/
    parsed_items[].name/retrieved_foods[].name 모두 NFC 후 비교.
    """
    if not user_allergies:
        return set()
    normalized_user = {unicodedata.normalize("NFC", a) for a in user_allergies}

    texts: list[str] = []
    for item in parsed_items:
        if item.name:
            texts.append(unicodedata.normalize("NFC", item.name))
    for food in retrieved_foods:
        if food.name:
            texts.append(unicodedata.normalize("NFC", food.name))
        if food.nutrition:
            cat = food.nutrition.get("category")
            if isinstance(cat, str) and cat:
                texts.append(unicodedata.normalize("NFC", cat))

    detected: set[str] = set()
    for text in texts:
        # (1) 22종 직접 substring 매칭.
        for label in KOREAN_22_ALLERGENS:
            if label in text:
                detected.add(label)
        # (2) ALLERGEN_ALIAS_MAP — alias substring → 22종 표준 라벨.
        for alias, standard in ALLERGEN_ALIAS_MAP.items():
            if alias in text:
                detected.add(standard)

    return detected & normalized_user


def band_for_score(score: int) -> FitLabel:
    """0-100 정수 score → ``fit_label`` band 분류.

    알레르기 위반은 ``compute_fit_score`` 단락 분기에서 직접 ``"allergen_violation"`` set —
    본 함수는 정상 케이스만 처리.
    """
    if score >= 80:
        return "good"
    if score >= 60:
        return "caution"
    return "needs_adjust"


def _build_macro_reason(meal: MealMacros, target: MacroTargets) -> str | None:
    """매크로 편차가 큰 카테고리 1건만 짧은 한국어 reason."""
    total_g = meal.carb_g + meal.protein_g + meal.fat_g
    if total_g <= 0:
        return None
    pcts = {
        "탄수화물": meal.carb_g / total_g,
        "단백질": meal.protein_g / total_g,
        "지방": meal.fat_g / total_g,
    }
    targets = {
        "탄수화물": target.carb_pct,
        "단백질": target.protein_pct,
        "지방": target.fat_pct,
    }
    worst = max(pcts.keys(), key=lambda k: abs(pcts[k] - targets[k]))
    deviation = pcts[worst] - targets[worst]
    if abs(deviation) < 0.05:
        return None
    direction = "초과" if deviation > 0 else "부족"
    return (
        f"{worst} 비중 {round(pcts[worst] * 100)}% — 권장 "
        f"{round(targets[worst] * 100)}% {direction}"
    )


def compute_fit_score(
    *,
    profile: UserProfileSnapshot | None,
    parsed_items: list[FoodItem],
    retrieved_foods: list[RetrievedFood],
) -> FitEvaluation:
    """결정성 entry — 알레르기 단락 → incomplete_data → 정상 3-way.

    단계:
    1. 알레르기 위반 검출 — 위반 ≥ 1 시 ``fit_score=0`` 단락 + ``fit_reason="allergen_violation"``.
    2. ``profile`` None 또는 ``parsed_items`` 빈 리스트 → ``fit_reason="incomplete_data"``.
    3. 정상 — BMR(default sex=female) → TDEE → meal target kcal = (TDEE + adj)/3
       → macro/calorie/balance 합산 → fit_label band.
    """
    # 순환 import 회피 — lazy import.
    from app.graph.state import FitEvaluation

    # (1) 알레르기 단락 — profile.allergies가 있고 위반 검출되면 즉시 score=0.
    if profile is not None and profile.allergies:
        violations = detect_allergen_violations(parsed_items, retrieved_foods, profile.allergies)
        if violations:
            return FitEvaluation(
                fit_score=0,
                fit_reason="allergen_violation",
                fit_label="allergen_violation",
                reasons=[f"알레르기 위반: {a}" for a in sorted(violations)],
                components=FitScoreComponents.allergen_violation(),
            )

    # (2) incomplete_data — profile/parsed_items 부재 시 graceful 0점.
    if profile is None or not parsed_items:
        return FitEvaluation(
            fit_score=0,
            fit_reason="incomplete_data",
            fit_label="needs_adjust",
            reasons=["프로필 또는 식사 정보 부재 — 분석 진행 불가"],
            components=FitScoreComponents.zero(),
        )

    # (3) 정상 — BMR/TDEE → target meal kcal → 3 컴포넌트 합산.
    bmr = compute_bmr_mifflin(
        sex="female",  # AC1 docstring 정합 — UserProfileSnapshot.sex 부재
        age=profile.age,
        weight_kg=profile.weight_kg,
        height_cm=profile.height_cm,
    )
    tdee = compute_tdee(bmr=bmr, activity_level=profile.activity_level)
    target_meal_kcal = (tdee + get_calorie_adjustment(profile.health_goal)) / 3.0
    target_macros = get_macro_targets(profile.health_goal)

    meal = aggregate_meal_macros(parsed_items, retrieved_foods)
    macro_score = compute_macro_score(meal, target_macros)
    calorie_score = compute_calorie_score(meal.kcal, target_meal_kcal)
    balance_score = compute_balance_score(meal)
    allergen_score = 20  # 위반 없음 — 만점

    total = macro_score + calorie_score + allergen_score + balance_score

    reasons: list[str] = []
    macro_reason = _build_macro_reason(meal, target_macros)
    if macro_reason:
        reasons.append(macro_reason)
    if calorie_score == 25:
        reasons.append("칼로리 적정 범위(±15%)")
    elif calorie_score == 0:
        reasons.append("칼로리 권장 범위 ±30% 이탈")
    if meal.coverage_ratio < 0.5:
        reasons.append("매칭 신뢰도 낮음 — 식사 식별 일부 누락")
    if not reasons:
        reasons.append("전반적으로 권장 범위에 부합")

    return FitEvaluation(
        fit_score=total,
        fit_reason="ok",
        fit_label=band_for_score(total),
        reasons=reasons,
        components=FitScoreComponents(
            macro=macro_score,
            calorie=calorie_score,
            allergen=allergen_score,
            balance=balance_score,
            coverage_ratio=round(meal.coverage_ratio, 4),
        ),
    )


__all__ = [
    "ALLERGEN_ALIAS_MAP",
    "FitLabel",
    "FitReason",
    "FitScoreComponents",
    "MealMacros",
    "aggregate_meal_macros",
    "band_for_score",
    "compute_balance_score",
    "compute_calorie_score",
    "compute_fit_score",
    "compute_macro_score",
    "detect_allergen_violations",
]
