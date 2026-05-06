/**
 * Web 주간 리포트 client-side TanStack Query hook (Story 4.3 forward-compat).
 *
 * 본 스토리는 SSR fetch만 사용하므로 본 hook은 *forward-compat*. Story 4.4 인사이트
 * 카드 + 사용자 액션(예: 새로고침 / 시점 이동)에서 client refetch 필요 시 활용.
 *
 * Story 1.2 패턴 정합 — `apiFetch` 401 인터셉터(refresh token), staleTime 60s default.
 * queryKey: `["weekly-report", fromDate, toDate]`.
 */
"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api-fetch";
import type { components } from "@/lib/api-client";

export type WeeklyReportResponse = components["schemas"]["WeeklyReportResponse"];

// Story 4.3 CR P21 — 명시적 4xx retry 차단(invalid 파라미터 알면서도 3회 hammering
// 회귀 가드) + staleTime 60s(spec Story 1.2 패턴 명시 정합 — TanStack Query 기본은 0).
class WeeklyReportFetchError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "WeeklyReportFetchError";
  }
}

export function useWeeklyReportQuery(fromDate: string, toDate: string) {
  return useQuery({
    queryKey: ["weekly-report", fromDate, toDate],
    queryFn: async (): Promise<WeeklyReportResponse> => {
      const params = new URLSearchParams({ from_date: fromDate, to_date: toDate });
      const response = await apiFetch(`/v1/reports/weekly?${params.toString()}`, {
        method: "GET",
      });
      if (!response.ok) {
        throw new WeeklyReportFetchError(
          response.status,
          `weekly report fetch failed: ${response.status}`,
        );
      }
      return (await response.json()) as WeeklyReportResponse;
    },
    staleTime: 60_000,
    retry: (failureCount, error) => {
      if (error instanceof WeeklyReportFetchError && error.status >= 400 && error.status < 500) {
        return false;
      }
      return failureCount < 1;
    },
  });
}
