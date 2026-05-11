"use client";

/**
 * Admin 식단 이력 테이블 — Story 7.2 AC#8.
 *
 * 반응형(`sm:` breakpoint) 모바일 카드 / 데스크톱 테이블 분기. 삭제 버튼은
 * native ``window.confirm`` MVP — shadcn/ui Dialog는 Story 8.4 polish forward.
 * raw_text는 length-only(NFR-S5 마스킹).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { adminApiFetch } from "@/lib/admin-api";
import type { AdminMealItem, AdminMealListResponse } from "@/features/admin/types";

interface Props {
  userId: string;
}

const MEALS_QUERY_KEY = ["admin", "users", "meals"] as const;

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

export function UserMealsTable({ userId }: Props) {
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery<AdminMealListResponse>({
    queryKey: [...MEALS_QUERY_KEY, userId],
    queryFn: async () => {
      const response = await adminApiFetch(
        `/v1/admin/users/${userId}/meals?limit=50`,
      );
      if (!response.ok) {
        throw new Error(`fetch meals failed: ${response.status}`);
      }
      return (await response.json()) as AdminMealListResponse;
    },
    staleTime: 30_000,
  });

  const handleDelete = async (mealId: string) => {
    const confirmed =
      typeof window !== "undefined" && window.confirm("이 식단을 삭제하시겠습니까?");
    if (!confirmed) return;
    const response = await adminApiFetch(
      `/v1/admin/users/${userId}/meals/${mealId}`,
      { method: "DELETE" },
    );
    if (response.ok || response.status === 404) {
      // 404는 이미 삭제됨 — invalidate해서 UI 갱신.
      await queryClient.invalidateQueries({ queryKey: [...MEALS_QUERY_KEY, userId] });
      refetch();
    } else {
      window.alert(`식단 삭제 실패 (${response.status})`);
    }
  };

  if (isLoading) return <p className="text-sm text-zinc-500">식단 이력 로딩 중…</p>;
  if (error) return <p className="text-sm text-red-600">식단 이력 조회 실패.</p>;
  if (!data || data.meals.length === 0)
    return <p className="text-sm text-zinc-500">식단 이력이 없습니다.</p>;

  return (
    <>
      <ul className="space-y-2 sm:hidden" aria-label="모바일 식단 카드">
        {data.meals.map((m) => (
          <MealCard key={m.meal_id} meal={m} onDelete={handleDelete} />
        ))}
      </ul>
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-left text-zinc-600">
              <th className="px-3 py-2 font-medium">식사 시각</th>
              <th className="px-3 py-2 font-medium">텍스트 길이</th>
              <th className="px-3 py-2 font-medium">분석</th>
              <th className="px-3 py-2 font-medium">상태</th>
              <th className="px-3 py-2 font-medium">동작</th>
            </tr>
          </thead>
          <tbody>
            {data.meals.map((m) => (
              <MealRow key={m.meal_id} meal={m} onDelete={handleDelete} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function MealRow({
  meal,
  onDelete,
}: {
  meal: AdminMealItem;
  onDelete: (mealId: string) => void;
}) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="px-3 py-2">{formatDate(meal.ate_at)}</td>
      <td className="px-3 py-2">{meal.raw_text_length}자</td>
      <td className="px-3 py-2">
        {meal.analysis_summary ? (
          <span
            className={`rounded px-2 py-0.5 text-xs ${fitScoreBadgeClass(
              meal.analysis_summary.fit_score_label,
            )}`}
          >
            {meal.analysis_summary.fit_score} · {meal.analysis_summary.fit_score_label}
          </span>
        ) : (
          <span className="text-xs text-zinc-400">미분석</span>
        )}
      </td>
      <td className="px-3 py-2">
        {meal.deleted_at ? (
          <span className="text-xs text-red-600">삭제됨</span>
        ) : (
          <span className="text-xs text-green-700">활성</span>
        )}
      </td>
      <td className="px-3 py-2">
        {meal.deleted_at === null && (
          <button
            type="button"
            onClick={() => onDelete(meal.meal_id)}
            className="rounded bg-red-50 px-2 py-1 text-xs text-red-700 hover:bg-red-100"
          >
            삭제
          </button>
        )}
      </td>
    </tr>
  );
}

function MealCard({
  meal,
  onDelete,
}: {
  meal: AdminMealItem;
  onDelete: (mealId: string) => void;
}) {
  return (
    <li className="rounded-lg border border-zinc-200 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">{formatDate(meal.ate_at)}</span>
        {meal.deleted_at && (
          <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
            삭제됨
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-zinc-500">텍스트 길이 {meal.raw_text_length}자</p>
      {meal.analysis_summary && (
        <p className="mt-1">
          <span
            className={`rounded px-2 py-0.5 text-xs ${fitScoreBadgeClass(
              meal.analysis_summary.fit_score_label,
            )}`}
          >
            {meal.analysis_summary.fit_score} · {meal.analysis_summary.fit_score_label}
          </span>
        </p>
      )}
      {meal.analysis_summary && (
        <p className="mt-1 text-xs text-zinc-600">
          {meal.analysis_summary.feedback_summary}
        </p>
      )}
      {meal.deleted_at === null && (
        <button
          type="button"
          onClick={() => onDelete(meal.meal_id)}
          className="mt-2 rounded bg-red-50 px-3 py-1 text-xs text-red-700 hover:bg-red-100"
        >
          삭제
        </button>
      )}
    </li>
  );
}
