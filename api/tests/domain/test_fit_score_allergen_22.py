"""Story 3.5 — 22종 알레르기 100% 회귀 가드 (AC5).

식약처 별표 22종 + ALLERGEN_ALIAS_MAP 매핑이 fit_score 단락 가드를 모두 발화하는지
매개변수화 테스트. epic L654 ≥ 22건 100% 통과 정합 (NFR-C5 SOT 정합).

본 테스트는 *PR 머지 전 default 실행* — fast pure function (eval/perf marker X).
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.allergens import KOREAN_22_ALLERGENS
from app.domain.fit_score import (
    ALLERGEN_ALIAS_MAP,
    compute_fit_score,
    detect_allergen_violations,
)
from app.graph.state import FoodItem, UserProfileSnapshot


def _profile(allergies: list[str]) -> UserProfileSnapshot:
    """profile fixture — *지수* 데모 페르소나."""
    return UserProfileSnapshot(
        user_id=uuid.uuid4(),
        health_goal="weight_loss",
        age=30,
        weight_kg=60.0,
        height_cm=165.0,
        activity_level="light",
        allergies=allergies,
    )


# 22 case — 각 알레르기 + 매칭 음식명 1쌍. 음식명은 22종 라벨 자체 또는
# ALLERGEN_ALIAS_MAP key를 substring으로 포함.
ALLERGEN_22_CASES: list[tuple[str, str]] = [
    ("우유", "우유라떼"),
    ("메밀", "메밀국수"),
    ("땅콩", "땅콩버터쿠키"),
    ("대두", "대두볶음"),
    ("밀", "밀가루빵"),
    ("고등어", "고등어구이"),
    ("게", "게살볶음밥"),
    ("새우", "쉬림프카레"),
    ("돼지고기", "돼지고기찌개"),
    ("아황산류", "아황산류첨가와인"),
    ("복숭아", "복숭아주스"),
    ("토마토", "토마토파스타"),
    ("호두", "호두강정"),
    ("닭고기", "치킨샌드위치"),
    ("난류(가금류)", "달걀말이"),
    ("쇠고기", "비프스테이크"),
    ("오징어", "오징어볶음"),
    ("조개류(굴/전복/홍합 포함)", "조개류(굴/전복/홍합 포함)전골"),
    ("잣", "잣죽"),
    ("아몬드", "아몬드초콜릿"),
    ("잔류 우유 단백", "잔류 우유 단백 함유 두부"),
    ("기타", "기타알레르기성분 포함"),
]


@pytest.mark.parametrize("allergen,food_name", ALLERGEN_22_CASES)
def test_22_allergens_short_circuit_fit_score_to_zero(allergen: str, food_name: str) -> None:
    """각 22종 알레르기에 대해 매칭 음식 → fit_score=0 단락 + reason."""
    profile = _profile([allergen])
    items = [FoodItem(name=food_name, confidence=0.9)]
    result = compute_fit_score(profile=profile, parsed_items=items, retrieved_foods=[])
    assert result.fit_score == 0
    assert result.fit_reason == "allergen_violation"
    assert result.fit_label == "allergen_violation"
    assert result.reasons[0].startswith("알레르기 위반:")
    assert allergen in result.reasons[0]


def test_22_cases_columns_match_korean_22_allergens_sot() -> None:
    """ALLERGEN_22_CASES의 allergen 컬럼이 KOREAN_22_ALLERGENS와 1:1 정합 — drift 가드."""
    case_allergens = [a for a, _ in ALLERGEN_22_CASES]
    assert len(case_allergens) == 22
    assert set(case_allergens) == set(KOREAN_22_ALLERGENS), (
        f"22 case의 allergen 컬럼이 SOT와 mismatch — diff: "
        f"{set(case_allergens) ^ set(KOREAN_22_ALLERGENS)}"
    )


# ALLERGEN_ALIAS_MAP 매핑 검증 — alias 음식명 → 22종 표준 라벨로 단락
# (각 entry 1 case — detect_allergen_violations 단위 layer).
ALIAS_MAP_CASES: list[tuple[str, str]] = [
    (alias, target) for alias, target in ALLERGEN_ALIAS_MAP.items()
]


@pytest.mark.parametrize("alias,target_label", ALIAS_MAP_CASES)
def test_allergen_alias_map_each_entry_resolves(alias: str, target_label: str) -> None:
    """ALLERGEN_ALIAS_MAP 각 entry — alias substring → target 22종 label 매칭."""
    items = [FoodItem(name=f"{alias}요리", confidence=0.9)]
    out = detect_allergen_violations(items, [], [target_label])
    assert target_label in out


def test_allergen_alias_map_targets_all_in_22_sot() -> None:
    """ALLERGEN_ALIAS_MAP value(target)는 모두 22종 SOT 안 — invariant."""
    sot = set(KOREAN_22_ALLERGENS)
    for alias, target in ALLERGEN_ALIAS_MAP.items():
        assert target in sot, f"alias {alias!r} → target {target!r} not in 22 SOT"


def test_allergen_alias_map_baseline_size_in_range() -> None:
    """baseline 8-13건 (story L62 8-12 + CR B-3 `기타알레르기성분` 추가)."""
    assert 8 <= len(ALLERGEN_ALIAS_MAP) <= 13
