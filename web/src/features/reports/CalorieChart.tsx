"use client";

/**
 * 일별 섭취 칼로리 vs TDEE 비교 차트 (Story 4.3 AC3).
 *
 * recharts ``ComposedChart`` + ``Bar`` (섭취 kcal) + ``ReferenceLine`` (TDEE 권장 라인).
 * ``tdee=null`` (프로필 미완성) 시 ReferenceLine 미렌더 + 캡션 안내.
 */

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "@/lib/api-client";

type DailySummary = components["schemas"]["DailySummary"];

export interface CalorieChartProps {
  dailySummaries: DailySummary[];
  tdee: number | null;
  mounted: boolean;
}

function formatMmDd(isoDate: string): string {
  const [, mm, dd] = isoDate.split("-");
  return `${mm}-${dd}`;
}

export function CalorieChart({ dailySummaries, tdee, mounted }: CalorieChartProps) {
  const chartData = dailySummaries.map((d) => ({
    date: formatMmDd(d.kst_date),
    kcal: d.energy_kcal_total ?? 0,
  }));
  const totalKcal = chartData.reduce((acc, d) => acc + d.kcal, 0);
  const avgKcal = chartData.length > 0 ? totalKcal / chartData.length : 0;

  return (
    <section
      className="rounded-lg border border-slate-200 bg-white p-4"
      role="img"
      aria-label="섭취 칼로리 vs TDEE 비교 차트 — 자세한 데이터는 아래 표 참조"
      tabIndex={0}
    >
      <h2 className="text-base font-semibold text-slate-900">섭취 칼로리 vs TDEE</h2>
      <p className="mb-3 text-xs text-slate-500">
        {tdee !== null && tdee !== undefined
          ? `TDEE 권장: ${tdee} kcal/day`
          : "TDEE 표시는 프로필 입력 후 노출됩니다"}
      </p>

      <div className="h-64">
        {mounted ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" stroke="#475569" />
              <YAxis stroke="#475569" />
              <Tooltip />
              <Legend />
              <Bar dataKey="kcal" name="섭취(kcal)" fill="#22c55e" />
              {tdee !== null && tdee !== undefined ? (
                <ReferenceLine
                  y={tdee}
                  stroke="#f97316"
                  strokeDasharray="5 5"
                  label={{ value: `TDEE ${tdee}`, position: "right", fill: "#f97316" }}
                />
              ) : null}
            </ComposedChart>
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
              <th scope="col" className="py-1 pr-2">날짜</th>
              <th scope="col" className="py-1 pr-2 text-right">섭취(kcal)</th>
              <th scope="col" className="py-1 pr-2 text-right">TDEE(kcal)</th>
              <th scope="col" className="py-1 text-right">차이(kcal)</th>
            </tr>
          </thead>
          <tbody>
            {chartData.map((d) => (
              <tr key={d.date} className="border-b border-slate-100">
                <td className="py-1 pr-2">{d.date}</td>
                <td className="py-1 pr-2 text-right">{d.kcal.toFixed(0)}</td>
                <td className="py-1 pr-2 text-right">
                  {tdee !== null && tdee !== undefined ? tdee : "—"}
                </td>
                <td className="py-1 text-right">
                  {tdee !== null && tdee !== undefined ? (d.kcal - tdee).toFixed(0) : "—"}
                </td>
              </tr>
            ))}
            <tr className="border-t-2 border-slate-300 text-sm font-medium text-slate-700">
              <td className="py-1 pr-2">주간 평균</td>
              <td className="py-1 pr-2 text-right">{avgKcal.toFixed(0)}</td>
              <td className="py-1 pr-2 text-right">
                {tdee !== null && tdee !== undefined ? tdee : "—"}
              </td>
              <td className="py-1 text-right">
                {tdee !== null && tdee !== undefined ? (avgKcal - tdee).toFixed(0) : "—"}
              </td>
            </tr>
          </tbody>
        </table>
      </details>
    </section>
  );
}
