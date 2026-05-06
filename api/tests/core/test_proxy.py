"""Story 3.9 AC1 — Cloudflare + Railway proxy IP trust 검증 (8 케이스).

테스트 매트릭스:
1. ``CF-Connecting-IP`` 우선 적용
2. Cloudflare/사설 IP가 아닌 ``X-Forwarded-For``는 untrusted(raw fallback)
3. 사설(Railway internal) IP에서 ``X-Forwarded-For`` trust
4. IPv6 정규화
5. malformed 헤더 graceful fallback
6. 헤더 부재 시 ``request.client.host`` 사용
7. Cloudflare IPv4 range 매칭
8. Cloudflare IPv6 range 매칭
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.proxy import (
    _CLOUDFLARE_IPV4,
    _CLOUDFLARE_IPV6,
    _is_trusted_proxy_ip,
    get_real_client_ip,
    init_trusted_proxies,
)


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
    """Starlette Request 호환 stub — client + headers만 노출."""

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


# --- AC1 케이스 1 ----------------------------------------------------------


def test_cf_connecting_ip_takes_priority_over_xff() -> None:
    """CF-Connecting-IP가 X-Forwarded-For보다 우선 — 사설 client.host 정합."""
    req = _FakeRequest.make(
        client_host="10.0.0.1",
        cf_connecting_ip="203.0.113.42",
        x_forwarded_for="198.51.100.99",
    )
    assert get_real_client_ip(req) == "203.0.113.42"  # type: ignore[arg-type]


# --- AC1 케이스 2 ----------------------------------------------------------


def test_xff_from_untrusted_client_falls_back_to_raw() -> None:
    """공인 IP(non-Cloudflare, non-private)에서 X-Forwarded-For는 spoofing — 무시."""
    req = _FakeRequest.make(
        client_host="8.8.8.8",  # 공인 IP, non-Cloudflare
        x_forwarded_for="1.2.3.4",
    )
    assert get_real_client_ip(req) == "8.8.8.8"  # type: ignore[arg-type]


# --- AC1 케이스 3 ----------------------------------------------------------


def test_xff_from_private_ip_is_trusted() -> None:
    """Railway 내부 사설 IP(10.0.0.0/8)에서 X-Forwarded-For trust."""
    req = _FakeRequest.make(
        client_host="10.0.0.5",  # Railway 내부 (사설)
        x_forwarded_for="203.0.113.99, 10.0.0.1",
    )
    assert get_real_client_ip(req) == "203.0.113.99"  # type: ignore[arg-type]


# --- AC1 케이스 4 ----------------------------------------------------------


def test_ipv6_normalization() -> None:
    """IPv6 입력은 canonical form으로 정규화."""
    req = _FakeRequest.make(
        client_host="172.64.0.1",  # Cloudflare IPv4
        cf_connecting_ip="2001:DB8::0001",  # uppercase + leading zeros
    )
    # ipaddress 모듈은 lowercase + compressed 형태로 canonicalize
    assert get_real_client_ip(req) == "2001:db8::1"  # type: ignore[arg-type]


# --- AC1 케이스 5 ----------------------------------------------------------


def test_malformed_header_graceful_fallback() -> None:
    """malformed CF-Connecting-IP → fallthrough → X-Forwarded-For trusted → raw."""
    # malformed CF-Connecting-IP, malformed XFF — raw client.host
    req = _FakeRequest.make(
        client_host="10.0.0.1",  # 사설 — XFF trust
        cf_connecting_ip="not-an-ip",
        x_forwarded_for="also-not-an-ip",
    )
    assert get_real_client_ip(req) == "10.0.0.1"  # type: ignore[arg-type]


# --- AC1 케이스 6 ----------------------------------------------------------


def test_no_proxy_headers_uses_raw_client_host() -> None:
    """헤더 부재 시 request.client.host 그대로."""
    req = _FakeRequest.make(client_host="203.0.113.250")
    assert get_real_client_ip(req) == "203.0.113.250"  # type: ignore[arg-type]


# --- AC1 케이스 7 ----------------------------------------------------------


def test_cloudflare_ipv4_range_matched() -> None:
    """``162.158.0.0/15`` Cloudflare 대표 range — trust."""
    assert _is_trusted_proxy_ip("162.158.5.42") is True
    # 이 range의 X-Forwarded-For trust 동작
    req = _FakeRequest.make(
        client_host="162.158.5.42",
        x_forwarded_for="203.0.113.7",
    )
    assert get_real_client_ip(req) == "203.0.113.7"  # type: ignore[arg-type]


# --- AC1 케이스 8 ----------------------------------------------------------


def test_cloudflare_ipv6_range_matched() -> None:
    """``2606:4700::/32`` Cloudflare IPv6 — trust."""
    assert _is_trusted_proxy_ip("2606:4700:0:0::1") is True
    req = _FakeRequest.make(
        client_host="2606:4700::1",
        cf_connecting_ip="203.0.113.10",
    )
    assert get_real_client_ip(req) == "203.0.113.10"  # type: ignore[arg-type]


# --- AC1 보조 가드 ---------------------------------------------------------


def test_cloudflare_ipv4_set_size() -> None:
    """SOT 회귀 가드 — 정적 IP range 갯수가 silent rollback되지 않도록."""
    assert len(_CLOUDFLARE_IPV4) == 15
    assert len(_CLOUDFLARE_IPV6) == 7


def test_no_request_client_returns_empty_string() -> None:
    """request.client가 None(테스트 stub) → 빈 문자열 반환(graceful)."""
    req = _FakeRequest.make(client_host=None)
    assert get_real_client_ip(req) == ""  # type: ignore[arg-type]


def test_init_trusted_proxies_exposes_state() -> None:
    """``init_trusted_proxies`` 호출 후 app.state에 SOT가 박혀있는지."""

    class _State:
        pass

    class _App:
        state = _State()

    app = _App()
    init_trusted_proxies(app)  # type: ignore[arg-type]
    assert app.state.cloudflare_ipv4 == _CLOUDFLARE_IPV4
    assert app.state.cloudflare_ipv6 == _CLOUDFLARE_IPV6
    assert len(app.state.trusted_proxy_networks) == 22


def test_public_ip_not_trusted() -> None:
    """8.8.8.8 (Google DNS) 같은 공인 non-Cloudflare IP는 trust 거부."""
    assert _is_trusted_proxy_ip("8.8.8.8") is False
    assert _is_trusted_proxy_ip("1.1.1.1") is False  # Cloudflare DNS는 *서비스* IP — range 외


# --- CR P1 (2026-05-06) — CF-Connecting-IP source 검증 ---------------------


def test_cf_connecting_ip_rejected_when_origin_not_trusted() -> None:
    """CR P1 — Railway origin URL 직접 호출 시 CF-Connecting-IP spoofing 거부.

    공인 IP(non-Cloudflare, non-private)에서 CF-Connecting-IP를 첨부해도 trust 거부 →
    raw client.host 사용. WAF bypass 공격자가 PIPA audit / rate-limit IP를 변조할 수
    없도록 source 검증.
    """
    req = _FakeRequest.make(
        client_host="8.8.8.8",  # 공인 IP, non-Cloudflare — proxy 아님
        cf_connecting_ip="203.0.113.42",  # 첨부된 CF 헤더는 spoofing
        x_forwarded_for="1.2.3.4",
    )
    assert get_real_client_ip(req) == "8.8.8.8"  # type: ignore[arg-type]


def test_ipv6_link_local_trusted_via_is_private() -> None:
    """IPv6 link-local(fe80::/10)은 IANA 특수 등기상 private — ``is_private``로 trust.

    Edge-case 검토 결과 ``is_link_local``을 별도 제거할 이유 없음(``is_private``가
    동등 의미 포함, 명시적 제거 시 IPv6 SLAAC 내부 routing 깨짐).
    """
    assert _is_trusted_proxy_ip("fe80::1") is True
