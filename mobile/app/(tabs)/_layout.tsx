import { Redirect, Tabs, usePathname } from 'expo-router';

import { useAuth } from '@/lib/auth';

/**
 * (tabs) 그룹은 보호 라우트 — 인증 + 동의 게이트 3단계 통과 시에만 진입.
 *
 * Story 1.2: 인증 게이트(`isAuthed`).
 * Story 1.3 AC2: 4종 동의 게이트(`consentStatus.basic_consents_complete`) — 미동의 시
 * `(auth)/onboarding/disclaimer`로 redirect, 진입 시도한 경로는 `?next=` 쿼리로 보존.
 * Story 1.4 AC8: 자동화 의사결정 게이트(`automated_decision_consent_complete`) —
 * 미동의 시 `(auth)/onboarding/automated-decision`으로 redirect.
 *
 * 가드 *순서*가 중요 — basic 미통과 사용자가 AD 화면으로 우선 라우팅되면 하위 검증이
 * 실패한다. (1) 인증 → (2) basic → (3) AD.
 *
 * `consentStatus`는 AuthProvider bootstrap에서 `GET /v1/users/me/consents` 1회 fetch로
 * 채워진다. signIn 직후엔 null — null인 동안에는 동의 게이트를 통과시키지 않고 onboarding
 * 진입(신규 사용자가 default flow).
 */
export default function TabsLayout() {
  const { isAuthed, isReady, consentStatus } = useAuth();
  const pathname = usePathname();

  if (!isReady) return null;
  if (!isAuthed) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    return <Redirect href={`/(auth)/login?next=${next}`} />;
  }
  if (!consentStatus?.basic_consents_complete) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    const target = `/(auth)/onboarding/disclaimer?next=${next}` as Parameters<
      typeof Redirect
    >[0]['href'];
    return <Redirect href={target} />;
  }
  if (!consentStatus.automated_decision_consent_complete) {
    const next = encodeURIComponent(pathname || '/(tabs)');
    const target = `/(auth)/onboarding/automated-decision?next=${next}` as Parameters<
      typeof Redirect
    >[0]['href'];
    return <Redirect href={target} />;
  }

  return <Tabs screenOptions={{ headerShown: false }} />;
}
