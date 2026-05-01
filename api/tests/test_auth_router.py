"""Story 1.2 — `/v1/auth/*` 라우터 통합 테스트 (AC #1, #4, #5, #12.b).

검증:
- POST /v1/auth/google: 신규 가입 + 기존 사용자 (mobile platform — body 토큰)
- POST /v1/auth/google: Web platform — Set-Cookie 발급, body에 토큰 X
- POST /v1/auth/google: email_verified=False → 401 + auth.google.email_unverified
- POST /v1/auth/refresh: rotation + replay detection
- POST /v1/auth/logout: refresh 토큰 revoke + 204
- POST /v1/auth/admin/exchange: admin user → 통과, user → 403

Google API mock: monkeypatch로 `app.api.v1.auth.google_exchange_code` /
`google_verify_id_token` stub. `respx`는 도입 X.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC as _UTC
from datetime import datetime as _dt
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import update as _sa_update

from app.adapters.google_oauth import GoogleIdTokenClaims, GoogleTokenResponse
from app.core.exceptions import EmailUnverifiedError
from app.db.models.user import User as _User
from app.main import app as _app
from tests.conftest import UserFactory, auth_headers

GOOGLE_SUB_FIXTURE = "1234567890987654321"
EMAIL_FIXTURE = "tester@example.com"


def _stub_google(
    monkeypatch: pytest.MonkeyPatch,
    *,
    google_sub: str = GOOGLE_SUB_FIXTURE,
    email: str = EMAIL_FIXTURE,
    email_verified: bool = True,
    raise_on_verify: type[BaseException] | None = None,
) -> None:
    async def fake_exchange_code(**_kwargs: Any) -> GoogleTokenResponse:
        return GoogleTokenResponse(
            access_token="g-access",
            id_token="g-id-token",
            expires_in=3600,
            token_type="Bearer",
        )

    def fake_verify(_token: str, _expected_audience: str) -> GoogleIdTokenClaims:
        if raise_on_verify is not None:
            raise raise_on_verify("stubbed")
        return GoogleIdTokenClaims(
            sub=google_sub,
            email=email,
            email_verified=email_verified,
            name="Tester",
            picture="https://example.com/p.png",
            issuer="https://accounts.google.com",
            audience="client-id",
        )

    monkeypatch.setattr("app.api.v1.auth.google_exchange_code", fake_exchange_code)
    monkeypatch.setattr("app.api.v1.auth.google_verify_id_token", fake_verify)


@pytest_asyncio.fixture
async def stubbed_google(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    _stub_google(monkeypatch)
    yield


def _login_payload(platform: str = "mobile") -> dict[str, str]:
    return {
        "platform": platform,
        "code": "auth-code-from-client",
        "redirect_uri": "https://app.example.com/callback",
        "code_verifier": "x" * 64,
    }


async def test_google_login_creates_new_user_mobile(
    client: AsyncClient, stubbed_google: None
) -> None:
    response = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in_seconds"] == 30 * 24 * 60 * 60
    assert body["user"]["email"] == EMAIL_FIXTURE
    assert body["user"]["role"] == "user"


async def test_google_login_reuses_existing_user_mobile(
    client: AsyncClient, stubbed_google: None
) -> None:
    # 1회: 신규 가입
    r1 = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    user_id_1 = r1.json()["user"]["id"]
    # 2회: 동일 google_sub → 같은 user
    r2 = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    assert r2.status_code == 200
    assert r2.json()["user"]["id"] == user_id_1


async def test_google_login_web_uses_cookies(client: AsyncClient, stubbed_google: None) -> None:
    response = await client.post("/v1/auth/google", json=_login_payload("web"))
    assert response.status_code == 200
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    cookies = response.headers.get_list("set-cookie")
    cookie_keys = [c.split("=", 1)[0] for c in cookies]
    assert "bn_access" in cookie_keys
    assert "bn_refresh" in cookie_keys

    access_cookie = next(c for c in cookies if c.startswith("bn_access="))
    refresh_cookie = next(c for c in cookies if c.startswith("bn_refresh="))

    # AC2/NFR-S2: HttpOnly + SameSite=Strict + Path 정합 + 정확한 Max-Age.
    for cookie in (access_cookie, refresh_cookie):
        assert "HttpOnly" in cookie, cookie
        assert "samesite=lax" in cookie.lower(), cookie
    assert "Path=/" in access_cookie and "Path=/v1/auth" not in access_cookie
    assert "Path=/v1/auth" in refresh_cookie
    assert "Max-Age=2592000" in access_cookie  # 30일
    assert "Max-Age=7776000" in refresh_cookie  # 90일
    # test 환경(NON_SECURE_COOKIE_ENVIRONMENTS)이라 Secure flag 없음 — prod에선 강제(별 NFR).
    assert "Secure" not in access_cookie
    assert "Secure" not in refresh_cookie


async def test_google_login_email_unverified_raises_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_google(
        monkeypatch,
        email_verified=False,
        raise_on_verify=EmailUnverifiedError,
    )
    response = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "auth.google.email_unverified"
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_refresh_rotates_and_revokes_old(client: AsyncClient, stubbed_google: None) -> None:
    login = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    refresh1 = login.json()["refresh_token"]

    rotate1 = await client.post("/v1/auth/refresh", json={"refresh_token": refresh1})
    assert rotate1.status_code == 200
    refresh2 = rotate1.json()["refresh_token"]
    assert refresh2 != refresh1
    assert rotate1.json()["access_token"]

    # 같은(이미 revoked된) refresh1 재사용 → replay detection
    replay = await client.post("/v1/auth/refresh", json={"refresh_token": refresh1})
    assert replay.status_code == 401
    assert replay.json()["code"] == "auth.refresh.replay_detected"

    # replay 후 family 전체 revoke — refresh2도 무효화됨.
    # 재제시 시 row.revoked_at != None이므로 다시 replay_detected 분기에 들어감(설계 의도).
    after_replay = await client.post("/v1/auth/refresh", json={"refresh_token": refresh2})
    assert after_replay.status_code == 401
    assert after_replay.json()["code"] == "auth.refresh.replay_detected"


async def test_refresh_invalid_token_returns_401(client: AsyncClient) -> None:
    response = await client.post("/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.refresh.invalid"


async def test_refresh_replay_revokes_only_originating_family(
    client: AsyncClient, stubbed_google: None
) -> None:
    """OWASP family-cascade 정합 — replay된 family는 모두 revoke, 다른 family는 정상."""
    # family A (디바이스 1) — 첫 로그인.
    login_a = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    refresh_a1 = login_a.json()["refresh_token"]
    rotate_a = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_a1})
    refresh_a2 = rotate_a.json()["refresh_token"]

    # family B (디바이스 2) — 동일 user의 두 번째 로그인 (별 family_id).
    login_b = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    refresh_b = login_b.json()["refresh_token"]

    # family A에서 replay 발동 → family A 전체 revoke.
    replay = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_a1})
    assert replay.status_code == 401
    assert replay.json()["code"] == "auth.refresh.replay_detected"

    # family A의 활성 토큰(refresh_a2)도 revoked → 401.
    after_a = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_a2})
    assert after_a.status_code == 401

    # family B는 영향 없음 — 정상 rotate.
    rotate_b = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_b})
    assert rotate_b.status_code == 200, rotate_b.text
    assert rotate_b.json()["access_token"]


async def test_google_login_account_deleted_returns_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, user_factory: UserFactory
) -> None:
    """탈퇴(deleted_at != None) 사용자가 같은 google_sub으로 재로그인.

    → 403 + auth.account.deleted (P19).
    """
    deleted_sub = "google-sub-deleted-fixture"
    await user_factory(google_sub=deleted_sub, deleted=True)
    _stub_google(monkeypatch, google_sub=deleted_sub)
    response = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "auth.account.deleted"


async def test_logout_revokes_refresh_and_returns_204(
    client: AsyncClient, stubbed_google: None
) -> None:
    login = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    refresh = login.json()["refresh_token"]

    logout = await client.post("/v1/auth/logout", json={"refresh_token": refresh})
    assert logout.status_code == 204
    # logout 후 같은 refresh 재사용 → 401(이미 revoke).
    after = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert after.status_code == 401


async def test_logout_web_clears_all_three_cookies_with_max_age_zero(
    client: AsyncClient, stubbed_google: None
) -> None:
    """AC5 — Web logout 응답에 bn_access/bn_refresh/bn_admin_access 3종 Set-Cookie Max-Age=0."""
    login = await client.post("/v1/auth/google", json=_login_payload("web"))
    assert login.status_code == 200
    # Web logout — 쿠키 자동(httpx AsyncClient가 cookies 보존).
    logout = await client.post("/v1/auth/logout", json={})
    assert logout.status_code == 204

    cookies = logout.headers.get_list("set-cookie")
    by_key = {c.split("=", 1)[0]: c for c in cookies}
    for key in ("bn_access", "bn_refresh", "bn_admin_access"):
        assert key in by_key, f"missing expire Set-Cookie: {key} (got {list(by_key)})"
        assert "Max-Age=0" in by_key[key], by_key[key]
    # 발급 시 path와 일치해야 브라우저가 매칭해 expire.
    assert "Path=/" in by_key["bn_access"] and "Path=/v1/auth" not in by_key["bn_access"]
    assert "Path=/v1/auth" in by_key["bn_refresh"]
    assert "Path=/v1/admin" in by_key["bn_admin_access"]


async def test_admin_exchange_succeeds_for_admin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """모바일 분기 — body로 admin token 반환.

    token은 verify_admin_token 통과 + sub/issuer 정합.
    """
    from app.core.config import JWT_ADMIN_AUDIENCE
    from app.core.config import settings as core_settings
    from app.core.security import verify_admin_token

    admin = await user_factory(role="admin")
    response = await client.post("/v1/auth/admin/exchange", headers=auth_headers(admin))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["admin_access_token"]
    assert body["expires_in_seconds"] == 8 * 60 * 60

    claims = verify_admin_token(body["admin_access_token"])
    assert claims.sub == admin.id
    assert claims.role == "admin"
    assert claims.issuer == core_settings.jwt_admin_issuer
    assert claims.audience == JWT_ADMIN_AUDIENCE


async def test_admin_exchange_web_returns_cookie_only_no_body_token(
    client: AsyncClient, stubbed_google: None, user_factory: UserFactory
) -> None:
    """P20 — Web 분기(`bn_refresh` 쿠키 보유): body의 admin_access_token=None + Set-Cookie 발급."""
    # admin 사용자 + Web 로그인으로 bn_refresh 쿠키 부여.
    admin = await user_factory(role="admin", google_sub="admin-sub-web-flow")
    # _stub_google이 기본 GOOGLE_SUB_FIXTURE를 사용하므로 admin sub으로 재 stub.
    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    try:
        _stub_google(monkeypatch, google_sub=admin.google_sub, email=admin.email)
        web_login = await client.post("/v1/auth/google", json=_login_payload("web"))
        assert web_login.status_code == 200
    finally:
        monkeypatch.undo()

    # Web admin exchange — 쿠키가 자동 동봉되며 별도 Authorization 헤더도 필요.
    response = await client.post("/v1/auth/admin/exchange", headers=auth_headers(admin))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["admin_access_token"] is None  # NFR-S2 — Web은 body에 token 노출 X.
    assert body["expires_in_seconds"] == 8 * 60 * 60

    # bn_admin_access Set-Cookie 발급 + Path=/v1/admin.
    cookies = response.headers.get_list("set-cookie")
    admin_cookie = next((c for c in cookies if c.startswith("bn_admin_access=")), None)
    assert admin_cookie is not None, cookies
    assert "Path=/v1/admin" in admin_cookie
    assert "HttpOnly" in admin_cookie
    assert "samesite=lax" in admin_cookie.lower()


async def test_admin_exchange_blocks_non_admin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory(role="user")
    response = await client.post("/v1/auth/admin/exchange", headers=auth_headers(user))
    assert response.status_code == 403
    assert response.json()["code"] == "auth.admin.role_required"


async def test_admin_exchange_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/v1/auth/admin/exchange")
    assert response.status_code == 401
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_admin_token_rejected_on_user_endpoint(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """admin secret으로 서명된 토큰은 user verify(다른 secret)에서 서명 실패로 차단.

    secret 분리가 1차 방어선이라 jose는 서명 단계에서 실패 → `auth.access_token.invalid`.
    issuer mismatch 코드는 user secret으로 서명된 admin issuer 토큰 위조 시 노출.
    """
    from app.core.security import create_admin_token

    admin = await user_factory(role="admin")
    admin_token = create_admin_token(admin.id)
    response = await client.post(
        "/v1/auth/admin/exchange",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 401
    # 두 secret 분리 → 서명 검증 단계에서 차단(invalid). 같은 secret에서 issuer만 위조하면 mismatch.
    assert response.json()["code"] == "auth.access_token.invalid"


async def test_user_token_with_admin_issuer_rejected(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    """user secret + admin issuer로 위조된 토큰 → issuer mismatch로 차단."""
    import time
    import uuid as _uuid

    from jose import jwt as jose_jwt

    from app.core.config import JWT_USER_AUDIENCE, settings
    from app.core.security import JWT_ALGORITHM

    admin = await user_factory(role="admin")
    forged_payload = {
        "sub": str(admin.id),
        "iss": settings.jwt_admin_issuer,  # 위조 — admin issuer
        "aud": JWT_USER_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(_uuid.uuid4()),
        "role": "admin",
        "platform": "mobile",
    }
    forged = jose_jwt.encode(forged_payload, settings.jwt_user_secret, algorithm=JWT_ALGORITHM)
    response = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.token.issuer_mismatch"


async def test_protected_endpoint_returns_problem_json_when_unauth(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/users/me")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    auth_header = response.headers.get("www-authenticate", "")
    assert auth_header.startswith("Bearer ")
    assert 'realm="balancenote"' in auth_header
    assert 'error="invalid_token"' in auth_header
    assert response.json()["code"] == "auth.access_token.invalid"


# --- Story 1.6 — UserPublic.onboarded_at 노출 (AC #6) ---


async def test_google_login_response_exposes_onboarded_at(
    client: AsyncClient, stubbed_google: None
) -> None:
    """``POST /v1/auth/google`` 응답 ``user.onboarded_at`` 키 노출 — 신규 사용자는 null.

    refresh 응답(``RefreshResponseMobile``)은 토큰만 — user 정보 X. ``UserPublic``의
    ``onboarded_at`` 신규 필드 회귀 차단.
    """
    response = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    assert response.status_code == 200
    body = response.json()
    assert "onboarded_at" in body["user"]
    # 신규 사용자 — 프로필 입력 전이라 onboarded_at은 null.
    assert body["user"]["onboarded_at"] is None

    # refresh 응답에는 user 정보 X (RefreshResponseMobile은 토큰만).
    refresh = await client.post("/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refresh.status_code == 200
    assert "user" not in refresh.json()


async def test_google_login_response_forwards_existing_onboarded_at(
    client: AsyncClient,
    user_factory: UserFactory,
    stubbed_google: None,
) -> None:
    """기존 사용자(``onboarded_at`` set) 재로그인 시 응답이 그 값을 ISO datetime으로 forward.

    ``UserPublic.onboarded_at`` *값* 경로 검증 — None 케이스만 검증하면 forward
    회귀(``_user_to_public``에서 필드 누락) 발견 X. AC #6 + AC #7 server-state 분기 보장.
    """
    pre_set = _dt(2025, 6, 1, 10, 30, 45, tzinfo=_UTC)
    await user_factory(
        google_sub=GOOGLE_SUB_FIXTURE,
        email=EMAIL_FIXTURE,
        profile_completed=True,
    )
    # user_factory는 ``onboarded_at``을 set하지 않으므로 수동 UPDATE.
    session_maker = _app.state.session_maker
    async with session_maker() as session:
        await session.execute(
            _sa_update(_User).where(_User.email == EMAIL_FIXTURE).values(onboarded_at=pre_set)
        )
        await session.commit()

    response = await client.post("/v1/auth/google", json=_login_payload("mobile"))
    assert response.status_code == 200
    body = response.json()
    onboarded_at = body["user"]["onboarded_at"]
    assert isinstance(onboarded_at, str)
    parsed = _dt.fromisoformat(onboarded_at.replace("Z", "+00:00"))
    assert parsed == pre_set
