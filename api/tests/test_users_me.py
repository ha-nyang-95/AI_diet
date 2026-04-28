"""Story 1.2 — `GET /v1/users/me` 통합 테스트 (AC #9, #12.c)."""

from __future__ import annotations

import time
import uuid

from httpx import AsyncClient
from jose import jwt as jose_jwt

from app.core.config import JWT_USER_AUDIENCE, settings
from app.core.security import JWT_ALGORITHM, create_user_token
from tests.conftest import UserFactory, auth_headers


async def test_me_returns_user_payload(client: AsyncClient, user_factory: UserFactory) -> None:
    user = await user_factory(email="me@example.com", display_name="Me")
    response = await client.get("/v1/users/me", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["email"] == "me@example.com"
    assert body["display_name"] == "Me"
    assert body["role"] == "user"
    assert body["created_at"]
    # Story 1.5 — profile_completed_at 필드 노출 검증 (4번째 가드 분기 입력).
    assert "profile_completed_at" in body
    assert body["profile_completed_at"] is None  # 미입력 사용자


async def test_me_exposes_profile_completed_at_when_filled(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """Story 1.5 — profile_completed=True 사용자 → profile_completed_at ISO datetime."""
    user = await user_factory(profile_completed=True)
    response = await client.get("/v1/users/me", headers=auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert body["profile_completed_at"] is not None
    # ISO 8601 형식 — Python datetime ISO 직렬화 정합.
    assert "T" in body["profile_completed_at"]


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/v1/users/me")
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_me_with_expired_token(client: AsyncClient, user_factory: UserFactory) -> None:
    user = await user_factory()
    # 만료된 토큰 직조 (exp 30일 과거)
    payload = {
        "sub": str(user.id),
        "iss": settings.jwt_user_issuer,
        "aud": JWT_USER_AUDIENCE,
        "iat": int(time.time()) - 86400 * 31,
        "exp": int(time.time()) - 86400,
        "jti": str(uuid.uuid4()),
        "role": "user",
        "platform": "mobile",
    }
    expired = jose_jwt.encode(payload, settings.jwt_user_secret, algorithm=JWT_ALGORITHM)
    response = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.expired"


async def test_me_with_admin_issuer_token_blocked(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """admin secret으로 서명된 토큰은 user verify(다른 secret)에서 1차 차단.

    secret 분리가 1차 방어선이므로 jose가 signature 단계에서 reject(invalid).
    user secret으로 서명된 admin issuer 위조 토큰은 별 테스트(test_auth_router.py)에서 검증.
    """
    from app.core.security import create_admin_token

    admin = await user_factory(role="admin")
    admin_token = create_admin_token(admin.id)
    response = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 401
    # secret 분리로 서명 단계에서 차단 → invalid 코드. issuer mismatch는 user secret으로 위조한
    # admin issuer 토큰 케이스에서만 도달(test_user_token_with_admin_issuer_rejected).
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_me_with_deleted_user_returns_401(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """deleted_at != None 사용자의 토큰 → `current_user`가 401 + auth.access_token.invalid.

    `/v1/auth/google` 재로그인 흐름의 403 + `auth.account.deleted`(P19)와는 분리된 분기.
    """
    deleted = await user_factory(deleted=True)
    token = create_user_token(deleted.id, role=deleted.role, platform="mobile")
    response = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"
