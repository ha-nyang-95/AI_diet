/**
 * `GET /v1/users/me/consents` — 동의 상태 server-only fetch (Story 1.3 AC2/AC14).
 *
 * `import "server-only"` 첫 줄 (Story 1.2 W1 정합 — `"use server"` 절대 금지).
 * cookie-direct-forward 패턴 — `getServerSideUser`와 동일.
 */
import "server-only";

import { cookies } from "next/headers";

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
  const cookieHeader = store
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const response = await fetch(`${API_BASE_URL}/v1/users/me/consents`, {
    headers: { Cookie: cookieHeader },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as ConsentStatus;
}
