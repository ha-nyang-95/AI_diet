"use client";

/**
 * 일별 단백질 g/kg 추이 + 권장 범위 ReferenceArea (Story 4.3 AC3).
 *
 * recharts ``LineChart`` + ``Line`` (protein_g_per_kg) + ``ReferenceArea`` (권장 영역).
 * ``health_goal``/``weight_kg`` 미설정 또는 ``protein_target_*`` None이면 권장 영역
 * 미렌더 + 캡션 안내.
 */

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "@/lib/api-client";

type DailySummary = components["schemas"]["DailySummary"];

export interface ProteinChartProps {
  dailySummaries: DailySummary[];
  healthGoal: components["schemas"]["WeeklyReportResponse"]["health_goal"];
  proteinTargetLower: number | null;
  proteinTargetUpper: number | null;
  weightKg: number | null;
  mounted: boolean;
}

function formatMmDd(isoDate: string): string {
  const [, mm, dd] = isoDate.split("-");
  return `${mm}-${dd}`;
}

export function ProteinChart({
  dailySummaries,
  healthGoal,
  proteinTargetLower,
  proteinTargetUpper,
  weightKg,
  mounted,
}: ProteinChartProps) {
  const chartData = dailySummaries.map((d) => ({
    date: formatMmDd(d.kst_date),
    proteinPerKg: d.macros?.protein_g_per_kg ?? null,
    proteinAbs: d.macros?.protein_g ?? null,
  }));

  const showRange =
    proteinTargetLower !== null &&
    proteinTargetUpper !== null &&
    weightKg !== null;
  const rangeLabel =
    showRange && healthGoal
      ? `권장 ${proteinTargetLower}-${proteinTargetUpper} g/kg/day (${healthGoal})`
      : "권장 범위는 프로필 + 목표 설정 후 노출";

  return (
    <section
      className="rounded-lg border border-slate-200 bg-white p-4"
      role="img"
      aria-label="단백질 g/kg 추이 차트 — 자세한 데이터는 아래 표 참조"
      tabIndex={0}
    >
      <h2 className="text-base font-semibold text-slate-900">단백질 g/kg 추이</h2>
      <p className="mb-3 text-xs text-slate-500">{rangeLabel}</p>

      <div className="h-64">
        {mounted ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" stroke="#475569" />
              <YAxis stroke="#475569" />
              <Tooltip />
              <Legend />
              {showRange && proteinTargetLower !== null && proteinTargetUpper !== null ? (
                <ReferenceArea
                  y1={proteinTargetLower}
                  y2={proteinTargetUpper}
                  fill="#86efac"
                  fillOpacity={0.15}
                />
              ) : null}
              <Line
                dataKey="proteinPerKg"
                name="단백질 (g/kg)"
                stroke="#2563eb"
                strokeWidth={2}
                connectNulls
              />
            </LineChart>
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
              <th scope="col" className="py-1 pr-2 text-right">단백질(g)</th>
              <th scope="col" className="py-1 pr-2 text-right">단백질(g/kg)</th>
              <th scope="col" className="py-1 text-right">권장 범위(g/kg)</th>
            </tr>
          </thead>
          <tbody>
            {chartData.map((d) => (
              <tr key={d.date} className="border-b border-slate-100">
                <td className="py-1 pr-2">{d.date}</td>
                <td className="py-1 pr-2 text-right">
                  {d.proteinAbs !== null ? d.proteinAbs.toFixed(1) : "—"}
                </td>
                <td className="py-1 pr-2 text-right">
                  {d.proteinPerKg !== null ? d.proteinPerKg.toFixed(2) : "—"}
                </td>
                <td className="py-1 text-right">
                  {showRange
                    ? `${proteinTargetLower}-${proteinTargetUpper}`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
