/**
 * Mobile auth — TanStack Query 클라이언트 + fetch 래퍼(401 → refresh 1회 → 재시도) +
 * AuthContext (signIn / signOut / 현재 user 상태).
 *
 * 핵심 제약 (AC4):
 * - 401 시 refresh 1회만 시도 (인터셉터 무한 루프 차단).
 * - refresh 실패 → 로컬 토큰 클리어 + /(auth)/login 라우팅 트리거.
 */
import { QueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { clearOnboardingState } from '@/features/onboarding/tutorialState';

import {
  clearAuth,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from './secure-store';

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  picture_url: string | null;
  role: 'user' | 'admin';
  // Story 1.5 — 건강 프로필 입력 시점(미입력 시 null). (tabs)/_layout.tsx의 4번째
  // 가드(profile) 분기 입력. 본 필드는 GET /v1/users/me 응답에서 forward됨.
  profile_completed_at: string | null;
  // Story 1.6 — 최초 온보딩 흐름 통과 시점(멱등 set, profile 수정 시 변경 X).
  // GET /v1/users/me + POST /v1/auth/google(UserPublic) 응답에서 forward됨. 본
  // 필드는 향후 *환영 메시지*(Story 4.x) / admin audit(Story 7.x) hook이며 본
  // 스토리에서는 *값 노출*만 — UI 활용 X.
  onboarded_at: string | null;
}

export interface ConsentStatus {
  disclaimer_acknowledged_at: string | null;
  terms_consent_at: string | null;
  privacy_consent_at: string | null;
  sensitive_personal_info_consent_at: string | null;
  disclaimer_version: string | null;
  terms_version: string | null;
  privacy_version: string | null;
  sensitive_personal_info_version: string | null;
  basic_consents_complete: boolean;
  // Story 1.4 — PIPA 2026.03.15 자동화 의사결정 동의 (별도 게이트).
  automated_decision_consent_at: string | null;
  automated_decision_revoked_at: string | null;
  automated_decision_version: string | null;
  automated_decision_consent_complete: boolean;
}

export interface AuthContextValue {
  user: AuthUser | null;
  consentStatus: ConsentStatus | null;
  isAuthed: boolean;
  isReady: boolean;
  signIn: (payload: { access: string; refresh: string; user: AuthUser }) => Promise<void>;
  signOut: () => Promise<void>;
  setConsentStatus: (status: ConsentStatus) => void;
  // Story 1.5 — `POST /v1/users/me/profile` 성공 직후 4번째 가드 stale-cache loop를
  // 차단하기 위해 user state의 profile_completed_at만 즉시 갱신. /me refetch가 settle
  // 되기 전 (tabs) 가드가 stale null을 봐 onboarding으로 재 redirect되는 flicker 차단.
  markProfileCompleted: (profileCompletedAt: string) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,
      retry: 1,
    },
  },
});

const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
const REFRESH_PATH = '/v1/auth/refresh';

interface RefreshResponse {
  access_token: string;
  refresh_token: string;
  expires_in_seconds: number;
}

let refreshInFlight: Promise<string | null> | null = null;

// AuthProvider가 mount 시 등록 — refresh 실패로 세션 무효화 시 user state 동기화 신호.
let onSessionCleared: (() => void) | null = null;

export function subscribeSessionCleared(cb: () => void): () => void {
  onSessionCleared = cb;
  return () => {
    if (onSessionCleared === cb) onSessionCleared = null;
  };
}

// 재시도 응답이 또 401일 때 재-refresh 무한 루프 방어용 sentinel 헤더.
const RETRY_HEADER = 'X-Auth-Refreshed';

async function performRefresh(): Promise<string | null> {
  const refresh = await getRefreshToken();
  if (!refresh) {
    onSessionCleared?.();
    return null;
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${REFRESH_PATH}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
  } catch {
    // 네트워크/타임아웃: 토큰을 지우지 않고 caller가 재시도할 수 있도록 null만 반환.
    return null;
  }
  if (!response.ok) {
    await clearAuth();
    await clearOnboardingState();
    onSessionCleared?.();
    return null;
  }
  let body: RefreshResponse;
  try {
    body = (await response.json()) as RefreshResponse;
  } catch {
    await clearAuth();
    await clearOnboardingState();
    onSessionCleared?.();
    return null;
  }
  await Promise.all([setAccessToken(body.access_token), setRefreshToken(body.refresh_token)]);
  return body.access_token;
}

/**
 * 백엔드 보호 endpoint 호출용 래퍼.
 * - access 토큰 자동 첨부.
 * - 401 → refresh 1회 → 재시도. 실패 시 로그인 화면으로 라우팅.
 * - 재시도 응답에는 `X-Auth-Refreshed: 1` 헤더 표시 — 재-refresh 무한 루프 방어.
 */
export async function authFetch(input: string, init?: RequestInit): Promise<Response> {
  const access = await getAccessToken();
  const headers = new Headers(init?.headers);
  if (access) headers.set('Authorization', `Bearer ${access}`);
  const url = input.startsWith('http') ? input : `${API_BASE_URL}${input}`;

  const first = await fetch(url, { ...init, headers });
  if (first.status !== 401) return first;
  // 이미 한 번 refresh 후 재시도된 요청이라면 추가 refresh 시도 금지(무한 루프 차단).
  if (headers.get(RETRY_HEADER) === '1') {
    router.replace('/(auth)/login');
    return first;
  }

  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null;
  });
  const newAccess = await refreshInFlight;
  if (!newAccess) {
    router.replace('/(auth)/login');
    return first;
  }

  const retryHeaders = new Headers(init?.headers);
  retryHeaders.set('Authorization', `Bearer ${newAccess}`);
  retryHeaders.set(RETRY_HEADER, '1');
  return fetch(url, { ...init, headers: retryHeaders });
}

/**
 * 동의 상태를 한 번 fetch — 네트워크 오류 / non-2xx는 null 반환(호출부가 fallback 결정).
 * 401은 ``authFetch``가 refresh + redirect를 자동 처리 후 401 그대로 반환 → null.
 */
async function fetchConsentStatus(): Promise<ConsentStatus | null> {
  try {
    const resp = await authFetch('/v1/users/me/consents');
    if (!resp.ok) return null;
    return (await resp.json()) as ConsentStatus;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [consentStatus, setConsentStatusState] = useState<ConsentStatus | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    // signOut/refresh 실패로 세션 클리어 신호 → user state 동기화(stale fetch 결과 부활 방지).
    return subscribeSessionCleared(() => {
      setUser(null);
      setConsentStatusState(null);
    });
  }, []);

  useEffect(() => {
    let isCancelled = false;
    void (async () => {
      const access = await getAccessToken();
      if (!access) {
        if (!isCancelled) setIsReady(true);
        return;
      }
      try {
        const meResponse = await authFetch('/v1/users/me');
        if (isCancelled) return;
        if (!meResponse.ok) return;
        const body = (await meResponse.json()) as AuthUser;
        if (isCancelled) return;
        setUser(body);
        // Story 1.3 AC2 — bootstrap 시 동의 상태도 1회 fetch. 네트워크 오류는
        // 무시(consentStatus는 null 유지 → onboarding 가드가 fallback). 401은
        // authFetch 인터셉터가 이미 /(auth)/login으로 라우팅.
        const consent = await fetchConsentStatus();
        if (isCancelled) return;
        if (consent !== null) setConsentStatusState(consent);
      } finally {
        if (!isCancelled) setIsReady(true);
      }
    })();
    return () => {
      isCancelled = true;
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      consentStatus,
      isAuthed: user !== null,
      isReady,
      async signIn(payload) {
        await Promise.all([setAccessToken(payload.access), setRefreshToken(payload.refresh)]);
        setUser(payload.user);
        // 새 로그인 — 이전 세션의 동의 상태 클리어 후 즉시 refetch. 기존 사용자가 신규
        // 로그인 시 onboarding으로 잘못 redirect되는 loop 방지.
        setConsentStatusState(null);
        const status = await fetchConsentStatus();
        if (status !== null) setConsentStatusState(status);
      },
      async signOut() {
        const [access, refresh] = await Promise.all([getAccessToken(), getRefreshToken()]);
        if (refresh) {
          try {
            // spec AC5: 모바일은 Authorization 헤더 + body의 refresh_token 둘 다 동봉.
            const headers: Record<string, string> = { 'Content-Type': 'application/json' };
            if (access) headers['Authorization'] = `Bearer ${access}`;
            await fetch(`${API_BASE_URL}/v1/auth/logout`, {
              method: 'POST',
              headers,
              body: JSON.stringify({ refresh_token: refresh }),
            });
          } catch {
            // ignore — 로컬 클리어는 계속 진행
          }
        }
        // 토큰 clear는 보안 critical(secure-store 책임), onboarding state clear는
        // UX(tutorialState 책임). 두 책임을 분리 + 순차 await — Promise.all로 묶지
        // 않는 이유는 실패 시 fallback 의미 분명 + secure-store.ts의 *토큰 전용*
        // 책임을 유지(secure-store.ts:4 "AsyncStorage 평문 저장 금지" 주석 정합).
        // tutorialState helper는 내부에서 AsyncStorage 실패를 swallow하나, 라우팅·
        // user state 클리어가 차단되지 않도록 호출 자체에도 try/catch 가드(defense-in-depth).
        await clearAuth();
        try {
          await clearOnboardingState();
        } catch {
          // ignore — signOut의 후속 라우팅이 절대 차단되면 안 됨.
        }
        setUser(null);
        setConsentStatusState(null);
        router.replace('/(auth)/login');
      },
      setConsentStatus(status) {
        setConsentStatusState(status);
      },
      markProfileCompleted(profileCompletedAt) {
        setUser((prev) => (prev ? { ...prev, profile_completed_at: profileCompletedAt } : prev));
      },
    }),
    [user, consentStatus, isReady],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
