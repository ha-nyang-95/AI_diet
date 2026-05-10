"""Story 7.1 AC1 + AC2 + AC4 — admin auth baseline 회귀 가드 + ``GET /v1/auth/admin/whoami``
smoke 통합 테스트.

본 파일은 *Story 7.1 owner* — Story 1.2가 만든 admin auth core SOT(``create_admin_token``/
``verify_admin_token``/``current_admin``/``POST /v1/auth/admin/exchange``/``bn_admin_access``
쿠키/``users.role``/``idx_users_role_admin``)의 invariant들을 *integration owner* 관점에서
회귀 가드. Story 1.2 baseline 가드 5건(``test_auth_router.py``의 ``test_admin_exchange_*``)
은 1.2 파일에 그대로 보존 — 본 파일은 *별 owner 6건 + smoke 3건 + IP 가드 1건* = 10 케이스.

테스트:
- ``test_admin_token_expires_at_8_hours`` — TTL 상수 회귀
- ``test_admin_token_no_refresh_capability`` — admin 쿠키만으로 ``/refresh`` 호출 차단
- ``test_admin_token_8h_expired_returns_401`` — 만료 admin 토큰 → 401 expired
- ``test_admin_token_issuer_mismatch_returns_401`` — admin secret + user issuer 위조 → 401
- ``test_user_token_blocked_on_admin_endpoint_with_403`` — admin secret + role=user 위조 → 403
- ``test_admin_role_change_to_user_blocks_admin_endpoint`` — DB role flip 즉시 반영
- ``test_admin_whoami_succeeds_for_admin`` — 200 + 마스킹 email + role + token_expires_at
- ``test_admin_whoami_blocks_non_admin`` — admin secret + role=user 위조 → /admin/whoami 403
- ``test_admin_whoami_blocks_missing_token`` — 헤더+쿠키 부재 → 401
- ``test_admin_whoami_blocked_when_ip_not_allowlisted`` — admin_ip_allowlist + non-match 403
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt as jose_jwt
from sqlalchemy import update as sa_update

from app.core.config import (
    ADMIN_ACCESS_TOKEN_TTL_SECONDS,
    JWT_ADMIN_AUDIENCE,
    settings,
)
from app.core.security import (
    JWT_ALGORITHM,
    create_admin_token,
    verify_admin_token,
)
from app.db.models.user import User
from app.main import app
from tests.conftest import UserFactory

# --- AC1 케이스 1: TTL 상수 회귀 ----------------------------------------


def test_admin_token_expires_at_8_hours() -> None:
    """``ADMIN_ACCESS_TOKEN_TTL_SECONDS`` = 8h 회귀 가드.

    fixed_now 기준으로 토큰 발급 → ``verify_admin_token``의 ``expires_at`` claim이
    fixed_now + 8h와 *정확히* 일치(±leeway 무관 — exp claim 자체 검증).
    """
    fixed_now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
    token = create_admin_token(uuid.uuid4(), now=fixed_now)
    claims = verify_admin_token(token)
    assert claims.expires_at == fixed_now + timedelta(seconds=ADMIN_ACCESS_TOKEN_TTL_SECONDS)
    assert ADMIN_ACCESS_TOKEN_TTL_SECONDS == 8 * 60 * 60


# --- AC1 케이스 2: refresh 미지원 ---------------------------------------


async def test_admin_token_no_refresh_capability(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``bn_admin_access`` 쿠키만 보유 + ``bn_refresh`` 부재 상태로 ``/v1/auth/refresh``
    호출 → 401 ``auth.refresh.invalid``. admin은 refresh 흐름에 미관여 invariant.
    """
    admin = await user_factory(role="admin")
    admin_token = create_admin_token(admin.id)
    # `bn_admin_access` 쿠키만 보유한 상태로 refresh 호출(body 없음).
    response = await client.post(
        "/v1/auth/refresh",
        json={},
        cookies={"bn_admin_access": admin_token},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "auth.refresh.invalid"


# --- AC1 케이스 3: 만료 admin 토큰 → /admin/whoami 401 ------------------


async def test_admin_token_8h_expired_returns_401(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """*과거 발행* 만료 토큰(JWT leeway 60s 초과) → 401 expired."""
    admin = await user_factory(role="admin")
    # 60s leeway(``JWT_LEEWAY_SECONDS``) 초과해 명확히 만료 분기 진입.
    past = datetime.now(UTC) - timedelta(seconds=ADMIN_ACCESS_TOKEN_TTL_SECONDS + 120)
    expired_token = create_admin_token(admin.id, now=past)
    response = await client.get(
        "/v1/auth/admin/whoami",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.expired"


# --- AC1 케이스 4: issuer mismatch → 401 -------------------------------


async def test_admin_token_issuer_mismatch_returns_401(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """admin secret으로 서명되었지만 issuer claim이 ``balancenote-user`` 위조 →
    401 ``auth.token.issuer_mismatch``. admin secret이 분리되어 있어도 *issuer 명시
    검증*이 second-line guard.
    """
    admin = await user_factory(role="admin")
    forged_payload = {
        "sub": str(admin.id),
        "iss": settings.jwt_user_issuer,  # 위조: user issuer
        "aud": JWT_ADMIN_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "admin",
    }
    forged = jose_jwt.encode(forged_payload, settings.jwt_admin_secret, algorithm=JWT_ALGORITHM)
    response = await client.get(
        "/v1/auth/admin/whoami",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "auth.token.issuer_mismatch"


# --- AC1 케이스 5: admin secret + role=user 위조 → 403 ------------------


async def test_user_token_blocked_on_admin_endpoint_with_403(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """*합법 admin secret으로 발급되지만 role claim이 user인 토큰* — admin user가
    role을 user로 다운그레이드하려는 시도 시뮬레이션 → 403 ``auth.admin.role_required``.

    ``verify_admin_token``의 role==admin 재확인 분기가 차단(role 미적합 시 403).
    """
    admin = await user_factory(role="admin")
    forged_payload = {
        "sub": str(admin.id),
        "iss": settings.jwt_admin_issuer,
        "aud": JWT_ADMIN_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "user",  # 위조 — admin → user 다운그레이드
    }
    forged = jose_jwt.encode(forged_payload, settings.jwt_admin_secret, algorithm=JWT_ALGORITHM)
    response = await client.get(
        "/v1/auth/admin/whoami",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "auth.admin.role_required"


# --- AC1 케이스 6: DB role 변경 → 권한 박탈 즉시 반영 -------------------


async def test_admin_role_change_to_user_blocks_admin_endpoint(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """admin user의 valid admin JWT가 발급된 *후* DB ``users.role``이 ``'user'``로 update →
    같은 JWT 재사용 → ``current_admin``의 *DB role 재확인* 분기에서 403.

    DB가 SOT — JWT claim 신뢰 X(권한 박탈 즉시 반영). FR35 invariant 회귀.
    """
    admin = await user_factory(role="admin")
    admin_token = create_admin_token(admin.id)

    # 발급 후 DB에서 role을 'user'로 update.
    session_maker = app.state.session_maker
    async with session_maker() as session:
        await session.execute(sa_update(User).where(User.id == admin.id).values(role="user"))
        await session.commit()

    # 토큰은 여전히 valid(서명/만료/role 모두 admin) 그러나 DB가 user.
    response = await client.get(
        "/v1/auth/admin/whoami",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "auth.admin.role_required"


# --- AC2 smoke 1: 정상 admin → 200 + 마스킹 echo ------------------------


async def test_admin_whoami_succeeds_for_admin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """admin user + admin JWT → 200. body는 user_id + 마스킹 email + role=admin +
    token_expires_at(JWT exp claim) 4 필드.
    """
    admin = await user_factory(role="admin", email="admin.tester@example.com")
    admin_token = create_admin_token(admin.id)
    response = await client.get(
        "/v1/auth/admin/whoami",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(admin.id)
    # 마스킹 — local part 첫 1자 + ``***`` + ``@domain``.
    assert body["email_masked"] == "a***@example.com"
    assert body["role"] == "admin"
    assert "token_expires_at" in body
    # ``token_expires_at`` 정합 — verify_admin_token claims와 동일.
    claims = verify_admin_token(admin_token)
    parsed = datetime.fromisoformat(body["token_expires_at"].replace("Z", "+00:00"))
    assert parsed == claims.expires_at


# --- AC2 smoke 2: non-admin (위조) → 403 -------------------------------


async def test_admin_whoami_blocks_non_admin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """``GET /v1/auth/admin/whoami`` 자체에 대한 *role 미적합* assertion (AC1 케이스 5와
    동일 시나리오, 별 endpoint에 대한 명시 회귀).
    """
    user = await user_factory(role="user")
    forged_payload = {
        "sub": str(user.id),
        "iss": settings.jwt_admin_issuer,
        "aud": JWT_ADMIN_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "user",
    }
    forged = jose_jwt.encode(forged_payload, settings.jwt_admin_secret, algorithm=JWT_ALGORITHM)
    response = await client.get(
        "/v1/auth/admin/whoami",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "auth.admin.role_required"


# --- AC2 smoke 3: 토큰 부재 → 401 --------------------------------------


async def test_admin_whoami_blocks_missing_token(client: AsyncClient) -> None:
    """Authorization 헤더 + ``bn_admin_access`` 쿠키 모두 부재 → 401 invalid."""
    response = await client.get("/v1/auth/admin/whoami")
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


# --- AC4 IP 가드: allowlist 미일치 → 403 -------------------------------


async def test_admin_whoami_blocked_when_ip_not_allowlisted(
    client: AsyncClient,
    user_factory: UserFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ADMIN_IP_ALLOWLIST=10.0.0.0/24`` + ASGITransport client(None)에서 admin JWT
    호출 → 403 ``auth.admin.ip_blocked``.

    ASGITransport는 ``request.client``를 None으로 둔다 → ``get_real_client_ip``는 빈
    문자열 → ``check_admin_ip_allowed``는 deny by default(False) → 403.
    """
    monkeypatch.setattr(settings, "admin_ip_allowlist", ["10.0.0.0/24"])
    admin = await user_factory(role="admin")
    admin_token = create_admin_token(admin.id)
    response = await client.get(
        "/v1/auth/admin/whoami",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "auth.admin.ip_blocked"
