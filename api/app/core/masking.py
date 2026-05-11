"""민감정보 마스킹 helper — NFR-S5 SOT (Story 7.2).

architecture.md:309 *"Sentry before_send hook + structlog processor — 정규식으로
이메일/체중/식단 raw_text/알레르기 항목 마스킹"* 정합. 본 모듈은 *구조화 데이터*
마스킹(이메일/숫자/배열 길이) 단일 지점. *프리텍스트 정규식 마스킹*(structlog processor
SOT)과 분리 — 책임 명료(structlog는 임의 dict, masking.py는 typed value).

Story 7.4 — plaintext 분기 ``reveal_*`` 4 helper 흡수 완료 (FR39 원문 보기 토글).
``mask_*``와 별 함수 4개로 분리 — caller 의도가 *마스킹 vs 노출* type-system 차원에서
명시(grep으로 PII 노출 지점 추적 가능). ``reveal_*``는 NULL-safe pass-through wrapper.

Story 7.1의 ``app/api/v1/auth.py:_mask_email`` private helper를 본 모듈의 public
``mask_email``로 이동(SOT 위치 변경, 동작 동일). admin endpoint + Sentry beforeSend
hook + structlog processor + admin/whoami 모두 본 모듈 import.
"""

from __future__ import annotations

from decimal import Decimal


def mask_email(email: str) -> str:
    """``j***@example.com`` 패턴 — Story 7.1 SOT 동형.

    local part 첫 1자 + ``***`` + ``@domain``. local part 길이 1자 시 ``***@domain``
    (개인 식별성 0). ``@`` 부재/빈 string은 ``***``로 안전 fallback.
    """
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_weight(weight_kg: Decimal | float | int | None) -> str | None:
    """체중 마스킹 — ``**kg`` (값 자체 노출 0).

    ``None`` 입력 시 ``None`` pass-through(미입력 사용자). 원문 보기 토글(7.4)은
    ``f"{value:.1f}kg"`` 분기 추가 예정.
    """
    if weight_kg is None:
        return None
    return "**kg"


def mask_height(height_cm: int | None) -> str | None:
    """신장 마스킹 — ``**cm``. ``mask_weight`` 동형 패턴."""
    if height_cm is None:
        return None
    return "**cm"


def mask_allergies_count(allergies: list[str] | None) -> str | None:
    """알레르기 *상세 항목명*은 마스킹, *건수*는 운영 컨텍스트로 노출.

    - ``None``: 미입력 — ``None`` 응답.
    - ``[]``: 등록 없음 — ``"*** 등록 없음"``.
    - ``[...]``: ``"*** N건 등록"``.

    원문 보기 토글(7.4)은 ``reveal_allergies`` 분기로 흡수.
    """
    if allergies is None:
        return None
    if not allergies:
        return "*** 등록 없음"
    return f"*** {len(allergies)}건 등록"


# --- Story 7.4 AC3 — plaintext 분기 (FR39 원문 보기) ---------------------


def reveal_email(email: str) -> str:
    """원문 이메일 그대로 반환 — *명시 의도* 표기 (FR39, Story 7.4).

    호출처는 ``admin.py:reveal_user_pii``(POST .../pii-reveal)만 — 명시 *원문
    보기* 액션 + audit ``user_pii_view`` 기록과 함께만 호출돼야 함. grep으로
    PII 노출 지점 추적 가능(``reveal_email`` 패턴).
    """
    return email


def reveal_weight(weight_kg: Decimal | float | int | None) -> Decimal | float | int | None:
    """원문 체중 그대로 반환 (None pass-through). FR39 명시 액션 시점만."""
    return weight_kg


def reveal_height(height_cm: int | None) -> int | None:
    """원문 신장 그대로 반환 (None pass-through). FR39 명시 액션 시점만."""
    return height_cm


def reveal_allergies(allergies: list[str] | None) -> list[str] | None:
    """원문 알레르기 list 그대로 반환 (None pass-through). FR39 명시 액션 시점만.

    빈 list(``[]``)도 그대로 — *등록 없음*과 *미입력*은 의미 분리(NULL vs []).
    """
    return allergies
