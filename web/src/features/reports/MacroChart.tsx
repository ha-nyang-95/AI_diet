"use client";

/**
 * 일별 매크로(탄/단/지) 그램 스택 차트 (Story 4.3 AC3).
 *
 * recharts ``BarChart`` + 3 ``Bar`` 스택. NFR-A5 — 차트 wrapper aria-label + 하단
 * `<details>` 데이터 테이블 fallback. 색상 SOT(Tailwind v4 토큰):
 * - 탄 amber-400 #fbbf24
 * - 단 blue-500 #3b82f6
 * - 지 red-500  #ef4444
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "@/lib/api-client";

type DailySummary = components["schemas"]["DailySummary"];

export interface MacroChartProps {
  dailySummaries: DailySummary[];
  mounted: boolean;
}

const COLOR_CARB = "#fbbf24"; // amber-400
const COLOR_PROTEIN = "#3b82f6"; // blue-500
const COLOR_FAT = "#ef4444"; // red-500

function formatMmDd(isoDate: string): string {
  // KST date string "YYYY-MM-DD" → "MM-DD"
  const [, mm, dd] = isoDate.split("-");
  return `${mm}-${dd}`;
}

export function MacroChart({ dailySummaries, mounted }: MacroChartProps) {
  const chartData = dailySummaries.map((d) => ({
    date: formatMmDd(d.kst_date),
    carb: d.macros?.carbohydrate_g ?? 0,
    protein: d.macros?.protein_g ?? 0,
    fat: d.macros?.fat_g ?? 0,
    kcal: d.energy_kcal_total ?? 0,
  }));

  return (
    <section
      className="rounded-lg border border-slate-200 bg-white p-4"
      role="img"
      aria-label="매크로 비율 추이 차트 — 자세한 데이터는 아래 표 참조"
      tabIndex={0}
    >
      <h2 className="text-base font-semibold text-slate-900">매크로 비율 추이</h2>
      <p className="mb-3 text-xs text-slate-500">탄/단/지 g 일별 스택</p>

      <div className="h-64">
        {mounted ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" stroke="#475569" />
              <YAxis stroke="#475569" />
              <Tooltip />
              <Legend />
              <Bar dataKey="carb" name="탄수화물(g)" stackId="macro" fill={COLOR_CARB} />
              <Bar dataKey="protein" name="단백질(g)" stackId="macro" fill={COLOR_PROTEIN} />
              <Bar dataKey="fat" name="지방(g)" stackId="macro" fill={COLOR_FAT} />
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
              <th scope="col" className="py-1 pr-2">날짜</th>
              <th scope="col" className="py-1 pr-2 text-right">탄(g)</th>
              <th scope="col" className="py-1 pr-2 text-right">단(g)</th>
              <th scope="col" className="py-1 pr-2 text-right">지(g)</th>
              <th scope="col" className="py-1 text-right">합계(kcal)</th>
            </tr>
          </thead>
          <tbody>
            {chartData.map((d) => (
              <tr key={d.date} className="border-b border-slate-100">
                <td className="py-1 pr-2">{d.date}</td>
                <td className="py-1 pr-2 text-right">{d.carb.toFixed(1)}</td>
                <td className="py-1 pr-2 text-right">{d.protein.toFixed(1)}</td>
                <td className="py-1 pr-2 text-right">{d.fat.toFixed(1)}</td>
                <td className="py-1 text-right">{d.kcal.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
