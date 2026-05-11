"""Story 7.2 AC1/AC2/AC3 — ``app/core/masking.py`` NFR-S5 SOT 회귀 가드.

Story 7.1 ad-hoc ``test_email_mask.py``를 본 파일로 흡수 + 신규 helper
(``mask_weight`` / ``mask_height`` / ``mask_allergies_count``) 케이스 추가. masking.py
는 admin endpoint + Sentry beforeSend hook + structlog processor의 단일 SOT.

Story 7.4 AC3 — plaintext 분기 ``reveal_*`` 4 helper 추가 (FR39 원문 보기 토글).
기존 16 케이스 PASS 보존 invariant.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.masking import (
    mask_allergies_count,
    mask_email,
    mask_height,
    mask_weight,
    reveal_allergies,
    reveal_email,
    reveal_height,
    reveal_weight,
)

# --- mask_email (Story 7.1 SOT 흡수) -----------------------------------


def test_mask_email_typical_local_part() -> None:
    """일반 — 첫 1자 + ``***`` + ``@domain``."""
    assert mask_email("john@example.com") == "j***@example.com"


def test_mask_email_single_char_local() -> None:
    """1자 local — local 자체 노출 차단(``***@domain``)."""
    assert mask_email("a@example.com") == "***@example.com"


def test_mask_email_no_at_sign_returns_redacted() -> None:
    """``@`` 부재 — 안전 fallback ``***``."""
    assert mask_email("not-an-email") == "***"


def test_mask_email_empty_string_returns_redacted() -> None:
    """빈 string — ``***``."""
    assert mask_email("") == "***"


# --- mask_weight ----------------------------------------------------------


def test_mask_weight_decimal_value_returns_double_asterisk_kg() -> None:
    """Decimal 입력 — 값 노출 0, ``**kg`` 고정."""
    assert mask_weight(Decimal("70.5")) == "**kg"


def test_mask_weight_int_or_float_returns_double_asterisk_kg() -> None:
    """int/float 입력도 동일 — 값 자체 노출 0."""
    assert mask_weight(70) == "**kg"
    assert mask_weight(70.5) == "**kg"


def test_mask_weight_none_passthrough() -> None:
    """None 입력 — None pass-through(미입력 사용자)."""
    assert mask_weight(None) is None


# --- mask_height ----------------------------------------------------------


def test_mask_height_int_value_returns_double_asterisk_cm() -> None:
    """일반 — ``**cm``."""
    assert mask_height(175) == "**cm"


def test_mask_height_zero_value_returns_double_asterisk_cm() -> None:
    """0 입력도 ``**cm`` (None과 분리 — None만 미입력 신호)."""
    assert mask_height(0) == "**cm"


def test_mask_height_none_passthrough() -> None:
    """None 입력 — None pass-through."""
    assert mask_height(None) is None


# --- mask_allergies_count -----------------------------------------------


def test_mask_allergies_count_none_passthrough() -> None:
    """None — 미입력 사용자."""
    assert mask_allergies_count(None) is None


def test_mask_allergies_count_empty_list_returns_no_registered() -> None:
    """빈 배열 — 명시 등록 0건."""
    assert mask_allergies_count([]) == "*** 등록 없음"


def test_mask_allergies_count_single_item_returns_count_1() -> None:
    """1건 — ``*** 1건 등록``."""
    assert mask_allergies_count(["우유"]) == "*** 1건 등록"


def test_mask_allergies_count_three_items_returns_count_3() -> None:
    """3건 — ``*** 3건 등록``."""
    assert mask_allergies_count(["우유", "달걀", "땅콩"]) == "*** 3건 등록"


def test_mask_allergies_count_many_items_returns_count_n() -> None:
    """대량 — ``*** Nん 등록`` 형식 유지."""
    items = [f"item-{i}" for i in range(10)]
    assert mask_allergies_count(items) == "*** 10건 등록"


def test_mask_allergies_count_does_not_leak_item_names() -> None:
    """*상세 항목명* 비노출 — 정확히 ``*** N건 등록`` 형식만 노출."""
    result = mask_allergies_count(["우유", "달걀"])
    assert result is not None
    assert "우유" not in result
    assert "달걀" not in result
    assert result == "*** 2건 등록"


# --- Story 7.4 AC3 reveal_* (FR39 원문 보기) ---------------------------


def test_reveal_email_passes_through_plaintext() -> None:
    """plaintext 이메일 그대로 반환 — 명시 *원문 보기* 흐름 SOT."""
    assert reveal_email("alice@example.com") == "alice@example.com"


def test_reveal_email_passes_through_empty_string() -> None:
    """빈 string 입력도 그대로 — caller responsibility (마스킹은 ``***``였음)."""
    assert reveal_email("") == ""


def test_reveal_weight_passes_through_decimal() -> None:
    """Decimal 입력 — 그대로 반환."""
    assert reveal_weight(Decimal("65.4")) == Decimal("65.4")


def test_reveal_weight_passes_through_none() -> None:
    """None pass-through — 미입력 사용자."""
    assert reveal_weight(None) is None


def test_reveal_height_passes_through_int() -> None:
    """int 입력 — 그대로 반환."""
    assert reveal_height(175) == 175


def test_reveal_height_passes_through_none() -> None:
    """None pass-through."""
    assert reveal_height(None) is None


def test_reveal_allergies_passes_through_list() -> None:
    """list 입력 — 그대로 반환 (item 명 포함)."""
    assert reveal_allergies(["우유", "달걀"]) == ["우유", "달걀"]


def test_reveal_allergies_passes_through_empty_list_distinct_from_none() -> None:
    """빈 list — ``[]`` 그대로 (NULL과 명확 구분)."""
    assert reveal_allergies([]) == []
    assert reveal_allergies(None) is None
