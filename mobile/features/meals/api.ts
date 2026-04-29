/**
 * Story 2.1 — `/v1/meals` TanStack Query hooks.
 *
 * - `useMealsQuery`        — `GET /v1/meals?from_date=&to_date=&limit=`
 * - `useCreateMealMutation` — `POST /v1/meals`
 * - `useUpdateMealMutation` — `PATCH /v1/meals/{meal_id}`
 * - `useDeleteMealMutation` — `DELETE /v1/meals/{meal_id}`
 *
 * 모든 mutation은 성공 시 `['meals']` 무효화 — list 자동 refetch. optimistic update
 * 회피 (yagni — 실패 시 rollback 복잡, baseline은 단순; Story 8 polish 시점 도입).
 *
 * `MealSubmitError` 패턴은 Story 1.5 `ProfileSubmitError`와 1:1 정합 — typed status +
 * code + detail.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { authFetch } from '@/lib/auth';

import type {
  MealCreateRequest,
  MealListResponse,
  MealResponse,
  MealUpdateRequest,
  MealsListQuery,
} from './mealSchema';

export class MealSubmitError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `meal request failed (${status})`);
    this.name = 'MealSubmitError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function _parseProblem(
  response: Response,
): Promise<{ code?: string; detail?: string }> {
  try {
    const problem = (await response.json()) as { code?: string; detail?: string };
    return { code: problem.code, detail: problem.detail };
  } catch {
    return {};
  }
}

function buildMealsQueryString(params: MealsListQuery | undefined): string {
  if (!params) return '';
  const usp = new URLSearchParams();
  if (params.from_date) usp.set('from_date', params.from_date);
  if (params.to_date) usp.set('to_date', params.to_date);
  if (params.limit !== undefined) usp.set('limit', String(params.limit));
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

async function fetchMeals(params: MealsListQuery | undefined): Promise<MealListResponse> {
  const response = await authFetch(`/v1/meals${buildMealsQueryString(params)}`);
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealListResponse;
}

async function createMeal(body: MealCreateRequest): Promise<MealResponse> {
  const response = await authFetch('/v1/meals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealResponse;
}

async function updateMeal(args: {
  meal_id: string;
  body: MealUpdateRequest;
}): Promise<MealResponse> {
  const response = await authFetch(`/v1/meals/${args.meal_id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args.body),
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  return (await response.json()) as MealResponse;
}

async function deleteMeal(meal_id: string): Promise<void> {
  const response = await authFetch(`/v1/meals/${meal_id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const problem = await _parseProblem(response);
    throw new MealSubmitError(response.status, problem.code, problem.detail);
  }
  // 204 No Content — body 없음.
}

export function useMealsQuery(params?: MealsListQuery) {
  return useQuery({
    // params를 query key에 직접 spread하지 않고 직렬화 가능한 plain object로 forward.
    queryKey: ['meals', params ?? {}],
    queryFn: () => fetchMeals(params),
  });
}

export function useCreateMealMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createMeal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['meals'] });
    },
  });
}

export function useUpdateMealMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateMeal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['meals'] });
    },
  });
}

export function useDeleteMealMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteMeal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['meals'] });
    },
  });
}
