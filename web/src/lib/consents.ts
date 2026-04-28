/**
 * `GET /v1/users/me/consents` — 동의 상태 server-only fetch (Story 1.3 AC2/AC14).
 *
 * `import "server-only"` 첫 줄 (Story 1.2 W1 정합 — `"use server"` 절대 금지).
 * cookie-direct-forward 패턴 — `getServerSideUser`와 동일하지만 `bn_access`만 선별
 * 전송한다(불필요 쿠키 leak 차단, Gemini PR #5 security-medium 정합).
 *
 * 401 → 만료 토큰 → `/login`으로 RSC redirect(`next/navigation` `redirect`).
 * 5xx → throw — error boundary가 처리. 호출부는 null을 "동의 row 없음" 또는 "쿠키
 * 미보유"로만 해석.
 */
import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export interface ConsentStatus {
  disclaimer_acknowledged_at: string | null;
  terms_consent_at: string | null;
  privacy_consent_at: string | null;
  sensitive_personal_info_consent_at: string | null;
  disclaimer_version: string | null;
  terms_version: string | null;
  privacy_version: string | null;
  sensitive_personal_info_version: string | null;
  basic_consents_complete: boolean;
}

export async function getServerSideConsents(): Promise<ConsentStatus | null> {
  const store = await cookies();
  const access = store.get("bn_access")?.value;
  if (!access) return null;
  const response = await fetch(`${API_BASE_URL}/v1/users/me/consents`, {
    headers: { Cookie: `bn_access=${access}` },
    cache: "no-store",
  });
  if (response.status === 401) redirect("/login");
  if (response.status >= 500) {
    throw new Error(`consents fetch failed: upstream ${response.status}`);
  }
  if (!response.ok) return null;
  return (await response.json()) as ConsentStatus;
}
