"""Story 3.5 — Mifflin-St Jeor BMR + Harris-Benedict 활동 계수 TDEE SOT.

순수 결정성 함수 모듈 — DB·LLM·외부 의존 X. ``app/domain/fit_score.py`` 에서만
직접 호출되며, 단위는 모두 ``kcal/day``.

수식 출처:
- BMR(Mifflin-St Jeor 1990): 의학 표준식. 약 ±10% 평균 정확도.
  - 남성 ``BMR = 10*w + 6.25*h - 5*a + 5``
  - 여성 ``BMR = 10*w + 6.25*h - 5*a - 161``
- Activity multiplier(Harris-Benedict 표준): 5단계
  ``sedentary 1.2`` / ``light 1.375`` / ``moderate 1.55`` /
  ``active 1.725`` / ``very_active 1.9``.

NFR-S5 마스킹: 본 모듈은 *순수 함수*라 자체 로깅 X. caller(``fit_score.py``)가
PII 마스킹 SOT를 가진다(weight/height/age raw 로그 금지 — int kcal만).

Caller 책임:
- ``health_goal`` 별 칼로리 deficit/surplus 적용은 본 모듈 X — ``fit_score.py``
  가 ``kdris.get_calorie_adjustment(...)`` lookup으로 분리.
- ``UserProfileSnapshot.sex`` 필드 부재(Story 1.5 baseline) 정합 — caller가
  암묵 default ``"female"``를 적용한다(데모 페르소나 *지수* 정합 — ``data/README.md``
  SOP 등재). ``sex`` 필드 추가는 Story 8.4 polish 슬롯.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.domain.health_profile import ActivityLevel

# Harris-Benedict 표준 활동 계수 (Mifflin-St Jeor 1990 결합 — Story 3.5 SOT).
# Mapping 타입(immutable view) — runtime 변경 차단.
ACTIVITY_MULTIPLIERS: Mapping[ActivityLevel, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


def compute_bmr_mifflin(
    *,
    sex: Literal["male", "female"],
    age: int,
    weight_kg: float,
    height_cm: float,
) -> float:
    """Mifflin-St Jeor 1990 표준식으로 BMR(kcal/day) 산출.

    - 남성 ``BMR = 10*w + 6.25*h - 5*a + 5``
    - 여성 ``BMR = 10*w + 6.25*h - 5*a - 161``

    입력 검증(``users`` CHECK 제약 정합 + fail-fast):
    - ``age < 1`` 또는 ``age > 150``,
    - ``weight_kg <= 0``,
    - ``height_cm <= 0``,
    - 위 조건 위반 시 ``ValueError("invalid bmr inputs")``.
    """
    if age < 1 or age > 150 or weight_kg <= 0 or height_cm <= 0:
        raise ValueError("invalid bmr inputs")
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    bmr = base + (5 if sex == "male" else -161)
    # CR m-6: 극단 valid 입력 조합(예: age=150 + weight=1 + height=1)이 음수 BMR을
    # silent 통과해 downstream `target_meal_kcal < 0` → score 왜곡되는 경로 차단.
    if bmr <= 0:
        raise ValueError("invalid bmr inputs")
    return bmr


def compute_tdee(*, bmr: float, activity_level: ActivityLevel) -> float:
    """``bmr × ACTIVITY_MULTIPLIERS[activity_level]`` — kcal/day.

    Literal 타입이 컴파일타임 enum 차단 + runtime KeyError raise (``_node_wrapper``
    가 NodeError로 변환 — domain 호출자 책임).
    """
    return bmr * ACTIVITY_MULTIPLIERS[activity_level]
