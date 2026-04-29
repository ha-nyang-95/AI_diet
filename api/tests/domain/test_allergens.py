"""Story 1.5 — ``app.domain.allergens`` 단위 테스트 (AC #5, #14).

22종 SOT 무결성 + helper 함수 분기 (정의 순 dedup, ValueError 메시지 매칭).
본 테스트는 DB·HTTP 의존성 X — 순수 모듈 단위.
"""

from __future__ import annotations

import pytest

from app.domain.allergens import (
    KOREAN_22_ALLERGENS,
    KOREAN_22_ALLERGENS_SET,
    is_valid_allergen,
    normalize_allergens,
)


def test_korean_22_allergens_length() -> None:
    """SOT tuple 길이가 정확히 22 — 식약처 별표 22종 정합."""
    assert len(KOREAN_22_ALLERGENS) == 22


def test_korean_22_allergens_set_consistency() -> None:
    """frozenset이 tuple과 1:1 — 22종 모두 set으로 lookup 가능."""
    assert len(KOREAN_22_ALLERGENS_SET) == 22
    assert frozenset(KOREAN_22_ALLERGENS) == KOREAN_22_ALLERGENS_SET


def test_korean_22_allergens_first_and_last() -> None:
    """정의 순서 보존 — 식약처 표시기준 별표 PDF 순.

    첫 번째 ``우유`` + 마지막 ``기타`` — Story 3.5 fit_score 단위 테스트가 본 순서에 의존.
    """
    assert KOREAN_22_ALLERGENS[0] == "우유"
    assert KOREAN_22_ALLERGENS[-1] == "기타"


def test_korean_22_allergens_no_single_quote() -> None:
    """22종 라벨에 ``'`` 미포함 — alembic SQL 인라인 escaping 안전 (0005 마이그레이션 정합)."""
    for allergen in KOREAN_22_ALLERGENS:
        assert "'" not in allergen


def test_is_valid_allergen_known() -> None:
    """22종 모두 valid 인식."""
    for allergen in KOREAN_22_ALLERGENS:
        assert is_valid_allergen(allergen) is True


def test_is_valid_allergen_unknown() -> None:
    """22종 외 라벨은 invalid."""
    assert is_valid_allergen("unknown") is False
    assert is_valid_allergen("milk") is False  # 영문 라벨은 OUT(Story 8 i18n)
    assert is_valid_allergen("") is False


def test_normalize_allergens_empty() -> None:
    """빈 리스트 → 빈 리스트 — 알레르기 없음 의미 (분기 단순화)."""
    assert normalize_allergens([]) == []


def test_normalize_allergens_single_valid() -> None:
    assert normalize_allergens(["우유"]) == ["우유"]


def test_normalize_allergens_dedup_preserves_definition_order() -> None:
    """중복 dedup + 정의 순 정렬 — frozenset 거친 후 KOREAN_22_ALLERGENS 순서로 재정렬."""
    # 입력 순서(메밀 → 우유)와 무관하게 정의 순(우유 → 메밀)으로 출력.
    assert normalize_allergens(["메밀", "우유", "메밀"]) == ["우유", "메밀"]


def test_normalize_allergens_dedup_3items() -> None:
    """3 종 중복 + 입력 순서 무시 — 정의 순(우유 → 메밀 → 땅콩)으로 정렬."""
    assert normalize_allergens(["땅콩", "우유", "메밀", "우유"]) == ["우유", "메밀", "땅콩"]


def test_normalize_allergens_invalid_raises_value_error() -> None:
    """22종 외 항목 발견 시 ValueError + 메시지 매칭 — Pydantic ValidationError 변환 정합."""
    with pytest.raises(ValueError, match=r"unknown allergen: 'invalid'"):
        normalize_allergens(["invalid"])


def test_normalize_allergens_partial_invalid_raises() -> None:
    """valid + invalid 혼합 입력 → 첫 invalid에서 raise (전체 거부)."""
    with pytest.raises(ValueError, match=r"unknown allergen: 'milk'"):
        normalize_allergens(["우유", "milk"])


def test_normalize_allergens_nfd_input_normalized_to_nfc() -> None:
    """NFD-encoded Hangul (decomposed jamo) → NFC normalize 후 SOT 매칭 (CR patch)."""
    import unicodedata

    nfd_milk = unicodedata.normalize("NFD", "우유")
    assert nfd_milk != "우유", "test setup: NFD must differ byte-wise"
    # NFD 입력도 정상 통과하고 응답은 NFC 라벨.
    assert normalize_allergens([nfd_milk]) == ["우유"]


def test_is_valid_allergen_nfd_input_normalized_to_nfc() -> None:
    """NFD-encoded Hangul → NFC normalize 후 valid 판정."""
    import unicodedata

    nfd_milk = unicodedata.normalize("NFD", "우유")
    assert is_valid_allergen(nfd_milk) is True
