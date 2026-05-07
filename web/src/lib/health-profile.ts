/**
 * Web 건강 프로필 server-only fetch (Story 5.1).
 *
 * 백엔드 ``GET /v1/users/me/profile`` SSR fetch + Pydantic ``HealthProfileResponse``
 * wire format 미러. ``getServerSideMacroGoal`` 패턴 1:1 정합 — 401/5xx non-ok는
 * ``null`` 반환(페이지가 redirect/fallback 결정).
 */
import "server-only";

import { cookies } from "next/headers";

import type { HealthProfileResponse } from "@/features/onboarding/healthProfileSchema";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * 건강 프로필 SSR fetch.
 *
 * @returns ``HealthProfileResponse`` 또는 401/5xx 시 ``null``. 미입력 사용자는
 *          200 + 6 필드 NULL + ``allergies=[]`` + ``profile_completed_at=null`` 응답
 *          (Story 1.5 SOT — 404 미사용).
 */
export async function getServerSideHealthProfile(): Promise<HealthProfileResponse | null> {
  const store = await cookies();
  const access = store.get("bn_access")?.value;
  if (!access) return null;
  const response = await fetch(`${API_BASE_URL}/v1/users/me/profile`, {
    headers: { Cookie: `bn_access=${access}` },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as HealthProfileResponse;
}
