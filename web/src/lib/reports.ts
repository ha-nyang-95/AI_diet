/**
 * Web 주간 리포트 server-only fetch (Story 4.3).
 *
 * - 서버 컴포넌트: `getServerSideWeeklyReport(fromDate, toDate)` — 백엔드
 *   `/v1/reports/weekly` 호출 (cookie 직접 forward, `cache: "no-store"`).
 * - 클라이언트: `useWeeklyReportQuery` — TanStack Query hook (forward-compat,
 *   `features/reports/api.ts`).
 *
 * `import "server-only"` — 클라이언트 컴포넌트가 import 시 빌드 에러로 차단(서버 전용 모듈 보호).
 *
 * Story 1.2 `getServerSideUser` 패턴 정합 — cookie-direct-forward + 401 분기.
 * 401 → `/login` redirect, 4xx → null 반환(빈 차트 fallback), 5xx → throw(error
 * boundary 처리).
 */
import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { components } from "@/lib/api-client";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export type WeeklyReportResponse = components["schemas"]["WeeklyReportResponse"];

/**
 * 주간 리포트 SSR fetch.
 *
 * @param fromDate - ISO 8601 date string (KST 시작일, 포함).
 * @param toDate - ISO 8601 date string (KST 종료일, 포함, fromDate <= toDate).
 * @returns ``WeeklyReportResponse`` 또는 401/4xx 시 ``null``.
 */
export async function getServerSideWeeklyReport(
  fromDate: string,
  toDate: string,
): Promise<WeeklyReportResponse | null> {
  const store = await cookies();
  const access = store.get("bn_access")?.value;
  if (!access) return null;
  const params = new URLSearchParams({ from_date: fromDate, to_date: toDate });
  const response = await fetch(
    `${API_BASE_URL}/v1/reports/weekly?${params.toString()}`,
    {
      headers: { Cookie: `bn_access=${access}` },
      cache: "no-store",
    },
  );
  if (response.status === 401) redirect("/login");
  if (response.status >= 500) {
    throw new Error(`weekly report fetch failed: upstream ${response.status}`);
  }
  if (!response.ok) return null;
  return (await response.json()) as WeeklyReportResponse;
}

/**
 * KST 기준 7일 윈도우 [today - 6일, today]를 ISO 8601 문자열로 계산.
 *
 * 결정성 — `now` 인자(테스트 격리). default `new Date()`은 SSR 시점 KST.
 */
export function computeWeeklyWindowKst(now: Date = new Date()): {
  from_date: string;
  to_date: string;
} {
  // KST = UTC+9. SSR runtime은 UTC가 디폴트(Vercel/Railway 정합)이므로 KST 변환 필요.
  const kstNow = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const toDate = kstNow.toISOString().slice(0, 10);
  const from = new Date(kstNow);
  from.setUTCDate(from.getUTCDate() - 6);
  const fromDate = from.toISOString().slice(0, 10);
  return { from_date: fromDate, to_date: toDate };
}
