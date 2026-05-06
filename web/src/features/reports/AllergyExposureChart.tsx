"use client";

/**
 * 사용자 22종 알레르기 중 주간 노출 횟수 horizontal bar chart (Story 4.3 AC3).
 *
 * recharts ``BarChart`` (layout="vertical") + 사용자 ``users.allergies`` 미설정 시
 * 차트 미렌더 + 캡션 안내. 노출 0건이면 빈 텍스트 + 빈 차트 영역(NFR-A4).
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "@/lib/api-client";

type DailySummary = components["schemas"]["DailySummary"];

export interface AllergyExposureChartProps {
  dailySummaries: DailySummary[];
  userAllergies: readonly string[];
  mounted: boolean;
}

export function AllergyExposureChart({
  dailySummaries,
  userAllergies,
  mounted,
}: AllergyExposureChartProps) {
  // 주간 합산 — allergen별 7일 노출 카운트.
  const weeklyTotals = new Map<string, number>();
  for (const day of dailySummaries) {
    for (const exposure of day.allergen_exposures) {
      weeklyTotals.set(
        exposure.allergen,
        (weeklyTotals.get(exposure.allergen) ?? 0) + exposure.count,
      );
    }
  }

  const chartData = Array.from(weeklyTotals.entries())
    .filter(([, count]) => count > 0)
    .map(([allergen, count]) => ({ allergen, count }));

  const noUserAllergies = userAllergies.length === 0;
  const noExposure = !noUserAllergies && chartData.length === 0;

  return (
    <section
      className="rounded-lg border border-slate-200 bg-white p-4"
      role="img"
      aria-label="주간 알레르기 노출 횟수 차트 — 자세한 데이터는 아래 표 참조"
      tabIndex={0}
    >
      <h2 className="text-base font-semibold text-slate-900">알레르기 노출</h2>
      <p className="mb-3 text-xs text-slate-500">
        {noUserAllergies
          ? "알레르기 항목 설정 시 노출 모니터링이 시작됩니다"
          : noExposure
            ? "이번 주 알레르기 노출 0건"
            : `사용자 알레르기 ${userAllergies.length}건 모니터링 중`}
      </p>

      <div className="h-64">
        {noUserAllergies ? (
          <div className="flex h-full w-full items-center justify-center text-sm text-slate-400">
            (차트 미렌더)
          </div>
        ) : mounted ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 5, right: 20, bottom: 5, left: 60 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis type="number" stroke="#475569" allowDecimals={false} />
              <YAxis dataKey="allergen" type="category" stroke="#475569" />
              <Tooltip />
              <Bar dataKey="count" name="노출 횟수" fill="#dc2626" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full w-full animate-pulse bg-slate-50" />
        )}
      </div>

      <details className="mt-3 text-sm text-slate-700">
        <summary className="cursor-pointer text-slate-600 hover:text-slate-900">
          데이터 표 보기
        </summary>
        <table className="mt-2 w-full text-left">
          <thead>
            <tr className="border-b border-slate-200 text-xs text-slate-500">
              <th scope="col" className="py-1 pr-2">알레르기</th>
              <th scope="col" className="py-1 text-right">노출 횟수</th>
            </tr>
          </thead>
          <tbody>
            {chartData.length === 0 ? (
              <tr>
                <td className="py-1 pr-2 text-slate-400" colSpan={2}>
                  {noUserAllergies ? "—" : "이번 주 노출 0건"}
                </td>
              </tr>
            ) : (
              chartData.map((d) => (
                <tr key={d.allergen} className="border-b border-slate-100">
                  <td className="py-1 pr-2">{d.allergen}</td>
                  <td className="py-1 text-right">{d.count}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </details>
    </section>
  );
}
