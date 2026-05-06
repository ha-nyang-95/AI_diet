"use client";

/**
 * 주간 리포트 orchestrator client component (Story 4.3 AC2/AC3/AC5).
 *
 * 4 차트 grid + 빈 데이터 fallback + Story 4.4 forward-compat insights placeholder.
 * recharts ResponsiveContainer는 SSR 시점 0 width를 측정하므로 useEffect mounted
 * flag 패턴으로 hydration 후만 차트 렌더(SSR-Hydration mismatch 회피).
 */

import { useSyncExternalStore } from "react";

import { AllergyExposureChart } from "@/features/reports/AllergyExposureChart";
import { CalorieChart } from "@/features/reports/CalorieChart";
import { MacroChart } from "@/features/reports/MacroChart";
import { ProteinChart } from "@/features/reports/ProteinChart";
import type { WeeklyReportResponse } from "@/lib/reports";

// SSR-safe mounted flag — recharts ResponsiveContainer는 SSR 시 0 width를 측정해
// 차트 미렌더. ``useSyncExternalStore``는 server snapshot=false / client snapshot=true로
// SSR-Hydration mismatch 회피하는 React 표준 패턴.
function _subscribe(): () => void {
  return () => {};
}
function _getMountedClient(): boolean {
  return true;
}
function _getMountedServer(): boolean {
  return false;
}
function useMounted(): boolean {
  return useSyncExternalStore(_subscribe, _getMountedClient, _getMountedServer);
}

export interface WeeklyReportProps {
  report: WeeklyReportResponse;
  userAllergies: readonly string[];
}

/**
 * 7-요소 ``daily_summaries``의 ``meal_count`` 합 — 0이면 빈 화면.
 */
function isEmpty(report: WeeklyReportResponse): boolean {
  return (report.daily_summaries ?? []).every((d) => d.meal_count === 0);
}

export function WeeklyReport({ report, userAllergies }: WeeklyReportProps) {
  const mounted = useMounted();

  const empty = isEmpty(report);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          주간 리포트
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          {report.from_date} ~ {report.to_date}
        </p>
      </header>

      {empty ? (
        <section className="rounded-lg border border-slate-200 bg-white p-12 text-center">
          <p className="text-base text-slate-700">
            이번 주 기록이 없습니다 — 모바일에서 첫 식단을 입력하세요.
          </p>
          <p className="mt-3 text-sm text-slate-500">
            <a
              href="balancenote://meals/input"
              className="text-blue-600 underline-offset-4 hover:underline"
            >
              앱 열기
            </a>
          </p>
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <MacroChart
            dailySummaries={report.daily_summaries}
            mounted={mounted}
          />
          <CalorieChart
            dailySummaries={report.daily_summaries}
            tdee={report.tdee}
            mounted={mounted}
          />
          <ProteinChart
            dailySummaries={report.daily_summaries}
            healthGoal={report.health_goal}
            proteinTargetLower={report.protein_target_g_per_kg_lower}
            proteinTargetUpper={report.protein_target_g_per_kg_upper}
            weightKg={report.weight_kg}
            mounted={mounted}
          />
          <AllergyExposureChart
            dailySummaries={report.daily_summaries}
            userAllergies={userAllergies}
            mounted={mounted}
          />
        </div>
      )}

      {/* Story 4.4 forward-compat — insights 카드 영역. baseline에서는 항상 None이라
          미렌더. */}
      {report.insights ? (
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6">
          {/* Story 4.4 인사이트 카드 컴포넌트가 본 영역에 mount. */}
        </section>
      ) : null}

      {/* Story 4.4 forward-compat CTA placeholder — 본 스토리는 비활성. */}
      <section className="mt-6 flex justify-end">
        <button
          type="button"
          disabled
          aria-disabled="true"
          title="Story 4.4에서 활성화"
          className="cursor-not-allowed rounded-md border border-slate-300 bg-slate-100 px-4 py-2 text-sm text-slate-400"
        >
          다음 주 권장 매크로 조정 (준비 중)
        </button>
      </section>
    </main>
  );
}
