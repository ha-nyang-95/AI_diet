/**
 * Story 6.1 — 활성 구독 조회 query 훅 + Web 결제 진입 URL 헬퍼.
 *
 * 모바일은 *결제 위젯 미노출* (App Store IAP 정책 정합 — prd.md:676 SOT). 사용자가
 * "구독 신청" 버튼을 누르면 ``Linking.openURL(getSubscribeWebUrl())``로 외부 브라우저에
 * Web ``/account/subscribe`` 페이지를 노출한다.
 *
 * 본 훅은:
 * - ``useSubscriptionQuery()`` — ``GET /v1/payments/subscription`` 호출. 200이면
 *   ``SubscriptionDto``, 404이면 ``null``로 정규화(미신청 사용자 정상 케이스).
 * - ``getSubscribeWebUrl()`` — Web 결제 페이지 URL 헬퍼.
 *   ``EXPO_PUBLIC_WEB_BASE_URL || 'https://balancenote.app'`` fallback.
 *
 * Story 5.x ``useDataExport`` / ``useAccountDelete`` 패턴 정합 — typed status + code.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { authFetch } from '@/lib/auth';

export type SubscriptionStatus = 'active' | 'cancelled' | 'expired';
export type SubscriptionPlan = 'monthly';
export type SubscriptionProvider = 'toss' | 'stripe';

export interface SubscriptionDto {
  id: string;
  user_id: string;
  status: SubscriptionStatus;
  plan: SubscriptionPlan;
  plan_price_krw: number;
  started_at: string;
  expires_at: string | null;
  cancelled_at: string | null;
  provider: SubscriptionProvider;
  created_at: string;
}

export class SubscriptionFetchError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(status: number, code?: string, detail?: string) {
    super(detail ?? `subscription fetch failed (${status})`);
    this.name = 'SubscriptionFetchError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

// CR P14 — userId를 queryKey에 포함해 계정 전환 시 직전 사용자 cache 누출 차단.
// 호출자는 ``getSubscriptionQueryKey(user.id)``로 안정 key를 얻는다.
export const SUBSCRIPTION_QUERY_KEY_PREFIX = ['payments', 'subscription'] as const;
export function getSubscriptionQueryKey(userId: string): readonly [string, string, string] {
  return [...SUBSCRIPTION_QUERY_KEY_PREFIX, userId] as const;
}

// 하위 호환 — 본 상수 import한 기존 코드(있다면)는 prefix 의미로 동작.
export const SUBSCRIPTION_QUERY_KEY = SUBSCRIPTION_QUERY_KEY_PREFIX;

const WEB_SUBSCRIBE_PATH = '/account/subscribe';
const WEB_BASE_URL_FALLBACK = 'https://balancenote.app';

/**
 * Web 결제 페이지 URL — `EXPO_PUBLIC_WEB_BASE_URL` 우선 + 미설정 시 prod fallback.
 *
 * App Store IAP 정합 — 모바일 위젯 노출 X, 외부 브라우저로 진입.
 */
export function getSubscribeWebUrl(): string {
  const base = process.env.EXPO_PUBLIC_WEB_BASE_URL || WEB_BASE_URL_FALLBACK;
  // trailing slash 정규화 — base가 ``/``로 끝나면 Path와 충돌 회피.
  const normalized = base.endsWith('/') ? base.slice(0, -1) : base;
  return `${normalized}${WEB_SUBSCRIBE_PATH}`;
}

async function fetchActiveSubscription(): Promise<SubscriptionDto | null> {
  const response = await authFetch('/v1/payments/subscription');
  if (response.status === 404) {
    // 활성 구독 0건 — 미신청 사용자 정상 케이스. null 정규화로 client 분기 단순화.
    return null;
  }
  if (!response.ok) {
    let code: string | undefined;
    let detail: string | undefined;
    try {
      const problem = (await response.json()) as { code?: string; detail?: string };
      code = problem.code;
      detail = problem.detail;
    } catch {
      // RFC 7807 본문 아니면 status만 사용.
    }
    throw new SubscriptionFetchError(response.status, code, detail);
  }
  return (await response.json()) as SubscriptionDto;
}

/**
 * Story 6.1 — 활성 구독 조회 hook.
 *
 * - 200 → ``SubscriptionDto``.
 * - 404 → ``null``.
 * - 401/403/5xx → ``SubscriptionFetchError`` (caller가 ``error`` 분기 처리).
 *
 * CR P14 — ``userId``를 queryKey에 포함해 계정 전환 시 cache leak 차단(staleTime 30s
 * 동안 직전 사용자 구독이 표시되는 race 회피).
 *
 * cache key ``["payments", "subscription", userId]`` — Story 6.2 cancel 흐름이 invalidate.
 */
export function useSubscriptionQuery(
  userId: string,
): UseQueryResult<SubscriptionDto | null, SubscriptionFetchError> {
  return useQuery({
    queryKey: getSubscriptionQueryKey(userId),
    queryFn: fetchActiveSubscription,
    staleTime: 30_000,
    enabled: userId.length > 0,
  });
}
