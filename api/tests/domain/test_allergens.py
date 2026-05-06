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


# --- Story 4.3 — contains_allergen 헬퍼 ---


from app.domain.allergens import contains_allergen  # noqa: E402


@pytest.mark.parametrize("allergen", list(KOREAN_22_ALLERGENS))
def test_contains_allergen_each_22_happy_path(allergen: str) -> None:
    """22종 각각 — 라벨 자체가 텍스트에 들어있으면 True (alias 의존 X 케이스).

    ``기타``는 ``_SKIP_SUBSTRING_LABELS``로 substring 매칭 스킵 — alias
    ``기타알레르기성분``로 매칭한다(별도 테스트).
    """
    text = f"{allergen} 함유 식품"
    expected = allergen != "기타"  # 기타는 skip — substring 직접 매칭 X
    assert contains_allergen(text, allergen) is expected


def test_contains_allergen_milk_buckwheat_false_positive_guard() -> None:
    """``메밀국수``의 ``밀`` substring이어도 False — ``_LABEL_SUBSTRING_EXCLUSIONS``."""
    assert contains_allergen("메밀국수", "밀") is False


def test_contains_allergen_wheat_actual_match() -> None:
    """``밀빵 샐러드``는 ``밀`` 매칭 True — neighbor 제외 후에도 substring 잔존."""
    assert contains_allergen("밀빵 샐러드", "밀") is True


def test_contains_allergen_donut_walnut_false_positive_guard() -> None:
    """``도넛``에 alias ``넛``이 substring이지만 False — ``_ALIAS_TEXT_EXCLUSIONS``."""
    assert contains_allergen("도넛 1개", "호두") is False


def test_contains_allergen_coconut_walnut_false_positive_guard() -> None:
    """``코코넛`` → 호두 alias false positive 차단."""
    assert contains_allergen("코코넛 라떼", "호두") is False


def test_contains_allergen_misc_substring_label_skip() -> None:
    """``기타 가공품`` 텍스트에 ``기타`` substring이 있어도 False — ``_SKIP_SUBSTRING_LABELS``."""
    assert contains_allergen("기타 가공품", "기타") is False


def test_contains_allergen_misc_via_explicit_alias() -> None:
    """``기타알레르기성분`` alias만 ``기타`` 매칭 — explicit alias 경로 유지."""
    assert contains_allergen("기타알레르기성분 함유", "기타") is True


def test_contains_allergen_alias_cheese_to_milk() -> None:
    """``치즈`` alias → ``우유`` 매칭."""
    assert contains_allergen("치즈피자 1조각", "우유") is True


def test_contains_allergen_walnut_via_walnut_food() -> None:
    """``호두빵`` 같이 ``호두`` 직접 substring → True (alias 가드는 도넛/코코넛만)."""
    assert contains_allergen("호두빵 1개", "호두") is True


def test_contains_allergen_nfc_normalization() -> None:
    """NFD-encoded Hangul 텍스트 → NFC normalize 후 매칭."""
    import unicodedata

    nfd_text = unicodedata.normalize("NFD", "우유 라떼")
    assert nfd_text != "우유 라떼"
    assert contains_allergen(nfd_text, "우유") is True


def test_contains_allergen_empty_text() -> None:
    """빈 문자열 입력 → False (매칭 없음)."""
    assert contains_allergen("", "우유") is False


def test_contains_allergen_none_text_raises() -> None:
    """None 입력 → ValueError fail-fast (caller 가드 단순화)."""
    with pytest.raises(ValueError, match=r"text must not be None"):
        contains_allergen(None, "우유")  # type: ignore[arg-type]


def test_contains_allergen_unknown_label_raises() -> None:
    """22종 외 라벨 입력 → ValueError fail-fast (caller 가드 단순화)."""
    with pytest.raises(ValueError, match=r"unknown allergen: 'milk'"):
        contains_allergen("milk text", "milk")


def test_contains_allergen_multi_allergen_independent() -> None:
    """동일 텍스트가 여러 알레르기에 매칭 — 각각 독립 True."""
    text = "치즈피자와 새우튀김 세트"
    assert contains_allergen(text, "우유") is True  # 치즈 alias
    assert contains_allergen(text, "새우") is True  # 직접 substring


def test_contains_allergen_egg_alias() -> None:
    """``계란`` alias → ``난류(가금류)`` 매칭."""
    assert contains_allergen("계란말이 정식", "난류(가금류)") is True
    assert contains_allergen("달걀 후라이", "난류(가금류)") is True


def test_contains_allergen_label_not_present() -> None:
    """라벨이 없는 텍스트는 False — happy 음성."""
    assert contains_allergen("바나나 1개", "우유") is False
    assert contains_allergen("바나나 1개", "메밀") is False
