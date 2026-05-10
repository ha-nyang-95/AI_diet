/**
 * Admin JWT claim decode (Story 7.1 AC#6).
 *
 * 신뢰 경계: 본 함수는 "이 쿠키가 *관리자처럼 보이는가*"만 판정. 실제 권한 검증은 백엔드
 * (``current_admin``)가 SOT — layout은 unauthenticated 사용자를 *빨리* redirect.
 *
 * 3-tier defense-in-depth:
 *   (a) ``middleware.ts``: 1차 라우팅 차단 (쿠키 형식/exp 검증).
 *   (b) ``(admin)/admin/layout.tsx``: 2차 빠른 로컬 검증 (exp/role/iss decode).
 *   (c) backend ``current_admin``: 3차 *진짜* 검증 (서명 + DB role 재확인) — 보호된 admin
 *       endpoint 실 호출 시점.
 */

interface AdminJwtClaims {
  readonly exp: number;
  readonly role: string;
  readonly iss: string;
}

const MIN_TOKEN_LENGTH = 20;
const CLOCK_SKEW_SECONDS = 5;
const ADMIN_ISSUER = "balancenote-admin";

export function decodeAdminJwtClaims(
  token: string | undefined,
): AdminJwtClaims | null {
  if (!token || token.length < MIN_TOKEN_LENGTH) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1];
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded =
      normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const json = atob(padded);
    const claims = JSON.parse(json) as Partial<AdminJwtClaims>;
    if (typeof claims.exp !== "number") return null;
    if (typeof claims.role !== "string") return null;
    if (typeof claims.iss !== "string") return null;
    return { exp: claims.exp, role: claims.role, iss: claims.iss };
  } catch {
    return null;
  }
}

export type AdminGuardResult =
  | { kind: "ok" }
  | { kind: "missing" }
  | { kind: "expired" }
  | { kind: "forbidden" }; // role !== admin OR iss !== balancenote-admin

export function evaluateAdminCookie(
  token: string | undefined,
): AdminGuardResult {
  if (!token) return { kind: "missing" };
  const claims = decodeAdminJwtClaims(token);
  if (!claims) return { kind: "missing" }; // 형식 위반 = 익명 등가.
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (claims.exp <= nowSeconds + CLOCK_SKEW_SECONDS) {
    return { kind: "expired" };
  }
  if (claims.iss !== ADMIN_ISSUER) return { kind: "forbidden" };
  if (claims.role !== "admin") return { kind: "forbidden" };
  return { kind: "ok" };
}
