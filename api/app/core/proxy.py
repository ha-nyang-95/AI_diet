"""Story 3.9 — Cloudflare + Railway proxy IP trust SOT (AC1-3).

Topology: ``Mobile/Web → Cloudflare(WAF/DNS/DDoS) → Railway(uvicorn) → Postgres/Redis/R2``.

AC1 SOT — IP trust 우선순위:
1. ``CF-Connecting-IP``: Cloudflare가 원본 클라이언트 IP를 강제 첨부 — 직접 신뢰 가능.
2. ``X-Forwarded-For`` 첫 번째 IP: 신뢰 proxy(Railway 내부 사설 IP 또는 Cloudflare 범위)에서
   왔을 때만 trust — 그 외에는 client spoofing 차단.
3. ``request.client.host`` raw fallback: 헤더 부재 또는 모두 invalid 시 안전 fallback.

AC1 — ``_CLOUDFLARE_IPV4`` 15 entries + ``_CLOUDFLARE_IPV6`` 7 entries (정적 SOT,
2026-05 기준 ``https://www.cloudflare.com/ips/`` 캡처). 분기 1회 갱신 SOP는
``docs/runbook/cloudflare-ip-refresh.md``.

AC2 — ``init_trusted_proxies(app)``는 lifespan startup에서 1회 호출되며 uvicorn
``proxy_headers`` + ``forwarded_allow_ips``는 *uvicorn 실행 시점* env로 wire한다(본
모듈은 process-wide trusted set만 노출). Limiter ``key_func``로 ``get_real_client_ip``
를 사용하면 5 callsite(refresh_token / consents PIPA audit / SSE rate limit / 향후 추가)
에서 동일 정확도 보장 — DRY 1지점 SOT.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request


# --- Cloudflare IP ranges (2026-05 캡처, 분기 1회 갱신) ----------------------

# https://www.cloudflare.com/ips-v4 — 15 ranges.
_CLOUDFLARE_IPV4: Final[frozenset[str]] = frozenset(
    {
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
    }
)

# https://www.cloudflare.com/ips-v6 — 7 ranges.
_CLOUDFLARE_IPV6: Final[frozenset[str]] = frozenset(
    {
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    }
)

# Frozenset → tuple of (network) for runtime membership check (compile-time once).
_CLOUDFLARE_NETWORKS: Final[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]] = tuple(
    ipaddress.ip_network(cidr) for cidr in (_CLOUDFLARE_IPV4 | _CLOUDFLARE_IPV6)
)


def _is_trusted_proxy_ip(client_host: str | None) -> bool:
    """``client_host``가 신뢰 proxy 범위(Cloudflare CIDR 또는 사설/loopback)인지.

    Railway 내부 routing은 사설 IP(10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)로
    forwarding되므로 ``ip.is_private``로 자동 trust. ``ip.is_loopback``은 dev/test
    (uvicorn 127.0.0.1) 정합. ``ip.is_link_local``은 IPv6 fe80::/10 시 신뢰.
    """
    if not client_host:
        return False
    try:
        ip = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return True
    return any(ip in network for network in _CLOUDFLARE_NETWORKS)


def _normalize_ip(value: str) -> str | None:
    """IPv4/IPv6 정규화 — invalid string 시 ``None`` (graceful)."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except (ValueError, AttributeError):
        return None


def get_real_client_ip(request: Request) -> str:
    """3-tier 우선순위로 실 클라이언트 IP를 결정 (NFR-S5 정합 — IP 외 PII 미접근).

    우선순위:
    1. ``CF-Connecting-IP`` — Cloudflare가 첨부한 원본 IP(직접 신뢰).
    2. ``X-Forwarded-For`` 첫 번째 IP — ``request.client.host``가 신뢰 proxy 범위일 때만.
    3. ``request.client.host`` raw — 위 모두 실패 시 fallback.

    부적절 헤더(non-IP / malformed) 또는 ``request.client``가 ``None``(테스트 환경)일 때
    빈 문자열 반환 — 호출 측이 추가 안전 분기.

    NFR-S5 — 본 함수의 반환값을 log에 출력하는 것은 호출 측 책임(IP는 PII에 준함 —
    Story 1.2 ``RefreshToken.ip_address`` / Story 1.3 PIPA audit 정합).
    """
    raw_client_host = request.client.host if request.client else None

    # CF-Connecting-IP는 Cloudflare가 첨부 — 신뢰 proxy를 통하지 않은 raw 클라이언트가
    # 자체 첨부했을 가능성도 있으나, prod 토폴로지(Cloudflare 강제 in-front)에서는
    # CF가 항상 덮어쓴다(Cloudflare WAF rule이 보장). dev/test 환경은
    # ``init_trusted_proxies``가 wire되지 않으므로 raw fallback이 자연스럽게 우선.
    cf_connecting = request.headers.get("CF-Connecting-IP") or request.headers.get(
        "Cf-Connecting-Ip"
    )
    if cf_connecting:
        normalized = _normalize_ip(cf_connecting)
        if normalized is not None:
            return normalized
        # malformed CF-Connecting-IP — 다음 헤더로 fallthrough.

    # X-Forwarded-For는 client spoofing 가능 — 신뢰 proxy를 통과했을 때만 trust.
    if _is_trusted_proxy_ip(raw_client_host):
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            first_ip = xff.split(",")[0].strip()
            normalized = _normalize_ip(first_ip)
            if normalized is not None:
                return normalized

    # Raw fallback — request.client가 None이면 빈 문자열(테스트 환경 graceful).
    if raw_client_host is None:
        return ""
    normalized = _normalize_ip(raw_client_host)
    return normalized if normalized is not None else ""


def init_trusted_proxies(app: FastAPI) -> None:
    """lifespan startup에서 1회 호출 — ``app.state.trusted_proxies``에 set 노출.

    uvicorn ``proxy_headers=True`` + ``forwarded_allow_ips=...``는 *uvicorn 실행 시점*
    CLI/env로 별도 wire한다(본 함수는 application-layer SOT만 노출). 외주 인수 시점에
    ``docs/runbook/deployment.md``의 마이그레이션 SOP로 갱신 흐름 정합.

    설정 부재 시 graceful — slowapi Limiter의 ``key_func``가 ``get_real_client_ip``를
    사용하므로 본 init 실패는 fatal 아님.
    """
    app.state.cloudflare_ipv4 = _CLOUDFLARE_IPV4
    app.state.cloudflare_ipv6 = _CLOUDFLARE_IPV6
    app.state.trusted_proxy_networks = _CLOUDFLARE_NETWORKS


def get_remote_address_with_proxy(request: Request) -> str:
    """slowapi ``Limiter(key_func=...)`` 호환 시그니처 — ``get_real_client_ip`` wrap.

    slowapi의 default ``get_remote_address``는 ``X-Forwarded-For`` 첫 번째 IP를
    *무조건* 신뢰해 client spoofing이 가능하다. 본 wrapper로 trust 검증 추가.
    """
    return get_real_client_ip(request)


__all__ = [
    "_CLOUDFLARE_IPV4",
    "_CLOUDFLARE_IPV6",
    "_CLOUDFLARE_NETWORKS",
    "get_real_client_ip",
    "get_remote_address_with_proxy",
    "init_trusted_proxies",
]
