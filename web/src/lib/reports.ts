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
 * Story 1.2 `getServerSideUser` 패턴 정합 — non-ok 응답은 모두 ``null`` 반환.
 * 페이지(`dashboard/weekly/page.tsx`)가 ``null`` 시 redirect/empty-fallback 결정.
 * (Story 4.3 CR P9 — 라이브러리는 라우팅 결정 X, fetcher 책임만.)
 */
import "server-only";

import { cookies } from "next/headers";

import type { components } from "@/lib/api-client";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export type WeeklyReportResponse = components["schemas"]["WeeklyReportResponse"];

/**
 * 주간 리포트 SSR fetch.
 *
 * @param fromDate - ISO 8601 date string (KST 시작일, 포함).
 * @param toDate - ISO 8601 date string (KST 종료일, 포함, fromDate <= toDate).
 * @returns ``WeeklyReportResponse`` 또는 non-ok 응답 시 ``null``. 페이지 측이 `null`
 *          분기에서 redirect/fallback UI 결정 (`getServerSideUser` 패턴 정합).
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
  if (!response.ok) return null;
  return (await response.json()) as WeeklyReportResponse;
}

/**
 * KST 기준 7일 윈도우 [today - 6일, today]를 ISO 8601 문자열로 계산.
 *
 * 결정성 — `now` 인자(테스트 격리). default `new Date()`은 SSR 시점.
 *
 * Story 4.3 CR P8 — `Intl.DateTimeFormat` SOT 사용 (manual `now + 9h` offset 회피).
 * SSR runtime TZ가 UTC가 아닌 환경(Vercel TZ 설정/local dev)에서도 KST 정확.
 */
export function computeWeeklyWindowKst(now: Date = new Date()): {
  from_date: string;
  to_date: string;
} {
  const kstFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  // en-CA locale → "YYYY-MM-DD" (ISO 8601 정합).
  const toDate = kstFormatter.format(now);
  // 6일 전 KST 날짜 — KST 12:00 정오 anchor로 DST/zone 경계 안전(Asia/Seoul DST 미운영
  // 이지만 일반화된 패턴).
  const sixDaysAgoUtc = new Date(now.getTime() - 6 * 24 * 60 * 60 * 1000);
  const fromDate = kstFormatter.format(sixDaysAgoUtc);
  return { from_date: fromDate, to_date: toDate };
}
