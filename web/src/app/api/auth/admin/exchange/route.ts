/**
 * Admin JWT exchange — Story 7.1 AC#5.
 *
 * 흐름:
 * 1. ``bn_access`` 쿠키 부재 → ``/admin/login?error=login_first`` redirect (chain start로
 *    돌리지 않음 — 사용자 의도 명시).
 * 2. 백엔드 ``POST /v1/auth/admin/exchange?platform=web`` 호출 + cookie forward.
 * 3. 백엔드 응답의 ``Set-Cookie`` (``bn_admin_access``) forward + ``?next=`` safe redirect.
 * 4. 백엔드 403 (``auth.admin.role_required``) → ``/admin/login?error=role_required``.
 *
 * 절대 금지: ``bn_access`` 쿠키 plaintext를 query string 또는 client 측 노출.
 *
 * Story 7.1 CR — POST 메서드 강제 (GET은 prefetch/SafeLinks/CSRF 위험), ``?platform=web``
 * 명시 (이전 ``bn_refresh`` cookie 추론은 path scope 불일치로 부정확), prod에서 ``API_BASE_URL``
 * 미설정 시 fail-fast (silent localhost fallback로 cookie leak 방지).
 */
import { type NextRequest, NextResponse } from "next/server";

import { safeNext } from "@/lib/safe-next";

function resolveApiBaseUrl(): string {
  const url = process.env.API_BASE_URL;
  if (url) return url;
  const env = (
    process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? ""
  ).toLowerCase();
  if (env === "production" || env === "prod" || env === "staging") {
    throw new Error(
      "API_BASE_URL env is required in production/staging — silent localhost fallback would leak admin cookies.",
    );
  }
  return "http://localhost:8000";
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const url = request.nextUrl;
  const next = safeNext(url.searchParams.get("next"), "/admin");
  const accessToken = request.cookies.get("bn_access")?.value;

  if (!accessToken) {
    return NextResponse.redirect(
      new URL(
        `/admin/login?error=login_first&next=${encodeURIComponent(next)}`,
        request.url,
      ),
      { status: 303 },
    );
  }

  const apiBaseUrl = resolveApiBaseUrl();
  const backendResponse = await fetch(
    `${apiBaseUrl}/v1/auth/admin/exchange?platform=web`,
    {
      method: "POST",
      headers: {
        // user JWT 보유 cookie 포함 — 백엔드 ``current_user``가 user JWT 검증.
        cookie: request.headers.get("cookie") ?? "",
      },
      // Web 흐름은 body=null 응답 + Set-Cookie 발급. 별도 body 송신 불필요.
    },
  );

  if (!backendResponse.ok) {
    const code =
      backendResponse.status === 403 ? "role_required" : "exchange_failed";
    return NextResponse.redirect(
      new URL(`/admin/login?error=${code}`, request.url),
      { status: 303 },
    );
  }

  const setCookieHeaders = backendResponse.headers.getSetCookie?.() ?? [];
  if (setCookieHeaders.length === 0) {
    return NextResponse.redirect(
      new URL("/admin/login?error=cookie_not_issued", request.url),
      { status: 303 },
    );
  }

  // 303 See Other — POST 응답 후 GET redirect (RFC 7231 §6.4.4).
  const response = NextResponse.redirect(new URL(next, request.url), {
    status: 303,
  });
  for (const sc of setCookieHeaders) {
    response.headers.append("set-cookie", sc);
  }
  return response;
}
