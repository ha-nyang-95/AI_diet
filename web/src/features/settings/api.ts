/**
 * Web 매크로 목표 client-side TanStack Query hooks (Story 4.4 AC4).
 *
 * - ``useMacroGoalQuery``: ``GET /v1/users/me/macro_goal`` (forward-compat — 폼 prefill은
 *   SSR fetch가 SOT이지만 client refetch 가능).
 * - ``useMacroGoalMutation``: ``PATCH /v1/users/me/macro_goal``. 성공 시 ``["macro-goal"]``
 *   + ``["weekly-report"]`` queryKey invalidate(인사이트 카드 재계산 트리거).
 *
 * Story 4.3 ``api.ts`` 정합 — ``apiFetch`` 401 인터셉터 활용 + 4xx retry 차단.
 */
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api-fetch";

/** 사용자 매크로 목표 — 5 partial 필드 (`web/src/lib/macro-goal.ts` SOT 미러). */
export interface MacroGoal {
  daily_calorie_target_kcal?: number;
  protein_target_g_per_meal?: number;
  macro_ratio_carb_pct?: number;
  macro_ratio_protein_pct?: number;
  macro_ratio_fat_pct?: number;
}

class MacroGoalFetchError extends Error {
  constructor(
    public readonly status: number,
    public readonly bodyCode: string | null,
    message: string,
  ) {
    super(message);
    this.name = "MacroGoalFetchError";
  }
}

export function useMacroGoalQuery() {
  return useQuery({
    queryKey: ["macro-goal"],
    queryFn: async (): Promise<MacroGoal> => {
      const response = await apiFetch("/v1/users/me/macro_goal", { method: "GET" });
      if (!response.ok) {
        throw new MacroGoalFetchError(
          response.status,
          null,
          `macro goal fetch failed: ${response.status}`,
        );
      }
      return (await response.json()) as MacroGoal;
    },
    staleTime: 60_000,
    retry: (failureCount, error) => {
      if (
        error instanceof MacroGoalFetchError &&
        error.status >= 400 &&
        error.status < 500
      ) {
        return false;
      }
      return failureCount < 1;
    },
  });
}

export interface MacroGoalPatchPayload {
  daily_calorie_target_kcal?: number | null;
  protein_target_g_per_meal?: number | null;
  macro_ratio_carb_pct?: number | null;
  macro_ratio_protein_pct?: number | null;
  macro_ratio_fat_pct?: number | null;
}

export function useMacroGoalMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: MacroGoalPatchPayload): Promise<MacroGoal> => {
      const response = await apiFetch("/v1/users/me/macro_goal", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          code?: string;
          detail?: string;
        };
        throw new MacroGoalFetchError(
          response.status,
          body.code ?? null,
          body.detail ?? `macro goal patch failed: ${response.status}`,
        );
      }
      return (await response.json()) as MacroGoal;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["macro-goal"] });
      queryClient.invalidateQueries({ queryKey: ["weekly-report"] });
    },
  });
}

export { MacroGoalFetchError };
