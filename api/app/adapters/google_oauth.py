"""Google OAuth adapter — Authorization Code 교환 + id_token 검증.

흐름:
1. exchange_code(): code + code_verifier → Google token endpoint POST →
   {access_token, id_token, ...}
2. verify_id_token(): id_token 서명 검증 + issuer/audience/exp/email_verified 검증.

검증 실패는 도메인 예외로 변환:
- 서명 / issuer / audience / exp 실패 → InvalidIdTokenError
- email_verified=False → EmailUnverifiedError
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import GOOGLE_ID_TOKEN_ALLOWED_ISSUERS
from app.core.exceptions import EmailUnverifiedError, InvalidIdTokenError

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_TOKEN_EXCHANGE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class GoogleTokenResponse:
    access_token: str
    id_token: str
    expires_in: int
    token_type: str
    scope: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleIdTokenClaims:
    sub: str  # Google subject id (= google_sub)
    email: str
    email_verified: bool
    name: str | None
    picture: str | None
    issuer: str
    audience: str


async def exchange_code(
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_id: str,
    client_secret: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> GoogleTokenResponse:
    """Authorization code → Google token endpoint 교환.

    PKCE flow: client_secret 없이 code_verifier로 검증(native mobile public client).
    Web confidential client은 client_secret + code_verifier 둘 다 첨부.
    `client_id`/`client_secret`은 호출자(라우터)가 platform별로 결정해 주입 — 단일 globals
    참조를 끊어 mobile/web에서 같은 어댑터를 사용 가능하게 한다.
    """
    payload: dict[str, str] = {
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    if client_secret:
        # Web confidential client인 경우만 첨부.
        payload["client_secret"] = client_secret

    own_client = client is None
    http_client = client or httpx.AsyncClient(timeout=GOOGLE_TOKEN_EXCHANGE_TIMEOUT_SECONDS)
    try:
        try:
            response = await http_client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
        except httpx.HTTPError as exc:
            # network/timeout 등 transient 실패 — Google 응답 본문 노출 금지(상태/secret 누출 차단).
            raise InvalidIdTokenError("google token exchange transport error") from exc
    finally:
        if own_client:
            await http_client.aclose()

    if response.status_code >= 400:
        # status code만 노출 — Google 응답 body는 client_secret/code_verifier echo 위험.
        raise InvalidIdTokenError(f"google token exchange failed: status={response.status_code}")

    try:
        body: dict[str, Any] = response.json()
    except ValueError as exc:
        raise InvalidIdTokenError("google token response not JSON") from exc

    if "id_token" not in body or "access_token" not in body:
        raise InvalidIdTokenError("google token response missing id_token/access_token")

    try:
        expires_in = int(body.get("expires_in", 0))
    except (TypeError, ValueError) as exc:
        raise InvalidIdTokenError("google token response invalid expires_in") from exc

    return GoogleTokenResponse(
        access_token=body["access_token"],
        id_token=body["id_token"],
        expires_in=expires_in,
        token_type=str(body.get("token_type", "Bearer")),
        scope=body.get("scope"),
    )


def verify_id_token(id_token_str: str, expected_audience: str) -> GoogleIdTokenClaims:
    """Google id_token 검증.

    google.oauth2.id_token.verify_oauth2_token이 audience(client_id), exp, signature를
    검증한다. issuer는 `accounts.google.com` / `https://accounts.google.com` 둘 다 발급
    가능 — 본 함수가 별도로 검증해 화이트리스트 enforcement.

    `expected_audience`: 호출자가 platform별 client_id를 주입(mobile=android/ios, web=web).
    Native 클라이언트로 발급된 id_token의 `aud` claim은 native client_id이므로 web client_id로
    검증하면 ValueError가 던져진다.
    """
    try:
        # google-auth는 stub 미제공 → mypy 경고. mypy override(`google.*`)로 일괄 무시 처리.
        claims: dict[str, Any] = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            id_token_str,
            google_requests.Request(),
            expected_audience,
        )
    except ValueError as exc:
        raise InvalidIdTokenError(f"google id_token invalid: {exc}") from exc

    issuer = str(claims.get("iss", ""))
    if issuer not in GOOGLE_ID_TOKEN_ALLOWED_ISSUERS:
        raise InvalidIdTokenError(f"google id_token issuer not allowed: {issuer!r}")

    email = claims.get("email")
    email_verified = bool(claims.get("email_verified", False))
    if not email:
        raise InvalidIdTokenError("google id_token missing email")
    if not email_verified:
        raise EmailUnverifiedError("google email not verified")

    sub = claims.get("sub")
    if not sub:
        raise InvalidIdTokenError("google id_token missing sub")

    return GoogleIdTokenClaims(
        sub=str(sub),
        email=str(email),
        email_verified=True,
        name=claims.get("name"),
        picture=claims.get("picture"),
        issuer=issuer,
        audience=str(claims.get("aud", "")),
    )
