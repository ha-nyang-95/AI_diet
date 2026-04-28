/**
 * Next.js middleware — 보호 route 가드 (Story 1.2 AC#6, #11).
 *
 * - `/(user)/*` 그룹 진입 시 `bn_access` 쿠키 부재면 `/login` redirect.
 * - `/(admin)/*` 그룹 진입 시 `bn_admin_access` 쿠키 부재면 `/admin/login` redirect.
 * - `?next=` 파라미터로 원래 URL 보존.
 * - 이미 인증된 사용자가 `/login` 접근 시 `/dashboard`로 redirect (symmetric guard).
 */
import { type NextRequest, NextResponse } from "next/server";

// JWT 최소 길이 — `header.payload.signature` 3 segment + base64 → 수십 자.
// 빈/짧은 값은 garbage로 간주해 무인증 처리(임의 cookie injection 방어).
const MIN_TOKEN_LENGTH = 20;

function hasValidLookingCookie(request: NextRequest, name: string): boolean {
  const value = request.cookies.get(name)?.value;
  return typeof value === "string" && value.length >= MIN_TOKEN_LENGTH;
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  const url = request.nextUrl.clone();

  // route group은 URL에 노출되지 않으므로 matcher는 group 내부 path 기준으로 작성한다.
  // 본 스토리는 (user)/dashboard 정도의 placeholder만 — 실제 path는 후속 스토리에서 확장.

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

  if (pathname.startsWith("/dashboard")) {
    if (!hasValidLookingCookie(request, "bn_access")) {
      url.pathname = "/login";
      url.searchParams.set("next", pathname + search);
      return NextResponse.redirect(url);
    }
  }

  // symmetric guard — 이미 인증된 사용자가 /login 진입 시 dashboard로(또는 next로) redirect.
  if (pathname === "/login" && hasValidLookingCookie(request, "bn_access")) {
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/admin/:path*", "/login"],
};
