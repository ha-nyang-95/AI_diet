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

export function useHealthProfileQuery() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: fetchHealthProfile,
  });
}
