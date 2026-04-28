/**
 * Google OAuth callback — Story 1.2 AC#11.
 *
 * 1. state 검증 (쿠키 vs 쿼리스트링) + 일회성 사용 후 삭제.
 * 2. 백엔드 `POST /v1/auth/google` 서버사이드 호출 (code + code_verifier 동봉, platform="web").
 * 3. 백엔드 응답의 Set-Cookie 헤더를 그대로 클라이언트에 forward.
 *    - prod: 백엔드와 Web을 동일 등록 도메인으로 운영(`Domain=balancenote.app`)해야 cookie 공유.
 *    - dev: API_BASE_URL이 localhost일 때는 Set-Cookie를 forward하면 도메인 mismatch가 생길 수 있어
 *      Next.js 측에서 cookie를 직접 set(아래 `_setUserCookies` fallback) — 마찰 적음.
 *
 * 절대 금지: next-auth 도입.
 */
import { type NextRequest, NextResponse } from "next/server";

import { safeNext } from "@/lib/safe-next";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";
const OAUTH_TEMP_COOKIE_KEYS = ["bn_oauth_state", "bn_oauth_pkce", "bn_oauth_next"] as const;

function isProductionEnvironment(): boolean {
  const env = (process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? "").toLowerCase();
  return env === "production" || env === "prod" || env === "staging";
}

function clearOAuthTempCookies(response: NextResponse): void {
  const secure = isProductionEnvironment();
  for (const key of OAUTH_TEMP_COOKIE_KEYS) {
    response.cookies.set(key, "", {
      httpOnly: true,
      secure,
      sameSite: "lax",
      path: "/api/auth/google",
      maxAge: 0,
    });
  }
}

function loginRedirect(request: NextRequest, message: string): NextResponse {
  const url = new URL(`/login?error=${encodeURIComponent(message)}`, request.url);
  const response = NextResponse.redirect(url);
  // 실패 분기에서도 임시 OAuth 쿠키 즉시 expire — stale 잔존이 다음 시도와 충돌하지 않도록.
  clearOAuthTempCookies(response);
  return response;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const url = request.nextUrl;
  const code = url.searchParams.get("code");
  const stateFromQuery = url.searchParams.get("state");
  const errorFromGoogle = url.searchParams.get("error");

  if (errorFromGoogle) {
    return loginRedirect(request, `Google OAuth error: ${errorFromGoogle}`);
  }
  if (!code || !stateFromQuery) {
    return loginRedirect(request, "missing code or state");
  }

  const stateCookie = request.cookies.get("bn_oauth_state")?.value;
  const codeVerifier = request.cookies.get("bn_oauth_pkce")?.value;
  // open redirect 방어 — `bn_oauth_next` 쿠키 값도 same-origin 상대 경로만 허용.
  const next = safeNext(request.cookies.get("bn_oauth_next")?.value);

  if (!stateCookie || stateCookie !== stateFromQuery || !codeVerifier) {
    return loginRedirect(request, "invalid OAuth state");
  }

  const redirectUri = process.env.GOOGLE_OAUTH_REDIRECT_URI ?? "";
  const backendResponse = await fetch(`${API_BASE_URL}/v1/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      platform: "web",
      code,
      redirect_uri: redirectUri,
      code_verifier: codeVerifier,
    }),
  });

  if (!backendResponse.ok) {
    // 백엔드 raw text는 사용자 PII/내부 경로 echo 위험 — status code만 메시지에 포함.
    return loginRedirect(request, `로그인 실패 (HTTP ${backendResponse.status})`);
  }

  // 백엔드는 Web platform 응답에서 Set-Cookie(`bn_access`/`bn_refresh`)를 직접 발급 —
  // 동일 등록 도메인일 때 그대로 forward 가능. dev에서 도메인 mismatch 시 fail-closed.
  const response = NextResponse.redirect(new URL(next, request.url));

  const setCookieHeaders = backendResponse.headers.getSetCookie?.() ?? [];
  for (const sc of setCookieHeaders) {
    response.headers.append("set-cookie", sc);
  }

  if (setCookieHeaders.length === 0) {
    return loginRedirect(request, "백엔드가 쿠키를 발급하지 않음 (도메인 정합 확인 필요)");
  }

  clearOAuthTempCookies(response);
  return response;
}
