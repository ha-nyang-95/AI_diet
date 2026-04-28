/**
 * 동의 상태 fetch + 4종 동의 제출 훅 (Story 1.3 AC2/AC3).
 *
 * `useMutation.onSuccess` 시 (a) `['consents']` 쿼리 invalidate, (b) AuthProvider의
 * `consentStatus` state도 동기 갱신해 (tabs) 가드가 즉시 통과하도록 한다.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { authFetch, useAuth, type ConsentStatus } from '@/lib/auth';

export interface ConsentSubmitRequest {
  disclaimer_version: string;
  terms_version: string;
  privacy_version: string;
  sensitive_personal_info_version: string;
}

async function fetchConsents(): Promise<ConsentStatus> {
  const response = await authFetch('/v1/users/me/consents');
  if (!response.ok) {
    throw new Error(`consents fetch failed (${response.status})`);
  }
  return (await response.json()) as ConsentStatus;
}

async function submitConsents(body: ConsentSubmitRequest): Promise<ConsentStatus> {
  const response = await authFetch('/v1/users/me/consents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`consents submit failed (${response.status})`);
  }
  return (await response.json()) as ConsentStatus;
}

export function useConsentsQuery() {
  return useQuery({
    queryKey: ['consents'],
    queryFn: fetchConsents,
  });
}

export function useSubmitConsents() {
  const queryClient = useQueryClient();
  const { setConsentStatus } = useAuth();
  return useMutation({
    mutationFn: submitConsents,
    onSuccess: (status) => {
      setConsentStatus(status);
      void queryClient.invalidateQueries({ queryKey: ['consents'] });
    },
  });
}
