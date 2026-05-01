"""`/v1/auth/*` — Google OAuth + JWT 발급/refresh/logout (Story 1.2).

엔드포인트:
- POST /v1/auth/google           — Authorization Code → user JWT 발급
- POST /v1/auth/refresh          — refresh token rotation + replay detection
- POST /v1/auth/logout           — 현재 디바이스 refresh revoke
- POST /v1/auth/admin/exchange   — user JWT → admin JWT(8h) 교환

Cookie 정책:
- bn_access:        HttpOnly + Secure(prod) + SameSite=Lax + Path=/         (30일)
- bn_refresh:       HttpOnly + Secure(prod) + SameSite=Lax + Path=/v1/auth  (90일)
- bn_admin_access:  HttpOnly + Secure(prod) + SameSite=Lax + Path=/v1/admin (8h)

`Secure` flag는 dev/ci/test 환경에서만 생략(NON_SECURE_COOKIE_ENVIRONMENTS).
SameSite=Lax 채택 사유: Strict는 OAuth callback의 cross-site initiated redirect chain
(Google → /callback → /dashboard)에서 첫 보호 라우트 요청에 쿠키가 포함되지 않아 무한 redirect.
Lax도 CSRF는 충분 방어(state-changing POST 차단). 본 결정은 deferred-work.md에 기록.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.google_oauth import (
    exchange_code as google_exchange_code,
)
from app.adapters.google_oauth import (
    verify_id_token as google_verify_id_token,
)
from app.api.deps import (
    DbSession,
    current_user,
)
from app.core.config import (
    ADMIN_ACCESS_TOKEN_TTL_SECONDS,
    NON_SECURE_COOKIE_ENVIRONMENTS,
    USER_ACCESS_TOKEN_TTL_SECONDS,
    USER_REFRESH_TOKEN_TTL_SECONDS,
    settings,
)
from app.core.exceptions import (
    AccountDeletedError,
    AdminRoleRequiredError,
    RefreshTokenInvalidError,
    RefreshTokenReplayError,
)
from app.core.security import (
    create_admin_token,
    create_refresh_token,
    create_user_token,
    hash_refresh_token,
)
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User

router = APIRouter()


# --- Pydantic 스키마 (snake_case 양방향) -----------------------------------

PlatformLiteral = Literal["mobile", "web"]


class GoogleLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: PlatformLiteral
    code: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)
    code_verifier: str = Field(min_length=1)


class UserPublic(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    picture_url: str | None
    role: str
    # Story 1.5 — 모바일/Web 클라이언트가 signIn 직후 4번째 가드(profile) 분기에 사용.
    profile_completed_at: datetime | None
    # Story 1.6 — *최초 온보딩 흐름 통과 시점* (멱등 set, profile 수정 시 변경 X).
    # 신규 사용자는 null. Web ``AuthUser``는 Story 1.2 baseline에서 이미 보유.
    # Mobile ``AuthUser``는 본 스토리에서 추가 — 향후 *환영 메시지*(Story 4.x) hook.
    onboarded_at: datetime | None


class GoogleLoginResponseMobile(BaseModel):
    """모바일은 토큰을 응답 body로 반환(secure-store에서 보관)."""

    access_token: str
    refresh_token: str
    expires_in_seconds: int
    user: UserPublic


class GoogleLoginResponseWeb(BaseModel):
    """Web은 토큰을 httpOnly 쿠키로만 반환 — body에는 user만."""

    user: UserPublic


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = None  # 모바일 — body로 전달. Web은 쿠키 자동.


class RefreshResponseMobile(BaseModel):
    access_token: str
    refresh_token: str
    expires_in_seconds: int


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = None


class AdminExchangeResponse(BaseModel):
    """`admin_access_token`은 mobile에서만 채움(secure-store 저장).

    Web 흐름에서는 `bn_admin_access` httpOnly 쿠키만 발급되고 body는 `null` —
    JS에서 token 노출 차단(NFR-S2).
    """

    admin_access_token: str | None
    expires_in_seconds: int


# --- 쿠키 헬퍼 ------------------------------------------------------------


def _is_secure_environment() -> bool:
    return settings.environment not in NON_SECURE_COOKIE_ENVIRONMENTS


def _set_user_cookies(response: Response, access: str, refresh: str) -> None:
    secure = _is_secure_environment()
    response.set_cookie(
        key="bn_access",
        value=access,
        max_age=USER_ACCESS_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key="bn_refresh",
        value=refresh,
        max_age=USER_REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/v1/auth",
    )


def _set_admin_cookie(response: Response, admin_access: str) -> None:
    response.set_cookie(
        key="bn_admin_access",
        value=admin_access,
        max_age=ADMIN_ACCESS_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=_is_secure_environment(),
        samesite="lax",
        path="/v1/admin",
    )


def _clear_auth_cookies(response: Response) -> None:
    # Max-Age=0 + 발급 시 사용한 path를 동일하게 명시(브라우저가 일치할 때만 expire 처리).
    for key, path in (
        ("bn_access", "/"),
        ("bn_refresh", "/v1/auth"),
        ("bn_admin_access", "/v1/admin"),
    ):
        response.set_cookie(
            key=key,
            value="",
            max_age=0,
            httponly=True,
            secure=_is_secure_environment(),
            samesite="lax",
            path=path,
        )


def _user_to_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        picture_url=user.picture_url,
        profile_completed_at=user.profile_completed_at,
        onboarded_at=user.onboarded_at,
        role=user.role,
    )


# --- /google ------------------------------------------------------------


def _apply_google_profile(
    user: User,
    *,
    email: str,
    email_verified: bool,
    display_name: str | None,
    picture_url: str | None,
    now: datetime,
) -> None:
    user.email = email
    user.email_verified = email_verified
    user.display_name = display_name
    user.picture_url = picture_url
    user.last_login_at = now
    # `User.updated_at`은 `onupdate=text("now()")` (Story 1.2 chunk 1 P8 patch)로
    # SQLAlchemy가 commit 시 자동 갱신 — 명시 set 불필요.


async def _upsert_user_from_google(
    db: AsyncSession,
    *,
    google_sub: str,
    email: str,
    email_verified: bool,
    display_name: str | None,
    picture_url: str | None,
) -> User:
    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        user = User(
            google_sub=google_sub,
            email=email,
            email_verified=email_verified,
            display_name=display_name,
            picture_url=picture_url,
            last_login_at=now,
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # 동시 가입 race — 다른 트랜잭션이 먼저 INSERT 함. 롤백 후 재조회·업데이트.
            await db.rollback()
            result = await db.execute(select(User).where(User.google_sub == google_sub))
            user = result.scalar_one()
            if user.deleted_at is not None:
                raise AccountDeletedError("account is deleted") from None
            _apply_google_profile(
                user,
                email=email,
                email_verified=email_verified,
                display_name=display_name,
                picture_url=picture_url,
                now=now,
            )
            await db.flush()
        return user

    if user.deleted_at is not None:
        # 탈퇴 후 같은 google_sub로 재로그인 — 본 스토리는 회복 시도하지 않음(Story 5.x 결정).
        raise AccountDeletedError("account is deleted")
    _apply_google_profile(
        user,
        email=email,
        email_verified=email_verified,
        display_name=display_name,
        picture_url=picture_url,
        now=now,
    )
    await db.flush()
    return user


_REVERSE_CLIENT_SCHEME_PREFIX = "com.googleusercontent.apps."


def _resolve_oauth_client(platform: PlatformLiteral, redirect_uri: str) -> tuple[str, str | None]:
    """Platform별 google OAuth client_id + client_secret 결정.

    - web: confidential client → secret 첨부.
    - mobile: native public client(PKCE only). redirect_uri의 reverse-client-id 스킴
      (`com.googleusercontent.apps.<client_id>:/...`)에서 client_id를 파싱해 Android/iOS
      를 정확히 구분. 두 native client가 모두 설정된 환경에서 mobile→Android 강제 매칭으로
      iOS 요청에 401이 나는 회귀 차단(Gemini Code Assist PR #19 review). 매칭 실패/스킴
      형식 불일치 시 Android → iOS → web 순으로 fallback (Expo Go / 미설정 환경 호환).
    """
    if platform == "web":
        return (
            settings.google_oauth_client_id,
            settings.google_oauth_client_secret or None,
        )

    # Native mobile: redirect_uri에서 reverse-client-id 추출 시도.
    if redirect_uri.startswith(_REVERSE_CLIENT_SCHEME_PREFIX):
        # 형식: `com.googleusercontent.apps.<id>:/oauth2redirect` (single-slash, path-style).
        # `:` 인덱스로 split — split('.')[3] 같은 인덱스 의존을 피해 strict 추출.
        scheme_end = redirect_uri.find(":")
        if scheme_end > len(_REVERSE_CLIENT_SCHEME_PREFIX):
            scheme_id = redirect_uri[len(_REVERSE_CLIENT_SCHEME_PREFIX) : scheme_end]
            inferred = f"{scheme_id}.apps.googleusercontent.com"
            if inferred and inferred == settings.google_oauth_android_client_id:
                return settings.google_oauth_android_client_id, None
            if inferred and inferred == settings.google_oauth_ios_client_id:
                return settings.google_oauth_ios_client_id, None

    # Fallback chain — Android 우선(현재 dev 환경), 그 다음 iOS, 마지막 web 호환.
    if settings.google_oauth_android_client_id:
        return settings.google_oauth_android_client_id, None
    if settings.google_oauth_ios_client_id:
        return settings.google_oauth_ios_client_id, None
    return (
        settings.google_oauth_client_id,
        settings.google_oauth_client_secret or None,
    )


@router.post("/google")
async def google_login(
    body: GoogleLoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> GoogleLoginResponseMobile | GoogleLoginResponseWeb:
    client_id, client_secret = _resolve_oauth_client(body.platform, body.redirect_uri)
    token_response = await google_exchange_code(
        code=body.code,
        redirect_uri=body.redirect_uri,
        code_verifier=body.code_verifier,
        client_id=client_id,
        client_secret=client_secret,
    )
    # id_token aud는 code를 발급받은 client_id와 동일 — 같은 값으로 검증.
    claims = google_verify_id_token(token_response.id_token, client_id)

    user = await _upsert_user_from_google(
        db,
        google_sub=claims.sub,
        email=claims.email,
        email_verified=claims.email_verified,
        display_name=claims.name,
        picture_url=claims.picture,
    )
    # access는 platform별로 재발급(claim에 platform 박힘 — verify에서 검증되진 않지만 audit/log 용).
    access = create_user_token(user.id, role=user.role, platform=body.platform)
    plaintext, token_hash = create_refresh_token()
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=USER_REFRESH_TOKEN_TTL_SECONDS)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=uuid.uuid4(),
            expires_at=expires_at,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    if body.platform == "web":
        _set_user_cookies(response, access, plaintext)
        return GoogleLoginResponseWeb(user=_user_to_public(user))

    return GoogleLoginResponseMobile(
        access_token=access,
        refresh_token=plaintext,
        expires_in_seconds=USER_ACCESS_TOKEN_TTL_SECONDS,
        user=_user_to_public(user),
    )


# --- /refresh ----------------------------------------------------------


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: DbSession,
    bn_refresh: Annotated[str | None, Cookie()] = None,
) -> RefreshResponseMobile | dict[str, str]:
    plaintext = body.refresh_token or bn_refresh
    if not plaintext:
        raise RefreshTokenInvalidError("refresh token missing")

    token_hash = hash_refresh_token(plaintext)
    # `with_for_update`로 SELECT 시점에 row lock — 동일 plaintext 동시 두 요청이 발생해도
    # 두 번째 요청은 첫 번째 트랜잭션 커밋까지 대기 → revoked_at 갱신 후 진입하므로
    # replay 분기로 흘러간다(race-free rotation + replay detection).
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise RefreshTokenInvalidError("refresh token not recognized")

    now = datetime.now(UTC)
    if row.revoked_at is not None:
        # token-replay — family 전체 revoke + 401. (만료 검사보다 *앞서* 실행: 만료된
        # 토큰의 재사용은 단순 만료보다 우선으로 보고하지 않지만, 이미 revoked된 토큰의
        # 재사용은 어떤 expires_at 상태에서도 명백한 replay 신호이므로.)
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == row.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await db.commit()
        raise RefreshTokenReplayError("refresh token replay detected")

    if row.expires_at <= now:
        raise RefreshTokenInvalidError("refresh token expired")

    user_result = await db.execute(
        select(User).where(User.id == row.user_id, User.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise RefreshTokenInvalidError("user not found")

    # rotation: 새 row 생성 + 이전 row revoke + replaced_by 마킹.
    new_plaintext, new_hash = create_refresh_token()
    new_expires_at = now + timedelta(seconds=USER_REFRESH_TOKEN_TTL_SECONDS)
    new_row = RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        family_id=row.family_id,
        expires_at=new_expires_at,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.add(new_row)
    await db.flush()

    row.revoked_at = now
    row.replaced_by = new_row.id
    await db.commit()

    # platform: bn_refresh 쿠키가 있으면 Web, 그 외(body refresh_token)는 Mobile.
    is_web = bool(bn_refresh) and not body.refresh_token
    platform: PlatformLiteral = "web" if is_web else "mobile"
    new_access = create_user_token(user.id, role=user.role, platform=platform)

    if is_web:
        # Web 흐름 — 쿠키 갱신 + body 비공개.
        _set_user_cookies(response, new_access, new_plaintext)
        return {"status": "refreshed"}

    return RefreshResponseMobile(
        access_token=new_access,
        refresh_token=new_plaintext,
        expires_in_seconds=USER_ACCESS_TOKEN_TTL_SECONDS,
    )


# --- /logout ------------------------------------------------------------


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    response: Response,
    db: DbSession,
    bn_refresh: Annotated[str | None, Cookie()] = None,
) -> Response:
    plaintext = body.refresh_token or bn_refresh
    if plaintext:
        token_hash = hash_refresh_token(plaintext)
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
    # 의존주입된 `response`에 `_clear_auth_cookies`가 raw_headers list로 다중 Set-Cookie를
    # 누적함. 새 Response 객체로 복사하면 단일 값으로 평탄화되어 누락 위험. 그대로 반환.
    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# --- /admin/exchange ----------------------------------------------------


@router.post("/admin/exchange")
async def admin_exchange(
    response: Response,
    user: Annotated[User, Depends(current_user)],
    bn_refresh: Annotated[str | None, Cookie()] = None,
) -> AdminExchangeResponse:
    if user.role != "admin":
        raise AdminRoleRequiredError("admin role required")
    admin_token = create_admin_token(user.id)
    # platform 추론: bn_refresh 쿠키가 있으면 Web → 쿠키만 발급(body는 token 노출 X).
    # 그 외(모바일)는 body로 token 반환(secure-store 저장).
    is_web = bool(bn_refresh)
    _set_admin_cookie(response, admin_token)
    return AdminExchangeResponse(
        admin_access_token=None if is_web else admin_token,
        expires_in_seconds=ADMIN_ACCESS_TOKEN_TTL_SECONDS,
    )
