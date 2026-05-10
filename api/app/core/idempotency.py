"""Idempotency-Key UUID v4 검증 helper SOT (DF49 흡수, Story 6.3).

RFC 4122 v4 regex + length 36 검증. None/빈/공백 패딩은 None 정규화(미송신 등가).
비공백 패딩 후 형식 위반은 ``ValueError`` raise — 도메인별 *예외 클래스만* 다름.

본 모듈은 *함수 helper만 제공*(예외 계층 통합은 Growth deferred — 도메인별 catalog
prefix 분리 정책 + 외주 인수 후 클라이언트별 catalog 분리 정책 확정 후 재검토).

3 도메인 호출 측:
- ``app/api/v1/meals.py:_validate_idempotency_key`` → ``MealIdempotencyKeyInvalidError``.
- ``app/api/v1/payments.py:_validate_payment_idempotency_key`` →
  ``PaymentIdempotencyKeyInvalidError``.
- (Story 6.3) ``app/api/v1/payments.py:webhook`` → ``PaymentIdempotencyKeyInvalidError``
  (헤더 송신 시).

Story 2.5/6.1 SOT 1:1 정합 — 같은 regex/길이 invariant 보존(catalog 코드만 분리).
"""

from __future__ import annotations

import re
from typing import Final

# RFC 4122 v4 — 14번째 hex가 ``4``, 19번째가 ``8|9|a|A|b|B`` (variant 비트). length 36
# (대시 4건 포함). Python ``uuid.UUID(version=4)`` 우회 사유: version arg가 *clock_seq
# 비트 정상화*만 수행하고 format을 강제하지 않아 ``00000000-0000-0000-0000-000000000000``
# 같은 invalid 패딩도 통과(version arg 무시 케이스). regex가 SOT.
_IDEMPOTENCY_KEY_PATTERN: Final[str] = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_IDEMPOTENCY_KEY_REGEX: Final[re.Pattern[str]] = re.compile(_IDEMPOTENCY_KEY_PATTERN)
_IDEMPOTENCY_KEY_LENGTH: Final[int] = 36


def validate_idempotency_key_uuid_v4(key: str | None) -> str | None:
    """UUID v4 형식 검증 + None/공백 정규화 + lowercase 정규화.

    Returns:
        - ``None``: 미송신/빈/공백 패딩 (skip 신호 — 호출 측이 멱등 처리 비활성).
        - ``str``: 정규화된 lowercase 36-char UUID v4 (정상). RFC 4122 §3 — UUID hex
          digit은 case-insensitive. mixed-case 재시도 2건이 *다른 키*로 stored되어
          멱등성이 깨지는 회귀 차단.

    Raises:
        ValueError: 비공백 패딩 후 형식 위반(길이 ≠ 36 또는 regex 불일치). 호출 측이
            도메인 예외(``MealIdempotencyKeyInvalidError``/``PaymentIdempotencyKeyInvalidError``)로
            변환 의무 — 본 helper는 *검증 로직만* SOT.
    """
    if key is None:
        return None
    stripped = key.strip()
    if not stripped:
        return None
    if len(stripped) != _IDEMPOTENCY_KEY_LENGTH or not _IDEMPOTENCY_KEY_REGEX.match(stripped):
        raise ValueError(f"Idempotency-Key invalid UUID v4 format: len={len(stripped)}")
    # CR P6 (Story 6.3) — RFC 4122 case-insensitivity 정규화. 같은 key의 mixed-case
    # 재시도가 다른 row로 INSERT 되는 race 차단.
    return stripped.lower()


__all__ = ["validate_idempotency_key_uuid_v4"]
