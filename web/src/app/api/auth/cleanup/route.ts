/**
 * 쿠키 정리 라우트 — stale-cookie 회복 (loop 차단의 두번째 layer).
 *
 * 사용 시나리오:
 * 서버 컴포넌트가 `bn_access`로 백엔드 호출 시 401을 받으면(예: JWT 서명 무효, 사용자 레코드
 * 제거 등 middleware의 가벼운 exp 검사로는 못 잡는 케이스), 페이지가 직접 `redirect("/login")`을
 * 하면 middleware가 valid-looking 쿠키 보고 다시 보호 라우트로 보내며 ping-pong이 된다.
 * Server Component는 쿠키를 set할 수 없으므로(읽기 전용), Route Handler 한 단계를 거쳐
 * `Set-Cookie: Max-Age=0`을 동봉한 redirect 응답을 만든다.
 *
 * 멱등 — 쿠키가 이미 없어도 Max-Age=0이 no-op이라 안전하다.
 */
import { type NextRequest, NextResponse } from "next/server";

import { safeNext } from "@/lib/safe-next";

const COOKIE_BN_ACCESS = "bn_access";
const COOKIE_BN_REFRESH = "bn_refresh";

function isProductionEnvironment(): boolean {
  const env = (process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? "").toLowerCase();
  return env === "production" || env === "prod" || env === "staging";
}

export function GET(request: NextRequest): NextResponse {
  const next = safeNext(request.nextUrl.searchParams.get("next"), "/login");
  const response = NextResponse.redirect(new URL(next, request.url));
  const secure = isProductionEnvironment();
  // 발급 시 사용한 path와 동일하게 — path 불일치 시 브라우저가 expire 처리 안 함.
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
  return response;
}
