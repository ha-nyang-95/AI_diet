/**
 * 인사이트 카드 list orchestrator (Story 4.4 AC5).
 *
 * 빈 list 또는 null 시 미렌더(부모가 surrounding section을 미렌더하도록 forward).
 * 카드 우선순위 정렬은 백엔드 ``generate_weekly_insights`` SOT — 본 컴포넌트는 받은
 * 순서 그대로 vertical stack 렌더.
 */

import { InsightCard, type InsightCardData } from "@/features/reports/InsightCard";

export interface InsightCardListProps {
  insights: readonly InsightCardData[] | null | undefined;
}

export function InsightCardList({ insights }: InsightCardListProps) {
  if (!insights || insights.length === 0) {
    return null;
  }
  return (
    <section
      className="space-y-3"
      aria-label="주간 인사이트 카드"
    >
      <h2 className="text-base font-semibold text-slate-900">
        주간 인사이트
      </h2>
      <div className="space-y-3">
        {insights.map((insight, idx) => (
          <InsightCard key={`${insight.kind}-${idx}`} insight={insight} />
        ))}
      </div>
    </section>
  );
}
