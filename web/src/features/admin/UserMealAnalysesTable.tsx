"use client";

/**
 * Admin 사용자 피드백 로그 테이블 — Story 7.2 AC#8.
 *
 * 반응형(`sm:` breakpoint) + fit_score 색상 라벨(NFR-A4 정합 — Story 4.3 색상 룰 재사용).
 * feedback_text(full body)는 응답 모델에서 의도적 생략 — Story 7.4 *원문 보기* 시점에 흡수.
 */
import { useQuery } from "@tanstack/react-query";

import { adminApiFetch } from "@/lib/admin-api";
import type {
  AdminMealAnalysisItem,
  AdminMealAnalysisListResponse,
} from "@/features/admin/types";

interface Props {
  userId: string;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR");
}

function fitScoreBadgeClass(label: string): string {
  switch (label) {
    case "excellent":
      return "bg-green-100 text-green-800";
    case "good":
      return "bg-emerald-100 text-emerald-800";
    case "moderate":
      return "bg-yellow-100 text-yellow-800";
    case "low":
      return "bg-orange-100 text-orange-800";
    case "allergen_violation":
      return "bg-red-100 text-red-800";
    default:
      return "bg-zinc-100 text-zinc-700";
  }
}

export function UserMealAnalysesTable({ userId }: Props) {
  const { data, isLoading, error } = useQuery<AdminMealAnalysisListResponse>({
    queryKey: ["admin", "users", "analyses", userId],
    queryFn: async () => {
      const response = await adminApiFetch(
        `/v1/admin/users/${userId}/meal-analyses?limit=50`,
      );
      if (!response.ok) {
        throw new Error(`fetch analyses failed: ${response.status}`);
      }
      return (await response.json()) as AdminMealAnalysisListResponse;
    },
    staleTime: 30_000,
  });

  if (isLoading) return <p className="text-sm text-zinc-500">피드백 로그 로딩 중…</p>;
  if (error) return <p className="text-sm text-red-600">피드백 로그 조회 실패.</p>;
  if (!data || data.items.length === 0)
    return <p className="text-sm text-zinc-500">피드백 로그가 없습니다.</p>;

  return (
    <>
      <ul className="space-y-2 sm:hidden" aria-label="모바일 피드백 카드">
        {data.items.map((a) => (
          <AnalysisCard key={a.meal_analysis_id} item={a} />
        ))}
      </ul>
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-left text-zinc-600">
              <th className="px-3 py-2 font-medium">분석 시각</th>
              <th className="px-3 py-2 font-medium">fit score</th>
              <th className="px-3 py-2 font-medium">분류</th>
              <th className="px-3 py-2 font-medium">요약</th>
              <th className="px-3 py-2 font-medium">LLM</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((a) => (
              <AnalysisRow key={a.meal_analysis_id} item={a} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function AnalysisRow({ item }: { item: AdminMealAnalysisItem }) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="px-3 py-2">{formatDate(item.created_at)}</td>
      <td className="px-3 py-2">
        <span className={`rounded px-2 py-0.5 text-xs ${fitScoreBadgeClass(item.fit_score_label)}`}>
          {item.fit_score} · {item.fit_score_label}
        </span>
      </td>
      <td className="px-3 py-2 text-xs">{item.fit_reason}</td>
      <td className="px-3 py-2 text-xs">{item.feedback_summary}</td>
      <td className="px-3 py-2 text-xs">{item.used_llm}</td>
    </tr>
  );
}

function AnalysisCard({ item }: { item: AdminMealAnalysisItem }) {
  return (
    <li className="rounded-lg border border-zinc-200 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">{formatDate(item.created_at)}</span>
        <span className="text-xs text-zinc-500">{item.used_llm}</span>
      </div>
      <p className="mt-1">
        <span className={`rounded px-2 py-0.5 text-xs ${fitScoreBadgeClass(item.fit_score_label)}`}>
          {item.fit_score} · {item.fit_score_label}
        </span>
      </p>
      <p className="mt-1 text-xs text-zinc-600">{item.feedback_summary}</p>
      <p className="mt-1 text-xs text-zinc-500">사유: {item.fit_reason}</p>
    </li>
  );
}
