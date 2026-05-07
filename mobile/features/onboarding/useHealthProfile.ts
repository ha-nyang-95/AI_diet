/**
 * Story 1.5 — 건강 프로필 입력 mutation + 조회 query 훅 + ProfileSubmitError.
 *
 * ``ConsentSubmitError`` 패턴(Story 1.3·1.4) 1:1 정합 — typed status + code + detail.
 * 성공 시 ``['profile']`` + ``['user-me']`` 무효화(``profile_completed_at`` 갱신 → 4번째
 * 가드 통과 신호).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { authFetch } from '@/lib/auth';

import type { HealthProfileFormData, HealthProfileResponse } from './healthProfileSchema';

export class ProfileSubmitError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `health profile submit failed (${status})`);
    this.name = 'ProfileSubmitError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function submitHealthProfile(
  body: HealthProfileFormData,
): Promise<HealthProfileResponse> {
  const response = await authFetch('/v1/users/me/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let code: string | undefined;
    let detail: string | undefined;
    try {
      const problem = (await response.json()) as { code?: string; detail?: string };
      code = problem.code;
      detail = problem.detail;
    } catch {
      // RFC 7807 본문이 아니면 status만 사용.
    }
    throw new ProfileSubmitError(response.status, code, detail);
  }
  return (await response.json()) as HealthProfileResponse;
}

async function patchHealthProfile(
  body: HealthProfileFormData,
): Promise<HealthProfileResponse> {
  // Story 5.1 — *수정* 흐름. 폼은 prefill된 6 필드를 *전체 송신*(full replace 동작),
  // 백엔드 PATCH endpoint는 partial 입력도 수용하지만 폼 UX는 일관성을 위해 전체 송신.
  // 신규 mutation 라이프사이클 분리로 onboarding(POST)과 settings(PATCH) cache invalidate
  // 패턴을 동일하게 유지하되 endpoint method만 변경.
  const response = await authFetch('/v1/users/me/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let code: string | undefined;
    let detail: string | undefined;
    try {
      const problem = (await response.json()) as { code?: string; detail?: string };
      code = problem.code;
      detail = problem.detail;
    } catch {
      // RFC 7807 본문이 아니면 status만 사용.
    }
    throw new ProfileSubmitError(response.status, code, detail);
  }
  return (await response.json()) as HealthProfileResponse;
}

async function fetchHealthProfile(): Promise<HealthProfileResponse> {
  const response = await authFetch('/v1/users/me/profile');
  if (!response.ok) {
    throw new Error(`health profile fetch failed (${response.status})`);
  }
  return (await response.json()) as HealthProfileResponse;
}

export function useSubmitHealthProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: submitHealthProfile,
    onSuccess: () => {
      // GET /v1/users/me/profile 갱신 + GET /v1/users/me 무효화(profile_completed_at
      // boolean 갱신용 — 4번째 가드 통과 트리거).
      void queryClient.invalidateQueries({ queryKey: ['profile'] });
      void queryClient.invalidateQueries({ queryKey: ['user-me'] });
    },
  });
}

export function useUpdateHealthProfile() {
  // Story 5.1 — PATCH /me/profile 흐름. POST와 동일 invalidate 패턴(profile + user-me)
  // 으로 통일 — macro_goal/notifications 영향 0건.
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: patchHealthProfile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['profile'] });
      void queryClient.invalidateQueries({ queryKey: ['user-me'] });
    },
  });
}

export function useHealthProfileQuery() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: fetchHealthProfile,
  });
}
