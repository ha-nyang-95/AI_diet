"""Story 7.1 AC2 — ``_mask_email`` helper NFR-S5 SOT 회귀 가드.

마스킹 패턴(``j***@example.com``)은 admin/whoami response + 향후 audit log payload +
Sentry beforeSend hook이 사용하는 동일 규칙. 본 helper의 4 케이스 회귀 가드는 *별 파일
owner*로 분리(NFR-S5 invariant).
"""

from __future__ import annotations

from app.api.v1.auth import _mask_email


def test_mask_email_typical_local_part() -> None:
    """일반 — 첫 1자 + ``***`` + ``@domain``."""
    assert _mask_email("john@example.com") == "j***@example.com"


def test_mask_email_single_char_local() -> None:
    """1자 local — local 자체 노출 차단(``***@domain``)."""
    assert _mask_email("a@example.com") == "***@example.com"


def test_mask_email_no_at_sign_returns_redacted() -> None:
    """``@`` 부재 — 안전 fallback ``***``."""
    assert _mask_email("not-an-email") == "***"


def test_mask_email_empty_string_returns_redacted() -> None:
    """빈 string — ``***``."""
    assert _mask_email("") == "***"
