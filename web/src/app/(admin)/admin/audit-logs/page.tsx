/**
 * Admin self-audit 페이지 — Story 7.4 AC#4 (FR38).
 *
 * Server Component shell — `bn_admin_access` cookie SSR forward + 첫 페이지 SSR
 * fetch + initial data Client Component prefill. 토큰 부재/401/403 → /admin/login
 * redirect (Story 7.2 [user_id]/page.tsx 패턴 정합).
 */
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AuditLogTable } from "@/features/admin/AuditLogTable";
import type { AdminAuditLogListResponse } from "@/features/admin/types";

export const metadata: Metadata = { title: "감사 로그 — 관리자" };

async function fetchInitialAuditLogs(): Promise<AdminAuditLogListResponse> {
  const cookieStore = await cookies();
  const adminToken = cookieStore.get("bn_admin_access")?.value;
  if (!adminToken) redirect("/admin/login?error=expired");
  const apiBase = process.env.API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(
    `${apiBase}/v1/admin/audit-logs?actor_id=me&limit=50`,
    {
      headers: { Authorization: `Bearer ${adminToken}` },
      cache: "no-store",
    },
  );
  if (response.status === 401 || response.status === 403) {
    redirect("/admin/login?error=expired");
  }
  if (!response.ok) {
    throw new Error(`fetch audit-logs failed: ${response.status}`);
  }
  return (await response.json()) as AdminAuditLogListResponse;
}

export default async function AdminAuditLogsPage() {
  const initial = await fetchInitialAuditLogs();
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold">내 활동 로그</h2>
        <p className="mt-1 text-sm text-zinc-600">
          관리자 계정으로 수행한 조회·수정 액션이 시간순으로 기록됩니다.
        </p>
      </header>
      <AuditLogTable initial={initial} />
    </div>
  );
}
