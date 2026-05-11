/**
 * Admin API fetch wrapper — Story 7.2 AC#7.
 *
 * `apiFetch`(`web/src/lib/api-fetch.ts`)는 401 시 `/v1/auth/refresh` 호출 후 재시도하나,
 * admin JWT는 refresh 미지원(NFR-S7) — 401 → 즉시 `/admin/login?error=expired` redirect.
 * 403 → `/admin/login?error=forbidden`(role 박탈/IP 가드 차단 후 OAuth chain 재시작).
 *
 * `bn_admin_access` cookie path=`/`(Story 7.1 CR 정합) — `/v1/admin/*` 호출 시 자동 첨부.
 * `credentials: "include"` 강제.
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function adminApiFetch(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = input.startsWith("http") ? input : `${API_BASE_URL}${input}`;
  const response = await fetch(url, { ...init, credentials: "include" });

  if (response.status === 401 && typeof window !== "undefined") {
    window.location.href = "/admin/login?error=expired";
    return response;
  }
  if (response.status === 403 && typeof window !== "undefined") {
    window.location.href = "/admin/login?error=forbidden";
    return response;
  }
  return response;
}
