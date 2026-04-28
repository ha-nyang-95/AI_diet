/**
 * 동의 상태 fetch + 4종 동의 제출 + 자동화 의사결정 grant/revoke 훅
 * (Story 1.3 AC2/AC3 + Story 1.4 AC #7, #8, #10).
 *
 * `useMutation.onSuccess` 시 (a) `['consents']` 쿼리 invalidate, (b) AuthProvider의
 * `consentStatus` state도 동기 갱신해 (tabs) 가드가 즉시 통과하도록 한다.
 *
 * 실패 응답은 ``ConsentSubmitError``로 typed surface — UI가 ``code``(409 →
 * ``consent.version_mismatch`` / ``consent.automated_decision.version_mismatch``,
 * 404 → ``consent.automated_decision.not_granted``)와 ``status``로 분기 가능.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { authFetch, useAuth, type ConsentStatus } from '@/lib/auth';

export interface ConsentSubmitRequest {
  disclaimer_version: string;
  terms_version: string;
  privacy_version: string;
  sensitive_personal_info_version: string;
}

export interface AutomatedDecisionGrantRequest {
  automated_decision_version: string;
}

export class ConsentSubmitError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `consents submit failed (${status})`);
    this.name = 'ConsentSubmitError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
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
    let code: string | undefined;
    let detail: string | undefined;
    try {
      const problem = (await response.json()) as { code?: string; detail?: string };
      code = problem.code;
      detail = problem.detail;
    } catch {
      // RFC 7807 본문이 아니면 status만 사용.
    }
    throw new ConsentSubmitError(response.status, code, detail);
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

// --- Story 1.4 — 자동화 의사결정 동의 grant / revoke -----------------------

async function grantAutomatedDecision(
  body: AutomatedDecisionGrantRequest,
): Promise<ConsentStatus> {
  const response = await authFetch('/v1/users/me/consents/automated-decision', {
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
    throw new ConsentSubmitError(response.status, code, detail);
  }
  return (await response.json()) as ConsentStatus;
}

async function revokeAutomatedDecision(): Promise<ConsentStatus> {
  const response = await authFetch('/v1/users/me/consents/automated-decision', {
    method: 'DELETE',
  });
  if (!response.ok) {
    let code: string | undefined;
    let detail: string | undefined;
    try {
      const problem = (await response.json()) as { code?: string; detail?: string };
      code = problem.code;
      detail = problem.detail;
    } catch {
      // empty body 등.
    }
    throw new ConsentSubmitError(response.status, code, detail);
  }
  return (await response.json()) as ConsentStatus;
}

export function useGrantAutomatedDecisionConsent() {
  const queryClient = useQueryClient();
  const { setConsentStatus } = useAuth();
  return useMutation({
    mutationFn: grantAutomatedDecision,
    onSuccess: (status) => {
      setConsentStatus(status);
      void queryClient.invalidateQueries({ queryKey: ['consents'] });
    },
  });
}

export function useRevokeAutomatedDecisionConsent() {
  const queryClient = useQueryClient();
  const { setConsentStatus } = useAuth();
  return useMutation({
    mutationFn: revokeAutomatedDecision,
    onSuccess: (status) => {
      setConsentStatus(status);
      void queryClient.invalidateQueries({ queryKey: ['consents'] });
    },
  });
}
