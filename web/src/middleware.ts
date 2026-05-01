/**
 * Next.js middleware — 보호 route 가드 (Story 1.2 AC#6, #11).
 *
 * - `/(user)/*` 그룹 진입 시 `bn_access` 쿠키 부재면 `/login` redirect.
 * - `/(admin)/*` 그룹 진입 시 `bn_admin_access` 쿠키 부재면 `/admin/login` redirect.
 * - `?next=` 파라미터로 원래 URL 보존.
 * - 이미 인증된 사용자가 `/login` 접근 시 `/dashboard`로 redirect (symmetric guard).
 *
 * Stale-cookie self-healing: `bn_access`의 JWT payload(`exp` claim)를 가벼운 base64+JSON
 * 디코드로 검사. 만료/형식불량이면 응답에서 Max-Age=0으로 cookie를 만료시키고 미인증으로
 * 처리 — symmetric guard와 protected guard 사이의 redirect ping-pong(`ERR_TOO_MANY_REDIRECTS`)
 * 회복. 서명 검증은 backend가 책임지므로 middleware는 가벼운 exp 검사만 수행 (Edge runtime
 * 비용 최소화).
 */
import { type NextRequest, NextResponse } from "next/server";

// JWT 최소 길이 — `header.payload.signature` 3 segment + base64 → 수십 자.
// 빈/짧은 값은 garbage로 간주해 무인증 처리(임의 cookie injection 방어).
const MIN_TOKEN_LENGTH = 20;
// 시계 어긋남 보정 — exp 직전 5초는 만료 임박으로 간주해 stale 처리(refresh 트리거 일치).
const CLOCK_SKEW_SECONDS = 5;

const COOKIE_BN_ACCESS = "bn_access";
const COOKIE_BN_REFRESH = "bn_refresh";

type CookieStatus = "missing" | "valid" | "stale";

function decodeJwtExp(token: string): number | null {
  if (token.length < MIN_TOKEN_LENGTH) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1];
    // base64url → base64 padding 복원
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    // Edge runtime은 globalThis.atob 지원.
    const json = atob(padded);
    const claims = JSON.parse(json) as { exp?: unknown };
    return typeof claims.exp === "number" ? claims.exp : null;
  } catch {
    return null;
  }
}

function classifyAccessCookie(token: string | undefined): CookieStatus {
  if (!token) return "missing";
  const exp = decodeJwtExp(token);
  if (exp === null) return "stale";
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (exp <= nowSeconds + CLOCK_SKEW_SECONDS) return "stale";
  return "valid";
}

function isProductionEnvironment(): boolean {
  const env = (process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? "").toLowerCase();
  return env === "production" || env === "prod" || env === "staging";
}

function expireAuthCookies(response: NextResponse): void {
  const secure = isProductionEnvironment();
  // 발급 시 사용한 path와 동일하게 명시 — path 불일치 시 브라우저가 expire 처리 안 함.
  response.cookies.set(COOKIE_BN_ACCESS, "", {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  response.cookies.set(COOKIE_BN_REFRESH, "", {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/v1/auth",
    maxAge: 0,
  });
}

// 짧은-only(legacy `hasValidLookingCookie`) 검사는 admin 쿠키에만 유지 — 본 스토리에서는
// admin OAuth 흐름을 고치지 않음. 추후 admin도 동일 stale-self-heal로 확장 가능.
function hasValidLookingCookie(request: NextRequest, name: string): boolean {
  const value = request.cookies.get(name)?.value;
  return typeof value === "string" && value.length >= MIN_TOKEN_LENGTH;
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  const url = request.nextUrl.clone();

  const accessStatus = classifyAccessCookie(request.cookies.get(COOKIE_BN_ACCESS)?.value);
  const isAuthed = accessStatus === "valid";
  const hasStaleCookie = accessStatus === "stale";

  // /admin/login 자체와 그 하위 path만 가드 우회 — `/admin/loginExtra`는 가드 적용.
  const isAdminLogin = pathname === "/admin/login" || pathname.startsWith("/admin/login/");
  if (pathname.startsWith("/admin") && !isAdminLogin) {
    if (!hasValidLookingCookie(request, "bn_admin_access")) {
      url.pathname = "/admin/login";
      url.searchParams.set("next", pathname + search);
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

  if (pathname.startsWith("/dashboard") || pathname.startsWith("/onboarding")) {
    if (!isAuthed) {
      url.pathname = "/login";
      url.searchParams.set("next", pathname + search);
      const response = NextResponse.redirect(url);
      // stale cookie를 응답에서 만료 — 다음 요청은 깨끗한 미인증 상태로 진입(loop 차단).
      if (hasStaleCookie) expireAuthCookies(response);
      return response;
    }
  }

  if (pathname === "/login") {
    if (isAuthed) {
      // 정상적으로 인증된 사용자만 dashboard로 자동 라우팅 (symmetric guard).
      url.pathname = "/dashboard";
      url.search = "";
      return NextResponse.redirect(url);
    }
    if (hasStaleCookie) {
      // stale cookie를 expired-out 시키고 login 화면 그대로 진입 — 사용자가 재로그인 가능.
      const response = NextResponse.next();
      expireAuthCookies(response);
      return response;
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/admin/:path*", "/login", "/onboarding/:path*"],
};
