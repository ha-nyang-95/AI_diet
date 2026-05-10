/**
 * Admin logout — Story 7.1 AC#6.
 *
 * ``bn_admin_access`` cookie를 Max-Age=0로 expire + ``/admin/login`` redirect. 백엔드
 * ``/v1/auth/logout`` 미호출 — admin 토큰은 *stateless* (refresh 없음 → DB row 없음).
 * cookie expire만으로 라우팅 차단(만료까지 ≤ 8h 형식 잔존이지만 *사용자 표면 화면 부재*
 * + middleware/layout 가드 동시 차단).
 *
 * 일반 사용자 ``bn_access``/``bn_refresh``는 그대로 유지(별 의도 — 관리자 권한만 박탈).
 *
 * Story 7.1 CR — POST 메서드 강제 (GET은 ``<img>`` CSRF + 메신저 unfurling으로 우발적
 * logout 위험), cookie path=/ (발급 path와 동기화).
 */
import { type NextRequest, NextResponse } from "next/server";

function isProductionEnvironment(): boolean {
  const env = (
    process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? ""
  ).toLowerCase();
  return env === "production" || env === "prod" || env === "staging";
}

export function POST(request: NextRequest): NextResponse {
  // 303 See Other — POST 응답 후 GET redirect.
  const response = NextResponse.redirect(new URL("/admin/login", request.url), {
    status: 303,
  });
  const secure = isProductionEnvironment();
  response.cookies.set("bn_admin_access", "", {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/", // Story 7.1 CR — 발급 path(/v1/admin → /)와 동기화.
    maxAge: 0,
  });
  return response;
}
