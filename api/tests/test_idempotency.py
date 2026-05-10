"""Story 6.3 AC2 — ``app.core.idempotency.validate_idempotency_key_uuid_v4`` helper 단위 테스트.

DF49 흡수 — meals/payments/webhook 3 도메인 SOT helper.

5 케이스:
1. ``None`` 입력 → ``None`` 반환(skip 신호).
2. 빈 문자열 → ``None`` 반환(skip 신호).
3. 공백 패딩 → ``None`` 반환(skip 신호).
4. UUID without dashes(32-char) → ``ValueError`` raise(형식 위반).
5. 정상 UUID v4(36-char) → 정규화된 str 반환.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.idempotency import validate_idempotency_key_uuid_v4


def test_validate_idempotency_key_none_returns_none() -> None:
    """``None`` 입력 → ``None`` (skip 신호 — 멱등 처리 비활성)."""
    assert validate_idempotency_key_uuid_v4(None) is None


def test_validate_idempotency_key_empty_string_returns_none() -> None:
    """빈 문자열 → ``None`` (미송신과 등가 — Story 2.5/6.1 baseline 정합)."""
    assert validate_idempotency_key_uuid_v4("") is None


def test_validate_idempotency_key_whitespace_only_returns_none() -> None:
    """공백 패딩만 → ``None`` (trim 후 빈 문자열과 등가)."""
    assert validate_idempotency_key_uuid_v4("   ") is None
    assert validate_idempotency_key_uuid_v4("\t\n") is None


def test_validate_idempotency_key_invalid_format_raises_value_error() -> None:
    """대시 없는 32-char hex(``uuid.uuid4().hex``) → ``ValueError`` (regex 위반).

    Toss는 32-char hex `event_id`도 송신 가능 — 헤더 ``Idempotency-Key`` 검증은 *UUID v4
    36-char 표기 강제* (본 helper는 헤더 검증 SOT — body event_id는 별 namespace).
    """
    invalid_no_dash = uuid.uuid4().hex  # 32-char, no dashes.
    with pytest.raises(ValueError, match="Idempotency-Key invalid"):
        validate_idempotency_key_uuid_v4(invalid_no_dash)

    # 길이가 맞아도 version 비트가 4가 아니면 reject.
    invalid_version = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(ValueError, match="Idempotency-Key invalid"):
        validate_idempotency_key_uuid_v4(invalid_version)


def test_validate_idempotency_key_valid_uuid_v4_returns_normalized() -> None:
    """정상 UUID v4 36-char → 정규화된 str 반환(strip 적용).

    공백 패딩이 있어도 trim 후 정상 UUID이면 정규화된 36-char str 반환.
    """
    valid = str(uuid.uuid4())
    assert validate_idempotency_key_uuid_v4(valid) == valid

    # 공백 패딩 + 정상 UUID → 정규화 후 반환.
    assert validate_idempotency_key_uuid_v4(f"  {valid}  ") == valid

    # 길이 36 + regex match invariant 보존.
    result = validate_idempotency_key_uuid_v4(valid)
    assert result is not None
    assert len(result) == 36
