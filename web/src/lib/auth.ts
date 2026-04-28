/**
 * Web auth helpers (Story 1.2).
 *
 * - 서버 컴포넌트: `getServerSideUser()` — 백엔드 `/v1/users/me` 호출 (cookie 직접 forward).
 * - 클라이언트: `useUser()` — TanStack Query로 fetch (Story 4.3에서 도입).
 *
 * `import "server-only"` — 클라이언트 컴포넌트가 import 시 빌드 에러로 차단(서버 전용 모듈 보호).
 * `"use server"` 디렉티브는 사용 금지 — 그건 모든 export를 Server Action(클라이언트 RPC)으로 만든다.
 *
 * 절대 금지: next-auth 도입(architecture 결정 위반). cookie 디코드 직접 수행 금지(서명 검증 누락).
 */
import "server-only";

import { cookies } from "next/headers";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  picture_url: string | null;
  role: "user" | "admin";
  created_at: string;
  last_login_at: string | null;
  onboarded_at: string | null;
}

export async function getServerSideUser(): Promise<AuthUser | null> {
  const store = await cookies();
  const access = store.get("bn_access")?.value;
  if (!access) return null;
  // AGENTS.md "백엔드 JWT를 httpOnly 쿠키로 직접 교환" 정합 — 쿠키를 그대로 forward.
  // 백엔드 deps는 Authorization 헤더 / `bn_access` cookie 둘 다 fallback 지원하므로 cookie 직접.
  const cookieHeader = store
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const response = await fetch(`${API_BASE_URL}/v1/users/me`, {
    headers: { Cookie: cookieHeader },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as AuthUser;
}
