/**
 * Google OAuth start — Authorization Code + PKCE 흐름 시작 (Story 1.2 AC#11).
 *
 * 1. state + code_verifier 생성 (CSRF + PKCE).
 * 2. httpOnly 쿠키에 임시 저장 (`SameSite=Lax` — 반드시 Lax: Strict이면 Google → 우리 callback의
 *    cross-site top-level navigation에서 쿠키 차단되어 흐름 깨짐).
 * 3. Google authorize endpoint로 302 redirect.
 */
import { createHash, randomBytes } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";

import { safeNext } from "@/lib/safe-next";

const GOOGLE_AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth";

function base64url(buffer: Buffer): string {
  return buffer
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function isProductionEnvironment(): boolean {
  const env = (process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? "").toLowerCase();
  return env === "production" || env === "prod" || env === "staging";
}

export function GET(request: NextRequest): NextResponse {
  const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID;
  const redirectUri = process.env.GOOGLE_OAUTH_REDIRECT_URI;

  if (!clientId || !redirectUri) {
    return NextResponse.redirect(
      new URL(
        "/login?error=" + encodeURIComponent("OAuth 설정이 누락되었습니다."),
        request.url,
      ),
    );
  }

  // open redirect 방어 — same-origin 상대 경로만 허용.
  const next = safeNext(request.nextUrl.searchParams.get("next"));
  const state = base64url(randomBytes(24));
  const codeVerifier = base64url(randomBytes(32));
  const codeChallenge = base64url(createHash("sha256").update(codeVerifier).digest());

  const url = new URL(GOOGLE_AUTHORIZE_ENDPOINT);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("access_type", "online");
  url.searchParams.set("prompt", "select_account");

  const response = NextResponse.redirect(url);
  const secure = isProductionEnvironment();
  // SameSite=Lax 필수 — Strict는 cross-site top-level navigation에서 쿠키 차단 → 흐름 깨짐.
  response.cookies.set("bn_oauth_state", state, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/api/auth/google",
    maxAge: 600,
  });
  response.cookies.set("bn_oauth_pkce", codeVerifier, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/api/auth/google",
    maxAge: 600,
  });
  response.cookies.set("bn_oauth_next", next, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/api/auth/google",
    maxAge: 600,
  });
  return response;
}
