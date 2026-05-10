"""Story 7.1 AC4 — admin IP 화이트리스트 helper + Settings validator 단위 테스트.

8 케이스:
1. 빈 list → True (graceful default — MVP NFR-S8 정합)
2. 매칭 IPv4 CIDR → True
3. 비매칭 IPv4 → False
4. IPv6 CIDR + IPv6 client → True
5. trusted proxy(loopback) + ``X-Forwarded-For`` first IP CIDR 매칭 → True
6. ``request.client=None`` + 헤더 부재 → False (deny by default)
7. ``Settings(admin_ip_allowlist=["not-a-cidr"])`` → ValueError raise (부팅 시 fail-fast)
8. IPv4-mapped IPv6 client(``::ffff:203.0.113.42``) + IPv4 CIDR 매칭 → True (Story 7.1 CR)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.core.config import Settings
from app.core.proxy import check_admin_ip_allowed


@dataclass
class _Client:
    host: str | None


class _FakeHeaders(dict[str, str]):
    """Starlette Headers 호환 — case-insensitive get."""

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


@dataclass
class _FakeRequest:
    client: _Client | None
    headers: _FakeHeaders

    @classmethod
    def make(
        cls,
        *,
        client_host: str | None,
        cf_connecting_ip: str | None = None,
        x_forwarded_for: str | None = None,
    ) -> _FakeRequest:
        headers = _FakeHeaders()
        if cf_connecting_ip is not None:
            headers["CF-Connecting-IP"] = cf_connecting_ip
        if x_forwarded_for is not None:
            headers["X-Forwarded-For"] = x_forwarded_for
        return cls(
            client=_Client(host=client_host) if client_host is not None else None,
            headers=headers,
        )


# --- 케이스 1: 빈 list → graceful default ------------------------------


def test_check_allowed_with_empty_allowlist_returns_true() -> None:
    req = _FakeRequest.make(client_host="203.0.113.42")
    assert check_admin_ip_allowed(req, []) is True  # type: ignore[arg-type]


# --- 케이스 2: 매칭 IPv4 CIDR ------------------------------------------


def test_check_allowed_with_matching_ipv4_cidr_returns_true() -> None:
    req = _FakeRequest.make(client_host="203.0.113.42")
    assert check_admin_ip_allowed(req, ["203.0.113.0/24"]) is True  # type: ignore[arg-type]


# --- 케이스 3: 비매칭 IPv4 → False -------------------------------------


def test_check_allowed_with_non_matching_returns_false() -> None:
    req = _FakeRequest.make(client_host="198.51.100.1")
    assert check_admin_ip_allowed(req, ["203.0.113.0/24"]) is False  # type: ignore[arg-type]


# --- 케이스 4: IPv6 ----------------------------------------------------


def test_check_allowed_with_ipv6_cidr_supported() -> None:
    """IPv6 CIDR ``2001:db8::/32`` + IPv6 client → True."""
    req = _FakeRequest.make(client_host="2001:db8::1")
    assert check_admin_ip_allowed(req, ["2001:db8::/32"]) is True  # type: ignore[arg-type]


# --- 케이스 5: XFF via trusted proxy ------------------------------------


def test_check_allowed_with_x_forwarded_for_via_trusted_proxy() -> None:
    """trusted proxy(loopback ``127.0.0.1``)에서 ``X-Forwarded-For=203.0.113.42`` →
    ``get_real_client_ip`` SOT가 XFF first IP를 신뢰 → CIDR 매칭 성공.
    """
    req = _FakeRequest.make(
        client_host="127.0.0.1",  # trusted proxy(loopback)
        x_forwarded_for="203.0.113.42",
    )
    assert check_admin_ip_allowed(req, ["203.0.113.0/24"]) is True  # type: ignore[arg-type]


# --- 케이스 6: client.host=None + 헤더 부재 → deny by default ----------


def test_check_allowed_with_no_client_ip_returns_false() -> None:
    req = _FakeRequest.make(client_host=None)
    assert check_admin_ip_allowed(req, ["203.0.113.0/24"]) is False  # type: ignore[arg-type]


# --- 케이스 7: Settings validator boot-time 검증 -----------------------


def test_settings_validator_rejects_invalid_cidr_at_boot() -> None:
    """잘못된 CIDR은 ``Settings(...)`` 생성 자체에서 ValueError raise(부팅 fail-fast)."""
    with pytest.raises(ValueError, match="invalid admin IP allowlist CIDR"):
        Settings(admin_ip_allowlist=["not-a-cidr"])


# --- 케이스 8: IPv4-mapped IPv6 unwrap (Story 7.1 CR) ------------------


def test_check_allowed_with_ipv4_mapped_ipv6_unwraps_to_ipv4() -> None:
    """Cloudflare/Railway IPv6 dual-stack에서 client IP가 ``::ffff:203.0.113.42`` 형태로
    도착할 수 있다. raw 비교는 IPv6Address vs IPv4Network → silently False (admin lockout).
    ``ipv4_mapped`` unwrap 후 IPv4 CIDR과 매칭 성공해야 함.
    """
    req = _FakeRequest.make(client_host="::ffff:203.0.113.42")
    assert check_admin_ip_allowed(req, ["203.0.113.0/24"]) is True  # type: ignore[arg-type]
