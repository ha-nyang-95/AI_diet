/**
 * 단일 인사이트 카드 (Story 4.4 AC5).
 *
 * 백엔드 ``app/domain/insights.py:InsightCard`` Pydantic wire format 미러.
 * - severity warning: 좌측 amber border + warning icon.
 * - severity info: 좌측 blue border.
 * - cta set: ``Link``로 ``/settings/macro-goal`` 노출. cta=null(allergen_exposure)은
 *   링크 미렌더.
 */

import Link from "next/link";

export type InsightKind =
  | "protein_deficit"
  | "calorie_diff"
  | "macro_ratio_drift"
  | "allergen_exposure";

export type InsightSeverity = "info" | "warning";

export interface InsightCta {
  action: "adjust_macro_goal";
  label: string;
}

export interface InsightCardData {
  kind: InsightKind;
  severity: InsightSeverity;
  title: string;
  body: string;
  citation: string;
  cta: InsightCta | null;
}

export interface InsightCardProps {
  insight: InsightCardData;
}

export function InsightCard({ insight }: InsightCardProps) {
  const borderClass =
    insight.severity === "warning"
      ? "border-l-4 border-amber-500"
      : "border-l-4 border-blue-500";
  return (
    <article
      className={`rounded-md bg-white p-4 shadow-sm ${borderClass}`}
      aria-label={`${insight.severity === "warning" ? "주의" : "정보"} 인사이트: ${insight.title}`}
    >
      <h3 className="text-base font-semibold text-slate-900">{insight.title}</h3>
      <p className="mt-2 text-sm text-slate-700">{insight.body}</p>
      <p className="mt-2 text-xs text-slate-500">{insight.citation}</p>
      {insight.cta ? (
        <div className="mt-3">
          <Link
            href="/settings/macro-goal"
            className="inline-flex items-center text-sm font-medium text-blue-600 underline-offset-4 hover:underline"
          >
            {insight.cta.label} →
          </Link>
        </div>
      ) : null}
    </article>
  );
}
